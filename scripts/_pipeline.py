#!/usr/bin/env python3
"""Shared orchestration for the explicitly selected demo or research mode."""

from __future__ import annotations

import json
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import time

from export_public_assessments import export_payload


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PATENT_DIR = PROJECT_ROOT / "src" / "patent_scoring"
BEP_SCRIPT = PROJECT_ROOT / "src" / "bep_analysis" / "run_analysis.py"
MACRO_FILENAME = "industry_reference.xlsx"
REQUIRED_INPUTS = {
    "company_data": "company_data.xlsx",
    "patent_detail": "patent_records.xlsx",
    "high_value_patents": "high_value_patents.xlsx",
    "ipc_reference": "ipc_reference.xlsx",
    "industry_reference": MACRO_FILENAME,
}


def _check_inputs(data_dir: Path) -> None:
    missing = [name for name in REQUIRED_INPUTS.values() if not (data_dir / name).is_file()]
    if missing:
        raise FileNotFoundError("Missing prepared inputs: " + ", ".join(missing))


def _run(command: list[str], cwd: Path, env: dict[str, str]) -> None:
    completed = subprocess.run(command, cwd=str(cwd), env=env, check=False)
    if completed.returncode:
        raise RuntimeError(f"Stage failed with exit code {completed.returncode}: {command[1]}")


def run_pipeline(*, mode: str, data_dir: Path, output_dir: Path) -> Path:
    if mode not in {"demo", "research"}:
        raise ValueError(f"Unsupported mode: {mode}")

    started = time.time()
    started_ns = time.time_ns()
    data_dir = data_dir.resolve()
    output_dir = output_dir.resolve()
    reports_dir = output_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    _check_inputs(data_dir)

    patent_report = reports_dir / "patent_scoring_report.xlsx"
    env = os.environ.copy()
    env.update({
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "PATENT_DATA_DIR": str(data_dir),
        "PATENT_OUTPUT_PATH": str(patent_report),
    })

    stage_total = 3 if mode == "demo" else 2
    print(f"\n[1/{stage_total}] Patent scoring", flush=True)
    _run([sys.executable, str(PATENT_DIR / "main.py")], PATENT_DIR, env)

    print(f"\n[2/{stage_total}] BEP and credit analysis ({mode} mode)", flush=True)
    _run(
        [
            sys.executable,
            str(BEP_SCRIPT),
            "--mode", mode,
            "--patent-report", str(patent_report),
            "--company-data", str(data_dir / REQUIRED_INPUTS["company_data"]),
            "--macro-data", str(data_dir / MACRO_FILENAME),
            "--output-dir", str(output_dir),
        ],
        BEP_SCRIPT.parent,
        env,
    )

    preparation_summary_path = data_dir / "input_preparation_summary.json"
    preparation_summary = (
        json.loads(preparation_summary_path.read_text(encoding="utf-8"))
        if preparation_summary_path.is_file()
        else {}
    )

    if mode == "demo":
        print("\n[3/3] Derived website payload", flush=True)
        payload_path = export_payload(
            output_dir,
            output_dir / "public" / "company_assessments.json",
            preparation_summary,
        )
        print(f"Derived public assessment payload written to: {payload_path}")

    config_spec = importlib.util.spec_from_file_location(
        "kexintong_model_config", PATENT_DIR / "config.py"
    )
    model_config = importlib.util.module_from_spec(config_spec)
    config_spec.loader.exec_module(model_config)

    metadata = {
        "status": "success",
        "mode": mode,
        "dataset_version": "public_demo_v1" if mode == "demo" else "private_research_dataset",
        "normalization_scope": "demo_5_companies" if mode == "demo" else "research_universe",
        "score_version": "six_factor_20_12_20_13_25_10_v1",
        "score_weights": model_config.SCORE_WEIGHTS,
        "sample_size": len(preparation_summary.get("sample_companies", [])) or None,
        "financial_transform": preparation_summary.get("financial_transform"),
        "model_training": mode == "research",
        "elapsed_seconds": round(time.time() - started, 2),
        "outputs": sorted(
            str(path.relative_to(output_dir)).replace("\\", "/")
            for path in output_dir.rglob("*")
            if path.is_file()
            and path.name not in {"run_metadata.json", ".gitkeep"}
            and path.stat().st_mtime_ns >= started_ns
        ),
    }
    metadata_path = output_dir / "run_metadata.json"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return metadata_path
