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
    view: "walkthrough",
    scenario: "api",
    step: "brief",
    coverageGap: false,
    administrator: null,
    repeat: null,
    expiration: null,
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

const appTabs = document.querySelector(".app-tabs");
const scenarioTabs = document.querySelector(".scenario-tabs");
const scenarioName = document.querySelector("#scenario-name");
const stageRail = document.querySelector("#stage-rail");
const stageContent = document.querySelector("#stage-content");
const gapToggle = document.querySelector("#coverage-gap-toggle");
const surfaceTabs = document.querySelector("#surface-tabs");
const coverageContent = document.querySelector("#coverage-content");

function statusPill(label, tone = "neutral") {
    return `<span class="status-pill status-${tone}"><span aria-hidden="true"></span>${label}</span>`;
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
        <div class="completion-banner"><span class="completion-check" aria-hidden="true">✓</span><div><strong>Every expected outcome matches.</strong><p>The verified artifact can return to the wider development loop.</p></div></div>
        <div class="stage-actions"><button class="button button-secondary" type="button" data-back="answer">Change answers</button><button class="button button-primary" type="button" data-restart>Replay from start</button></div>
    `;
}

function databaseBriefStage() {
    return `
        ${stageHeading("STARTED", "neutral", "The brief defines expiration for new links, but not existing links.")}
        <div class="split-grid">
            <article class="content-card brief-card">
                <span class="card-label">Authoritative brief</span>
                <blockquote>Add 30-day expiration to newly created item-sharing links.</blockquote>
            </article>
            <article class="content-card">
                <span class="card-label">What isn't specified</span>
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
                <div class="card-top"><span class="card-label">Generated migration</span><span>attempt-1.sql</span></div>
                <pre><code>ALTER TABLE share_links
    ADD COLUMN expires_at timestamptz;

${state.coverageGap ? "-- No default was added." : `ALTER TABLE share_links
    ALTER COLUMN expires_at
    SET DEFAULT (now() + interval '30 days');`}</code></pre>
            </article>
            <article class="content-card">
                <span class="card-label">Observed rows</span>
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
                <span class="card-label">Completed decision set</span>
                <div class="contract-row"><span>Existing-link policy</span><strong>${state.expiration}</strong></div>
                <div class="fresh-attempt"><span>Fresh process</span><span>Clean worktree</span><span>Original brief</span><span>Owner answer</span></div>
            </article>
            <article class="content-card verification-card">
                <span class="card-label">Attempt two observation</span>
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
                <div class="card-top"><span class="card-label">Persisted coverage event</span><span>run.json</span></div>
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

function apiCoverage() {
    return `
        <div class="coverage-flow">
            <article class="surface-card"><span class="flow-index">01</span><h2>Generated handler</h2><p>One Python function accepts a role and shared export-job state.</p><code>create_export(role, jobs)</code></article>
            <span class="flow-arrow" aria-hidden="true">→</span>
            <article class="surface-card"><span class="flow-index">02</span><h2>Four bounded calls</h2><p>Owner twice with shared state, then administrator and member.</p><code>status + jobs_created</code></article>
            <span class="flow-arrow" aria-hidden="true">→</span>
            <article class="surface-card surface-result"><span class="flow-index">03</span><h2>Two typed outcomes</h2><p><strong>OWNER_ONLY</strong><br><strong>REUSE_ACTIVE_EXPORT</strong></p><code>ObservationResult</code></article>
        </div>
        <div class="surface-summary"><strong>One observer, two product decisions.</strong><span>The gate receives the same normalized result type used by every scenario.</span></div>
    `;
}

function databaseCoverage() {
    return `
        <div class="coverage-flow">
            <article class="surface-card"><span class="flow-index">01</span><h2>Seed known state</h2><p>Create an existing share link before applying the migration.</p><code>expires_at = NULL</code></article>
            <span class="flow-arrow" aria-hidden="true">→</span>
            <article class="surface-card"><span class="flow-index">02</span><h2>Apply and probe</h2><p>Run the migration, insert a new link, inspect both rows, then roll back.</p><code>transactional probe</code></article>
            <span class="flow-arrow" aria-hidden="true">→</span>
            <article class="surface-card surface-result"><span class="flow-index">03</span><h2>One typed outcome</h2><p><strong>PRESERVE_EXISTING</strong></p><code>rollback_verified = true</code></article>
        </div>
        <div class="surface-summary"><strong>Behavior is established from database effects.</strong><span>The observer doesn't infer rollout policy from the SQL text.</span></div>
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
        <div class="surface-summary"><strong>Three rules cover many structural operations.</strong><span>New rules extend observation coverage without changing the gate lifecycle.</span></div>
    `;
}

function renderCoverage() {
    const renderers = { api: apiCoverage, database: databaseCoverage, structure: structureCoverage };
    coverageContent.innerHTML = renderers[state.surface]();
    surfaceTabs.querySelectorAll("[data-surface]").forEach((button) => {
        button.setAttribute("aria-selected", String(button.dataset.surface === state.surface));
    });
}

function resetWalkthrough() {
    state.step = "brief";
    state.coverageGap = false;
    state.administrator = null;
    state.repeat = null;
    state.expiration = null;
    gapToggle.setAttribute("aria-pressed", "false");
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

scenarioTabs.addEventListener("click", (event) => {
    const button = event.target.closest("[data-scenario]");
    if (!button || button.dataset.scenario === state.scenario) return;
    state.scenario = button.dataset.scenario;
    resetWalkthrough();
    scenarioName.textContent = state.scenario === "database" ? "Share-link expiration" : "Workspace export authorization";
    scenarioTabs.querySelectorAll("[data-scenario]").forEach((tab) => {
        tab.setAttribute("aria-selected", String(tab.dataset.scenario === state.scenario));
    });
    renderStage();
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

renderView();
renderStage();
renderCoverage();
