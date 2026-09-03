# ============================================================
# scoring_engine.py  —  多维度专利质量综合评分引擎（v2，含CAGR维度）
# ============================================================
"""
综合评分公式（6维度）
─────────────────────────────────────────────────────
  PatentScore_raw = Σ(wi × score_i)

  维度                        权重  数据来源
  ──────────────────────────  ────  ──────────────────────────────────
  score_1 专利存量得分         20%  新版有效专利计数（法律状态过滤）
  score_2 专利类型质量得分     12%  授权发明×3/实用新型×2/外观设计×1
  score_3 IPC热度得分          20%  新版逐条IPC → 加权热度
  score_4 近三年CAGR成长性     13%  新版2022-2025年专利授权CAGR（新增）
  score_5 NLP语义相似度        25%  与高价值专利库TF-IDF余弦相似度
  score_6 关键词密度得分       10%  六大前沿技术关键词密度

  FinalScore = PatentScore_raw × IndustryWeight  →  归一化 0-100
"""
import numpy as np
import pandas as pd
from config import (
    CAGR_CAP,
    CAGR_FLOOR,
    CREDIT_GRADE_THRESHOLDS,
    PATENT_TYPE_WEIGHTS,
    SCORE_WEIGHTS,
)


def build_final_scores(comp_data, ipc_scores_df, nlp_scores_df):
    companies = comp_data["company_list"][
        ["Wind代码","证券简称","技术领域","行业","行业权重"]
    ].copy()

    stock_df = _score_patent_stock(comp_data)
    type_df  = _score_patent_type(comp_data)
    cagr_df  = _score_patent_cagr(comp_data)

    df = companies.merge(stock_df, on="Wind代码", how="left")
    df = df.merge(type_df, on="Wind代码", how="left")
    df = df.merge(cagr_df, on="Wind代码", how="left")
    df = df.merge(
        ipc_scores_df[["Wind代码","IPC热度得分(0-100)","核心IPC大类",
                        "核心IPC技术域","集中度CR3","近三年CAGR"]],
        on="Wind代码", how="left", suffixes=("","_ipc")
    )
    df = df.merge(
        nlp_scores_df[["Wind代码","NLP综合得分(0-100)","语义相似度得分(0-100)",
                        "关键词密度得分(0-100)","前沿关键词总分"]],
        on="Wind代码", how="left"
    )
    df = df.fillna(0)

    w = SCORE_WEIGHTS
    df["专利综合得分_基础"] = (
        df["专利存量得分(0-100)"]      * w["patent_stock"]
        + df["专利类型质量得分(0-100)"] * w["patent_type"]
        + df["IPC热度得分(0-100)"]      * w["ipc_heat"]
        + df["专利CAGR得分(0-100)"]     * w["patent_cagr"]
        + df["NLP综合得分(0-100)"]      * w["nlp_similarity"]
        + df["关键词密度得分(0-100)"]   * w["keyword_density"]
    ).round(2)

    df["行业权重乘数"]            = df["行业权重"]
    df["专利综合得分_含行业权重"] = (df["专利综合得分_基础"] * df["行业权重乘数"]).round(2)
    df["专利价值综合评分(0-100)"] = (_minmax(df["专利综合得分_含行业权重"]) * 100).round(2)
    df["信用增强等级"]            = df["专利价值综合评分(0-100)"].apply(_to_grade)
    df["融资建议"]                = df["信用增强等级"].apply(_to_advice)
    df["综合排名"]                = df["专利价值综合评分(0-100)"].rank(ascending=False, method="min").astype(int)
    return df.sort_values("综合排名").reset_index(drop=True)


# ── 维度1：专利存量得分 ──────────────────────────────────────────
def _score_patent_stock(comp_data):
    stats = (
        comp_data["patent_stats"][["Wind代码","专利总数"]]
        .groupby("Wind代码", as_index=False)["专利总数"].sum()
    )
    companies = comp_data["company_list"][["Wind代码","证券简称","技术领域"]].copy()
    df = companies.merge(stats, on="Wind代码", how="left").fillna({"专利总数": 0})

    df["存量_行业内归一"] = df.groupby("技术领域")["专利总数"].transform(_minmax)
    df["存量_全局归一"]   = _minmax(df["专利总数"])
    df["专利存量得分(0-100)"] = (
        df["存量_行业内归一"] * 0.6 + df["存量_全局归一"] * 0.4
    ) * 100
    df["专利存量得分(0-100)"] = df["专利存量得分(0-100)"].round(2)
    return df[["Wind代码","专利总数","专利存量得分(0-100)"]]


# ── 维度2：专利类型质量得分 ──────────────────────────────────────
def _score_patent_type(comp_data):
    pat = comp_data["patents"].copy()
    pat["类型权重"] = pat["专利类型"].map(
        lambda t: PATENT_TYPE_WEIGHTS.get(t, 1.0)
    )
    weighted = (
        pat.groupby("Wind代码")["类型权重"]
        .sum().reset_index().rename(columns={"类型权重": "加权专利数"})
    )
    inv_count = (
        pat[pat["专利类型"].isin(["授权发明","发明"])]
        .groupby("Wind代码").size().reset_index(name="发明专利数")
    )
    total_count = pat.groupby("Wind代码").size().reset_index(name="专利总数_明细")
    type_df = weighted.merge(inv_count, on="Wind代码", how="left").merge(total_count, on="Wind代码", how="left")
    type_df["发明专利数"] = type_df["发明专利数"].fillna(0)
    type_df["发明专利占比"] = (
        type_df["发明专利数"] / type_df["专利总数_明细"].replace(0, np.nan)
    ).fillna(0)
    type_df["类型质量综合"] = (
        _minmax(type_df["加权专利数"]) * 0.70
        + _minmax(type_df["发明专利占比"]) * 0.30
    )
    type_df["专利类型质量得分(0-100)"] = (type_df["类型质量综合"] * 100).round(2)
    return type_df[["Wind代码","加权专利数","发明专利占比","专利类型质量得分(0-100)"]]


# ── 维度3（新增）：近三年专利CAGR成长性得分 ───────────────────────
def _score_patent_cagr(comp_data):
    companies = comp_data["company_list"][["Wind代码"]].copy()
    if "patent_cagr" not in comp_data or comp_data["patent_cagr"].empty:
        companies["近三年CAGR_原始"] = 0.0
        companies["专利CAGR得分(0-100)"] = 50.0
        return companies[["Wind代码","专利CAGR得分(0-100)"]]

    cagr = comp_data["patent_cagr"][["Wind代码","近三年CAGR"]].copy()
    df = companies.merge(cagr, on="Wind代码", how="left").fillna({"近三年CAGR": 0.0})

    # CAGR 截断处理：上限150%，避免极端值扭曲分布
    df["近三年CAGR_截断"] = df["近三年CAGR"].clip(CAGR_FLOOR, CAGR_CAP)
    df["专利CAGR得分(0-100)"] = (_minmax(df["近三年CAGR_截断"]) * 100).round(2)
    return df[["Wind代码","专利CAGR得分(0-100)"]]


# ── 信用等级 & 投保贷建议 ────────────────────────────────────────
def _to_grade(score):
    for grade, (lo, hi) in CREDIT_GRADE_THRESHOLDS.items():
        if lo <= score <= hi:
            return grade
    return "CCC"


def _to_advice(grade):
    return {
        "AAA": "建议优先授信，可适度放宽抵押要求，给予最优惠利率（基准-50BP）",
        "AA":  "建议正常授信，可适度提高信用贷款比例，给予优惠利率（基准-30BP）",
        "A":   "建议正常授信，维持标准抵押要求，标准利率",
        "BBB": "建议审慎授信，需补充风险缓释措施，利率适当上浮（基准+20BP）",
        "BB":  "建议有条件授信，需强化风险监测，利率上浮（基准+50BP）",
        "B":   "建议限制授信规模，需充分抵押担保，利率显著上浮（基准+100BP）",
        "CCC": "暂不建议主动授信，建议等待技术积累和专利布局改善后重新评估",
    }.get(grade, "待评估")


def _minmax(series):
    mn, mx = series.min(), series.max()
    if mx == mn:
        return pd.Series([0.5] * len(series), index=series.index)
    return (series - mn) / (mx - mn)
