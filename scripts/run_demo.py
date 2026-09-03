#!/usr/bin/env python3
"""Run the deterministic five-company public demo. No model is trained."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys

from _pipeline import PROJECT_ROOT, run_pipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the five-company deterministic public demo")
    parser.add_argument("--package", type=Path, default=PROJECT_ROOT / "data")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "outputs" / "latest")
    parser.add_argument("--generated-dir", type=Path, default=PROJECT_ROOT / "data" / "generated")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    prepare_command = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "prepare_demo_inputs.py"),
        "--package", str(args.package),
        "--output-dir", str(args.generated_dir),
    ]
    completed = subprocess.run(prepare_command, cwd=str(PROJECT_ROOT), check=False)
    if completed.returncode:
        return completed.returncode

    metadata_path = run_pipeline(
        mode="demo",
        data_dir=args.generated_dir,
        output_dir=args.output_dir,
    )
    print(f"\nPublic demo completed. Run metadata: {metadata_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
