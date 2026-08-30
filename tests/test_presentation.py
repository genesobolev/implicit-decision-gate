from __future__ import annotations

import json
from pathlib import Path

WEB_INDEX = Path("web/public/index.html")
WEB_APP = Path("web/public/app.js")
NOTEBOOK = Path("notebooks/implicit-decision-gate-walkthrough.ipynb")
DIAGRAM_DIR = Path("notebooks/assets/diagrams")


def test_web_preserves_the_original_demo_story() -> None:
    index = WEB_INDEX.read_text(encoding="utf-8")
    app = WEB_APP.read_text(encoding="utf-8")

    assert index.index('data-view="workflow"') < index.index('data-view="walkthrough"')
    assert 'data-scenario="api" aria-selected="true"' in index
    assert 'data-replay-route="owner" aria-pressed="true"' in index

    primary_routes = ["owner", "supported", "gap", "verification_failure"]
    for route in primary_routes:
        assert f'data-replay-route="{route}"' in index

    original_surfaces = [
        "renderWorkflowInspector",
        "databaseStructureExample",
        "apiBriefStage",
        "apiObserveStage",
        "apiReviewStage",
        "apiAnswerStage",
        "apiVerifyStage",
    ]
    for surface in original_surfaces:
        assert f"function {surface}" in app

    assert 'scenario: "api"' in app
    assert 'replayRoute: "owner"' in app
    assert "UnknownEffect" in app
    assert "UNMODELED" not in app


def test_robustness_cases_remain_secondary_to_primary_replay_routes() -> None:
    index = WEB_INDEX.read_text(encoding="utf-8")

    primary_routes_end = index.index('data-replay-route="verification_failure"')
    robustness_start = index.index('<details class="robustness-routes">')
    assert primary_routes_end < robustness_start

    robustness_routes = [
        "invariant_violation",
        "forbidden_effect",
        "missing_coverage",
        "attempt2_unclassified",
    ]
    for route in robustness_routes:
        assert f'data-robustness-route="{route}"' in index


def test_notebook_keeps_the_live_story_before_the_robustness_appendix() -> None:
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    cells = notebook["cells"]
    cell_ids = [cell["id"] for cell in cells]

    narrative = [
        "motivation",
        "premise",
        "system-context",
        "first-attempt",
        "gate-pauses",
        "human-contract",
        "fresh-retry",
        "api-coverage",
        "api-gap",
        "postgres-behavior",
        "postgres-structure",
        "shared-gate",
        "why-this-matters",
    ]
    positions = [cell_ids.index(cell_id) for cell_id in narrative]
    assert positions == sorted(positions)
    assert cell_ids[-1] == "robustness-appendix"

    source = "\n".join("".join(cell.get("source", [])) for cell in cells)
    assert "UnknownEffect" in source
    assert "UNMODELED" not in source


def test_notebook_diagrams_are_reviewable_and_present() -> None:
    notebook_source = NOTEBOOK.read_text(encoding="utf-8")

    for name in ["system_context", "lifecycle", "gate_logic"]:
        source_path = DIAGRAM_DIR / f"{name}.mmd"
        image_path = DIAGRAM_DIR / f"{name}.png"
        mermaid = source_path.read_text(encoding="utf-8")

        assert source_path.name in notebook_source
        assert image_path.name in notebook_source
        assert image_path.stat().st_size > 0
        assert "(" not in mermaid
        assert ")" not in mermaid
