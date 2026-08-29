"use strict";

const state = {
    data: null,
    view: "workflow",
    scenario: "workspace-export-authorization",
    runId: null,
    attempt: 1,
};

const scenarioNames = {
    "workspace-export-authorization": "Workspace export authorization",
    "share-link-expiration": "Share-link expiration",
};

const scenarioAliases = {
    api: "workspace-export-authorization",
    database: "share-link-expiration",
};

const toneByState = {
    AWAITING_OWNER: "amber",
    COVERAGE_GAP: "violet",
    COMPLETED: "green",
    FAILED: "red",
};

async function initialize() {
    const response = await fetch("/demo-runs.json");
    if (!response.ok) throw new Error(`Unable to load replay data: ${response.status}`);
    state.data = await response.json();
    readHash();
    bindEvents();
    render();
}

function readHash() {
    const params = new URLSearchParams(location.hash.slice(1));
    state.view = params.get("view") === "walkthrough" ? "walkthrough" : "workflow";
    state.scenario = scenarioAliases[params.get("scenario")] || params.get("scenario") || state.scenario;
    const validRuns = runsForScenario(state.scenario);
    const requestedRun = params.get("run");
    state.runId = validRuns.some((run) => run.id === requestedRun)
        ? requestedRun
        : validRuns[0]?.id || null;
    state.attempt = Math.max(1, Number.parseInt(params.get("attempt") || "1", 10) || 1);
}

function writeHash() {
    const scenario = state.scenario === "share-link-expiration" ? "database" : "api";
    const params = new URLSearchParams({view: state.view, scenario});
    if (state.runId) params.set("run", state.runId);
    params.set("attempt", String(state.attempt));
    history.replaceState(null, "", `#${params}`);
}

function bindEvents() {
    document.addEventListener("click", (event) => {
        const target = event.target.closest("button");
        if (!target) return;
        if (target.dataset.view) {
            state.view = target.dataset.view;
        } else if (target.dataset.scenario || target.dataset.workflowScenario) {
            const alias = target.dataset.scenario || target.dataset.workflowScenario;
            state.scenario = scenarioAliases[alias] || alias;
            state.runId = runsForScenario(state.scenario)[0]?.id || null;
            state.attempt = 1;
        } else if (target.dataset.attempt) {
            state.attempt = Number(target.dataset.attempt);
        } else {
            return;
        }
        writeHash();
        render();
    });
    document.querySelector("#case-select").addEventListener("change", (event) => {
        state.runId = event.target.value;
        state.attempt = 1;
        writeHash();
        render();
    });
    window.addEventListener("hashchange", () => {
        readHash();
        render();
    });
}

function runsForScenario(scenario) {
    return state.data?.runs.filter((run) => run.scenario === scenario) || [];
}

function selectedRun() {
    return state.data.runs.find((run) => run.id === state.runId) || runsForScenario(state.scenario)[0];
}

function render() {
    document.querySelectorAll("[data-view-panel]").forEach((panel) => {
        panel.hidden = panel.dataset.viewPanel !== state.view;
    });
    document.querySelectorAll("[data-view]").forEach((tab) => {
        tab.setAttribute("aria-selected", String(tab.dataset.view === state.view));
    });
    document.querySelectorAll("[data-scenario], [data-workflow-scenario]").forEach((button) => {
        const alias = button.dataset.scenario || button.dataset.workflowScenario;
        button.setAttribute("aria-selected", String(scenarioAliases[alias] === state.scenario));
    });
    renderWorkflow();
    renderWalkthrough();
}

function renderWorkflow() {
    document.querySelector("#workflow-scenario-name").textContent = scenarioNames[state.scenario];
    const routes = runsForScenario(state.scenario);
    document.querySelector("#workflow-canvas").innerHTML = `
        <div class="gate-map" aria-label="Gate evaluation order">
            ${gateNode("1", "Observe", "Run every declared observer rule")}
            ${arrow()}
            ${gateNode("2", "Invariants", "Violation becomes FAILED", "red")}
            ${arrow()}
            ${gateNode("3", "Effects", "Forbidden fails; unclassified gaps", "violet")}
            ${arrow()}
            ${gateNode("4", "Coverage", "Missing attestation becomes COVERAGE_GAP", "violet")}
            ${arrow()}
            ${gateNode("5", "Decisions", "Review only owner-selectable choices", "amber")}
            ${arrow()}
            ${gateNode("6", "Verify", "Attempt two repeats the entire pipeline", "green")}
        </div>`;
    document.querySelector("#workflow-inspector").innerHTML = `
        <div class="workflow-inspector-header">
            <div>
                <div class="workflow-inspector-title"><h2>Routes are typed before product review</h2></div>
                <p>Unknown evidence is preserved. It is never silently converted into a decision, a pass, or a generic exception.</p>
            </div>
            <span class="workflow-example-label">Policy snapshot pinned per run</span>
        </div>
        <div class="route-card-grid">${routes.map((run) => routeCard(run)).join("")}</div>
        <details class="workflow-run-record">
            <summary>What every durable run records</summary>
            <div><ul>
                <li>Run schema and scenario policy digest</li>
                <li>Invariant evidence and owner-selectable observations</li>
                <li>One policy disposition for every structural effect</li>
                <li>Required coverage rules and their execution status</li>
                <li>Typed failure or coverage-gap category</li>
            </ul></div>
        </details>`;
}

function gateNode(number, title, copy, tone = "blue") {
    return `<article class="gate-node gate-node-${tone}"><span>${number}</span><strong>${title}</strong><small>${copy}</small></article>`;
}

function arrow() {
    return `<span class="gate-arrow" aria-hidden="true">→</span>`;
}

function routeCard(run) {
    const tone = toneByState[run.state] || "blue";
    const terminal = run.failure?.category || run.coverage_gaps?.[0]?.category || run.state;
    return `<article class="route-card route-card-${tone}">
        <span class="status-pill status-${tone}"><span></span>${escapeHtml(run.state)}</span>
        <h3>${escapeHtml(run.label)}</h3>
        <p>${escapeHtml(run.summary)}</p>
        <code>${escapeHtml(terminal)}</code>
    </article>`;
}

function renderWalkthrough() {
    const run = selectedRun();
    if (!run) return;
    state.runId = run.id;
    state.attempt = Math.min(state.attempt, run.attempts.length || 1);
    document.querySelector("#scenario-name").textContent = scenarioNames[state.scenario];
    document.querySelector("#case-select").innerHTML = runsForScenario(state.scenario)
        .map((item) => `<option value="${escapeHtml(item.id)}" ${item.id === run.id ? "selected" : ""}>${escapeHtml(item.label)}</option>`)
        .join("");
    renderAttemptRail(run);
    renderReplayPath(run);
    renderAssessment(run);
}

function renderAttemptRail(run) {
    document.querySelector("#stage-rail").innerHTML = run.attempts.map((attempt) => `
        <div class="stage-step-slot">
            <button class="stage-step ${attempt.number === state.attempt ? "stage-active" : ""}" type="button" data-attempt="${attempt.number}">
                <span class="step-marker">${attempt.number}</span>
                Attempt ${attempt.number}
            </button>
        </div>`).join("");
}

function renderReplayPath(run) {
    const nodes = ["Artifact", "Observe", "Invariants", "Effects", "Coverage", "Decisions"];
    if (run.attempts.length === 2) nodes.push("Clean retry");
    nodes.push(run.state);
    document.querySelector("#replay-path").innerHTML = `
        <strong>Evaluation path</strong>
        <div>${nodes.map((node, index) => `
            ${index ? '<span class="replay-path-arrow">→</span>' : ""}
            <span class="replay-path-node ${index === nodes.length - 1 ? `replay-path-node-${run.state === "COMPLETED" ? "complete" : "active"}` : "replay-path-node-complete"}">${escapeHtml(node)}</span>
        `).join("")}</div>`;
}

function renderAssessment(run) {
    const attempt = run.attempts.find((item) => item.number === state.attempt) || run.attempts[0];
    const tone = toneByState[run.state] || "blue";
    document.querySelector("#stage-content").innerHTML = `
        <div class="stage-heading">
            <div>
                <span class="eyebrow">Typed attempt assessment</span>
                <h2>${escapeHtml(run.label)}</h2>
                <p class="stage-summary">${escapeHtml(run.summary)}</p>
            </div>
            <span class="status-pill status-${tone}"><span></span>${escapeHtml(run.state)}</span>
        </div>
        <div class="assessment-grid">
            ${surfaceCard("Authoritative invariants", "Must hold", attempt.invariants, invariantRow)}
            ${surfaceCard("Owner decisions", "May pause", attempt.decisions, decisionRow, attempt.unknown_effects)}
            ${surfaceCard("Effect policy", "Every effect classified", attempt.effect_dispositions, effectRow)}
            ${surfaceCard("Coverage manifest", "Absence is explicit", attempt.coverage, coverageRow)}
        </div>
        ${terminalCard(run)}
        <div class="provenance-bar">
            <span>Attempt <code>${attempt.number}</code></span>
            <span>Policy <code>${escapeHtml(run.policy_digest)}</code></span>
            <span>Artifact <code>${escapeHtml(attempt.artifact_digest || "illustrative")}</code></span>
        </div>`;
}

function surfaceCard(title, rule, items = [], renderItem, unknowns = []) {
    const rows = [...items.map(renderItem), ...unknowns.map(unknownRow)];
    return `<section class="surface-card">
        <div class="surface-card-header"><div><h3>${title}</h3><span>${rule}</span></div><strong>${rows.length}</strong></div>
        <div class="surface-rows">${rows.length ? rows.join("") : '<p class="empty-surface">No observations on this attempt.</p>'}</div>
    </section>`;
}

function invariantRow(item) {
    return resultRow(item.status, item.invariant_id, `${item.observed} · expected ${item.expected}`);
}

function decisionRow(item) {
    return resultRow("OBSERVED", item.decision_id, item.option_id);
}

function unknownRow(item) {
    return resultRow("UNKNOWN", item.rule_id, item.description);
}

function effectRow(item) {
    const effect = item.effect;
    return resultRow(item.status, `${effect.change} ${effect.identity}`, item.reason);
}

function coverageRow(item) {
    return resultRow(item.status, item.rule_id, item.evidence_digest ? `Evidence ${item.evidence_digest}` : "No evidence digest");
}

function resultRow(status, title, detail) {
    const tone = statusTone(status);
    return `<article class="surface-row"><span class="mini-status mini-status-${tone}">${escapeHtml(status)}</span><div><strong>${escapeHtml(title)}</strong><p>${escapeHtml(detail)}</p></div></article>`;
}

function statusTone(status) {
    if (["PASSED", "EXPECTED", "ALLOWED", "SUPPORTED"].includes(status)) return "green";
    if (["VIOLATED", "FORBIDDEN", "FAILED"].includes(status)) return "red";
    if (["MISSING", "UNCLASSIFIED", "UNKNOWN"].includes(status)) return "violet";
    return "blue";
}

function terminalCard(run) {
    if (run.failure) {
        return `<section class="terminal-card terminal-card-red"><strong>${escapeHtml(run.failure.category)}</strong><p>${escapeHtml(run.failure.message)}</p><code>${escapeHtml(run.failure.stage)}</code></section>`;
    }
    if (run.coverage_gaps?.length) {
        return `<section class="terminal-card terminal-card-violet"><strong>${escapeHtml(run.coverage_gaps[0].category)}</strong><p>${escapeHtml(run.coverage_gaps[0].description)}</p><code>${escapeHtml(run.coverage_gaps[0].rule_id)}</code></section>`;
    }
    if (run.state === "AWAITING_OWNER") {
        return `<section class="terminal-card terminal-card-amber"><strong>Owner input required</strong><p>Only the declared decision axis is presented. Requirements and side effects are not negotiable choices.</p></section>`;
    }
    return `<section class="terminal-card terminal-card-green"><strong>Verified completion</strong><p>All required surfaces passed and every selected behavior matched the final observation.</p></section>`;
}

function escapeHtml(value) {
    return String(value)
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

initialize().catch((error) => {
    document.querySelector("main").innerHTML = `<p class="fatal-error">${escapeHtml(error.message)}</p>`;
});
