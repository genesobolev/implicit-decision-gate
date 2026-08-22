# implicit-decision-gate

## Implementation specification

## 1. Required behavior

For one supported PostgreSQL migration shape, the system must:

1. Accept a high-level brief and Git repository.
2. Ask the selected coding backend to create a migration in a detached Git worktree.
3. Execute the migration in a disposable PostgreSQL transaction and normalize its behavior.
4. Compare the observed existing-row behavior with evidence in the brief.
5. Enter `AWAITING_OWNER` when that behavior is `NOT_EVIDENCED` or `UNCERTAIN`.
6. Record one typed owner decision.
7. Start a fresh coding-model invocation in a new worktree at the original commit.
8. Complete when the second migration matches the owner decision; otherwise fail.

An **implicit-decision candidate** is an observed behavior classified as `NOT_EVIDENCED`. Do not label it unauthorized or contrary to intent.

## 2. Reference scenario

The input brief is:

```text
Add expiration support to share links.
Store it in public.share_links.expires_at as a nullable timestamp with time zone.
New share links should expire 30 days after creation.
```

The repository contains:

- `examples/share-link-expiration/brief.md` with the input brief.
- `examples/share-link-expiration/schema.sql` defining `public.share_links`.
- At least one existing share-link fixture row.
- `examples/share-link-expiration/migrations/` as the only migration output directory.

The implementation supports exactly two existing-row behaviors:

| Option | Existing share links | New share links | Column |
| --- | --- | --- | --- |
| `PRESERVE_EXISTING` | Remain non-expiring with `NULL` | Default to 30 days | Nullable |
| `EXPIRE_EXISTING` | Receive an expiration approximately 30 days from migration | Default to 30 days | Nullable |

All other observed behaviors are `UNMODELED`.

## 3. Components

| Component | Responsibility |
| --- | --- |
| CLI and orchestrator | Execute commands, enforce state transitions, and persist runs |
| Coding backend | Read reference files and submit one migration per attempt |
| Worktree manager | Create one clean detached worktree per attempt |
| PostgreSQL probe | Execute a migration and normalize observable behavior |
| Evidence reviewer | Classify support for the observed existing-row behavior |
| Gate | Convert probe and reviewer results into state transitions |

The default backend is a deterministic scripted demonstration that requires no credentials. The optional `codex` backend invokes an installed Codex CLI in non-interactive mode and reuses its saved local authentication. Each coding-model call and evidence review starts a separate ephemeral Codex process. The application does not accept or read model API keys.

## 4. Coding-backend tools

Expose two tools:

```text
read_file(path) -> contents
submit_migration(sql) -> proposal record
```

Requirements:

- `read_file` accepts only paths under `examples/share-link-expiration/` in the current worktree.
- `submit_migration` writes only under `examples/share-link-expiration/migrations/` in the current worktree.
- The application exposes only these two normalized tools. Codex runs with a read-only sandbox and returns one schema-constrained tool action; the application performs the migration write.
- Persist the proposal before executing it.
- Permit one submitted migration per attempt.
- Permit at most four model tool steps per attempt.

## 5. Worktree and context isolation

Record the repository's current commit as `base_commit` when the run starts. Create each worktree outside the primary checkout:

```text
git worktree add --detach WORKTREE_PATH BASE_COMMIT
```

Attempts one and two must use different worktree paths created from the same `base_commit`. Do not reuse or clean the first worktree for attempt two. Persist an immutable copy and SHA-256 digest of each migration.

Attempt one receives:

- The original brief.
- The normal tool definitions.
- Files read from the attempt-one worktree.

Attempt two receives:

- The original brief.
- The selected owner option and its full behavior description.
- The normal tool definitions.
- Files read from the attempt-two worktree.

Attempt two must not receive:

- The first migration or diff.
- The first model response, rationale, or tool transcript.
- The reviewer explanation or gate feedback.
- Instructions describing how to modify attempt one.

## 6. PostgreSQL probe

For each proposal:

1. Create the fixed baseline schema and seed row in a fresh test database.
2. Begin a transaction.
3. Apply the migration as a non-superuser role limited to the test database.
4. Inspect the column type, nullability, and default.
5. Inspect the seeded row.
6. Insert a row without `expires_at` and inspect the result.
7. Verify the target, timestamp type, nullable column, and 30-day behavior for new rows.
8. Map the existing-row behavior to `PRESERVE_EXISTING`, `EXPIRE_EXISTING`, or `UNMODELED`.
9. Roll back the transaction.

Use a PostgreSQL 17 container with no production credentials or user data.

The normalized result has this shape:

```json
{
  "table": "public.share_links",
  "column": "expires_at",
  "data_type": "timestamp with time zone",
  "nullable": true,
  "insert_without_value": "approximately_now_plus_30_days",
  "existing_row": "approximately_migration_time_plus_30_days",
  "rollout_option": "EXPIRE_EXISTING"
}
```

## 7. Evidence review and gate

After attempt one, call the evidence reviewer with only:

- The original brief.
- The normalized rollout option and its behavior description.

The reviewer returns:

```json
{
  "classification": "NOT_EVIDENCED",
  "evidence_quote": null
}
```

`classification` must be one of:

- `SUPPORTED`: The brief explicitly supports the observed behavior.
- `CONTRADICTED`: The brief explicitly requires different behavior.
- `NOT_EVIDENCED`: The brief does not address the behavior.
- `UNCERTAIN`: The reviewer cannot classify it.

`SUPPORTED` and `CONTRADICTED` require an exact quote from the brief. Verify that the quote is a literal substring. Convert a missing or invalid quote to `UNCERTAIN`. Quote validation verifies source presence only; it does not validate semantic correctness.

Create one decision-ledger record:

```json
{
  "decision_id": "existing_share_link_rollout",
  "impact": "HIGH",
  "observed": "EXPIRE_EXISTING",
  "classification": "NOT_EVIDENCED",
  "evidence_quote": null,
  "state": "AWAITING_OWNER",
  "options": ["PRESERVE_EXISTING", "EXPIRE_EXISTING"]
}
```

Apply these transitions after attempt one:

| Result | Transition |
| --- | --- |
| `SUPPORTED` | `COMPLETED` |
| `NOT_EVIDENCED` or `UNCERTAIN` | `AWAITING_OWNER` |
| `CONTRADICTED` or `UNMODELED` | `FAILED` |

After an owner decision, do not call the evidence reviewer again. Compare the attempt-two probe result directly with the selected option. A match transitions to `COMPLETED`; a mismatch or `UNMODELED` result transitions to `FAILED`.

## 8. Run state and limits

Store each run under `.idg/runs/<run-id>/`:

```text
run.json
attempt-1.sql
attempt-2.sql
```

Worktrees live under a configurable directory outside the primary checkout. Record their paths in `run.json`.

Persist:

- Run ID and state.
- Original brief and SHA-256 digest.
- Base commit.
- Worktree path and clean-start verification for each attempt.
- Agent backend and prompt version.
- Model requests, responses, and tool calls.
- Attempt and tool-step counts.
- Migration contents and digests.
- Probe results.
- Reviewer result and validated quote.
- Owner option.
- Timestamps.

Write `run.json` through a temporary file followed by an atomic rename.

Supported states:

```text
STARTED
AWAITING_OWNER
READY_TO_RESUME
COMPLETED
FAILED
```

Enforce these limits in code:

```text
MAX_CODING_ATTEMPTS = 2
MAX_TOOL_STEPS_PER_ATTEMPT = 4
MAX_TRANSPORT_RETRIES_PER_CALL = 1
MAX_OWNER_ANSWERS = 1
```

While `AWAITING_OWNER`, reject model execution and migration mutation. `answer` records one option and transitions to `READY_TO_RESUME`.

After attempt two, transition to `COMPLETED` or `FAILED`. Do not invoke a third coding attempt or request another owner answer. A mismatch after the owner decision is an execution failure.

## 9. CLI

Run commands from the repository root:

```bash
idg start --repo . --brief examples/share-link-expiration/brief.md
idg start --agent codex --repo . --brief examples/share-link-expiration/brief.md
idg show RUN_ID
idg answer RUN_ID --option PRESERVE_EXISTING
idg resume RUN_ID
```

`start` runs until `COMPLETED`, `AWAITING_OWNER`, or `FAILED`.

`start --agent` accepts `scripted` or `codex` and defaults to `scripted`. Persist the selected backend in the run. `resume` automatically reuses it and does not permit a backend change.

`show` prints the current state, observed option, classification, pending question, selected owner option, attempt digests, and final worktree path.

`answer` succeeds only in `AWAITING_OWNER` and accepts one of the two option IDs.

`resume` succeeds only in `READY_TO_RESUME`.

## 10. Repository structure

```text
implicit-decision-gate/
    README.md
    pyproject.toml
    compose.yaml
    src/implicit_decision_gate/
        __init__.py
        cli.py
        agent.py
        codex_client.py
        gate.py
        probe.py
        worktree.py
    examples/share-link-expiration/
        brief.md
        schema.sql
        migrations/
    tests/
        test_codex_client.py
        test_probe.py
        test_reviewer.py
        test_orchestrator.py
        test_context.py
```

Use Python 3.12, `argparse`, `psycopg`, Pydantic, pytest, Git CLI, and PostgreSQL 17 through Docker Compose. Codex mode additionally requires an installed and authenticated Codex CLI on the host.

## 11. Tests

CI uses a scripted model client. The live-model integration test runs only when `IDG_LIVE_CODEX=1`, Codex is installed and authenticated, and the PostgreSQL container is available.

Required tests:

1. The probe maps the two reference migrations to their expected options.
2. The reference brief classifies either option as `NOT_EVIDENCED`.
3. A brief that addresses existing rows produces `SUPPORTED` for the matching option and `CONTRADICTED` for the other.
4. A fabricated evidence quote becomes `UNCERTAIN`.
5. `AWAITING_OWNER` persists across processes and blocks further model calls.
6. Attempts use different worktree paths at the same base commit.
7. Attempt two starts clean and its model input excludes all attempt-one and reviewer material.
8. A scripted run can pause, accept the opposite option, produce a matching second migration, and complete.
9. A mismatching or `UNMODELED` second migration fails without another model call or owner question.
10. Tool-step and transport-retry limits terminate the run with `FAILED`.
11. An opt-in local Codex run can produce attempt one, pause, accept an owner option, and produce attempt two.

Assert states, normalized effects, context contents, counters, and digests rather than exact model prose.

## 12. Definition of done

The implementation is complete when:

- `start`, `show`, `answer`, and `resume` satisfy their contracts.
- Scripted mode completes the full workflow without model credentials.
- Optional Codex mode uses the locally authenticated Codex CLI to produce attempt one in a detached worktree.
- The probe classifies its existing-row behavior.
- The reviewer creates one `NOT_EVIDENCED` ledger record for the reference brief.
- The run persists `AWAITING_OWNER` and blocks model execution.
- `answer` records one typed option.
- Attempt two runs in a new worktree at the same base commit without attempt-one context.
- A matching second migration completes the run.
- A mismatching second migration fails without a third attempt or repeated question.
- The final run record contains the brief, model traces, migrations, observed effects, reviewer result, owner option, worktree paths, and digests.
