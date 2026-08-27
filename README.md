# Implicit Decision Gate

Implicit Decision Gate is a deliberately small, fictional contract-completion stage
inside the trust architecture described in 1Password's
[Verified Loops](https://1password.com/blog/verified-loops-building-ai-agent-trust).
That architecture makes the human-owned job definition the verification boundary and
leaves humans the consequential judgments that cannot be verified mechanically. This
demo makes one such boundary executable: what happens when a system-observed effect
reveals that the request never made a required choice?

## Motivation

Long-running AI work can quietly make important choices that the original request never
made. A request to add an export feature might not say who may export, how long exported
files should be kept, or whether each export must be recorded. The code must still choose
a behavior, and that choice can be hard to notice inside a large change.

The larger idea behind this project is one shared gate for these missing decisions.
Separate checks for important parts of a system report simple facts about what the agent
actually changed. A database check can report what happens to existing data, a permission
check can report who gained access, a storage check can report how long data is kept, and
an API check can report behavior visible to other software. If a reported fact matters
and the request contains no approved answer for it, the gate saves the work and asks a
person.

This scales by building each kind of check once and reusing it across many jobs. The
shared gate handles saving, asking, resuming, and checking the next result for all of
them. It does not promise to find every possible hidden choice. It covers important parts
of a system where effects can be observed reliably.

This repository implements two fixed examples of that wider design. The default
PostgreSQL scenario reports whether a proposed change preserves existing links or makes
them expire. A workspace export scenario reports which roles can create an export and
whether each request creates a job.

## PostgreSQL structural surface

The PostgreSQL observer also takes a catalog snapshot immediately before and after each
migration. Three reusable rules turn the difference into sorted `ADDED`, `REMOVED`, and
`CHANGED` effects:

| Rule | Observed structure | Covered operations |
| --- | --- | --- |
| `schema_shape` | Tables and column type, nullability, and default | Create or drop a table; add or drop a column; change the three observed column properties |
| `data_integrity` | Primary-key, unique, check, and foreign-key constraints | Add, remove, or replace an observed constraint |
| `indexing` | Standalone index definition and uniqueness | Add, remove, or replace an index with transactional DDL |

Each effect records the rule, change, object kind, schema-qualified identity, attribute,
and before and after values in `observation.effects`. Constraint-owned indexes are
reported as constraints rather than duplicated as indexes. The comparison itself is a
small pure function; an exact PostgreSQL 17 test matrix makes changes to the catalog
rules reviewable without changing the gate or orchestration code.

This is a bounded structural surface, not a claim to understand arbitrary SQL. It
observes the final structure of ordinary and partitioned tables in `public`. It does not
run PostgreSQL operations that cannot execute inside its migration transaction. It also
does not reveal transient operations, row rewrites, data loss, locks, or performance.
Those need targeted behavioral probes. The share-link example shows why: both supported
migrations produce the same final `expires_at` structure, but only a seeded-row probe
reveals whether existing links were backfilled.

## The fictional share-link scenario

Imagine a service behind 1Password item-sharing links. A brief asks a coding agent to
make newly created links expire after 30 days. The fictional service stores link records
in a PostgreSQL table named `public.share_links`.

The brief does not say what should happen to links customers already created. A valid
PostgreSQL migration must nevertheless choose between two materially different outcomes:

| Decision | Existing links | New links |
| --- | --- | --- |
| `PRESERVE_EXISTING` | Keep their current non-expiring behavior | Expire after 30 days |
| `EXPIRE_EXISTING` | Expire 30 days after migration | Expire after 30 days |

Either policy could be legitimate. The agent should not silently invent it. Expiring old
links can break customer workflows; preserving them can retain access longer than the new
policy intends.

This scenario is fictional. It makes no claim about 1Password's production services,
database schema, or implementation of item sharing. In `public.share_links`, `public` is
only the standard PostgreSQL schema namespace. It does **not** mean the table, its rows,
or the links are publicly accessible.

## The workspace export authorization scenario

A second brief asks the coding agent to add workspace export creation. It says owners
must receive 202 and create one export job, while members must receive 403 and create no
job. It does not say whether administrators are authorized.

The generated artifact is one Python module exposing this function:

```python
def create_export(role: str, export_jobs: list[str]) -> int: ...
```

A disposable, network-disabled container calls the function as an owner, administrator,
and member. The observer checks both the returned status and the number of jobs created,
then normalizes the result to one of two supported outcomes:

| Decision | Owner | Administrator | Member |
| --- | --- | --- | --- |
| `OWNER_ONLY` | 202, one job | 403, no job | 403, no job |
| `OWNER_AND_ADMIN` | 202, one job | 202, one job | 403, no job |

Any other combination is `UNMODELED` and fails the run. The gate asks the owner whether
administrators should be allowed, starts a fresh coding attempt with that answer, and
observes the result again.

## Where the demo fits in a verified loop

1. The application pins the scenario brief and technical context to one Git commit and
   creates a clean, detached worktree. Codex receives those exact inputs in an isolated
   non-repository process, and the application writes its proposed artifact into the
   worktree.
2. The scenario's disposable observer executes the artifact and normalizes its effects
   into a small outcome vocabulary.
3. A separate evidence reviewer sees only the brief and the normalized observed behavior.
4. Because the brief is silent about one observed choice, the run durably pauses in
   `AWAITING_OWNER`.
5. An owner records one of the scenario's two supported answers.
6. The application creates another clean worktree at the original commit. A new isolated
   coding invocation receives its brief, context, and owner decision without being given
   the checkout as its working root or receiving the first artifact or reviewer rationale.
7. The same observer verifies the regenerated artifact directly against that decision.

The important signal comes from system-observed effects, not the coding agent's
description of its own work. The pause is durable, so model execution and human judgment
can happen in different processes and at different times.

This repository does not implement the Verified Loops capabilities described by
1Password. A real integration would still rely on 1Password to supply authenticated
agent and human identity, a controlled tool gateway, trusted and attributable evidence,
and capability or permission enforcement. This prototype assumes those controls and
focuses only on detecting and completing missing intent.

In that integration, the gate would sit after trusted runtime evidence exposes the
undeclared choice and before any permission is earned. The authenticated owner decision
would amend or refine the human-owned job contract; the clean second attempt would then
return to the existing verifier. This demo never grants a capability itself.

## Run the demo

Requirements:

- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- An installed and authenticated [Codex CLI](https://learn.chatgpt.com/docs/non-interactive-mode)
- Docker, with Compose for the PostgreSQL 17 verifier
- [`jq`](https://jqlang.github.io/jq/) only for the optional manual inspection commands

From the repository root:

```bash
uv sync --extra dev
codex --version
docker compose up -d --wait
uv run idg start
```

This starts the default share-link scenario. The workspace export scenario does not need
the Compose service and starts with:

```bash
uv run idg start --scenario workspace-export-authorization
```

`start` invokes the locally authenticated Codex CLI. Copy the returned `run_id`; the
reference run stops in `AWAITING_OWNER` after its first artifact chooses one of the two
outcomes the brief left open. Its `decision_request` shows why the run paused, the
observed outcome, and both supported choices. The application defines these verifiable
choices; Codex does not select the missing policy.

The application pins every coding and evidence-review invocation to
[`gpt-5.6-terra`](https://developers.openai.com/api/docs/models/gpt-5.6-terra) with
`xhigh` reasoning. It passes both settings explicitly while ignoring user configuration,
and records the model, reasoning effort, invocation role, attempt number, and Codex CLI
version in `run.json`. The model slug is fixed by this repository; it is not a claim that
the provider's underlying weights are an immutable dated snapshot.

To make the contract amendment visible, select the policy opposite
`observed_option`, then resume the durable run. For the share-link scenario:

```bash
# If Codex chose EXPIRE_EXISTING:
uv run idg answer RUN_ID --option PRESERVE_EXISTING

# If Codex chose PRESERVE_EXISTING:
uv run idg answer RUN_ID --option EXPIRE_EXISTING

uv run idg resume RUN_ID
```

For the workspace export scenario:

```bash
# If Codex chose OWNER_AND_ADMIN:
uv run idg answer RUN_ID --option OWNER_ONLY

# If Codex chose OWNER_ONLY:
uv run idg answer RUN_ID --option OWNER_AND_ADMIN

uv run idg resume RUN_ID
```

`answer` only records the selected option. It does not invoke Codex or interpret free
text. `resume` deliberately remains separate so execution can occur later or in another
process. `show` is optional and returns the same structured decision request while the
run is paused:

```bash
uv run idg show RUN_ID
```

`resume` starts a fresh ephemeral Codex process automatically. The application reuses
the Codex CLI's saved authentication; it does not ask for or read model API keys.

## Walk through every stage in Jupyter

The [guided notebook](notebooks/implicit-decision-gate-walkthrough.ipynb) walks through
the default PostgreSQL scenario with the same public CLI. It opens each persisted stage
in causal order: pinned inputs, exact project-controlled prompts, generated SQL,
immutable digests, normalized PostgreSQL evidence, the evidence review, the typed owner
decision, the clean retry, and the final deterministic check. Every section identifies
the actor responsible for the action or evidence.

Launch it from the repository root:

```bash
uv run --with 'jupyterlab>=4.1,<5' jupyter lab \
    notebooks/implicit-decision-gate-walkthrough.ipynb
```

JupyterLab remains demo tooling rather than a project dependency. Run the launch command
once before presenting so `uv` can cache it. The notebook invokes the live Codex and
PostgreSQL path, creates a new durable run, and makes the typed owner choice an explicit
cell to review or edit before resuming. The checked-in outputs are one representative
earlier live run in which the owner selects the other supported policy. The notebook
notes its earlier database-specific field names; rerunning uses the current generic
fields. A new run may initially choose either supported rollout policy, and the owner may
confirm it or select the other one.

## Where the prompts come from

Each fixed scenario has one brief and one technical context:

- The share-link scenario uses
    [`brief.md`](examples/share-link-expiration/brief.md) and
    [`schema.sql`](examples/share-link-expiration/schema.sql).
- The workspace export scenario uses
    [`brief.md`](examples/workspace-export-authorization/brief.md) and
    [`handler.py`](examples/workspace-export-authorization/handler.py).

The project-controlled coding and evidence-review prompts are assembled in
[`agent.py`](src/implicit_decision_gate/agent.py).

The brief is the human-owned engineering ticket. The rendered coding prompt is an
application-owned execution envelope, not an engineer's reinterpretation of that ticket.
The first request combines isolation and structured-output instructions with the
verbatim brief and technical context. The second is a new request containing the same
inputs plus the selected owner option and its required behavior. It does not contain
attempt one's artifact, model response, or review rationale. The reviewer receives only
the verbatim brief and the normalized behavior the scenario observer produced.

The brief is stored separately and embedded in each applicable prompt because every
Codex process is ephemeral and needs its complete input. Persisting both also lets an
auditor compare the source contract with the exact materialized prompt. Product
requirements are not repeated in the prompt envelope; attempt two's additional behavior
and acceptance criteria are the explicit owner amendment.

Each Codex process runs from a fresh temporary directory instead of the repository. Its
sandbox is read-only, user configuration is ignored, and the application is the only
component that writes the returned artifact into the pinned worktree. This avoids
supplying checkout contents as normal model context; the trusted runtime in a production
integration would enforce the stronger filesystem boundary.

The exact project-controlled coding and reviewer prompts and normalized review results
are persisted in `run.json`; returned artifacts are stored as adjacent immutable files.
Raw model transcripts are not retained. The run record is therefore the best place to
inspect the material prompt rather than inferring it from a source template.

## Inspect the state and artifacts manually

Each run stores its current state, prompts, results, and immutable artifacts as they
become available. A share-link run contains `.sql` artifacts, while a workspace export
run contains `.py` artifacts:

```text
.idg/runs/RUN_ID/
    run.json
    attempt-1.sql or attempt-1.py
    attempt-2.sql or attempt-2.py
```

`run.json` is an atomically replaced current-state snapshot, not an append-only event
history. There is no separate graph database or hidden graph to inspect. The small state
machine is represented by the current run record, its ordered attempt records, and the
artifacts.

The reference path is `STARTED` → `AWAITING_OWNER` → `READY_TO_RESUME` → `COMPLETED`.
An unmodeled effect, contradictory evidence, execution error, or second-attempt mismatch
instead ends in `FAILED`.

Inspect the complete record and the most useful attempt evidence:

```bash
jq . .idg/runs/RUN_ID/run.json
jq '.model_invocations' .idg/runs/RUN_ID/run.json
jq '{state, decision, reviewer_result}' .idg/runs/RUN_ID/run.json
jq -r '.attempts[].coding_prompt' .idg/runs/RUN_ID/run.json
jq -r '.reviewer_prompt' .idg/runs/RUN_ID/run.json
jq '.attempts[] | {number, worktree_path, artifact_digest, observation}' \
    .idg/runs/RUN_ID/run.json
```

For a share-link run, compare what changed after the owner decision:

```bash
diff -u \
    .idg/runs/RUN_ID/attempt-1.sql \
    .idg/runs/RUN_ID/attempt-2.sql
```

List the detached worktrees, copy either path, and inspect it with ordinary Git commands:

```bash
jq -r '.attempts[].worktree_path' .idg/runs/RUN_ID/run.json
git -C /PATH/FROM/THE/PREVIOUS/COMMAND status --short
sed -n '1,200p' \
    /PATH/FROM/THE/PREVIOUS/COMMAND/examples/share-link-expiration/migrations/idg-*.sql
```

In each attempt record, compare `observation.outcome` with `decision.selected`. The
artifact shows the proposed mechanism; the observation shows the effect the scenario's
runtime produced.

## Why Docker is involved

PostgreSQL is the verifier in this example, not incidental demo infrastructure. The gate
needs to observe real PostgreSQL DDL and default semantics: the column type and
nullability, whether the seeded old row was backfilled, and what expiration a new row
receives. Parsing SQL or running it against SQLite would not establish those effects.

Docker Compose is the demo's only PostgreSQL runtime. It supplies a reproducible local
PostgreSQL 17 instance with fixed demo credentials and no production data. The public CLI
uses the loopback connection defined by `compose.yaml`; that connection string is internal
plumbing, not a user-selectable database target. Each probe creates a fresh test database,
executes through a limited role inside a transaction, records normalized observations,
and rolls the transaction back. The container's data directory is temporary.

The workspace export observer runs the generated Python module in a disposable,
network-disabled, read-only container. It calls `create_export` for the three modeled
roles and records only each returned status and job count. It does not start an HTTP
server or add an application framework.

When finished with the Compose instance:

```bash
docker compose down --volumes
```

## Validate the implementation

The normal suite is deterministic and does not invoke Codex. With the Compose service
running, it checks exact PostgreSQL 17 effects for table, column, constraint, and index
additions, removals, and changes. It also covers both decision vocabularies and includes
a six-case adversarial matrix for convergence, ignored owner decisions, and unmodeled
outcomes:

```bash
uv run pytest
```

To opt into the live Codex integration test after starting the Compose service:

```bash
IDG_LIVE_CODEX=1 uv run pytest tests/test_live.py -v
```
