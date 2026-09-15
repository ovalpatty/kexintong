#!/usr/bin/env python3
"""Export a compact, derived-only assessment payload for the separate website.

The exporter intentionally reads finished analytical workbooks and writes only
company-level assessment fields. It never copies raw financial observations,
patent records, abstracts, IPC rows, or reference corpora into the payload.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _number(value: object, digits: int = 2) -> float | None:
    if pd.isna(value):
        return None
    return round(float(value), digits)


def _english_risk(value: object) -> str:
    text = (
        str(value)
        .replace("🟢", "")
        .replace("🟡", "")
        .replace("🟠", "")
        .replace("🔴", "")
        .strip()
    )
    mapping = {
        "正常": "Normal",
        "黄色预警": "Watch",
        "橙色预警": "Elevated",
        "红色预警": "High",
        "优质标的": "Priority candidate",
        "稳健经营": "Resilient",
        "双重风险": "Dual risk",
        "技术待提升": "Technology watch",
    }
    return mapping.get(text, text or "Not assessed")


def _english_quadrant(value: object) -> str:
    text = str(value).strip()
    return {
        "优质标的": "Strong technology / resilient finance",
        "双重风险": "Technology and finance watch",
        "技术待变现": "Strong technology / finance watch",
        "财务韧性强": "Resilient finance / lower technology score",
        # Backward-compatible labels used by earlier research workbooks.
        "技术待提升": "Technology development watch",
        "稳健经营": "Financially resilient",
    }.get(text, text or "Not classified")


def _english_company(company_id: str, value: object) -> str:
    return {
        "002230.SZ": "iFLYTEK",
        "300760.SZ": "Mindray",
        "002273.SZ": "Crystal-Optech",
        "000157.SZ": "Zoomlion",
        "000333.SZ": "Midea Group",
    }.get(company_id, str(value))


def _english_field(value: object) -> str:
    return {
        "人工智能": "Artificial intelligence",
        "生物医药": "Biopharmaceuticals",
        "光学技术": "Optical technology",
        "机械制造": "Industrial machinery",
        "电子电气": "Electrical and electronics",
    }.get(str(value), str(value))


def _english_collateral(value: object) -> str:
    text = str(value).strip()
    return {
        "建议争取认股权证，行权价设为当前估值×1.2，期限3年": "Seek a warrant where appropriate: exercise price at 1.2× current valuation; three-year term.",
        "可选择性设置认股权证，行权价×1.3，期限2年": "Selective warrant: exercise price ×1.3; two-year term.",
        "暂不建议设置认股权证": "No warrant is recommended.",
    }.get(text, "Refer to the approved credit policy.")


def export_payload(input_dir: Path, output_path: Path) -> Path:
    reports = input_dir / "reports"
    dimensions = pd.read_excel(reports / "patent_scoring_report.xlsx", sheet_name=6)
    summary = pd.read_excel(reports / "bep_analysis_results.xlsx", sheet_name=0)
    portfolio = pd.read_excel(reports / "bep_analysis_results.xlsx", sheet_name=2)
    pricing = pd.read_excel(reports / "bep_analysis_results.xlsx", sheet_name=3)

    # Workbook sheet labels are deliberately not used here. Position-based
    # extraction keeps the public-export contract independent of presentation
    # wording in the compatibility workbooks.
    dimension_by_id = {
        str(row.iloc[1]): {
            "patent_stock": _number(row.iloc[8]),
            "patent_quality": _number(row.iloc[9]),
            "ipc_heat": _number(row.iloc[10]),
            "patent_growth": _number(row.iloc[11]),
            "nlp_similarity": _number(row.iloc[12]),
            "frontier_density": _number(row.iloc[13]),
        }
        for _, row in dimensions.iterrows()
    }
    pricing_by_id = {str(row.iloc[0]): row for _, row in pricing.iterrows()}
    portfolio_by_id = {str(row.iloc[0]): row for _, row in portfolio.iterrows()}

    companies = []
    for _, row in summary.iterrows():
        company_id = str(row.iloc[0])
        price = pricing_by_id.get(company_id)
        profile = portfolio_by_id.get(company_id)
        if price is None or profile is None:
            continue
        companies.append(
            {
                "company_id": company_id,
                "company_name": _english_company(company_id, row.iloc[1]),
                "company_name_cn": str(row.iloc[1]),
                "technology_field": _english_field(row.iloc[2]),
                "industry": _english_field(row.iloc[3]),
                "assessment_period": "2026 Q1",
                "patent_score": _number(row.iloc[5]),
                "credit_grade": str(row.iloc[4]),
                "patent_dimensions": dimension_by_id.get(company_id, {}),
                "financial_resilience": {
                    "bep_margin": _number(row.iloc[13]),
                    "gross_margin_pct": _number(row.iloc[9] * 100),
                    "fixed_cost_rate_pct": _number(row.iloc[10] * 100),
                    "industry_gross_margin_pct": _number(row.iloc[15] * 100),
                },
                "risk": {
                    "level": _english_risk(price.iloc[10]),
                    "quadrant": _english_quadrant(profile.iloc[10]),
                },
                "suggested_terms": {
                    "loan_adjustment_bp": _number(price.iloc[7], 0),
                    "insurance_factor": _number(price.iloc[8]),
                    "collateral_terms": _english_collateral(price.iloc[9]),
                    "monitoring": "Quarterly",
                },
            }
        )

    payload = {
        "payload_version": "1.0.0",
        "dataset_label": "Kexintong public demo - five-company sample",
        "assessment_type": "Derived technology credit assessment",
        "as_of": "2026 Q1",
        "scope_note": (
            "This payload contains derived company-level assessments only. "
            "It does not include raw patent, financial, IPC, or reference data."
        ),
        "companies": companies,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a derived assessment payload for the public website.")
    parser.add_argument("--input-dir", type=Path, default=PROJECT_ROOT / "outputs" / "latest")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "outputs" / "latest" / "public" / "company_assessments.json")
    args = parser.parse_args()
    output = export_payload(args.input_dir.resolve(), args.output.resolve())
    print(f"Derived public assessment payload written to: {output}")


if __name__ == "__main__":
    main()
