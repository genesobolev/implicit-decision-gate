# Implicit Decision Gate

A focused PostgreSQL migration demo that detects an important rollout choice the brief did not make explicit, pauses for an owner decision, and regenerates the migration from a clean Git worktree.

The default demonstration is deterministic and requires no model credentials. An optional Codex mode uses an installed, already authenticated Codex CLI.

## What the demo shows

1. A coding backend creates a migration in a detached worktree.
2. PostgreSQL applies and inspects the migration inside a disposable transaction.
3. An evidence reviewer checks whether the brief supports the observed treatment of existing rows.
4. The run pauses in `AWAITING_OWNER` when the brief is silent.
5. The owner selects `PRESERVE_EXISTING` or `EXPIRE_EXISTING`.
6. A fresh attempt starts from the original commit and must match that decision.

Every transition, prompt, result, migration, digest, and worktree path is persisted under `.idg/runs/<run-id>/`.

## Quick start

Requirements:

- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- Docker with Compose

Clone and start PostgreSQL:

```bash
git clone https://github.com/genesobolev/implicit-decision-gate.git
cd implicit-decision-gate
uv sync --extra dev
docker compose up -d --wait
```

Start the credential-free scripted run:

```bash
uv run idg start \
    --repo . \
    --brief examples/share-link-expiration/brief.md
```

Copy the returned `run_id`, inspect the pause, and record an owner decision:

```bash
uv run idg show RUN_ID
uv run idg answer RUN_ID --option PRESERVE_EXISTING
uv run idg resume RUN_ID
uv run idg show RUN_ID
```

The scripted first attempt consistently chooses `EXPIRE_EXISTING`. Selecting `PRESERVE_EXISTING` makes the second attempt visibly demonstrate regeneration from the owner's decision.

## Optional Codex run

Codex mode requires the Codex CLI to be installed and signed in. `codex exec` reuses saved CLI authentication, so this project does not request model credentials. See the [official Codex non-interactive documentation](https://learn.chatgpt.com/docs/non-interactive-mode).

```bash
codex --version

uv run idg start \
    --agent codex \
    --repo . \
    --brief examples/share-link-expiration/brief.md
```

Use the same `show`, `answer`, and `resume` commands. The selected backend is stored in `run.json`, so `resume` automatically starts a new ephemeral Codex process.

If Codex is unavailable or not authenticated, use the scripted command instead. The PostgreSQL probe, worktrees, state machine, persisted artifacts, and owner gate are identical in both modes.

## Tests

The normal suite is deterministic and does not invoke Codex:

```bash
uv run pytest
```

To opt into the live Codex integration test after starting PostgreSQL:

```bash
IDG_LIVE_CODEX=1 uv run pytest tests/test_live.py -v
```

Stop the demo database when finished:

```bash
docker compose down
```
