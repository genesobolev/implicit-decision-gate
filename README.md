# Implicit Decision Gate

Implicit Decision Gate is a deliberately small, fictional contract-completion stage
inside the trust architecture described in 1Password's
[Verified Loops](https://1password.com/blog/verified-loops-building-ai-agent-trust).
That architecture makes the human-owned job definition the verification boundary and
leaves humans the consequential judgments that cannot be verified mechanically. This
demo makes one such boundary executable: what happens when a system-observed effect
reveals that the request never made a required choice?

The repository demonstrates that question with one concrete migration, one observable
ambiguity, and one typed human decision.

## The fictional 1Password scenario

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

## Where the demo fits in a verified loop

1. The application pins the brief and schema to one Git commit and creates a clean,
   detached worktree. A coding backend receives those exact inputs in an isolated
   non-repository process, and the application writes its proposed migration into the
   worktree.
2. A disposable PostgreSQL 17 database applies the migration and observes its effects on
   both an old row and a newly inserted row.
3. A separate evidence reviewer sees only the brief and the normalized observed behavior.
4. Because the brief is silent about old rows, the run durably pauses in
   `AWAITING_OWNER`.
5. An owner records the smallest missing judgment: `PRESERVE_EXISTING` or
   `EXPIRE_EXISTING`.
6. The application creates another clean worktree at the original commit. A new isolated
   coding invocation receives its brief, schema, and owner decision without being given
   the checkout as its working root or receiving the first migration or reviewer rationale.
7. PostgreSQL verifies the regenerated migration directly against that decision.

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
- PostgreSQL 17, most easily provided by Docker with Compose
- [`jq`](https://jqlang.github.io/jq/) only for the optional manual inspection commands

From the repository root:

```bash
uv sync --extra dev
docker compose up -d --wait
uv run idg start
```

`start` uses a deterministic scripted backend by default, so the core demonstration does
not require model credentials. Copy the returned `run_id`; the reference run stops in
`AWAITING_OWNER` after its first migration expires old links.

Record the opposite policy and resume the durable run:

```bash
uv run idg answer RUN_ID --option PRESERVE_EXISTING
uv run idg resume RUN_ID
```

`answer` only records the decision. `resume` deliberately remains separate so execution
can occur later or in another process. `show` is optional and can inspect the current
summary at any point:

```bash
uv run idg show RUN_ID
```

To use a real, already authenticated Codex CLI instead of the deterministic backend:

```bash
codex --version
uv run idg start --agent codex
```

Use the same `answer`, `resume`, and optional `show` commands. The selected backend is
stored with the run, so `resume` starts a fresh ephemeral Codex process automatically.
The application does not ask for or read model API keys.

## Where the prompts come from

There is one fixed scenario brief at
[`examples/share-link-expiration/brief.md`](examples/share-link-expiration/brief.md) and
one fictional baseline schema at
[`examples/share-link-expiration/schema.sql`](examples/share-link-expiration/schema.sql).
The project-controlled coding and evidence-review prompts are assembled in
[`agent.py`](src/implicit_decision_gate/agent.py).

The first coding request contains the brief, the baseline schema, and the migration output
contract. The second is a new request containing the same inputs plus the selected owner
option and its required behavior. It does not contain attempt one's SQL, model response,
or review rationale. The reviewer receives only the brief and the behavior PostgreSQL
observed.

Each Codex process runs from a fresh temporary directory instead of the repository. Its
sandbox is read-only, user configuration is ignored, and the application is the only
component that writes the returned migration into the pinned worktree. This avoids
supplying checkout contents as normal model context; the trusted runtime in a production
integration would enforce the stronger filesystem boundary.

The exact project-controlled coding and reviewer prompts and normalized review results
are persisted in `run.json`; returned migrations are stored as adjacent immutable SQL
artifacts. Raw model transcripts are not retained. The run record is therefore the best
place to inspect the material prompt rather than inferring it from a source template.

## Inspect the state and artifacts manually

Each run stores its current state, prompts, results, and immutable migration artifacts,
as they become available, in:

```text
.idg/runs/RUN_ID/
    run.json
    attempt-1.sql
    attempt-2.sql
```

`run.json` is an atomically replaced current-state snapshot, not an append-only event
history. There is no separate graph database or hidden graph to inspect. The small state
machine is represented by the current run record, its ordered attempt records, and the
SQL artifacts.

The reference path is `STARTED` → `AWAITING_OWNER` → `READY_TO_RESUME` → `COMPLETED`.
An unmodeled effect, contradictory evidence, execution error, or second-attempt mismatch
instead ends in `FAILED`.

Inspect the complete record and the most useful attempt evidence:

```bash
jq . .idg/runs/RUN_ID/run.json
jq '{state, decision, reviewer_result}' .idg/runs/RUN_ID/run.json
jq -r '.attempts[].coding_prompt' .idg/runs/RUN_ID/run.json
jq -r '.reviewer_prompt' .idg/runs/RUN_ID/run.json
jq '.attempts[] | {number, worktree_path, migration_digest, probe_result}' \
    .idg/runs/RUN_ID/run.json
```

Compare what changed after the owner decision:

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

In each attempt record, compare `probe_result.rollout_option` with
`decision.selected`. The SQL files show the proposed mechanism; the probe result shows
the effect that PostgreSQL actually produced.

## Why PostgreSQL and Docker are involved

PostgreSQL is the verifier in this example, not incidental demo infrastructure. The gate
needs to observe real PostgreSQL DDL and default semantics: the column type and
nullability, whether the seeded old row was backfilled, and what expiration a new row
receives. Parsing SQL or running it against SQLite would not establish those effects.

Docker Compose supplies a reproducible local PostgreSQL 17 instance with no production
credentials or customer data. Each probe creates a fresh test database, executes through
a limited role inside a transaction, records normalized observations, and rolls the
transaction back. The container's data directory is temporary.

Docker itself is not fundamental. If a compatible disposable PostgreSQL 17 instance is
already available, point `IDG_POSTGRES_ADMIN_DSN` at it instead.

When finished with the Compose instance:

```bash
docker compose down
```

## Validate the implementation

The normal suite is deterministic and does not invoke Codex:

```bash
uv run pytest
```

To opt into the live Codex integration test after starting PostgreSQL:

```bash
IDG_LIVE_CODEX=1 uv run pytest tests/test_live.py -v
```
