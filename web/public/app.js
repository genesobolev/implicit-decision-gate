"use strict";

const SOURCE_COMMIT = "9b71603bda6bb3b232a7c0da7df735e1939b34a5";

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
    step: "brief",
    coverageGap: false,
    administrator: null,
    repeat: null,
    surface: "api",
    operation: "column",
};

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

const stageRail = document.querySelector("#stage-rail");
const stageContent = document.querySelector("#stage-content");
const gapToggle = document.querySelector("#coverage-gap-toggle");
const surfaceTabs = document.querySelector("#surface-tabs");
const coverageContent = document.querySelector("#coverage-content");

function sourceLink(path, label) {
    return `<a class="source-link" href="https://github.com/genesobolev/implicit-decision-gate/blob/${SOURCE_COMMIT}/${path}" target="_blank" rel="noreferrer">${label}<span aria-hidden="true">↗</span></a>`;
}

function statusPill(label, tone = "neutral") {
    return `<span class="status-pill status-${tone}"><span aria-hidden="true"></span>${label}</span>`;
}

function renderRail() {
    const steps = state.coverageGap ? gapSteps : normalSteps;
    const activeIndex = steps.findIndex((step) => step.id === state.step);
    stageRail.innerHTML = steps.map((step, index) => {
        const status = index < activeIndex ? "complete" : index === activeIndex ? "active" : "upcoming";
        const disabled = !state.coverageGap && step.id === "verify" && (!state.administrator || !state.repeat);
        return `
            <button class="stage-step stage-${status}" type="button" data-step="${step.id}" ${disabled ? "disabled" : ""} aria-current="${status === "active" ? "step" : "false"}">
                <span class="step-marker">${index + 1}</span>
                <span>${step.label}</span>
            </button>
        `;
    }).join("");
    const activeButton = stageRail.querySelector(".stage-active");
    if (activeButton) {
        stageRail.scrollLeft = activeButton.offsetLeft - (stageRail.clientWidth - activeButton.offsetWidth) / 2;
    }
}

function briefStage() {
    return `
        <div class="stage-heading">
            <div>${statusPill("STARTED", "neutral")}<h3>The brief defines required behavior, but leaves two choices open.</h3></div>
            ${sourceLink("examples/workspace-export-authorization/brief.md", "Open brief")}
        </div>
        <div class="split-grid">
            <article class="content-card brief-card">
                <span class="card-label">Authoritative brief</span>
                <blockquote>Add workspace export creation.<br><br>When no export job exists, workspace owners must receive 202 and create one export job. Workspace members must be denied with 403 and create no export job.</blockquote>
            </article>
            <article class="content-card">
                <span class="card-label">What isn't specified</span>
                <div class="open-question"><span>?</span><p>Can an administrator create an export?</p></div>
                <div class="open-question"><span>?</span><p>What happens when an owner requests another export?</p></div>
                <p class="card-note">The generated handler must still choose both behaviors.</p>
            </article>
        </div>
        <div class="stage-actions"><span></span><button class="button button-primary" type="button" data-next="observe">Observe attempt one</button></div>
    `;
}

function observationRows() {
    const repeatStatus = state.coverageGap ? "200" : "202";
    return `
        <div class="observation-row"><span class="role-dot owner"></span><strong>Owner, first request</strong><code>HTTP 202</code><span>+1 job</span></div>
        <div class="observation-row ${state.coverageGap ? "row-warning" : ""}"><span class="role-dot repeat"></span><strong>Owner, repeated request</strong><code>HTTP ${repeatStatus}</code><span>+0 jobs</span></div>
        <div class="observation-row"><span class="role-dot admin"></span><strong>Administrator</strong><code>HTTP 403</code><span>+0 jobs</span></div>
        <div class="observation-row"><span class="role-dot member"></span><strong>Member</strong><code>HTTP 403</code><span>+0 jobs</span></div>
    `;
}

function observeStage() {
    const repeatOutcome = state.coverageGap ? "UNMODELED" : "REUSE_ACTIVE_EXPORT";
    return `
        <div class="stage-heading">
            <div>${statusPill("OBSERVED", "blue")}<h3>The observer measures effects instead of asking the agent what it intended.</h3></div>
            ${sourceLink("src/implicit_decision_gate/api_probe.py", "Open observer")}
        </div>
        <div class="split-grid split-observe">
            <article class="content-card code-panel">
                <div class="card-top"><span class="card-label">Generated artifact</span><span>attempt-1.py</span></div>
                <pre><code>def create_export(role, export_jobs):
    if role != "owner":
        return 403
    if export_jobs:
        return ${state.coverageGap ? "200" : "202"}
    export_jobs.append("queued")
    return 202</code></pre>
            </article>
            <article class="content-card">
                <span class="card-label">Observed calls</span>
                <div class="observation-list">${observationRows()}</div>
            </article>
        </div>
        <div class="outcome-strip">
            <div><span>Administrator access</span><strong>OWNER_ONLY</strong></div>
            <div><span>Repeated request</span><strong class="${state.coverageGap ? "text-warning" : ""}">${repeatOutcome}</strong></div>
        </div>
        <div class="stage-actions"><button class="button button-secondary" type="button" data-back="brief">Back</button><button class="button button-primary" type="button" data-next="${state.coverageGap ? "gap" : "review"}">${state.coverageGap ? "Record coverage gap" : "Review against brief"}</button></div>
    `;
}

function reviewStage() {
    return `
        <div class="stage-heading">
            <div>${statusPill("NOT_EVIDENCED", "amber")}<h3>Each observed choice is reviewed independently against the original brief.</h3></div>
            ${sourceLink("src/implicit_decision_gate/agent.py", "Open review contract")}
        </div>
        <div class="decision-grid">
            <article class="decision-card">
                <div class="decision-top"><span>Decision 01</span>${statusPill("NOT_EVIDENCED", "amber")}</div>
                <h4>Administrator access</h4>
                <p>Observed: <code>OWNER_ONLY</code></p>
                <div class="evidence-box"><span>Brief evidence</span><strong>No supporting passage</strong></div>
            </article>
            <article class="decision-card">
                <div class="decision-top"><span>Decision 02</span>${statusPill("NOT_EVIDENCED", "amber")}</div>
                <h4>Repeated owner request</h4>
                <p>Observed: <code>REUSE_ACTIVE_EXPORT</code></p>
                <div class="evidence-box"><span>Brief evidence</span><strong>No supporting passage</strong></div>
            </article>
        </div>
        <div class="logic-note"><span class="logic-icon">i</span><p>The gate aggregates both unsupported choices into one durable human pause.</p></div>
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

function answerStage() {
    const ready = state.administrator && state.repeat;
    return `
        <div class="stage-heading">
            <div>${statusPill(ready ? "READY_TO_RESUME" : "AWAITING_OWNER", ready ? "green" : "amber")}<h3>Answer both product questions before a fresh attempt can start.</h3></div>
            ${sourceLink("src/implicit_decision_gate/gate.py", "Open gate transition")}
        </div>
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

function verifyStage() {
    const adminAllowed = state.administrator === "OWNER_AND_ADMIN";
    const repeatCreates = state.repeat === "CREATE_ANOTHER_EXPORT";
    return `
        <div class="stage-heading">
            <div>${statusPill("COMPLETED", "green")}<h3>The same observer verifies every selected outcome on one fresh result.</h3></div>
            ${sourceLink("src/implicit_decision_gate/orchestrator.py", "Open verification")}
        </div>
        <div class="verification-layout">
            <article class="content-card">
                <span class="card-label">Completed decision set</span>
                <div class="contract-row"><span>Administrator access</span><strong>${state.administrator}</strong></div>
                <div class="contract-row"><span>Repeated request</span><strong>${state.repeat}</strong></div>
                <div class="fresh-attempt"><span>Fresh process</span><span>Clean worktree</span><span>Original brief</span><span>Both answers</span></div>
            </article>
            <article class="content-card verification-card">
                <span class="card-label">Attempt two observation</span>
                <div class="verify-row"><span>First owner request</span><code>202 / +1</code>${statusPill("MATCH", "green")}</div>
                <div class="verify-row"><span>Repeated owner request</span><code>202 / +${repeatCreates ? "1" : "0"}</code>${statusPill("MATCH", "green")}</div>
                <div class="verify-row"><span>Administrator</span><code>${adminAllowed ? "202 / +1" : "403 / +0"}</code>${statusPill("MATCH", "green")}</div>
                <div class="verify-row"><span>Member</span><code>403 / +0</code>${statusPill("MATCH", "green")}</div>
            </article>
        </div>
        <div class="completion-banner"><span class="completion-check">✓</span><div><strong>Every expected outcome matches.</strong><p>The verified artifact can return to the wider development loop.</p></div></div>
        <div class="stage-actions"><button class="button button-secondary" type="button" data-back="answer">Change answers</button><button class="button button-primary" type="button" data-restart>Replay from start</button></div>
    `;
}

function gapStage() {
    return `
        <div class="stage-heading">
            <div>${statusPill("COVERAGE_GAP", "violet")}<h3>An unsupported observation stops the product workflow without becoming a product decision.</h3></div>
            ${sourceLink("src/implicit_decision_gate/orchestrator.py", "Open coverage-gap path")}
        </div>
        <div class="gap-layout">
            <article class="content-card event-card">
                <div class="card-top"><span class="card-label">Persisted coverage event</span><span>run.json</span></div>
                <pre><code>{
  "decision_id": "workspace_export_repeat_request",
  "observed": "UNMODELED",
  "attempt_number": 1,
  "facts": {
    "repeat_owner_status": 200,
    "repeat_owner_jobs_created": 0
  }
}</code></pre>
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
    const stages = {
        brief: briefStage,
        observe: observeStage,
        review: reviewStage,
        answer: answerStage,
        verify: verifyStage,
        gap: gapStage,
    };
    stageContent.innerHTML = stages[state.step]();
    renderRail();
}

function apiCoverage() {
    return `
        <div class="coverage-flow">
            <article class="surface-card"><span class="flow-index">01</span><h3>Generated handler</h3><p>One Python function accepts a role and shared export-job state.</p><code>create_export(role, jobs)</code></article>
            <span class="flow-arrow" aria-hidden="true">→</span>
            <article class="surface-card"><span class="flow-index">02</span><h3>Four bounded calls</h3><p>Owner twice with shared state, then administrator and member.</p><code>status + jobs_created</code></article>
            <span class="flow-arrow" aria-hidden="true">→</span>
            <article class="surface-card surface-result"><span class="flow-index">03</span><h3>Two typed outcomes</h3><p><strong>OWNER_ONLY</strong><br><strong>REUSE_ACTIVE_EXPORT</strong></p><code>ObservationResult</code></article>
        </div>
        <div class="surface-summary"><strong>One observer, two product decisions.</strong><span>The gate receives the same normalized result type used by every scenario.</span>${sourceLink("src/implicit_decision_gate/api_probe.py", "Inspect API observer")}</div>
    `;
}

function databaseCoverage() {
    return `
        <div class="coverage-flow">
            <article class="surface-card"><span class="flow-index">01</span><h3>Seed known state</h3><p>Create an existing share link before applying the migration.</p><code>expires_at = NULL</code></article>
            <span class="flow-arrow" aria-hidden="true">→</span>
            <article class="surface-card"><span class="flow-index">02</span><h3>Apply and probe</h3><p>Run the migration, insert a new link, inspect both rows, then roll back.</p><code>transactional probe</code></article>
            <span class="flow-arrow" aria-hidden="true">→</span>
            <article class="surface-card surface-result"><span class="flow-index">03</span><h3>One typed outcome</h3><p><strong>PRESERVE_EXISTING</strong></p><code>rollback_verified = true</code></article>
        </div>
        <div class="surface-summary"><strong>Behavior is established from database effects.</strong><span>The observer doesn't infer rollout policy from the SQL text.</span>${sourceLink("src/implicit_decision_gate/probe.py", "Inspect database probe")}</div>
    `;
}

function structureCoverage() {
    const operation = structureOperations[state.operation];
    const operationButtons = Object.entries(structureOperations).map(([id, item]) => `
        <button type="button" data-operation="${id}" class="operation-button ${id === state.operation ? "operation-active" : ""}" aria-pressed="${id === state.operation}">${item.label}</button>
    `).join("");
    return `
        <div class="operation-picker" aria-label="Database operation">${operationButtons}</div>
        <div class="structure-grid">
            <article class="content-card diff-card">
                <span class="card-label">Observed catalog change</span>
                <div class="effect-header"><span class="effect-change">${operation.before === "not present" ? "ADDED" : "CHANGED"}</span><strong>${operation.kind}</strong></div>
                <dl class="effect-details">
                    <div><dt>Identity</dt><dd>${operation.identity}</dd></div>
                    <div><dt>Attribute</dt><dd>${operation.attribute}</dd></div>
                    <div><dt>Before</dt><dd>${operation.before}</dd></div>
                    <div><dt>After</dt><dd>${operation.after}</dd></div>
                </dl>
            </article>
            <article class="rule-result">
                <span class="card-label">Matched reusable rule</span>
                <strong>${operation.rule}</strong>
                <p>${operation.summary}</p>
                <div class="rule-set"><span class="${operation.rule === "schema_shape" ? "rule-active" : ""}">schema_shape</span><span class="${operation.rule === "data_integrity" ? "rule-active" : ""}">data_integrity</span><span class="${operation.rule === "indexing" ? "rule-active" : ""}">indexing</span></div>
            </article>
        </div>
        <div class="surface-summary"><strong>Three rules cover many structural operations.</strong><span>New rules extend observation coverage without changing the gate lifecycle.</span>${sourceLink("src/implicit_decision_gate/postgres_surface.py", "Inspect structural surface")}</div>
    `;
}

function renderCoverage() {
    const renderers = { api: apiCoverage, database: databaseCoverage, structure: structureCoverage };
    coverageContent.innerHTML = renderers[state.surface]();
    surfaceTabs.querySelectorAll("[data-surface]").forEach((button) => {
        button.setAttribute("aria-selected", String(button.dataset.surface === state.surface));
    });
}

stageRail.addEventListener("click", (event) => {
    const button = event.target.closest("[data-step]");
    if (!button || button.disabled) return;
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
    if (restart) {
        state.coverageGap = state.step === "gap" ? false : state.coverageGap;
        state.step = "brief";
        state.administrator = null;
        state.repeat = null;
        gapToggle.setAttribute("aria-pressed", String(state.coverageGap));
    }
    renderStage();
});

stageContent.addEventListener("change", (event) => {
    if (event.target.name === "administrator") state.administrator = event.target.value;
    if (event.target.name === "repeat") state.repeat = event.target.value;
    renderStage();
});

gapToggle.addEventListener("click", () => {
    state.coverageGap = !state.coverageGap;
    state.step = state.step === "brief" ? "brief" : "observe";
    state.administrator = null;
    state.repeat = null;
    gapToggle.setAttribute("aria-pressed", String(state.coverageGap));
    renderStage();
});

surfaceTabs.addEventListener("click", (event) => {
    const button = event.target.closest("[data-surface]");
    if (!button) return;
    state.surface = button.dataset.surface;
    renderCoverage();
});

coverageContent.addEventListener("click", (event) => {
    const button = event.target.closest("[data-operation]");
    if (!button) return;
    state.operation = button.dataset.operation;
    renderCoverage();
});

renderStage();
renderCoverage();
