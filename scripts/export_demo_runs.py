"""Export persisted gate runs for presentation clients."""

from __future__ import annotations

import argparse
from pathlib import Path

from implicit_decision_gate.web_export import build_demo_dataset, load_demo_run


def main() -> None:
    """Print a validated demo dataset to standard output."""

    parser = argparse.ArgumentParser()
    parser.add_argument("runs", nargs="+", type=Path)
    parser.add_argument("--summary", default="Persisted gate run")
    arguments = parser.parse_args()
    runs = [
        load_demo_run(path, label=path.parent.name, summary=arguments.summary)
        for path in arguments.runs
    ]
    dataset = build_demo_dataset(runs, generated_from="persisted RunRecord snapshots")
    print(dataset.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
