#!/usr/bin/env python3
# ============================================================
# main.py  —  专利价值量化模型主入口（v2）
# ============================================================
import os, sys, time
sys.path.insert(0, os.path.dirname(__file__))

from data_loader      import load_all_data, build_company_patent_corpus
from ipc_analysis     import run_ipc_analysis
from nlp_analysis     import score_companies_nlp
from scoring_engine   import build_final_scores
from report_generator import generate_report


def main():
    t0 = time.time()
    print("=" * 62)
    print("  专利价值量化模型 v2  Patent Value Quantification Model")
    print("=" * 62)

    # ── 1. 数据加载 ─────────────────────────────────────────────
    print("\n[1/4] 加载数据...")
    all_data   = load_all_data()
    comp       = all_data["comprehensive"]
    hv         = all_data["high_value"]
    ipc        = all_data["ipc"]
    pat_detail = all_data["patent_detail"]

    print(f"  ✓ 公司基础数据：{len(comp['company_list'])} 家")
    print(f"  ✓ 高价值专利库：{len(hv)} 条")
    print(f"  ✓ 全市场IPC数据：{len(ipc['detail'])} 条（{ipc['detail']['Wind代码'].nunique()} 家）")
    print(f"  ✓ 新版逐条专利：{len(pat_detail)} 条 | "
          f"有效 {pat_detail['is_active'].sum()} 条")

    # ── 2. IPC热度分析（使用新版逐条数据）──────────────────────
    print("\n[2/4] IPC技术集群与热度分析...")
    ipc_heat_df, company_ipc_df, domain_cluster_df = run_ipc_analysis(
        ipc, hv, comp, patent_detail=pat_detail
    )
    print(f"  ✓ 识别IPC大类：{len(ipc_heat_df)} 个")
    print(f"  ✓ 技术领域集群：{len(domain_cluster_df)} 个")
    top = ipc_heat_df.iloc[0]
    print(f"  ✓ 最热赛道：{top['IPC_class']} ({top['技术领域']}) 热度={top['IPC热度指数']:.1f}")

    # ── 3. NLP语义分析 ──────────────────────────────────────────
    print("\n[3/4] NLP专利文本语义特征提取...")
    corpus_dict   = build_company_patent_corpus(comp)
    nlp_scores_df = score_companies_nlp(comp, hv, corpus_dict)
    print(f"  ✓ 平均语义相似度得分：{nlp_scores_df['语义相似度得分(0-100)'].mean():.1f}")
    print(f"  ✓ 平均NLP综合得分：{nlp_scores_df['NLP综合得分(0-100)'].mean():.1f}")

    # ── 4. 综合评分（6维度 + 行业权重）─────────────────────────
    print("\n[4/4] 生成综合评分（6维度 × 行业权重）...")
    final_df = build_final_scores(comp, company_ipc_df, nlp_scores_df)

    print(f"\n  {'排名':<5} {'公司':<10} {'综合评分':>8} {'等级':<6} {'行业':<12} {'CAGR':>8}")
    print(f"  {'-'*60}")
    for _, row in final_df.head(15).iterrows():
        cagr = company_ipc_df[company_ipc_df["Wind代码"]==row["Wind代码"]]["近三年CAGR"].values
        cagr_str = f"{cagr[0]:.1%}" if len(cagr) > 0 else "N/A"
        print(f"  {row['综合排名']:<5} {row['证券简称']:<10} "
              f"{row['专利价值综合评分(0-100)']:>8.1f} "
              f"{row['信用增强等级']:<6} {row['行业']:<12} {cagr_str:>8}")

    # ── 5. 生成报告 ─────────────────────────────────────────────
    print("\n[输出] 生成Excel报告...")
    out_path = generate_report(
        final_df, ipc_heat_df, company_ipc_df,
        domain_cluster_df, nlp_scores_df, comp
    )

    elapsed = time.time() - t0
    print(f"\n{'='*62}")
    print(f"  ✅ 完成！耗时 {elapsed:.1f}s")
    print(f"  📄 {out_path}")
    print(f"{'='*62}")


if __name__ == "__main__":
    main()
