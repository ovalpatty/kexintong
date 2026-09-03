# ============================================================
# nlp_analysis.py  —  基于NLP的专利文本深度语义特征提取
# ============================================================
"""
技术路径说明
────────────
1. 分词：使用 jieba 对中文专利文本进行分词
2. 向量化：TF-IDF（可替换为 BERT 等预训练模型，接口保持不变）
3. 与高价值专利库的语义相似度：
   - 按技术领域将高价值专利分组，构建行业子向量空间
   - 计算公司专利语料与各子空间的余弦相似度，取最相关领域的加权均值
4. 行业权重融合：相似度得分 × 行业权重系数
5. 创新关键词密度：统计前沿技术关键词出现频次，归一化为 0-100 分
"""
import re
import numpy as np
import pandas as pd
import jieba
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from config import FRONTIER_KEYWORDS, INDUSTRY_WEIGHTS, TECH_DOMAIN_TO_INDUSTRY


# ── 停用词（简化版，可替换为标准停用词表）──────────────────────────
_STOPWORDS = set([
    "的", "了", "在", "是", "和", "与", "或", "对", "一种", "该", "其",
    "通过", "可以", "进行", "本", "发明", "涉及", "提供",
    "具有", "包括", "方法", "装置", "系统", "设备", "技术",
    "领域", "实现", "用于", "以及", "使得", "并且", "从而",
    "具体", "优选", "实施", "例", "方案", "步骤", "结构",
])


def _tokenize(text):
    """jieba 分词 + 停用词过滤"""
    if not isinstance(text, str) or not text.strip():
        return ""
    words = jieba.cut(text)
    return " ".join(w for w in words if w not in _STOPWORDS and len(w) > 1)


# ── 构建高价值专利向量空间 ────────────────────────────────────────
def build_hv_vectorizer(hv_data):
    """
    对高价值专利库进行 TF-IDF 拟合，返回：
      - vectorizer   : 已拟合的 TfidfVectorizer
      - hv_matrix    : 高价值专利文本矩阵
      - hv_data_tok  : 含分词文本列的 hv_data 副本
    """
    df = hv_data.copy()
    df["text_tok"] = df["text"].apply(_tokenize)

    vectorizer = TfidfVectorizer(
        max_features=8000,
        ngram_range=(1, 2),
        min_df=1,
        sublinear_tf=True,
    )
    hv_matrix = vectorizer.fit_transform(df["text_tok"])
    return vectorizer, hv_matrix, df


def build_industry_subspaces(hv_data_tok, hv_matrix):
    """
    按技术领域将高价值专利分组，计算各行业的平均 TF-IDF 向量（质心）
    返回字典 {industry: centroid_vector (sparse)}
    """
    subspaces = {}
    for domain in hv_data_tok["技术领域"].unique():
        mask = (hv_data_tok["技术领域"] == domain).values
        if mask.sum() == 0:
            continue
        industry = TECH_DOMAIN_TO_INDUSTRY.get(domain, "其他")
        centroid = np.asarray(hv_matrix[mask].mean(axis=0))  # (1, n_features)
        # 同一行业可能有多个技术领域，取平均
        if industry in subspaces:
            subspaces[industry] = (subspaces[industry] + centroid) / 2
        else:
            subspaces[industry] = centroid
    return subspaces


# ── 公司级语义相似度评分 ─────────────────────────────────────────
def score_companies_nlp(comp_data, hv_data, corpus_dict):
    """
    参数
    ----
    comp_data   : comprehensive 数据字典
    hv_data     : 高价值专利 DataFrame
    corpus_dict : {Wind代码: 专利名称合并文本}

    返回
    ----
    DataFrame，含每家公司的各NLP维度得分
    """
    print("[NLP] 构建高价值专利向量空间…")
    vectorizer, hv_matrix, hv_data_tok = build_hv_vectorizer(hv_data)
    industry_subspaces = build_industry_subspaces(hv_data_tok, hv_matrix)

    companies = comp_data["company_list"][
        ["Wind代码", "证券简称", "技术领域", "行业", "行业权重"]
    ].copy()

    rows = []
    for _, row in companies.iterrows():
        code     = row["Wind代码"]
        industry = row["行业"]
        ind_wt   = row["行业权重"]
        corpus   = corpus_dict.get(code, "")

        tok = _tokenize(corpus)
        if not tok.strip():
            rows.append(_empty_row(row))
            continue

        # 公司专利文本向量
        comp_vec = vectorizer.transform([tok])    # (1, n_features)

        # ── a. 与对应行业高价值专利库相似度
        if industry in industry_subspaces:
            sim_industry = float(
                cosine_similarity(comp_vec, industry_subspaces[industry])[0, 0]
            )
        else:
            # 与全库整体相似度
            sim_industry = float(cosine_similarity(comp_vec, hv_matrix).mean())

        # ── b. 与全高价值专利库的最大相似度（Top-5 均值）
        all_sims = cosine_similarity(comp_vec, hv_matrix)[0]
        top5_mean = float(np.sort(all_sims)[-5:].mean()) if len(all_sims) >= 5 else float(all_sims.mean())

        # ── c. 文本困惑度替代指标：词汇丰富度（TTR）
        tokens = tok.split()
        ttr = len(set(tokens)) / len(tokens) if tokens else 0

        # ── d. 创新关键词密度
        keyword_scores = _calc_keyword_density(corpus)
        total_kw_score = sum(keyword_scores.values())

        rows.append({
            "Wind代码":           code,
            "证券简称":           row["证券简称"],
            "技术领域":           row["技术领域"],
            "行业":               industry,
            "行业权重":           ind_wt,
            "行业内语义相似度":   round(sim_industry, 4),
            "全库Top5相似度均值": round(top5_mean, 4),
            "词汇丰富度(TTR)":    round(ttr, 4),
            "前沿关键词总分":     round(total_kw_score, 2),
            **{f"关键词_{k}": round(v, 2) for k, v in keyword_scores.items()},
        })

    df = pd.DataFrame(rows)

    # ── 归一化各维度 → 0-100 分
    df["语义相似度得分(0-100)"] = (_minmax(df["行业内语义相似度"]) * 100).round(2)
    df["词汇丰富度得分(0-100)"] = (_minmax(df["词汇丰富度(TTR)"])   * 100).round(2)
    df["关键词密度得分(0-100)"] = (_minmax(df["前沿关键词总分"])     * 100).round(2)

    # ── NLP综合得分（行业权重已融入）
    df["NLP综合得分(原始)"] = (
        df["语义相似度得分(0-100)"] * 0.60
        + df["词汇丰富度得分(0-100)"] * 0.20
        + df["关键词密度得分(0-100)"] * 0.20
    )
    df["NLP综合得分×行业权重"] = (df["NLP综合得分(原始)"] * df["行业权重"]).round(2)

    # 最终归一化到 0-100
    df["NLP综合得分(0-100)"] = (_minmax(df["NLP综合得分(原始)"]) * 100).round(2)

    print(f"[NLP] 完成 {len(df)} 家公司评分")
    return df


# ── 创新关键词密度计算 ────────────────────────────────────────────
def _calc_keyword_density(text):
    """返回各关键词类别得分字典（出现次数归一化到文本长度）"""
    if not isinstance(text, str) or not text.strip():
        return {cat: 0.0 for cat in FRONTIER_KEYWORDS}
    text_len = max(len(text), 1)
    scores = {}
    for category, kws in FRONTIER_KEYWORDS.items():
        count = sum(text.count(kw) for kw in kws)
        # 每百字关键词数（密度），再乘10放大为可比分值
        scores[category] = round(count / text_len * 100, 4)
    return scores


def _empty_row(row):
    base = {
        "Wind代码":           row["Wind代码"],
        "证券简称":           row["证券简称"],
        "技术领域":           row["技术领域"],
        "行业":               row["行业"],
        "行业权重":           row["行业权重"],
        "行业内语义相似度":   0.0,
        "全库Top5相似度均值": 0.0,
        "词汇丰富度(TTR)":    0.0,
        "前沿关键词总分":     0.0,
        "语义相似度得分(0-100)": 50.0,
        "词汇丰富度得分(0-100)": 50.0,
        "关键词密度得分(0-100)": 50.0,
        "NLP综合得分(原始)":  50.0,
        "NLP综合得分×行业权重": 50.0,
        "NLP综合得分(0-100)": 50.0,
    }
    for cat in FRONTIER_KEYWORDS:
        base[f"关键词_{cat}"] = 0.0
    return base


def _minmax(series):
    mn, mx = series.min(), series.max()
    if mx == mn:
        return pd.Series([0.5] * len(series), index=series.index)
    return (series - mn) / (mx - mn)
