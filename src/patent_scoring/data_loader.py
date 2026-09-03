# ============================================================
# data_loader.py  —  数据加载与预处理模块（含新版逐条专利数据）
# ============================================================
import re
import pandas as pd
import numpy as np
from config import DATA_FILES, COMPANY_DOMAIN_TO_INDUSTRY, INDUSTRY_WEIGHTS, ACTIVE_LEGAL_STATUS


def load_all_data():
    """加载所有数据源，返回清洗后的 DataFrame 字典"""
    comp   = _load_comprehensive()
    hv     = _load_high_value()
    ipc    = _load_ipc()
    detail = _load_patent_detail()
    comp   = _enrich_with_detail(comp, detail)
    return {"comprehensive": comp, "high_value": hv, "ipc": ipc, "patent_detail": detail}


# ── 数据源1：公司综合数据 ─────────────────────────────────────────
def _load_comprehensive():
    xf = DATA_FILES["comprehensive"]
    out = {}
    out["company_list"] = pd.read_excel(xf, sheet_name="1_公司清单")
    out["finance"]      = pd.read_excel(xf, sheet_name="2_财务运营数据")
    out["patents"]      = pd.read_excel(xf, sheet_name="3_专利与创新数据")
    out["patent_stats"] = pd.read_excel(xf, sheet_name="5_专利统计")
    out["tech_domain"]  = pd.read_excel(xf, sheet_name="4_技术领域分布")

    company_df = out["company_list"].copy()
    company_df["行业"] = company_df["技术领域"].map(
        lambda x: COMPANY_DOMAIN_TO_INDUSTRY.get(x, "其他")
    )
    company_df["行业权重"] = company_df["行业"].map(
        lambda x: INDUSTRY_WEIGHTS.get(x, INDUSTRY_WEIGHTS["其他"])
    )
    out["company_list"] = company_df
    return out


# ── 数据源2：高价值专利清单 ───────────────────────────────────────
def _load_high_value():
    xf = DATA_FILES["high_value"]
    df = pd.read_excel(xf, sheet_name="专利清单")
    df["IPC_primary"] = df["IPC分类号"].apply(_extract_primary_ipc)
    df["IPC_section"] = df["IPC_primary"].str[0].fillna("U")
    df["IPC_class"]   = df["IPC_primary"].str[:3].fillna("U")
    df["text"]        = df["专利名称"].fillna("") + "。" + df["专利摘要"].fillna("")
    return df


# ── 数据源3：A股上市公司专利IPC分类数据（全市场基准）───────────────
def _load_ipc():
    xf = DATA_FILES["ipc_class"]
    out = {}
    out["total"]  = pd.read_excel(xf, sheet_name="A股公司专利总数")
    detail        = pd.read_excel(xf, sheet_name="IPC分类明细")
    detail["IPC_primary"] = detail["IPC分类号"].apply(_extract_primary_ipc)
    detail["IPC_section"] = detail["IPC_primary"].str[0].fillna("U")
    detail["IPC_class"]   = detail["IPC_primary"].str[:3].fillna("U")
    out["detail"] = detail
    return out


# ── 数据源4：逐条专利明细 ─────────────────────────────────────────
def _load_patent_detail():
    xf = DATA_FILES["patent_detail"]
    df = pd.read_excel(xf, sheet_name="专利数据")

    df["IPC_primary"] = df["IPC分类号"].apply(_extract_primary_ipc)
    df["IPC_section"] = df["IPC_primary"].str[0].fillna("U")
    df["IPC_class"]   = df["IPC_primary"].str[:3].fillna("U")
    df["is_active"]   = df["法律状态"].isin(ACTIVE_LEGAL_STATUS)
    df["公开公告日"]   = pd.to_datetime(df["公开公告日"], errors="coerce")
    df["年份"]         = df["公开公告日"].dt.year

    def _make_text(row):
        name = str(row["专利名称"]) if pd.notna(row["专利名称"]) else ""
        abst = str(row["专利摘要"]) if (pd.notna(row["专利摘要"])
                                        and row["专利摘要"] != "[数据未提供]") else ""
        return (name + "。" + abst).strip("。").strip()

    df["text"] = df.apply(_make_text, axis=1)

    print(f"[数据源4] {len(df)} 条专利 | "
          f"{df['Wind代码'].nunique()} 家公司 | "
          f"有效专利 {df['is_active'].sum()} 条 | "
          f"覆盖 {df['年份'].min():.0f}–{df['年份'].max():.0f}")
    return df


# ── 用新版详细数据丰富 comprehensive ─────────────────────────────
def _enrich_with_detail(comp, detail):
    new_codes = set(detail["Wind代码"].unique())

    # ── 重建 patent_stats（有效专利汇总）───────────────────────
    active = detail[detail["is_active"]].copy()
    new_stats = (
        active.groupby("Wind代码")
        .agg(
            证券简称   = ("证券简称", "first"),
            专利总数   = ("专利名称", "count"),
            授权发明数 = ("专利类型", lambda x: (x == "授权发明").sum()),
            实用新型数 = ("专利类型", lambda x: (x == "实用新型").sum()),
            外观设计数 = ("专利类型", lambda x: (x == "外观设计").sum()),
        )
        .reset_index()
    )
    new_stats["主要专利类型"] = new_stats.apply(
        lambda r: ", ".join([t for t, n in [
            ("授权发明", r["授权发明数"]),
            ("实用新型", r["实用新型数"]),
            ("外观设计", r["外观设计数"]),
        ] if n > 0]), axis=1
    )
    new_stats["专利权人"] = new_stats["证券简称"]

    old_only = comp["patent_stats"][~comp["patent_stats"]["Wind代码"].isin(new_codes)]
    comp["patent_stats"] = pd.concat([new_stats, old_only], ignore_index=True)

    # ── 替换 patents 明细（保留旧版未覆盖公司）──────────────────
    new_patents = detail[["Wind代码","证券简称","专利名称","专利权人",
                           "专利类型","法律状态","IPC_primary","IPC_class",
                           "is_active","年份","text"]].copy()
    old_only_pat = comp["patents"][~comp["patents"]["Wind代码"].isin(new_codes)].copy()
    for col in ["IPC_primary","IPC_class","is_active","年份","text"]:
        if col not in old_only_pat.columns:
            old_only_pat[col] = None
    comp["patents"] = pd.concat([new_patents, old_only_pat], ignore_index=True)

    # ── 新增：近三年专利CAGR ─────────────────────────────────
    comp["patent_cagr"] = _calc_patent_cagr(detail)

    print(f"[数据融合] patent_stats: {len(comp['patent_stats'])} 家 | "
          f"patents明细: {len(comp['patents'])} 条")
    return comp


def _calc_patent_cagr(detail):
    active = detail[detail["is_active"] & detail["年份"].between(2022, 2025)].copy()
    yearly = (
        active.groupby(["Wind代码", "证券简称", "年份"])
        .size().reset_index(name="当年专利数")
    )
    rows = []
    for code, grp in yearly.groupby("Wind代码"):
        name = grp["证券简称"].iloc[0]
        yr_map = dict(zip(grp["年份"], grp["当年专利数"]))
        v0 = int(yr_map.get(2022, 0))
        v3 = int(yr_map.get(2025, 0))
        yr2023 = int(yr_map.get(2023, 0))
        yr2024 = int(yr_map.get(2024, 0))
        cagr = ((v3/v0)**(1/3)-1) if v0 > 0 and v3 > 0 else (1.0 if v3 > 0 else 0.0)
        rows.append({
            "Wind代码":   code,
            "证券简称":   name,
            "2022专利数": v0,
            "2023专利数": yr2023,
            "2024专利数": yr2024,
            "2025专利数": v3,
            "近三年CAGR": round(cagr, 4),
        })
    return pd.DataFrame(rows)


# ── 公司专利语料构建 ──────────────────────────────────────────────
def build_company_patent_corpus(comp_data):
    pat_df = comp_data["patents"].copy()
    col = "text" if "text" in pat_df.columns else "专利名称"
    pat_df["_corpus"] = pat_df[col].fillna("").astype(str)
    corpus = (
        pat_df.groupby("Wind代码")["_corpus"]
        .apply(lambda s: " ".join(s.tolist()))
        .reset_index().rename(columns={"_corpus": "corpus"})
    )
    return dict(zip(corpus["Wind代码"], corpus["corpus"]))


# ── 用新版数据重建公司级 IPC 统计表（41家公司，更细粒度）─────────────
def build_company_ipc_from_detail(patent_detail, ipc_market_data):
    active = patent_detail[
        patent_detail["is_active"]
        & patent_detail["IPC_class"].str.match(r"^[A-H]\d{2}$", na=False)
    ].copy()
    detail_new = (
        active.groupby(["Wind代码","证券简称","IPC_class"])
        .size().reset_index(name="专利数量")
    )
    new_codes = set(active["Wind代码"].unique())
    old_only  = ipc_market_data["detail"][~ipc_market_data["detail"]["Wind代码"].isin(new_codes)]
    combined  = pd.concat(
        [detail_new, old_only[["Wind代码","证券简称","IPC_class","专利数量"]]],
        ignore_index=True
    )
    print(f"[IPC重建] 新版覆盖 {len(new_codes)} 家公司 | "
          f"合计 {len(combined)} 条IPC记录（原版 {len(ipc_market_data['detail'])} 条）")
    return combined


# ── 工具函数 ─────────────────────────────────────────────────────
def _extract_primary_ipc(raw):
    if pd.isna(raw):
        return "U99"
    raw = str(raw)
    m = re.search(r"([A-H]\d{2}[A-Z]?\d*/\d+)", raw)
    if m:
        return m.group(1)
    m2 = re.search(r"([A-H]\d{2})", raw)
    if m2:
        return m2.group(1)
    return "U99"
