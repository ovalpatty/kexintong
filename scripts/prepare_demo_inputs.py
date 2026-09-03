#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Adapt a Kexintong CSV package to the integrated patent and BEP workflow."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import zipfile

import pandas as pd


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUILTIN_REFERENCE_ROOT = PROJECT_ROOT / "data" / "reference"
ACTIVE_STATUSES = {"授权", "质押合同登记生效", "开放许可声明", "专利权保全", "专利权保全解除", "许可合同备案生效"}
FLOW_COLUMNS = [
    "revenue_cny_100m",
    "operating_cost_cny_100m",
    "selling_expense_cny_100m",
    "management_expense_cny_100m",
    "finance_expense_cny_100m",
    "rd_expense_cny_100m",
    "operating_cash_flow_cny_100m",
]
INDUSTRY_NAME_MAP = {
    "人工智能行业": "人工智能",
    "光学光电子行业": "光学技术",
    "医药制造业": "生物医药",
    "半导体行业": "半导体",
    "家用电器制造业": "电子电气",
    "新能源行业": "新能源",
    "智能制造装备行业": "机械制造",
    "汽车制造业": "汽车",
    "环保产业": "其他",
    "电子信息制造业": "电子信息",
    "航空航天制造业": "航空航天",
    "计算机及办公设备制造业": "计算机技术",
    "软件和信息技术服务业": "互联网",
    "通信设备制造业": "通信技术",
    "金融保险业": "其他",
    "食品饮料制造业": "其他",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare deterministic demo inputs from the public CSV package")
    parser.add_argument(
        "--package", type=Path, default=PROJECT_ROOT / "data",
        help="Extracted data package directory or ZIP file; defaults to the bundled public demo",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=PROJECT_ROOT / "data" / "generated",
        help="Directory for generated compatibility inputs",
    )
    return parser.parse_args()


def find_package_root(package: Path, scratch_dir: Path) -> Path:
    package = package.resolve()
    if package.is_file() and package.suffix.lower() == ".zip":
        extracted = scratch_dir / "source_package"
        if extracted.exists():
            shutil.rmtree(extracted)
        extracted.mkdir(parents=True)
        with zipfile.ZipFile(package) as archive:
            archive.extractall(extracted)
        candidates = [p for p in extracted.rglob("companies.csv") if p.parent.name == "demo"]
        if not candidates:
            raise FileNotFoundError("data/demo/companies.csv was not found in the ZIP")
        return candidates[0].parents[2]
    if package.is_dir() and (package / "demo" / "companies.csv").is_file():
        return package
    candidates = [package, *package.iterdir()] if package.is_dir() else []
    for candidate in candidates:
        if (candidate / "data" / "demo" / "companies.csv").is_file():
            return candidate
    raise FileNotFoundError("data/demo/companies.csv was not found; provide a package root or ZIP file")


def builtin_reference_root() -> Path:
    """返回冻结在项目内的市场与行业参照资产。

    外部 ZIP 只提供待评估公司的 demo 原始数据，避免用户上传的参照库
    改变 IPC 热度或高价值专利 NLP 语料的计算口径。
    """
    required = [
        "high_value_patent_corpus.csv",
        "ipc_market_reference.csv",
        "industry_bep_reference.csv",
        "raw_material_price_index.csv",
    ]
    missing = [name for name in required if not (BUILTIN_REFERENCE_ROOT / name).is_file()]
    if missing:
        raise FileNotFoundError("Built-in reference assets are incomplete: " + ", ".join(missing))
    return BUILTIN_REFERENCE_ROOT


def _convert_ytd_to_quarterly(financial: pd.DataFrame) -> pd.DataFrame:
    records = []
    for _, group in financial.sort_values(["company_id", "fiscal_year", "fiscal_quarter"]).groupby(["company_id", "fiscal_year"]):
        previous = None
        for _, row in group.iterrows():
            result = row.copy()
            if previous is not None:
                for col in FLOW_COLUMNS:
                    result[col] = row[col] - previous[col]
            previous = row
            result["value_basis"] = "derived_single_quarter"
            records.append(result)
    return pd.DataFrame(records)


def _infer_financial_basis(financial: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    """仅在缺少可靠元数据时，以收入序列作为兼容性推断。"""
    comparisons, declines = 0, 0
    for _, group in financial.sort_values(["company_id", "fiscal_year", "fiscal_quarter"]).groupby(["company_id", "fiscal_year"]):
        values = group["revenue_cny_100m"].to_list()
        comparisons += max(len(values) - 1, 0)
        declines += sum(later < earlier for earlier, later in zip(values, values[1:]))

    # 累计收入应当在同一会计年度单调不减；若频繁回落，说明原值本身为单季度流量。
    if comparisons and declines / comparisons > 0.10:
        return financial.copy(), "heuristic: reported_single_quarter (kept as reported)"
    return _convert_ytd_to_quarterly(financial), "heuristic: cumulative_ytd -> derived_single_quarter"


def normalize_financial_basis(financial: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    """优先使用显式 value_basis；只有元数据缺失或无效时才推断。"""
    if "value_basis" in financial.columns and financial["value_basis"].notna().all():
        bases = set(financial["value_basis"].astype(str).str.strip())
        if bases == {"reported_cumulative_ytd"}:
            return (
                _convert_ytd_to_quarterly(financial),
                "explicit: reported_cumulative_ytd -> derived_single_quarter",
            )
        if bases == {"reported_single_quarter"}:
            return financial.copy(), "explicit: reported_single_quarter (kept as reported)"
        print(
            f"value_basis contains unsupported or mixed values {sorted(bases)}; "
            "falling back to heuristic detection."
        )
    else:
        print("value_basis missing or incomplete; falling back to heuristic detection.")
    return _infer_financial_basis(financial)


def build_company_workbook(companies: pd.DataFrame, patents: pd.DataFrame, financial: pd.DataFrame, path: Path) -> str:
    quarterly, financial_basis = normalize_financial_basis(financial)
    company_list = companies.rename(columns={
        "company_id": "Wind代码", "company_name": "证券简称", "technology_field": "技术领域"
    })[["Wind代码", "证券简称", "技术领域"]]
    finance_sheet = quarterly.rename(columns={
        "company_id": "Wind代码", "company_name": "证券简称",
        "revenue_cny_100m": "营业总收入(亿元)",
        "operating_cost_cny_100m": "营业成本(亿元)",
        "selling_expense_cny_100m": "销售费用(亿元)",
        "management_expense_cny_100m": "管理费用(亿元)",
        "finance_expense_cny_100m": "财务费用(亿元)",
        "rd_expense_cny_100m": "研发费用(亿元)",
        "operating_cash_flow_cny_100m": "经营活动现金流(亿元)",
    })
    finance_sheet["日期"] = finance_sheet.apply(
        lambda r: f"Q{int(r['fiscal_quarter'])} FY{int(r['fiscal_year'])}", axis=1
    )
    finance_sheet = finance_sheet[[
        "Wind代码", "证券简称", "日期", "营业总收入(亿元)", "营业成本(亿元)",
        "销售费用(亿元)", "管理费用(亿元)", "财务费用(亿元)", "研发费用(亿元)", "经营活动现金流(亿元)"
    ]]
    patent_sheet = patents.rename(columns={
        "company_id": "Wind代码", "company_name": "证券简称", "patent_title": "专利名称",
        "assignee": "专利权人", "patent_type": "专利类型", "application_number": "专利申请号",
    })[["Wind代码", "证券简称", "专利名称", "专利权人", "专利类型", "专利申请号"]]
    active = patents[patents["legal_status"].isin(ACTIVE_STATUSES)].copy()
    patent_stats = (active.groupby("company_id").agg(
        证券简称=("company_name", "first"),
        专利权人=("assignee", "first"),
        专利总数=("patent_title", "count"),
    ).reset_index().rename(columns={"company_id": "Wind代码"}))
    patent_stats["主要专利类型"] = active.groupby("company_id")["patent_type"].apply(
        lambda values: ", ".join(sorted(values.dropna().unique()))
    ).reindex(patent_stats["Wind代码"]).to_list()
    domain = companies.groupby("technology_field").agg(公司数=("company_id", "count")).reset_index().rename(columns={"technology_field": "技术领域"})
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        company_list.to_excel(writer, sheet_name="1_公司清单", index=False)
        finance_sheet.to_excel(writer, sheet_name="2_财务运营数据", index=False)
        patent_sheet.to_excel(writer, sheet_name="3_专利与创新数据", index=False)
        domain.to_excel(writer, sheet_name="4_技术领域分布", index=False)
        patent_stats.to_excel(writer, sheet_name="5_专利统计", index=False)
    return financial_basis


def build_patent_detail_workbook(patents: pd.DataFrame, path: Path):
    detail = patents.rename(columns={
        "company_id": "Wind代码", "company_name": "证券简称", "patent_title": "专利名称",
        "assignee": "专利权人", "patent_type": "专利类型", "grant_number": "专利授权号",
        "ipc_code": "IPC分类号", "application_number": "专利申请号", "legal_status": "法律状态",
        "publication_date": "公开公告日", "patent_abstract": "专利摘要", "technology_field": "技术领域",
    })
    columns = ["Wind代码", "证券简称", "专利名称", "专利权人", "专利类型", "专利授权号", "IPC分类号", "专利申请号", "法律状态", "公开公告日", "专利摘要", "技术领域"]
    detail[columns].to_excel(path, sheet_name="专利数据", index=False)


def build_high_value_workbook(high_value: pd.DataFrame, path: Path):
    output = high_value.rename(columns={
        "patent_title": "专利名称", "company_name": "公司名称", "assignee": "专利权人",
        "grant_number": "专利授权号", "grant_date": "授权公告日", "patent_type": "专利类型",
        "legal_status": "法律状态", "ipc_code": "IPC分类号", "technology_field": "技术领域",
        "patent_abstract": "专利摘要",
    })
    output.to_excel(path, sheet_name="专利清单", index=False)


def build_ipc_workbook(ipc: pd.DataFrame, path: Path):
    detail = ipc.rename(columns={
        "company_id": "Wind代码", "company_name": "证券简称", "ipc_code": "IPC分类号", "patent_count": "专利数量"
    })[["Wind代码", "证券简称", "IPC分类号", "专利数量"]]
    total = detail.groupby(["Wind代码", "证券简称"], as_index=False)["专利数量"].sum().rename(columns={"专利数量": "有效专利数量(件)"})
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        total.to_excel(writer, sheet_name="A股公司专利总数", index=False)
        detail.to_excel(writer, sheet_name="IPC分类明细", index=False)


def build_macro_workbook(industry: pd.DataFrame, material: pd.DataFrame, path: Path):
    baseline = industry.copy()
    baseline["industry"] = baseline["industry"].map(INDUSTRY_NAME_MAP).fillna(baseline["industry"])
    bep_rows = [["行业名称", "平均营业收入", "平均营业成本", "平均营业成本率", "平均毛利率", "平均BEP营业收入"]]
    bep_rows += baseline[["industry", "avg_revenue_cny_100m", "avg_operating_cost_cny_100m", "avg_cost_ratio_pct", "avg_gross_margin_pct", "avg_bep_revenue_cny_100m"]].values.tolist()
    detail_rows = [["说明"], ["行业名称", "年份", "营业收入", "营业成本", "营业成本率", "毛利率", "BEP营业收入"]]
    for _, row in baseline.iterrows():
        detail_rows.append([row["industry"], 2025, row["avg_revenue_cny_100m"], row["avg_operating_cost_cny_100m"], row["avg_cost_ratio_pct"], row["avg_gross_margin_pct"], row["avg_bep_revenue_cny_100m"]])
    material_rows = [["说明"], ["年份", "钢材", "铜", "铝", "原油"]]
    material_rows += material[["year", "steel_price_index", "copper_usd_per_ton", "aluminum_usd_per_ton", "crude_oil_usd_per_ton"]].values.tolist()
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame(bep_rows).to_excel(writer, sheet_name="行业BEP基准", index=False, header=False)
        pd.DataFrame(detail_rows).to_excel(writer, sheet_name="行业财务指标明细", index=False, header=False)
        pd.DataFrame(material_rows).to_excel(writer, sheet_name="原材料价格指数", index=False, header=False)


def main() -> int:
    args = parse_args()
    adapted_dir = args.output_dir.resolve()
    adapted_dir.mkdir(parents=True, exist_ok=True)
    package_root = find_package_root(args.package, adapted_dir)
    data_root = package_root if (package_root / "demo").is_dir() else package_root / "data"
    reference_root = builtin_reference_root()
    companies = pd.read_csv(data_root / "demo" / "companies.csv", encoding="utf-8-sig")
    patents = pd.read_csv(data_root / "demo" / "patent_records.csv", encoding="utf-8-sig")
    financial = pd.read_csv(data_root / "demo" / "financial_quarterly.csv", encoding="utf-8-sig")
    high_value = pd.read_csv(reference_root / "high_value_patent_corpus.csv", encoding="utf-8-sig")
    ipc = pd.read_csv(reference_root / "ipc_market_reference.csv", encoding="utf-8-sig")
    industry = pd.read_csv(reference_root / "industry_bep_reference.csv", encoding="utf-8-sig")
    material = pd.read_csv(reference_root / "raw_material_price_index.csv", encoding="utf-8-sig")

    financial_basis = build_company_workbook(companies, patents, financial, adapted_dir / "company_data.xlsx")
    build_patent_detail_workbook(patents, adapted_dir / "patent_records.xlsx")
    build_high_value_workbook(high_value, adapted_dir / "high_value_patents.xlsx")
    build_ipc_workbook(ipc, adapted_dir / "ipc_reference.xlsx")
    build_macro_workbook(industry, material, adapted_dir / "industry_reference.xlsx")

    conversion_summary = {
        "sample_companies": companies[["company_id", "company_name", "technology_field"]].to_dict(orient="records"),
        "patent_records": int(len(patents)),
        "financial_observations": int(len(financial)),
        "financial_transform": financial_basis,
        "reference_rows": {"high_value_patents": int(len(high_value)), "ipc_market": int(len(ipc)), "industry_bep": int(len(industry)), "raw_material": int(len(material))},
    }
    (adapted_dir / "input_preparation_summary.json").write_text(
        json.dumps(conversion_summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("Using the frozen public reference assets bundled with the repository.")
    print(f"Prepared deterministic compatibility inputs: {adapted_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
