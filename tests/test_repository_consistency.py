"""Regression checks for public-repository documentation and data contracts."""

from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_exporter():
    spec = importlib.util.spec_from_file_location(
        "kexintong_exporter", ROOT / "scripts" / "export_public_assessments.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class RepositoryConsistencyTests(unittest.TestCase):
    def test_readme_does_not_reintroduce_pre_integration_status(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("organized around four output groups", readme)
        forbidden = [
            "reserved for the collaborator",
            "complete public run will become available",
            "input-schema validation",
        ]
        for phrase in forbidden:
            self.assertNotIn(phrase, readme)
        for module in [
            "config.py",
            "data_loader.py",
            "ipc_analysis.py",
            "nlp_analysis.py",
            "scoring_engine.py",
            "report_generator.py",
            "main.py",
        ]:
            self.assertTrue((ROOT / "src" / "patent_scoring" / module).is_file())

    def test_documented_row_counts_match_public_data(self):
        quality = json.loads(
            (ROOT / "metadata" / "quality_report.json").read_text(encoding="utf-8")
        )["checks"]
        expected = {
            "selected_company_count": ROOT / "data" / "demo" / "companies.csv",
            "demo_patent_rows": ROOT / "data" / "demo" / "patent_records.csv",
            "demo_financial_rows": ROOT / "data" / "demo" / "financial_quarterly.csv",
            "high_value_patent_rows": ROOT / "data" / "reference" / "high_value_patent_corpus.csv",
            "ipc_reference_rows": ROOT / "data" / "reference" / "ipc_market_reference.csv",
            "industry_reference_rows": ROOT / "data" / "reference" / "industry_bep_reference.csv",
            "raw_material_rows": ROOT / "data" / "reference" / "raw_material_price_index.csv",
        }
        for field, path in expected.items():
            self.assertEqual(quality[field], len(csv_rows(path)), field)

    def test_schema_fields_match_csv_headers(self):
        pairs = [
            ("demo", "companies"),
            ("demo", "financial_quarterly"),
            ("demo", "patent_records"),
            ("reference", "high_value_patent_corpus"),
            ("reference", "ipc_market_reference"),
            ("reference", "industry_bep_reference"),
            ("reference", "raw_material_price_index"),
        ]
        for directory, name in pairs:
            rows = csv_rows(ROOT / "data" / directory / f"{name}.csv")
            schema = json.loads(
                (ROOT / "data" / "schema" / f"{name}.schema.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(set(schema["fields"]), set(rows[0]), name)

    def test_exporter_covers_current_workbook_labels(self):
        exporter = load_exporter()
        self.assertEqual(exporter._english_risk("🟡 黄色预警"), "Watch")
        self.assertEqual(
            exporter._english_quadrant("技术待变现"),
            "Strong technology / finance watch",
        )
        self.assertEqual(
            exporter._english_quadrant("财务韧性强"),
            "Resilient finance / lower technology score",
        )
        self.assertNotEqual(
            exporter._english_collateral(
                "建议争取认股权证，行权价设为当前估值×1.2，期限3年"
            ),
            "Refer to the approved credit policy.",
        )

    def test_pipeline_checks_every_prepared_input(self):
        pipeline = (ROOT / "scripts" / "_pipeline.py").read_text(encoding="utf-8")
        self.assertIn('"industry_reference": MACRO_FILENAME', pipeline)

    def test_bep_delivery_summary_excludes_stale_files(self):
        analysis = (ROOT / "src" / "bep_analysis" / "run_analysis.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("st_mtime_ns >= RUN_STARTED_NS", analysis)
        self.assertIn("'.json': '[JSON]'", analysis)


if __name__ == "__main__":
    unittest.main()
