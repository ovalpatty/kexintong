#!/usr/bin/env python3
"""Run the private full-sample research workflow, including GBM evaluation."""

from __future__ import annotations

import argparse
from pathlib import Path

from _pipeline import PROJECT_ROOT, run_pipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run research mode with a prepared private full-sample dataset"
    )
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "outputs" / "research")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    metadata_path = run_pipeline(
        mode="research",
        data_dir=args.data_dir,
        output_dir=args.output_dir,
    )
    print(f"\nResearch analysis completed. Run metadata: {metadata_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
