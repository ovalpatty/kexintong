# ============================================================
# ipc_analysis.py  —  基于IPC分类的技术集群与热度分析
# 优先使用当前输入包中的逐条专利数据。
# ============================================================
import re
import pandas as pd
import numpy as np
from config import IPC_CLASS_MAP, IPC_SECTION_MAP, INDUSTRY_WEIGHTS
from data_loader import build_company_ipc_from_detail


def run_ipc_analysis(ipc_data, hv_data, comp_data, patent_detail=None):
    """
    主函数：输出三张分析表
      1. ipc_heat_df        — IPC大类热度指数
      2. company_ipc_df     — 每家公司的IPC分布与热度得分（含CAGR）
      3. domain_cluster_df  — 技术领域集群分析
    """
    # 如果有新版逐条数据，用它重建公司IPC统计（覆盖41家，更精确）
    if patent_detail is not None:
        enriched_ipc_detail = build_company_ipc_from_detail(patent_detail, ipc_data)
    else:
        enriched_ipc_detail = ipc_data["detail"]

    ipc_heat_df      = _build_ipc_heat(ipc_data, hv_data, enriched_ipc_detail)
    company_ipc_df   = _score_companies_by_ipc(comp_data, enriched_ipc_detail, ipc_heat_df)
    domain_cluster_df = _domain_cluster_analysis(ipc_heat_df)
    return ipc_heat_df, company_ipc_df, domain_cluster_df


# ── 1. IPC大类热度指数 ────────────────────────────────────────────
def _build_ipc_heat(ipc_data, hv_data, enriched_detail):
    # 全市场基准：使用原全市场IPC数据（5489家公司）
    market_detail = ipc_data["detail"].copy()
    valid_market  = market_detail[market_detail["IPC_class"].str.match(r"^[A-H]\d{2}$", na=False)]
    class_total   = (
        valid_market.groupby("IPC_class")["专利数量"]
        .sum().reset_index().rename(columns={"专利数量": "全市场专利数"})
    )

    # 高价值专利库中各大类占比
    hv_valid = hv_data[hv_data["IPC_class"].str.match(r"^[A-H]\d{2}$", na=False)]
    hv_class = hv_valid.groupby("IPC_class").size().reset_index(name="高价值专利数")

    heat = class_total.merge(hv_class, on="IPC_class", how="left").fillna(0)
    heat["技术领域"] = heat["IPC_class"].map(
        lambda c: IPC_CLASS_MAP.get(c, IPC_SECTION_MAP.get(c[0], "其他"))
    )
    heat["行业权重"] = heat["技术领域"].map(
        lambda x: INDUSTRY_WEIGHTS.get(x, INDUSTRY_WEIGHTS["其他"])
    )

    total_hv  = heat["高价值专利数"].sum()
    total_all = heat["全市场专利数"].sum()
    heat["高价值专利占比"] = heat["高价值专利数"] / total_hv  if total_hv  > 0 else 0
    heat["全市场占比"]     = heat["全市场专利数"] / total_all if total_all > 0 else 0

    # HHI（用当前输入公司的IPC数据计算竞争集中度）
    heat["HHI"] = heat["IPC_class"].apply(
        lambda c: _calc_hhi(enriched_detail[enriched_detail["IPC_class"] == c])
    )

    heat["高价值占比归一"] = _minmax(heat["高价值专利占比"])
    heat["全市场占比归一"] = _minmax(heat["全市场占比"])
    heat["HHI归一"]        = _minmax(heat["HHI"])

    heat["IPC热度指数_原始"] = (
        heat["高价值占比归一"] * 0.50
        + heat["全市场占比归一"] * 0.30
        + (1 - heat["HHI归一"]) * 0.20
    )
    heat["IPC热度指数"]    = (_minmax(heat["IPC热度指数_原始"]) * 100).round(2)
    heat["热度×行业权重"]  = (heat["IPC热度指数"] * heat["行业权重"]).round(2)

    return heat.sort_values("IPC热度指数", ascending=False).reset_index(drop=True)


def _calc_hhi(sub_df):
    if sub_df.empty or sub_df["专利数量"].sum() == 0:
        return 0.0
    shares = sub_df["专利数量"] / sub_df["专利数量"].sum()
    return float((shares ** 2).sum())


# ── 2. 每家公司IPC分布与热度得分 ──────────────────────────────────
def _score_companies_by_ipc(comp_data, enriched_detail, ipc_heat_df):
    valid = enriched_detail[enriched_detail["IPC_class"].str.match(r"^[A-H]\d{2}$", na=False)].copy()
    heat_map   = dict(zip(ipc_heat_df["IPC_class"], ipc_heat_df["IPC热度指数"]))
    domain_map = dict(zip(ipc_heat_df["IPC_class"], ipc_heat_df["技术领域"]))

    companies = comp_data["company_list"][["Wind代码","证券简称","技术领域","行业","行业权重"]].copy()
    cagr_map  = {}
    if "patent_cagr" in comp_data:
        cagr_map = dict(zip(comp_data["patent_cagr"]["Wind代码"],
                            comp_data["patent_cagr"]["近三年CAGR"]))

    rows = []
    for _, row in companies.iterrows():
        code = row["Wind代码"]
        sub  = valid[valid["Wind代码"] == code]

        if sub.empty:
            rows.append({
                "Wind代码": code, "证券简称": row["证券简称"],
                "技术领域": row["技术领域"], "行业权重": row["行业权重"],
                "有效IPC记录数": 0, "覆盖IPC大类数": 0,
                "核心IPC大类": "N/A", "核心IPC技术域": "N/A",
                "集中度CR3": 0, "加权IPC热度均值": 50.0,
                "近三年CAGR": cagr_map.get(code, 0.0),
                "IPC热度得分(0-100)": 50.0,
            })
            continue

        total_pat = sub["专利数量"].sum()
        top3      = sub.groupby("IPC_class")["专利数量"].sum().nlargest(3)
        cr3       = top3.sum() / total_pat if total_pat > 0 else 0
        top1_class  = top3.index[0] if len(top3) > 0 else "U99"
        top1_domain = domain_map.get(top1_class, "其他")

        sub = sub.copy()
        sub["热度"] = sub["IPC_class"].map(lambda c: heat_map.get(c, 30.0))
        weighted_heat = (
            (sub["热度"] * sub["专利数量"]).sum() / total_pat
            if total_pat > 0 else 30.0
        )

        rows.append({
            "Wind代码":           code,
            "证券简称":           row["证券简称"],
            "技术领域":           row["技术领域"],
            "行业权重":           row["行业权重"],
            "有效IPC记录数":      int(sub.shape[0]),
            "覆盖IPC大类数":      int(sub["IPC_class"].nunique()),
            "核心IPC大类":        top1_class,
            "核心IPC技术域":      top1_domain,
            "集中度CR3":          round(cr3, 4),
            "加权IPC热度均值":    round(weighted_heat, 2),
            "近三年CAGR":         cagr_map.get(code, 0.0),
            "IPC热度得分(0-100)": round(weighted_heat, 2),
        })

    df = pd.DataFrame(rows)
    df["IPC热度得分(0-100)"] = (_minmax(df["IPC热度得分(0-100)"]) * 100).round(2)
    return df


# ── 3. 技术领域集群分析 ────────────────────────────────────────────
def _domain_cluster_analysis(ipc_heat_df):
    merged = ipc_heat_df.groupby("技术领域").agg(
        IPC大类数    = ("IPC_class",      "count"),
        全市场专利数 = ("全市场专利数",   "sum"),
        高价值专利数 = ("高价值专利数",   "sum"),
        平均热度指数 = ("IPC热度指数",    "mean"),
        行业权重    = ("行业权重",        "first"),
    ).reset_index()
    merged["高价值率"] = (
        merged["高价值专利数"] / merged["全市场专利数"].replace(0, np.nan)
    ).fillna(0).round(4)
    merged["综合热度×行业权重"] = (merged["平均热度指数"] * merged["行业权重"]).round(2)
    return merged.sort_values("综合热度×行业权重", ascending=False).reset_index(drop=True)


# ── 工具函数 ─────────────────────────────────────────────────────
def _minmax(series):
    mn, mx = series.min(), series.max()
    if mx == mn:
        return pd.Series([0.5] * len(series), index=series.index)
    return (series - mn) / (mx - mn)
