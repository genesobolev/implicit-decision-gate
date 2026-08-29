"use strict";

const normalSteps = [
    { id: "brief", label: "Brief" },
    { id: "observe", label: "Observe" },
    { id: "review", label: "Review" },
    { id: "answer", label: "Decide" },
    { id: "verify", label: "Verify" },
];

const gapSteps = [
    { id: "brief", label: "Brief" },
    { id: "observe", label: "Observe" },
    { id: "gap", label: "Coverage gap" },
];

const state = {
    view: "workflow",
    scenario: "api",
    workflowNode: "started",
    step: "brief",
    coverageGap: false,
    administrator: null,
    repeat: null,
    expiration: null,
    operation: "column",
};

const workflowNodes = [
    {
        id: "started",
        x: 25,
        y: 245,
        title: "Run starts",
        state: "STARTED",
        tone: "normal",
        context: { api: "Pinned API inputs", database: "Pinned database inputs" },
        summary: "The gate creates a durable run before any model or observer executes.",
        trigger: "A caller starts one configured scenario from an authoritative brief.",
        persists: ["Original brief", "Pinned Git commit", "Scenario identifier", "STARTED state"],
        facts: {
            api: ["Workspace export authorization scenario", "Two declared behavior decisions"],
            database: ["Share-link expiration scenario", "One declared rollout decision"],
        },
        routes: [{ label: "Create attempt one", target: "Attempt one", tone: "normal" }],
    },
    {
        id: "attempt1",
        x: 205,
        y: 245,
        title: "Attempt one",
        state: "STARTED",
        tone: "normal",
        context: { api: "Fresh Python artifact", database: "Fresh SQL migration" },
        summary: "A fresh coding process receives the original brief and technical context.",
        trigger: "The persisted run is in STARTED and has no earlier coding attempt.",
        persists: ["Clean worktree record", "Coding prompt", "Model provenance", "Artifact digest"],
        facts: {
            api: ["Creates a Python handler", "Receives no owner decisions"],
            database: ["Creates a PostgreSQL migration", "Receives no owner decisions"],
        },
        routes: [
            { label: "Artifact executes", target: "Observe attempt one", tone: "normal" },
            { label: "Any execution error", target: "FAILED", tone: "failed" },
        ],
    },
    {
        id: "observe1",
        x: 385,
        y: 245,
        title: "Observe effects",
        state: "STARTED",
        tone: "normal",
        context: { api: "Four bounded calls", database: "Transactional row probe" },
        summary: "A bounded observer records system effects without relying on the coding model's explanation.",
        trigger: "Attempt one produced a non-empty artifact that can be executed by the scenario observer.",
        persists: ["Normalized facts", "Observed effects", "Typed outcomes", "Attempt completion time"],
        facts: {
            api: ["Owner called twice with shared state", "Administrator and member called once"],
            database: ["Existing row seeded before migration", "New row inserted and probe rolled back"],
        },
        routes: [{ label: "Observation recorded", target: "Validate outcomes", tone: "normal" }],
    },
    {
        id: "outcomes",
        x: 565,
        y: 245,
        title: "Validate outcomes",
        state: "STARTED",
        tone: "normal",
        context: { api: "Two outcome identifiers", database: "One outcome identifier" },
        summary: "The gate checks that every declared decision has exactly one covered or unmodeled outcome.",
        trigger: "Attempt one has a completed observation with normalized outcomes.",
        persists: ["Outcome identifiers", "Coverage-gap facts when present", "Validation error when invalid"],
        facts: {
            api: ["Administrator access outcome", "Repeated owner request outcome"],
            database: ["Existing-link expiration outcome", "New-link expiration remains required"],
        },
        routes: [
            { label: "All outcomes modeled", target: "Evidence review", tone: "normal" },
            { label: "Any UNMODELED outcome", target: "COVERAGE_GAP", tone: "gap" },
            { label: "Missing, extra, or undeclared outcome", target: "FAILED", tone: "failed" },
        ],
    },
    {
        id: "coverage_gap",
        x: 565,
        y: 30,
        title: "Coverage gap",
        state: "COVERAGE_GAP",
        tone: "gap",
        context: { api: "Unsupported API effect", database: "Unsupported row effect" },
        summary: "An unmodeled first-attempt effect ends the product workflow without becoming a human product decision.",
        trigger: "At least one first-attempt outcome is explicitly reported as UNMODELED.",
        persists: ["Coverage-gap record", "Normalized facts and effects", "Artifact digest", "Attempt number"],
        facts: {
            api: ["Example: repeated owner request returns an unsupported result", "No evidence review or owner request runs"],
            database: ["Example: a new link doesn't receive required expiration", "No evidence review or owner request runs"],
        },
        routes: [{ label: "Separate platform review", target: "Outside the product run", tone: "gap" }],
    },
    {
        id: "review",
        x: 745,
        y: 245,
        title: "Review evidence",
        state: "STARTED",
        tone: "normal",
        context: { api: "Two independent reviews", database: "One independent review" },
        summary: "Each modeled choice is reviewed independently against the original brief.",
        trigger: "Every first-attempt outcome matches a declared option and no coverage gap exists.",
        persists: ["Reviewer prompt per decision", "Evidence classification", "Evidence quote", "Reviewer provenance"],
        facts: {
            api: ["Administrator and repeat behavior reviewed separately", "One contradiction fails the complete run"],
            database: ["Existing-link rollout policy reviewed", "New-link expiration is already specified"],
        },
        routes: [
            { label: "All decisions SUPPORTED", target: "COMPLETED", tone: "complete" },
            { label: "Any NOT_EVIDENCED or UNCERTAIN", target: "AWAITING_OWNER", tone: "owner" },
            { label: "Any CONTRADICTED", target: "FAILED", tone: "failed" },
        ],
    },
    {
        id: "completed_first",
        x: 745,
        y: 30,
        title: "Review complete",
        state: "COMPLETED",
        tone: "complete",
        context: { api: "Both choices supported", database: "Rollout choice supported" },
        summary: "The first artifact completes the run when the brief supports every observed choice.",
        trigger: "Every evidence review returns SUPPORTED.",
        persists: ["Completed decision records", "Attempt-one artifact digest", "COMPLETED state"],
        facts: {
            api: ["No owner answers are needed", "No second coding attempt runs"],
            database: ["No owner answer is needed", "No second migration attempt runs"],
        },
        routes: [{ label: "Terminal state", target: "No further product transition", tone: "complete" }],
    },
    {
        id: "awaiting_owner",
        x: 925,
        y: 245,
        title: "Request decisions",
        state: "AWAITING_OWNER",
        tone: "owner",
        context: { api: "Up to two owner answers", database: "One owner answer" },
        summary: "The gate presents every unsupported or uncertain product choice in one durable pause.",
        trigger: "At least one review is NOT_EVIDENCED or UNCERTAIN and none is CONTRADICTED.",
        persists: ["Typed decision requests", "Available options", "Each submitted answer", "Answer timestamps"],
        facts: {
            api: ["Administrator access decision", "Repeated owner request decision"],
            database: ["Preserve or expire existing links", "Only one answer is required"],
        },
        routes: [
            { label: "Required answers remain", target: "AWAITING_OWNER", tone: "owner" },
            { label: "All required answers recorded", target: "READY_TO_RESUME", tone: "normal" },
        ],
    },
    {
        id: "ready",
        x: 1105,
        y: 245,
        title: "Ready to resume",
        state: "READY_TO_RESUME",
        tone: "normal",
        context: { api: "Complete two-decision set", database: "Complete one-decision set" },
        summary: "Recording the final required answer completes the decision set without invoking a model.",
        trigger: "Every decision that requires an owner has one selected option.",
        persists: ["Complete selected decision set", "READY_TO_RESUME state"],
        facts: {
            api: ["Both API behavior choices are fixed", "One resume operation covers both choices"],
            database: ["Existing-link rollout policy is fixed", "The required new-link behavior remains unchanged"],
        },
        routes: [{ label: "Resume run", target: "Attempt two", tone: "normal" }],
    },
    {
        id: "attempt2",
        x: 1105,
        y: 455,
        title: "Attempt two",
        state: "READY_TO_RESUME",
        tone: "normal",
        context: { api: "Fresh Python artifact", database: "Fresh SQL migration" },
        summary: "A clean coding process receives the original inputs and completed decision set.",
        trigger: "The run is READY_TO_RESUME and contains exactly one completed first attempt.",
        persists: ["Second clean worktree", "Prompt with owner decisions", "Second artifact digest", "Model provenance"],
        facts: {
            api: ["Receives both selected API outcomes", "Doesn't receive attempt one's artifact"],
            database: ["Receives the selected rollout policy", "Doesn't receive attempt one's migration"],
        },
        routes: [
            { label: "Artifact executes", target: "Verify outcomes", tone: "normal" },
            { label: "Any execution error", target: "FAILED", tone: "failed" },
        ],
    },
    {
        id: "verify",
        x: 925,
        y: 455,
        title: "Verify outcomes",
        state: "READY_TO_RESUME",
        tone: "normal",
        context: { api: "Compare two outcomes", database: "Compare one outcome" },
        summary: "The same observer compares every fresh outcome with the complete expected decision set.",
        trigger: "Attempt two produced a completed observation.",
        persists: ["Second observation", "Expected and observed outcomes", "Coverage event for second-attempt UNMODELED"],
        facts: {
            api: ["Selected answers override unsupported attempt-one choices", "Supported choices retain their observed value"],
            database: ["Existing-link policy must match the answer", "New links must still expire after 30 days"],
        },
        routes: [
            { label: "Every expected outcome matches", target: "COMPLETED", tone: "complete" },
            { label: "Missing, extra, mismatched, or UNMODELED", target: "FAILED", tone: "failed" },
        ],
    },
    {
        id: "completed_verified",
        x: 745,
        y: 455,
        title: "Verified complete",
        state: "COMPLETED",
        tone: "complete",
        context: { api: "Both outcomes match", database: "Rollout outcome matches" },
        summary: "The run completes only when the fresh artifact matches every expected outcome.",
        trigger: "Attempt two returns exactly the expected outcome for every declared decision.",
        persists: ["Both attempt records", "Verified decision set", "COMPLETED state"],
        facts: {
            api: ["Administrator behavior matches", "Repeated owner behavior matches"],
            database: ["Existing-link policy matches", "New-link expiration remains correct"],
        },
        routes: [{ label: "Terminal state", target: "No further product transition", tone: "complete" }],
    },
    {
        id: "failed",
        x: 565,
        y: 625,
        title: "Run fails",
        state: "FAILED",
        tone: "failed",
        context: { api: "Execution or behavior failure", database: "Execution or migration failure" },
        summary: "The gate records a terminal failure when execution, evidence, or verification violates the workflow contract.",
        trigger: "An attempt errors, outcomes are invalid, evidence is contradicted, or attempt two doesn't match.",
        persists: ["Failure message", "Available attempt evidence", "Artifact digest when available", "FAILED state"],
        facts: {
            api: ["Examples: container error or mismatched API outcome", "A second-attempt UNMODELED result is a mismatch"],
            database: ["Examples: invalid migration or mismatched row effect", "A second-attempt UNMODELED result is a mismatch"],
        },
        routes: [{ label: "Terminal state", target: "No automatic retry", tone: "failed" }],
    },
];

const workflowEdges = [
    { path: "M185 281 L205 281", label: "", x: 195, y: 265, tone: "normal" },
    { path: "M365 281 L385 281", label: "", x: 375, y: 265, tone: "normal" },
    { path: "M545 281 L565 281", label: "", x: 555, y: 265, tone: "normal" },
    { path: "M725 281 L745 281", label: "", x: 735, y: 265, tone: "normal" },
    { path: "M645 245 L645 102", label: "UNMODELED", x: 645, y: 174, tone: "gap" },
    { path: "M645 317 L645 625", label: "Invalid outcome set", x: 645, y: 472, tone: "failed" },
    { path: "M285 317 L285 590 L605 590 L605 625", label: "Execution error", x: 400, y: 574, tone: "failed" },
    { path: "M825 245 L825 102", label: "All supported", x: 825, y: 174, tone: "complete" },
    { path: "M905 281 L925 281", label: "Needs owner", x: 915, y: 225, tone: "owner" },
    { path: "M825 317 L825 570 L685 570 L685 625", label: "Contradicted", x: 790, y: 554, tone: "failed" },
    { path: "M965 245 C965 180 1045 180 1045 245", label: "Partial answers", x: 1005, y: 181, tone: "owner" },
    { path: "M1085 281 L1105 281", label: "All answered", x: 1095, y: 225, tone: "normal" },
    { path: "M1185 317 L1185 455", label: "Resume", x: 1185, y: 386, tone: "normal" },
    { path: "M1105 491 L1085 491", label: "Fresh result", x: 1095, y: 435, tone: "normal" },
    { path: "M925 491 L905 491", label: "Exact match", x: 915, y: 435, tone: "complete" },
    { path: "M1185 527 L1185 606 L725 606 L725 661", label: "Execution error", x: 1090, y: 590, tone: "failed" },
    { path: "M1005 527 L1005 582 L705 582 L705 625", label: "Mismatch", x: 900, y: 566, tone: "failed" },
];

const structureOperations = {
    column: {
        label: "Add column",
        rule: "schema_shape",
        kind: "COLUMN",
        identity: "public.share_links.expires_at",
        attribute: "data_type",
        before: "not present",
        after: "timestamp with time zone",
        summary: "A catalog fact appears for the new column and its observed attributes.",
    },
    nullability: {
        label: "Change nullability",
        rule: "schema_shape",
        kind: "COLUMN",
        identity: "public.share_links.token",
        attribute: "nullable",
        before: "true",
        after: "false",
        summary: "The same schema rule reports a changed attribute on an existing column.",
    },
    foreignKey: {
        label: "Add foreign key",
        rule: "data_integrity",
        kind: "CONSTRAINT",
        identity: "public.share_links.share_links_item_id_fkey",
        attribute: "definition",
        before: "not present",
        after: "FOREIGN KEY item_id REFERENCES items id",
        summary: "The integrity rule detects the new relationship from the final catalog state.",
    },
    unique: {
        label: "Add unique constraint",
        rule: "data_integrity",
        kind: "CONSTRAINT",
        identity: "public.share_links.share_links_token_key",
        attribute: "definition",
        before: "not present",
        after: "UNIQUE token",
        summary: "The integrity rule covers a different constraint without changing the gate.",
    },
    index: {
        label: "Create index",
        rule: "indexing",
        kind: "INDEX",
        identity: "public.share_links_created_at_idx",
        attribute: "definition",
        before: "not present",
        after: "CREATE INDEX ON share_links created_at",
        summary: "The indexing rule records the added index definition and uniqueness.",
    },
};

const appTabs = document.querySelector(".app-tabs");
const appMain = document.querySelector(".app-main");
const workflowScenarioTabs = document.querySelector(".workflow-example-switch");
const workflowScenarioName = document.querySelector("#workflow-scenario-name");
const workflowScenarioDetail = document.querySelector("#workflow-scenario-detail");
const workflowCanvas = document.querySelector("#workflow-canvas");
const workflowInspector = document.querySelector("#workflow-inspector");
const walkthroughScenarioTabs = document.querySelector(".walkthrough-scenario-tabs");
const scenarioName = document.querySelector("#scenario-name");
const stageRail = document.querySelector("#stage-rail");
const stageContent = document.querySelector("#stage-content");
const gapToggle = document.querySelector("#coverage-gap-toggle");

function statusPill(label, tone = "neutral") {
    return `<span class="status-pill status-${tone}"><span aria-hidden="true"></span>${label}</span>`;
}

function workflowStatusTone(tone) {
    return { normal: "blue", owner: "amber", complete: "green", gap: "violet", failed: "red" }[tone];
}

function workflowEdgeMarkup(edge) {
    const labelWidth = Math.max(58, edge.label.length * 6.2 + 18);
    const label = edge.label ? `
        <g class="workflow-edge-label workflow-edge-label-${edge.tone}" transform="translate(${edge.x} ${edge.y})">
            <rect x="${-labelWidth / 2}" y="-10" width="${labelWidth}" height="20" rx="6"></rect>
            <text text-anchor="middle" dominant-baseline="central">${edge.label}</text>
        </g>
    ` : "";
    return `
        <path class="workflow-edge-line workflow-edge-${edge.tone}" d="${edge.path}" marker-end="url(#workflow-arrow-${edge.tone})"></path>
        ${label}
    `;
}

function workflowNodeMarkup(node) {
    const selected = node.id === state.workflowNode;
    return `
        <button
            class="workflow-node workflow-node-${node.tone} ${selected ? "workflow-node-selected" : ""}"
            type="button"
            data-workflow-node="${node.id}"
            aria-pressed="${selected}"
            aria-controls="workflow-inspector"
            style="left: ${node.x}px; top: ${node.y}px"
        >
            <span class="workflow-node-state">${node.state}</span>
            <strong>${node.title}</strong>
            <small>${node.context[state.scenario]}</small>
        </button>
    `;
}

function renderWorkflowInspector() {
    const node = workflowNodes.find((item) => item.id === state.workflowNode) || workflowNodes[0];
    const exampleLabel = state.scenario === "api" ? "API example" : "Database example";
    const persisted = node.persists.map((item) => `<li>${item}</li>`).join("");
    const facts = node.facts[state.scenario].map((item) => `<li>${item}</li>`).join("");
    const routes = node.routes.map((route) => `
        <div class="workflow-route workflow-route-${route.tone}">
            <span>${route.label}</span>
            <strong>${route.target}</strong>
        </div>
    `).join("");

    workflowInspector.innerHTML = `
        <div class="workflow-inspector-header">
            <div>
                <div class="workflow-inspector-title">
                    ${statusPill(node.state, workflowStatusTone(node.tone))}
                    <h2>${node.title}</h2>
                </div>
                <p>${node.summary}</p>
            </div>
            <span class="workflow-example-label">${exampleLabel}</span>
        </div>
        <div class="workflow-inspector-grid">
            <article>
                <h3>Entry condition</h3>
                <p>${node.trigger}</p>
            </article>
            <article>
                <h3>Persisted evidence</h3>
                <ul>${persisted}</ul>
            </article>
            <article>
                <h3>${exampleLabel} facts</h3>
                <ul>${facts}</ul>
            </article>
        </div>
        ${workflowObservationDetails(node.id)}
        <div class="workflow-routes">
            <h3>Possible next routes</h3>
            <div>${routes}</div>
        </div>
    `;
}

function scrollToWorkflowInspector() {
    const behavior = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
    const block = workflowInspector.offsetHeight < appMain.clientHeight ? "end" : "start";
    workflowInspector.scrollIntoView({ behavior, block });
}

function renderWorkflow() {
    const markerTones = ["normal", "owner", "complete", "gap", "failed"];
    const markers = markerTones.map((tone) => `
        <marker id="workflow-arrow-${tone}" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="8" markerHeight="8" orient="auto-start-reverse">
            <path class="workflow-arrow-head workflow-arrow-head-${tone}" d="M0 0 L8 4 L0 8 Z"></path>
        </marker>
    `).join("");
    const edges = workflowEdges.map(workflowEdgeMarkup).join("");
    const nodes = workflowNodes.map(workflowNodeMarkup).join("");

    workflowCanvas.innerHTML = `
        <svg class="workflow-edges" viewBox="0 0 1340 720" aria-hidden="true">
            <defs>${markers}</defs>
            ${edges}
        </svg>
        <div class="workflow-nodes">${nodes}</div>
    `;

    workflowScenarioName.textContent = state.scenario === "api"
        ? "Workspace export authorization"
        : "Share-link expiration";
    workflowScenarioDetail.textContent = state.scenario === "api"
        ? "Two independent API behavior decisions"
        : "One database rollout decision";
    workflowScenarioTabs.querySelectorAll("[data-workflow-scenario]").forEach((button) => {
        button.setAttribute("aria-selected", String(button.dataset.workflowScenario === state.scenario));
    });
    renderWorkflowInspector();
}

function hasCompleteDecisionSet() {
    if (state.scenario === "database") return Boolean(state.expiration);
    return Boolean(state.administrator && state.repeat);
}

function verificationHelp() {
    if (state.scenario === "database") {
        return "Choose an answer in step 4 to enable verification.";
    }
    return "Choose an answer for both questions in step 4 to enable verification.";
}

function renderRail() {
    const steps = state.coverageGap ? gapSteps : normalSteps;
    const activeIndex = steps.findIndex((step) => step.id === state.step);
    stageRail.innerHTML = steps.map((step, index) => {
        const status = index < activeIndex ? "complete" : index === activeIndex ? "active" : "upcoming";
        const locked = !state.coverageGap && step.id === "verify" && !hasCompleteDecisionSet();
        const help = verificationHelp();
        return `
            <span class="stage-step-slot ${locked ? "has-tooltip" : ""}">
                <button
                    class="stage-step stage-${status}"
                    type="button"
                    data-step="${step.id}"
                    data-locked="${locked}"
                    aria-disabled="${locked}"
                    aria-current="${status === "active" ? "step" : "false"}"
                    ${locked ? "aria-describedby=\"verify-step-help\"" : ""}
                >
                    <span class="step-marker">${index + 1}</span>
                    <span>${step.label}</span>
                </button>
                ${locked ? `<span class="stage-tooltip" id="verify-step-help" role="tooltip">${help}</span>` : ""}
            </span>
        `;
    }).join("");

    const activeButton = stageRail.querySelector(".stage-active");
    if (activeButton) {
        stageRail.scrollLeft = activeButton.offsetLeft - (stageRail.clientWidth - activeButton.offsetWidth) / 2;
    }
}

function stageHeading(status, tone, title) {
    return `<div class="stage-heading"><div>${statusPill(status, tone)}<h2>${title}</h2></div></div>`;
}

function apiBriefStage() {
    return `
        ${stageHeading("STARTED", "neutral", "The brief defines required behavior, but leaves two choices open.")}
        <div class="split-grid">
            <article class="content-card brief-card">
                <blockquote>Add workspace export creation.<br><br>When no export job exists, workspace owners must receive 202 and create one export job. Workspace members must be denied with 403 and create no export job.</blockquote>
            </article>
            <article class="content-card">
                <div class="open-question"><span>?</span><p>Can an administrator create an export?</p></div>
                <div class="open-question"><span>?</span><p>What happens when an owner requests another export?</p></div>
                <p class="card-note">The generated handler must still choose both behaviors.</p>
            </article>
        </div>
        <div class="stage-actions"><span></span><button class="button button-primary" type="button" data-next="observe">Observe attempt one</button></div>
    `;
}

function apiObservationRows() {
    const repeatStatus = state.coverageGap ? "200" : "202";
    return `
        <div class="observation-row"><span class="role-dot owner"></span><strong>Owner, first request</strong><code>HTTP 202</code><span>+1 job</span></div>
        <div class="observation-row ${state.coverageGap ? "row-warning" : ""}"><span class="role-dot repeat"></span><strong>Owner, repeated request</strong><code>HTTP ${repeatStatus}</code><span>+0 jobs</span></div>
        <div class="observation-row"><span class="role-dot admin"></span><strong>Administrator</strong><code>HTTP 403</code><span>+0 jobs</span></div>
        <div class="observation-row"><span class="role-dot member"></span><strong>Member</strong><code>HTTP 403</code><span>+0 jobs</span></div>
    `;
}

function apiObserveStage() {
    const repeatOutcome = state.coverageGap ? "UNMODELED" : "REUSE_ACTIVE_EXPORT";
    return `
        ${stageHeading("OBSERVED", "blue", "The observer measures effects instead of asking the agent what it intended.")}
        <div class="split-grid split-observe">
            <article class="content-card code-panel">
                <div class="card-top"><span>attempt-1.py</span></div>
                <pre><code>def create_export(role, export_jobs):
    if role != "owner":
        return 403
    if export_jobs:
        return ${state.coverageGap ? "200" : "202"}
    export_jobs.append("queued")
    return 202</code></pre>
            </article>
            <article class="content-card">
                <div class="observation-list">${apiObservationRows()}</div>
            </article>
        </div>
        <div class="outcome-strip">
            <div><span>Administrator access</span><strong>OWNER_ONLY</strong></div>
            <div><span>Repeated request</span><strong class="${state.coverageGap ? "text-warning" : ""}">${repeatOutcome}</strong></div>
        </div>
        <div class="stage-actions"><button class="button button-secondary" type="button" data-back="brief">Back</button><button class="button button-primary" type="button" data-next="${state.coverageGap ? "gap" : "review"}">${state.coverageGap ? "Record coverage gap" : "Review against brief"}</button></div>
    `;
}

function apiReviewStage() {
    return `
        ${stageHeading("NOT_EVIDENCED", "amber", "Each observed choice is reviewed independently against the original brief.")}
        <div class="decision-grid">
            <article class="decision-card">
                <div class="decision-top"><span>Decision 01</span>${statusPill("NOT_EVIDENCED", "amber")}</div>
                <h3>Administrator access</h3>
                <p>Observed: <code>OWNER_ONLY</code></p>
                <div class="evidence-box"><span>Brief evidence</span><strong>No supporting passage</strong></div>
            </article>
            <article class="decision-card">
                <div class="decision-top"><span>Decision 02</span>${statusPill("NOT_EVIDENCED", "amber")}</div>
                <h3>Repeated owner request</h3>
                <p>Observed: <code>REUSE_ACTIVE_EXPORT</code></p>
                <div class="evidence-box"><span>Brief evidence</span><strong>No supporting passage</strong></div>
            </article>
        </div>
        <div class="logic-note"><span class="logic-icon" aria-hidden="true">i</span><p>The gate aggregates both unsupported choices into one durable human pause.</p></div>
        <div class="stage-actions"><button class="button button-secondary" type="button" data-back="observe">Back</button><button class="button button-primary" type="button" data-next="answer">Open decision request</button></div>
    `;
}

function choice(name, value, label, detail, selected) {
    return `
        <label class="choice ${selected ? "choice-selected" : ""}">
            <input type="radio" name="${name}" value="${value}" ${selected ? "checked" : ""}>
            <span class="choice-control" aria-hidden="true"></span>
            <span><strong>${label}</strong><small>${detail}</small></span>
        </label>
    `;
}

function apiAnswerStage() {
    const ready = hasCompleteDecisionSet();
    return `
        ${stageHeading(ready ? "READY_TO_RESUME" : "AWAITING_OWNER", ready ? "green" : "amber", "Answer both product questions before a fresh attempt can start.")}
        <div class="decision-grid">
            <fieldset class="choice-group">
                <legend><span>01</span>Who can create workspace exports?</legend>
                ${choice("administrator", "OWNER_ONLY", "Owners only", "Administrators receive 403 and create no job.", state.administrator === "OWNER_ONLY")}
                ${choice("administrator", "OWNER_AND_ADMIN", "Owners and administrators", "Administrators receive 202 and create one job.", state.administrator === "OWNER_AND_ADMIN")}
            </fieldset>
            <fieldset class="choice-group">
                <legend><span>02</span>What should a repeated owner request do?</legend>
                ${choice("repeat", "REUSE_ACTIVE_EXPORT", "Reuse active export", "Return 202 without creating another job.", state.repeat === "REUSE_ACTIVE_EXPORT")}
                ${choice("repeat", "CREATE_ANOTHER_EXPORT", "Create another export", "Return 202 and create one additional job.", state.repeat === "CREATE_ANOTHER_EXPORT")}
            </fieldset>
        </div>
        <div class="stage-actions"><button class="button button-secondary" type="button" data-back="review">Back</button><button class="button button-primary" type="button" data-next="verify" ${ready ? "" : "disabled"}>Start fresh attempt</button></div>
    `;
}

function apiVerifyStage() {
    const adminAllowed = state.administrator === "OWNER_AND_ADMIN";
    const repeatCreates = state.repeat === "CREATE_ANOTHER_EXPORT";
    return `
        ${stageHeading("COMPLETED", "green", "The same observer verifies every selected outcome on one fresh result.")}
        <div class="verification-layout">
            <article class="content-card">
                <div class="contract-row"><span>Administrator access</span><strong>${state.administrator}</strong></div>
                <div class="contract-row"><span>Repeated request</span><strong>${state.repeat}</strong></div>
                <div class="fresh-attempt"><span>Fresh process</span><span>Clean worktree</span><span>Original brief</span><span>Both answers</span></div>
            </article>
            <article class="content-card verification-card">
                <div class="verify-row"><span>First owner request</span><code>202 / +1</code>${statusPill("MATCH", "green")}</div>
                <div class="verify-row"><span>Repeated owner request</span><code>202 / +${repeatCreates ? "1" : "0"}</code>${statusPill("MATCH", "green")}</div>
                <div class="verify-row"><span>Administrator</span><code>${adminAllowed ? "202 / +1" : "403 / +0"}</code>${statusPill("MATCH", "green")}</div>
                <div class="verify-row"><span>Member</span><code>403 / +0</code>${statusPill("MATCH", "green")}</div>
            </article>
        </div>
        <div class="completion-banner"><span class="completion-check" aria-hidden="true">✓</span><div><strong>Every expected outcome matches.</strong><p>The verified artifact can return to the wider development loop.</p></div></div>
        <div class="stage-actions"><button class="button button-secondary" type="button" data-back="answer">Change answers</button><button class="button button-primary" type="button" data-restart>Replay from start</button></div>
    `;
}

function databaseBriefStage() {
    return `
        ${stageHeading("STARTED", "neutral", "The brief defines expiration for new links, but not existing links.")}
        <div class="split-grid">
            <article class="content-card brief-card">
                <blockquote>Add 30-day expiration to newly created item-sharing links.</blockquote>
            </article>
            <article class="content-card">
                <div class="open-question"><span>?</span><p>Should existing share links remain non-expiring or receive an expiration?</p></div>
                <p class="card-note">The migration must choose a rollout policy for existing rows.</p>
            </article>
        </div>
        <div class="stage-actions"><span></span><button class="button button-primary" type="button" data-next="observe">Observe attempt one</button></div>
    `;
}

function databaseObserveStage() {
    const newExpiration = state.coverageGap ? "NULL" : "+30 days";
    const outcome = state.coverageGap ? "UNMODELED" : "PRESERVE_EXISTING";
    return `
        ${stageHeading("OBSERVED", "blue", "The database probe measures row effects inside a rolled-back transaction.")}
        <div class="split-grid split-observe">
            <article class="content-card code-panel">
                <div class="card-top"><span>attempt-1.sql</span></div>
                <pre><code>ALTER TABLE share_links
    ADD COLUMN expires_at timestamptz;

${state.coverageGap ? "-- No default was added." : `ALTER TABLE share_links
    ALTER COLUMN expires_at
    SET DEFAULT (now() + interval '30 days');`}</code></pre>
            </article>
            <article class="content-card">
                <div class="observation-list">
                    <div class="observation-row"><span class="role-dot existing"></span><strong>Existing link</strong><code>expires_at</code><span>NULL</span></div>
                    <div class="observation-row ${state.coverageGap ? "row-warning" : ""}"><span class="role-dot created"></span><strong>New link</strong><code>expires_at</code><span>${newExpiration}</span></div>
                    <div class="observation-row"><span class="role-dot rollback"></span><strong>Probe cleanup</strong><code>transaction</code><span>rolled back</span></div>
                </div>
            </article>
        </div>
        <div class="outcome-strip outcome-strip-single">
            <div><span>Existing-link policy</span><strong class="${state.coverageGap ? "text-warning" : ""}">${outcome}</strong></div>
        </div>
        <div class="stage-actions"><button class="button button-secondary" type="button" data-back="brief">Back</button><button class="button button-primary" type="button" data-next="${state.coverageGap ? "gap" : "review"}">${state.coverageGap ? "Record coverage gap" : "Review against brief"}</button></div>
    `;
}

function databaseReviewStage() {
    return `
        ${stageHeading("NOT_EVIDENCED", "amber", "The observed rollout choice isn't supported by the original brief.")}
        <div class="decision-grid decision-grid-single">
            <article class="decision-card">
                <div class="decision-top"><span>Decision 01</span>${statusPill("NOT_EVIDENCED", "amber")}</div>
                <h3>Existing share-link expiration</h3>
                <p>Observed: <code>PRESERVE_EXISTING</code></p>
                <div class="evidence-box"><span>Brief evidence</span><strong>No supporting passage</strong></div>
            </article>
        </div>
        <div class="logic-note"><span class="logic-icon" aria-hidden="true">i</span><p>The gate pauses because the migration selected a policy that the brief didn't define.</p></div>
        <div class="stage-actions"><button class="button button-secondary" type="button" data-back="observe">Back</button><button class="button button-primary" type="button" data-next="answer">Open decision request</button></div>
    `;
}

function databaseAnswerStage() {
    const ready = hasCompleteDecisionSet();
    return `
        ${stageHeading(ready ? "READY_TO_RESUME" : "AWAITING_OWNER", ready ? "green" : "amber", "Choose the policy for existing share links before a fresh attempt can start.")}
        <div class="decision-grid decision-grid-single">
            <fieldset class="choice-group">
                <legend><span>01</span>What should happen to existing links?</legend>
                ${choice("expiration", "PRESERVE_EXISTING", "Preserve existing links", "Existing links remain non-expiring. New links expire after 30 days.", state.expiration === "PRESERVE_EXISTING")}
                ${choice("expiration", "EXPIRE_EXISTING", "Expire existing links", "Existing and new links receive an expiration.", state.expiration === "EXPIRE_EXISTING")}
            </fieldset>
        </div>
        <div class="stage-actions"><button class="button button-secondary" type="button" data-back="review">Back</button><button class="button button-primary" type="button" data-next="verify" ${ready ? "" : "disabled"}>Start fresh attempt</button></div>
    `;
}

function databaseVerifyStage() {
    const expiresExisting = state.expiration === "EXPIRE_EXISTING";
    return `
        ${stageHeading("COMPLETED", "green", "The database probe verifies the selected rollout policy on a fresh migration.")}
        <div class="verification-layout">
            <article class="content-card">
                <div class="contract-row"><span>Existing-link policy</span><strong>${state.expiration}</strong></div>
                <div class="fresh-attempt"><span>Fresh process</span><span>Clean worktree</span><span>Original brief</span><span>Owner answer</span></div>
            </article>
            <article class="content-card verification-card">
                <div class="verify-row"><span>Existing link</span><code>${expiresExisting ? "+30 days" : "NULL"}</code>${statusPill("MATCH", "green")}</div>
                <div class="verify-row"><span>New link</span><code>+30 days</code>${statusPill("MATCH", "green")}</div>
                <div class="verify-row"><span>Probe cleanup</span><code>rolled back</code>${statusPill("MATCH", "green")}</div>
            </article>
        </div>
        <div class="completion-banner"><span class="completion-check" aria-hidden="true">✓</span><div><strong>Every expected outcome matches.</strong><p>The verified migration can return to the wider development loop.</p></div></div>
        <div class="stage-actions"><button class="button button-secondary" type="button" data-back="answer">Change answer</button><button class="button button-primary" type="button" data-restart>Replay from start</button></div>
    `;
}

function gapStage() {
    const database = state.scenario === "database";
    const event = database ? `{
  "decision_id": "existing_share_link_expiration",
  "observed": "UNMODELED",
  "attempt_number": 1,
  "facts": {
    "existing_link_expires_at": null,
    "new_link_expires_at": null
  }
}` : `{
  "decision_id": "workspace_export_repeat_request",
  "observed": "UNMODELED",
  "attempt_number": 1,
  "facts": {
    "repeat_owner_status": 200,
    "repeat_owner_jobs_created": 0
  }
}`;
    return `
        ${stageHeading("COVERAGE_GAP", "violet", "An unsupported observation stops the product workflow without becoming a product decision.")}
        <div class="gap-layout">
            <article class="content-card event-card">
                <div class="card-top"><span>run.json</span></div>
                <pre><code>${event}</code></pre>
            </article>
            <div class="gap-route" aria-label="Coverage gap route">
                <div class="route-node route-stop"><span>1</span><div><strong>Product run stops</strong><p>No evidence review, owner request, or retry.</p></div></div>
                <div class="route-line"></div>
                <div class="route-node"><span>2</span><div><strong>Evidence remains durable</strong><p>Facts, artifact digest, attempt, and commit are retained.</p></div></div>
                <div class="route-line route-line-dashed"></div>
                <div class="route-node route-later"><span>3</span><div><strong>Platform review happens later</strong><p>Coverage can change only through a separate engineering process.</p></div></div>
            </div>
        </div>
        <div class="stage-actions"><button class="button button-secondary" type="button" data-back="observe">Back</button><button class="button button-primary" type="button" data-restart>Replay modeled path</button></div>
    `;
}

function renderStage() {
    const apiStages = {
        brief: apiBriefStage,
        observe: apiObserveStage,
        review: apiReviewStage,
        answer: apiAnswerStage,
        verify: apiVerifyStage,
        gap: gapStage,
    };
    const databaseStages = {
        brief: databaseBriefStage,
        observe: databaseObserveStage,
        review: databaseReviewStage,
        answer: databaseAnswerStage,
        verify: databaseVerifyStage,
        gap: gapStage,
    };
    const stages = state.scenario === "database" ? databaseStages : apiStages;
    stageContent.innerHTML = stages[state.step]();
    renderRail();
}

function observerFlow(cards) {
    return `<div class="observer-flow">${cards.map((card, index) => `
        ${index ? '<span class="observer-flow-arrow" aria-hidden="true">→</span>' : ""}
        <article class="observer-stage ${card.result ? "observer-stage-result" : ""}">
            <span class="observer-stage-index">0${index + 1}</span>
            <h4>${card.title}</h4>
            <p>${card.description}</p>
            <code>${card.output}</code>
        </article>
    `).join("")}</div>`;
}

function observerSummary(title, detail) {
    return `<div class="observer-summary"><strong>${title}</strong><span>${detail}</span></div>`;
}

function databaseStructureExample() {
    const operation = structureOperations[state.operation];
    const operationButtons = Object.entries(structureOperations).map(([id, item]) => `
        <button type="button" data-operation="${id}" class="operation-button ${id === state.operation ? "operation-active" : ""}" aria-pressed="${id === state.operation}">${item.label}</button>
    `).join("");
    return `
        <div class="operation-picker" role="group" aria-label="Database operation">${operationButtons}</div>
        <div class="structure-grid">
            <article class="content-card diff-card">
                <div class="effect-header"><span class="effect-change">${operation.before === "not present" ? "ADDED" : "CHANGED"}</span><strong>${operation.kind}</strong></div>
                <dl class="effect-details">
                    <div><dt>Identity</dt><dd>${operation.identity}</dd></div>
                    <div><dt>Attribute</dt><dd>${operation.attribute}</dd></div>
                    <div><dt>Before</dt><dd>${operation.before}</dd></div>
                    <div><dt>After</dt><dd>${operation.after}</dd></div>
                </dl>
            </article>
            <article class="rule-result">
                <strong>${operation.rule}</strong>
                <p>${operation.summary}</p>
                <div class="rule-set"><span class="${operation.rule === "schema_shape" ? "rule-active" : ""}">schema_shape</span><span class="${operation.rule === "data_integrity" ? "rule-active" : ""}">data_integrity</span><span class="${operation.rule === "indexing" ? "rule-active" : ""}">indexing</span></div>
            </article>
        </div>
    `;
}

function observationMethodDetails() {
    if (state.scenario === "api") {
        const flow = observerFlow([
            {
                title: "Generated handler",
                description: "One Python function accepts a role and shared export-job state.",
                output: "create_export(role, jobs)",
            },
            {
                title: "Four bounded calls",
                description: "Call owner twice with shared state, then administrator and member.",
                output: "status + jobs_created",
            },
            {
                title: "Typed outcomes",
                description: "Normalize the measured behavior into two independent decisions.",
                output: "OWNER_ONLY + REUSE_ACTIVE_EXPORT",
                result: true,
            },
        ]);
        return `
            <section class="workflow-observation" aria-label="Observation method">
                <div class="workflow-observation-header">
                    <h3>API behavior observer</h3>
                    <p>The observer executes the generated handler in a bounded container and records effects instead of trusting the agent's explanation.</p>
                </div>
                ${flow}
                ${observerSummary("One observer produces two product outcomes.", "Every scenario returns the same normalized ObservationResult shape to the gate.")}
            </section>
        `;
    }

    const behaviorFlow = observerFlow([
        {
            title: "Seed known state",
            description: "Create an existing share link before applying the migration.",
            output: "expires_at = NULL",
        },
        {
            title: "Apply and probe",
            description: "Run the migration, insert a new link, inspect both rows, then roll back.",
            output: "transactional probe",
        },
        {
            title: "Typed outcome",
            description: "Normalize the measured rollout behavior for existing links.",
            output: "PRESERVE_EXISTING",
            result: true,
        },
    ]);
    return `
        <section class="workflow-observation" aria-label="Observation method">
            <div class="workflow-observation-header">
                <h3>PostgreSQL behavior and structure observer</h3>
                <p>The observer measures row behavior and final catalog structure inside a rolled-back transaction.</p>
            </div>
            <div class="observer-subsection">
                <div class="observer-subsection-header"><h4>Row behavior</h4><p>The gate establishes rollout policy from database effects, not from SQL text.</p></div>
                ${behaviorFlow}
            </div>
            <div class="observer-subsection observer-structure">
                <div class="observer-subsection-header"><h4>Final database structure</h4><p>Choose an operation to inspect the normalized catalog effect and reusable rule.</p></div>
                ${databaseStructureExample()}
                ${observerSummary("Three rules cover multiple structural operations.", "Structural effects are evidence. They don't create additional product decisions in this scenario.")}
            </div>
        </section>
    `;
}

function vocabularyCard(title, values, detail, gap = false) {
    const valueList = values.map((value) => `<code>${value}</code>`).join("");
    return `
        <article class="observer-vocabulary-card ${gap ? "observer-vocabulary-gap" : ""}">
            <h4>${title}</h4>
            <div>${valueList}</div>
            <p>${detail}</p>
        </article>
    `;
}

function outcomeBoundaryDetails() {
    const cards = state.scenario === "api"
        ? [
            vocabularyCard("Required baseline effects", ["owner: 202 / +1", "member: 403 / +0"], "Both baseline calls must match before either product outcome is covered."),
            vocabularyCard("Administrator access", ["OWNER_ONLY", "OWNER_AND_ADMIN"], "The administrator call must match one supported status and job-count combination."),
            vocabularyCard("Repeated owner request", ["REUSE_ACTIVE_EXPORT", "CREATE_ANOTHER_EXPORT"], "The second owner call must return 202 and create zero or one additional job."),
            vocabularyCard("Outside the boundary", ["UNMODELED"], "Any other measured status or job-count combination stops the product workflow.", true),
        ]
        : [
            vocabularyCard("Existing-link rollout", ["PRESERVE_EXISTING", "EXPIRE_EXISTING"], "The seeded row must remain NULL or receive an expiration approximately 30 days from migration."),
            vocabularyCard("Required migration effects", ["timestamptz", "nullable", "default present", "new row +30 days"], "Every schema and inserted-row effect must match before a rollout outcome is covered."),
            vocabularyCard("Outside the boundary", ["UNMODELED"], "An unsupported row effect stops the product workflow before evidence review.", true),
        ];
    return `
        <section class="workflow-observation" aria-label="Supported outcome boundary">
            <div class="workflow-observation-header">
                <h3>Supported outcome vocabulary</h3>
                <p>The gate accepts only declared outcome identifiers produced from measured effects.</p>
            </div>
            <div class="observer-vocabulary">${cards.join("")}</div>
        </section>
    `;
}

function coverageGapDetails() {
    const detail = state.scenario === "api"
        ? {
            observed: "Repeated owner: HTTP 200 / +0 jobs",
            reason: "Neither repeat option permits HTTP 200, so the observer reports UNMODELED.",
        }
        : {
            observed: "New link: expires_at = NULL",
            reason: "The required 30-day expiration isn't present, so no supported rollout outcome is valid.",
        };
    return `
        <section class="workflow-observation workflow-observation-gap" aria-label="Coverage gap evidence">
            <div class="workflow-observation-header">
                <h3>Why this observation stops the run</h3>
                <p>A coverage gap is a platform-observation problem, not a product decision for the owner.</p>
            </div>
            <div class="observer-gap-grid">
                <article><h4>Observed effect</h4><code>${detail.observed}</code></article>
                <article><h4>No supported match</h4><p>${detail.reason}</p></article>
                <article><h4>Persist for review</h4><p>Record normalized facts, effects, artifact digest, attempt number, and the pinned commit.</p></article>
            </div>
        </section>
    `;
}

function verificationObservationDetails() {
    const comparison = state.scenario === "api"
        ? {
            input: "Complete administrator + repeat decisions",
            probe: "Four bounded handler calls",
            result: "Both typed outcomes must match",
        }
        : {
            input: "Selected existing-link rollout",
            probe: "Seed, migrate, insert, inspect, roll back",
            result: "Rollout outcome and new-link expiration must match",
        };
    const flow = observerFlow([
        { title: "Expected decisions", description: "Load the complete owner-approved decision set.", output: comparison.input },
        { title: "Run the same observer", description: "Measure the fresh artifact with the original bounded probe.", output: comparison.probe },
        { title: "Exact comparison", description: "Complete only when every fresh outcome equals its expected value.", output: comparison.result, result: true },
    ]);
    return `
        <section class="workflow-observation" aria-label="Verification observation">
            <div class="workflow-observation-header">
                <h3>Reuse the same observer</h3>
                <p>The second attempt is verified through measured effects using the same coverage boundary as attempt one.</p>
            </div>
            ${flow}
            ${observerSummary("Verification requires an exact match.", "A missing, extra, mismatched, or UNMODELED second-attempt outcome ends in FAILED.")}
        </section>
    `;
}

function workflowObservationDetails(nodeId) {
    const renderers = {
        observe1: observationMethodDetails,
        outcomes: outcomeBoundaryDetails,
        coverage_gap: coverageGapDetails,
        verify: verificationObservationDetails,
    };
    return renderers[nodeId] ? renderers[nodeId]() : "";
}

function resetWalkthrough() {
    state.step = "brief";
    state.coverageGap = false;
    state.administrator = null;
    state.repeat = null;
    state.expiration = null;
    gapToggle.setAttribute("aria-pressed", "false");
}

function setScenario(scenario) {
    if (!["api", "database"].includes(scenario) || scenario === state.scenario) return;
    state.scenario = scenario;
    resetWalkthrough();
    scenarioName.textContent = scenario === "database"
        ? "Share-link expiration"
        : "Workspace export authorization";
    walkthroughScenarioTabs.querySelectorAll("[data-scenario]").forEach((tab) => {
        tab.setAttribute("aria-selected", String(tab.dataset.scenario === scenario));
    });
    renderWorkflow();
    renderStage();
}

function renderView() {
    document.querySelectorAll("[data-view-panel]").forEach((panel) => {
        panel.hidden = panel.dataset.viewPanel !== state.view;
    });
    appTabs.querySelectorAll("[data-view]").forEach((button) => {
        button.setAttribute("aria-selected", String(button.dataset.view === state.view));
    });
}

appTabs.addEventListener("click", (event) => {
    const button = event.target.closest("[data-view]");
    if (!button) return;
    state.view = button.dataset.view;
    renderView();
});

workflowScenarioTabs.addEventListener("click", (event) => {
    const button = event.target.closest("[data-workflow-scenario]");
    if (!button) return;
    setScenario(button.dataset.workflowScenario);
});

workflowCanvas.addEventListener("click", (event) => {
    const button = event.target.closest("[data-workflow-node]");
    if (!button) return;
    state.workflowNode = button.dataset.workflowNode;
    workflowCanvas.querySelectorAll("[data-workflow-node]").forEach((node) => {
        const selected = node.dataset.workflowNode === state.workflowNode;
        node.classList.toggle("workflow-node-selected", selected);
        node.setAttribute("aria-pressed", String(selected));
    });
    renderWorkflowInspector();
    scrollToWorkflowInspector();
});

workflowInspector.addEventListener("click", (event) => {
    const button = event.target.closest("[data-operation]");
    if (!button || !structureOperations[button.dataset.operation]) return;
    state.operation = button.dataset.operation;
    renderWorkflowInspector();
});

walkthroughScenarioTabs.addEventListener("click", (event) => {
    const button = event.target.closest("[data-scenario]");
    if (!button) return;
    setScenario(button.dataset.scenario);
});

stageRail.addEventListener("click", (event) => {
    const button = event.target.closest("[data-step]");
    if (!button || button.dataset.locked === "true") return;
    state.step = button.dataset.step;
    renderStage();
});

stageContent.addEventListener("click", (event) => {
    const next = event.target.closest("[data-next]");
    const back = event.target.closest("[data-back]");
    const restart = event.target.closest("[data-restart]");
    if (!next && !back && !restart) return;
    if (next && !next.disabled) state.step = next.dataset.next;
    if (back) state.step = back.dataset.back;
    if (restart) resetWalkthrough();
    renderStage();
});

stageContent.addEventListener("change", (event) => {
    if (event.target.name === "administrator") state.administrator = event.target.value;
    if (event.target.name === "repeat") state.repeat = event.target.value;
    if (event.target.name === "expiration") state.expiration = event.target.value;
    renderStage();
});

gapToggle.addEventListener("click", () => {
    state.coverageGap = !state.coverageGap;
    state.step = state.step === "brief" ? "brief" : "observe";
    state.administrator = null;
    state.repeat = null;
    state.expiration = null;
    gapToggle.setAttribute("aria-pressed", String(state.coverageGap));
    renderStage();
});

renderView();
renderWorkflow();
renderStage();
