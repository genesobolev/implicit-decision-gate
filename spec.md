# Implicit decision gate design contract

## Purpose and boundary

This repository is a narrow proof of concept for completing missing intent in
long-running agent work. It begins after identity, authorization, tool access, and
evidence provenance have been established by a trusted agent loop, and it ends before
that loop grants a capability. An authenticated owner decision would refine the
human-owned job contract before the clean attempt returns to the existing verifier.

It does not implement 1Password's Verified Loops architecture. A real integration still
requires 1Password-provided identity, a controlled tool gateway, trusted evidence, and
capability enforcement. The service and schema used here are fictional and make no claim
about 1Password's production implementation.

## Reference decision

The fixed example models a service behind 1Password item-sharing links. The brief requires
new links to expire after 30 days but deliberately says nothing about customer links that
already exist.

The PostgreSQL migration must resolve exactly one modeled rollout decision:

| Option | Existing rows | New rows | Column |
| --- | --- | --- | --- |
| `PRESERVE_EXISTING` | Remain non-expiring with `NULL` | Default to approximately 30 days | Nullable |
| `EXPIRE_EXISTING` | Receive approximately 30 days at migration time | Default to approximately 30 days | Nullable |

Any other observed behavior is `UNMODELED`. `public` in `public.share_links` is a
PostgreSQL schema name, not an accessibility designation.

## Workflow contract

1. Record the repository's current commit, read the brief from that commit, and create a
   detached, clean worktree from it.
2. Read the schema from that worktree and give the pinned brief and schema to the coding
   backend in a fresh non-repository process. Accept one structured SQL migration and let
   the application write it to the worktree.
3. Persist an immutable copy and SHA-256 digest of the migration before probing it.
4. In a fresh PostgreSQL 17 test database, apply the migration with a limited role inside
   a transaction. Observe the column definition, a seeded old row, and a newly inserted
   row, then roll back.
5. Normalize the observed behavior to `PRESERVE_EXISTING`, `EXPIRE_EXISTING`, or
   `UNMODELED`.
6. Give an isolated evidence reviewer only the original brief and normalized behavior.
   It classifies the behavior as `SUPPORTED`, `CONTRADICTED`, `NOT_EVIDENCED`, or
   `UNCERTAIN`.
7. If the brief does not establish the observed choice, persist `AWAITING_OWNER` and stop
   all model and migration execution.
8. Accept one typed owner option, persist it, and move to `READY_TO_RESUME` without
   invoking a model.
9. On resume, create a different clean worktree at the same original commit. Start a new
   coding invocation with the brief, schema, and selected option only.
10. Probe the second migration. Complete only if its observed behavior matches the owner
    option; otherwise fail without a third attempt or another owner question.

## Evidence and transition contract

`SUPPORTED` and `CONTRADICTED` require an exact quotation from the brief. The application
must verify that the quote is a literal substring. A missing or fabricated required quote
becomes `UNCERTAIN`; substring validation establishes source presence, not semantic
correctness.

After attempt one:

| Observation and review | State |
| --- | --- |
| Modeled behavior and `SUPPORTED` | `COMPLETED` |
| Modeled behavior and `NOT_EVIDENCED` or `UNCERTAIN` | `AWAITING_OWNER` |
| `UNMODELED`, `CONTRADICTED`, or execution error | `FAILED` |

After an owner answer, the reviewer is not called again. Attempt two is checked directly
against the selected option and ends in either `COMPLETED` or `FAILED`.

## Context-isolation contract

Both coding attempts derive their inputs and receive their output in different worktrees
at the same base commit. Attempt two must not receive attempt one's migration, diff,
response, rationale, reviewer explanation, or gate feedback. It receives only the
original inputs plus the owner's selected option and the option's full behavioral meaning.

Each coding call and evidence review in Codex mode uses a separate ephemeral Codex
process in a fresh temporary directory instead of the repository. The checkout is not
supplied as the working root, user configuration is ignored, Codex operates read-only,
and the application owns the migration write. A production integration must enforce the
stronger filesystem boundary in its trusted runtime.

## Durability and inspection contract

The run record is an atomically replaced snapshot of current state, not an event-sourced
history. It and its adjacent immutable SQL artifacts retain enough material to reproduce
and inspect the decision:

- Run ID, current state, base commit, and selected backend
- Original brief, with the baseline schema embedded in each coding prompt
- Exact project-controlled coding and reviewer prompts
- Worktree path for each attempt
- Immutable migration SQL and digest for each attempt
- Normalized PostgreSQL probe results
- Normalized reviewer classification and source-backed quote, when applicable
- Decision identifier, observed behavior, and the owner's selected option
- Relevant timestamps and terminal error

The durable state machine consists of this run record and its ordered attempt artifacts;
there is no separate graph store. Concurrent answers or resumes must not create duplicate
decisions or attempts.

## Deliberate limits

The implementation supports one fixed PostgreSQL table, one decision dimension, at most
two coding attempts, and one owner answer. It is not a general migration framework, policy
engine, approval UI, identity system, capability gateway, or production integration with
1Password.
