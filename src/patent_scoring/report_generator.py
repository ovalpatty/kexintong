# ============================================================
# report_generator.py  —  Excel报告生成模块
# ============================================================
import os
import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import (
    Font, PatternFill, Alignment, Border, Side, numbers
)
from openpyxl.utils import get_column_letter
from openpyxl.chart import BarChart, Reference
from openpyxl.chart.series import SeriesLabel

from config import OUTPUT_PATH, SCORE_WEIGHTS, INDUSTRY_WEIGHTS, CREDIT_GRADE_THRESHOLDS


# ── 颜色常量 ─────────────────────────────────────────────────────
C_HEADER_DARK   = "1F3864"   # 深蓝色表头
C_HEADER_MID    = "2E75B6"   # 中蓝色二级表头
C_HEADER_LIGHT  = "BDD7EE"   # 浅蓝色
C_ACCENT        = "F4B942"   # 金色强调
C_WHITE         = "FFFFFF"
C_GRAY_LIGHT    = "F2F2F2"
C_GRAY_ROW      = "DEEAF1"

# 信用等级颜色
GRADE_COLORS = {
    "AAA": "00B050",  # 绿
    "AA":  "70AD47",
    "A":   "A9D18E",
    "BBB": "FFD966",  # 黄
    "BB":  "F4B942",
    "B":   "FF7043",  # 橙
    "CCC": "C00000",  # 红
}


def generate_report(final_df, ipc_heat_df, company_ipc_df,
                    domain_cluster_df, nlp_scores_df, comp_data):
    """生成完整Excel评分报告"""
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)

    wb = Workbook()
    wb.remove(wb.active)   # 删除默认空表

    _sheet_cover(wb, final_df)
    _sheet_final_score(wb, final_df)
    _sheet_patent_trend(wb, comp_data)
    _sheet_ipc_heat(wb, ipc_heat_df, domain_cluster_df)
    _sheet_company_ipc(wb, company_ipc_df)
    _sheet_nlp(wb, nlp_scores_df)
    _sheet_dimension_detail(wb, final_df)
    _sheet_methodology(wb)

    wb.save(OUTPUT_PATH)
    print(f"[报告] 已保存至：{OUTPUT_PATH}")
    return OUTPUT_PATH


# ════════════════════════════════════════════════════════════════
# Sheet 1  封面与摘要统计
# ════════════════════════════════════════════════════════════════
def _sheet_cover(wb, final_df):
    ws = wb.create_sheet("封面与摘要")
    ws.sheet_view.showGridLines = False

    _set_col_widths(ws, [3, 25, 20, 20, 20, 20, 20, 3])

    # 标题
    ws.merge_cells("B2:G2")
    c = ws["B2"]
    c.value = "专利价值量化评分报告"
    c.font  = Font(name="Arial", size=22, bold=True, color=C_WHITE)
    c.fill  = PatternFill("solid", fgColor=C_HEADER_DARK)
    c.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[2].height = 45

    ws.merge_cells("B3:G3")
    c = ws["B3"]
    c.value = "Patent Value Quantification Scoring Report"
    c.font  = Font(name="Arial", size=12, italic=True, color=C_WHITE)
    c.fill  = PatternFill("solid", fgColor=C_HEADER_MID)
    c.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[3].height = 22

    # 摘要统计
    stats = [
        ("覆盖公司数",         f"{len(final_df)} 家"),
        ("AAA级公司数",        f"{(final_df['信用增强等级']=='AAA').sum()} 家"),
        ("AA级公司数",         f"{(final_df['信用增强等级']=='AA').sum()} 家"),
        ("A级及以上公司数",    f"{(final_df['信用增强等级'].isin(['AAA','AA','A'])).sum()} 家"),
        ("平均专利价值综合评分", f"{final_df['专利价值综合评分(0-100)'].mean():.1f} 分"),
        ("最高得分公司",        final_df.iloc[0]["证券简称"] if len(final_df) > 0 else "-"),
        ("最高得分",           f"{final_df['专利价值综合评分(0-100)'].max():.1f} 分"),
    ]

    ws.merge_cells("B5:G5")
    hdr = ws["B5"]
    hdr.value = "摘要统计"
    hdr.font  = Font(name="Arial", size=12, bold=True, color=C_WHITE)
    hdr.fill  = PatternFill("solid", fgColor=C_HEADER_MID)
    hdr.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    ws.row_dimensions[5].height = 20

    for i, (label, val) in enumerate(stats, start=6):
        ws[f"B{i}"].value = label
        ws[f"B{i}"].font  = Font(name="Arial", size=11, bold=True)
        ws[f"B{i}"].fill  = PatternFill("solid", fgColor=C_GRAY_LIGHT)
        ws[f"C{i}"].value = val
        ws[f"C{i}"].font  = Font(name="Arial", size=11)
        ws.row_dimensions[i].height = 18

    # 权重说明
    start_r = 6 + len(stats) + 2
    ws.merge_cells(f"B{start_r}:G{start_r}")
    ws[f"B{start_r}"].value = "评分维度权重说明"
    ws[f"B{start_r}"].font  = Font(name="Arial", size=12, bold=True, color=C_WHITE)
    ws[f"B{start_r}"].fill  = PatternFill("solid", fgColor=C_HEADER_MID)
    ws[f"B{start_r}"].alignment = Alignment(horizontal="left", indent=1)
    ws.row_dimensions[start_r].height = 20

    weight_rows = [
        ("专利存量得分",     SCORE_WEIGHTS["patent_stock"],    "新版有效专利计数（法律状态过滤）"),
        ("专利类型质量",     SCORE_WEIGHTS["patent_type"],     "授权发明×3 / 实用新型×2 / 外观设计×1"),
        ("IPC热度得分",      SCORE_WEIGHTS["ipc_heat"],        "新版逐条IPC → 加权热度，HHI竞争度"),
        ("近三年CAGR成长性", SCORE_WEIGHTS["patent_cagr"],     "2022-2025年有效专利授权年均复合增长率（新增）"),
        ("NLP语义相似度",    SCORE_WEIGHTS["nlp_similarity"],  "与高价值专利库的TF-IDF余弦相似度"),
        ("关键词密度得分",   SCORE_WEIGHTS["keyword_density"], "六大前沿技术关键词密度"),
    ]

    _write_header_row(ws, start_r + 1,
                      ["评分维度", "权重", "说明"],
                      cols="BCD", bg=C_HEADER_LIGHT, fc=C_HEADER_DARK)

    for j, (dim, wt, desc) in enumerate(weight_rows, start=start_r + 2):
        ws[f"B{j}"].value = dim
        ws[f"C{j}"].value = f"{wt:.0%}"
        ws[f"D{j}"].value = desc
        ws[f"C{j}"].alignment = Alignment(horizontal="center")
        _zebra(ws, j, "BCDE", j % 2 == 0)
        ws.row_dimensions[j].height = 17

    # 行业权重说明
    iw_start = start_r + 2 + len(weight_rows) + 2
    ws.merge_cells(f"B{iw_start}:G{iw_start}")
    ws[f"B{iw_start}"].value = "行业权重系数说明（在基础评分上乘以以下系数）"
    ws[f"B{iw_start}"].font  = Font(name="Arial", size=12, bold=True, color=C_WHITE)
    ws[f"B{iw_start}"].fill  = PatternFill("solid", fgColor=C_HEADER_MID)
    ws[f"B{iw_start}"].alignment = Alignment(horizontal="left", indent=1)
    ws.row_dimensions[iw_start].height = 20

    _write_header_row(ws, iw_start + 1, ["行业", "权重系数", "代表性赛道"],
                      cols="BCD", bg=C_HEADER_LIGHT, fc=C_HEADER_DARK)

    iw_highlight = {"人工智能", "半导体", "电子信息", "通信技术"}
    for k, (ind, wt) in enumerate(
        sorted(INDUSTRY_WEIGHTS.items(), key=lambda x: -x[1]), start=iw_start + 2
    ):
        ws[f"B{k}"].value = ind
        ws[f"C{k}"].value = wt
        ws[f"C{k}"].number_format = "0.00"
        ws[f"C{k}"].alignment = Alignment(horizontal="center")
        if ind in iw_highlight:
            ws[f"B{k}"].font = Font(name="Arial", bold=True, color="C00000")
            ws[f"C{k}"].font = Font(name="Arial", bold=True, color="C00000")
        _zebra(ws, k, "BC", k % 2 == 0)
        ws.row_dimensions[k].height = 17


# ════════════════════════════════════════════════════════════════
# Sheet 2  综合评分排名
# ════════════════════════════════════════════════════════════════
def _sheet_final_score(wb, final_df):
    ws = wb.create_sheet("综合评分排名")
    ws.sheet_view.showGridLines = False

    cols = [
        "综合排名", "Wind代码", "证券简称", "技术领域", "行业",
        "专利总数", "专利价值综合评分(0-100)", "信用增强等级",
        "专利存量得分(0-100)", "专利类型质量得分(0-100)",
        "IPC热度得分(0-100)", "专利CAGR得分(0-100)", "NLP综合得分(0-100)", "关键词密度得分(0-100)",
        "行业权重乘数", "专利综合得分_基础", "融资建议",
    ]

    display_cols = [c for c in cols if c in final_df.columns]
    df = final_df[display_cols].copy()

    widths = [8, 14, 10, 12, 10, 10, 16, 12,
              14, 16, 14, 14, 16, 10, 14, 40]
    _set_col_widths(ws, widths[:len(display_cols) + 1])

    headers = [
        "排名", "Wind代码", "公司", "技术领域", "行业",
        "专利总数", "综合评分", "信用等级",
        "存量得分", "类型质量分", "IPC热度分", "NLP语义分", "关键词密度分",
        "行业权重×", "基础得分", "融资建议",
    ]

    _write_header_row(ws, 1, headers[:len(display_cols)],
                      start_col=1, bg=C_HEADER_DARK, fc=C_WHITE, row_height=22)

    for i, (_, row) in enumerate(df.iterrows(), start=2):
        for j, col in enumerate(display_cols, start=1):
            cell = ws.cell(row=i, column=j, value=row[col])
            cell.font = Font(name="Arial", size=10)
            cell.alignment = Alignment(
                horizontal="center" if j not in (16,) else "left",
                vertical="center", wrap_text=(j == len(display_cols))
            )

        # 信用等级着色
        grade = row.get("信用增强等级", "")
        grade_col_idx = display_cols.index("信用增强等级") + 1 if "信用增强等级" in display_cols else None
        if grade_col_idx:
            gc = ws.cell(row=i, column=grade_col_idx)
            gc.fill = PatternFill("solid", fgColor=GRADE_COLORS.get(grade, C_GRAY_LIGHT))
            gc.font = Font(name="Arial", bold=True, color=C_WHITE, size=10)

        _zebra(ws, i, [get_column_letter(c) for c in range(1, len(display_cols) + 1)
                       if get_column_letter(c) != get_column_letter(grade_col_idx or 0)],
               i % 2 == 0)
        ws.row_dimensions[i].height = 20

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(display_cols))}1"


# ════════════════════════════════════════════════════════════════
# Sheet 3  IPC热度分析
# ════════════════════════════════════════════════════════════════
def _sheet_ipc_heat(wb, ipc_heat_df, domain_cluster_df):
    ws = wb.create_sheet("IPC技术热度分析")
    ws.sheet_view.showGridLines = False

    # ── 技术领域集群 ────────────────────────────────────────────
    ws.merge_cells("A1:H1")
    _section_title(ws, "A1", "技术领域集群分析")
    ws.row_dimensions[1].height = 22

    domain_cols = ["技术领域", "IPC大类数", "全市场专利数", "高价值专利数",
                   "高价值率", "平均热度指数", "行业权重", "综合热度×行业权重"]
    _write_header_row(ws, 2, domain_cols, start_col=1,
                      bg=C_HEADER_MID, fc=C_WHITE)

    for i, (_, row) in enumerate(domain_cluster_df.iterrows(), start=3):
        for j, col in enumerate(domain_cols, start=1):
            v = row.get(col, "")
            c = ws.cell(row=i, column=j, value=v)
            c.font = Font(name="Arial", size=10)
            c.alignment = Alignment(horizontal="center")
            if col in ("高价值率",):
                c.number_format = "0.00%"
            elif col in ("平均热度指数", "综合热度×行业权重", "行业权重"):
                c.number_format = "0.00"
        _zebra(ws, i, [get_column_letter(k) for k in range(1, 9)], i % 2 == 0)
        ws.row_dimensions[i].height = 17

    # ── IPC大类热度明细 ─────────────────────────────────────────
    offset = len(domain_cluster_df) + 4

    ws.merge_cells(f"A{offset}:K{offset}")
    _section_title(ws, f"A{offset}", "IPC大类热度指数明细（Top 40）")
    ws.row_dimensions[offset].height = 22

    ipc_cols = ["IPC_class", "技术领域", "全市场专利数", "高价值专利数",
                "高价值专利占比", "HHI", "IPC热度指数", "行业权重", "热度×行业权重"]
    _write_header_row(ws, offset + 1, ipc_cols, start_col=1,
                      bg=C_HEADER_MID, fc=C_WHITE)

    top40 = ipc_heat_df.head(40)
    for i, (_, row) in enumerate(top40.iterrows(), start=offset + 2):
        for j, col in enumerate(ipc_cols, start=1):
            v = row.get(col, "")
            c = ws.cell(row=i, column=j, value=v)
            c.font = Font(name="Arial", size=10)
            c.alignment = Alignment(horizontal="center")
            if col in ("高价值专利占比",):
                c.number_format = "0.0000"
            elif col in ("HHI",):
                c.number_format = "0.0000"
            elif col in ("IPC热度指数", "热度×行业权重", "行业权重"):
                c.number_format = "0.00"
        _zebra(ws, i, [get_column_letter(k) for k in range(1, 10)], i % 2 == 0)
        ws.row_dimensions[i].height = 17

    _set_col_widths(ws, [14, 14, 14, 14, 14, 10, 14, 10, 16, 3])


# ════════════════════════════════════════════════════════════════
# Sheet 4  公司IPC分布
# ════════════════════════════════════════════════════════════════
def _sheet_company_ipc(wb, company_ipc_df):
    ws = wb.create_sheet("公司IPC分布与热度")
    ws.sheet_view.showGridLines = False

    cols = ["Wind代码", "证券简称", "技术领域", "行业权重",
            "有效IPC记录数", "覆盖IPC大类数", "核心IPC大类",
            "核心IPC技术域", "集中度CR3", "加权IPC热度均值", "IPC热度得分(0-100)"]
    headers = ["Wind代码", "公司", "技术领域", "行业权重",
               "IPC记录数", "覆盖大类数", "核心IPC大类",
               "核心技术域", "集中度CR3", "加权热度均值", "IPC热度得分"]

    _write_header_row(ws, 1, headers, start_col=1, bg=C_HEADER_DARK, fc=C_WHITE, row_height=22)
    _set_col_widths(ws, [12, 10, 12, 10, 10, 10, 14, 14, 12, 14, 14])

    df = company_ipc_df[[c for c in cols if c in company_ipc_df.columns]]
    df = df.sort_values("IPC热度得分(0-100)", ascending=False).reset_index(drop=True)

    for i, (_, row) in enumerate(df.iterrows(), start=2):
        for j, col in enumerate([c for c in cols if c in company_ipc_df.columns], start=1):
            v = row.get(col, "")
            c = ws.cell(row=i, column=j, value=v)
            c.font = Font(name="Arial", size=10)
            c.alignment = Alignment(horizontal="center")
            if col == "集中度CR3":
                c.number_format = "0.00%"
            elif col in ("行业权重", "加权IPC热度均值", "IPC热度得分(0-100)"):
                c.number_format = "0.00"
        _zebra(ws, i, [get_column_letter(k) for k in range(1, 12)], i % 2 == 0)
        ws.row_dimensions[i].height = 17

    ws.freeze_panes = "A2"


# ════════════════════════════════════════════════════════════════
# Sheet 5  NLP语义分析
# ════════════════════════════════════════════════════════════════
def _sheet_nlp(wb, nlp_df):
    ws = wb.create_sheet("NLP语义特征分析")
    ws.sheet_view.showGridLines = False

    base_cols = [
        "Wind代码", "证券简称", "技术领域", "行业", "行业权重",
        "行业内语义相似度", "全库Top5相似度均值", "词汇丰富度(TTR)",
        "前沿关键词总分", "语义相似度得分(0-100)",
        "词汇丰富度得分(0-100)", "关键词密度得分(0-100)",
        "NLP综合得分(0-100)", "NLP综合得分×行业权重",
    ]
    kw_cols = [c for c in nlp_df.columns if c.startswith("关键词_")]
    all_cols = base_cols + kw_cols

    headers = [
        "Wind代码", "公司", "技术领域", "行业", "行业权重",
        "行业内相似度", "全库Top5相似度", "TTR词汇丰富度",
        "关键词总分", "语义相似度(0-100)",
        "词汇丰富度(0-100)", "关键词密度(0-100)",
        "NLP综合(0-100)", "NLP×行业权重",
    ] + [c.replace("关键词_", "") for c in kw_cols]

    _write_header_row(ws, 1, headers, start_col=1,
                      bg=C_HEADER_DARK, fc=C_WHITE, row_height=22)

    display = [c for c in all_cols if c in nlp_df.columns]
    df = nlp_df[display].sort_values("NLP综合得分(0-100)", ascending=False).reset_index(drop=True)

    for i, (_, row) in enumerate(df.iterrows(), start=2):
        for j, col in enumerate(display, start=1):
            v = row.get(col, "")
            c = ws.cell(row=i, column=j, value=v)
            c.font = Font(name="Arial", size=10)
            c.alignment = Alignment(horizontal="center")
            if col in ("行业内语义相似度", "全库Top5相似度均值", "词汇丰富度(TTR)"):
                c.number_format = "0.0000"
        _zebra(ws, i, [get_column_letter(k) for k in range(1, len(display) + 1)], i % 2 == 0)
        ws.row_dimensions[i].height = 17

    widths = [12, 10, 12, 10, 10, 14, 14, 14, 12, 14, 14, 14, 14, 14] + [12] * len(kw_cols)
    _set_col_widths(ws, widths)
    ws.freeze_panes = "A2"


# ════════════════════════════════════════════════════════════════
# Sheet 6  各维度明细
# ════════════════════════════════════════════════════════════════
def _sheet_dimension_detail(wb, final_df):
    ws = wb.create_sheet("各维度得分明细")
    ws.sheet_view.showGridLines = False

    cols = [
        "综合排名", "Wind代码", "证券简称", "技术领域", "行业",
        "专利总数", "加权专利数", "发明专利占比",
        "专利存量得分(0-100)", "专利类型质量得分(0-100)",
        "IPC热度得分(0-100)", "NLP综合得分(0-100)", "关键词密度得分(0-100)",
        "专利综合得分_基础", "行业权重乘数",
        "专利综合得分_含行业权重", "专利价值综合评分(0-100)", "信用增强等级",
    ]
    display = [c for c in cols if c in final_df.columns]
    df = final_df[display].copy()

    _write_header_row(ws, 1, display, start_col=1,
                      bg=C_HEADER_DARK, fc=C_WHITE, row_height=22)

    for i, (_, row) in enumerate(df.iterrows(), start=2):
        for j, col in enumerate(display, start=1):
            v = row.get(col, "")
            c = ws.cell(row=i, column=j, value=v)
            c.font = Font(name="Arial", size=10)
            c.alignment = Alignment(horizontal="center")
            if col == "发明专利占比":
                c.number_format = "0.00%"
            elif "得分" in col or "评分" in col or col == "行业权重乘数":
                c.number_format = "0.00"
        _zebra(ws, i, [get_column_letter(k) for k in range(1, len(display) + 1)], i % 2 == 0)
        ws.row_dimensions[i].height = 17

    ws.freeze_panes = "C2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(display))}1"
    _set_col_widths(ws, [8, 14, 10, 12, 12, 10, 10, 12, 14, 16, 14, 14, 14, 16, 14, 10, 18, 16, 10])


# ════════════════════════════════════════════════════════════════
# Sheet 3b  近年专利趋势（新增）
# ════════════════════════════════════════════════════════════════
def _sheet_patent_trend(wb, comp_data):
    ws = wb.create_sheet("专利趋势与CAGR分析")
    ws.sheet_view.showGridLines = False

    if "patent_cagr" not in comp_data or comp_data["patent_cagr"].empty:
        ws["A1"].value = "（新版专利数据未加载）"
        return

    cagr_df = comp_data["patent_cagr"].copy()
    # 合并行业信息
    cl = comp_data["company_list"][["Wind代码","证券简称","技术领域","行业","行业权重"]]
    cagr_df = cagr_df.merge(cl, on="Wind代码", how="left")
    cagr_df = cagr_df.sort_values("近三年CAGR", ascending=False).reset_index(drop=True)

    cols = ["Wind代码","证券简称","技术领域","行业",
            "2022专利数","2023专利数","2024专利数","2025专利数",
            "近三年CAGR"]
    headers = ["Wind代码","公司","技术领域","行业",
               "2022","2023","2024","2025","近三年CAGR"]

    _write_header_row(ws, 1, headers, start_col=1, bg=C_HEADER_DARK, fc=C_WHITE, row_height=22)
    _set_col_widths(ws, [12, 10, 12, 12, 10, 10, 10, 10, 14])

    for i, (_, row) in enumerate(cagr_df[[c for c in cols if c in cagr_df.columns]].iterrows(), start=2):
        for j, col in enumerate([c for c in cols if c in cagr_df.columns], start=1):
            v = row.get(col, "")
            c = ws.cell(row=i, column=j, value=v)
            c.font = Font(name="Arial", size=10)
            c.alignment = Alignment(horizontal="center")
            if col == "近三年CAGR":
                c.number_format = "0.00%"
                cagr_val = float(v) if v else 0
                if cagr_val >= 0.2:
                    c.font = Font(name="Arial", size=10, bold=True, color="00B050")
                elif cagr_val < 0:
                    c.font = Font(name="Arial", size=10, color="C00000")
        _zebra(ws, i, [get_column_letter(k) for k in range(1, 10)], i % 2 == 0)
        ws.row_dimensions[i].height = 17

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len([c for c in cols if c in cagr_df.columns]))}1"


# ════════════════════════════════════════════════════════════════
# Sheet 7  方法论说明
# ════════════════════════════════════════════════════════════════
def _sheet_methodology(wb):
    ws = wb.create_sheet("方法论说明")
    ws.sheet_view.showGridLines = False
    _set_col_widths(ws, [3, 30, 60, 3])

    content = [
        ("模型概述",
         "专利价值量化模型旨在将非结构化专利信息转化为结构化信用增强指标，"
         "实现'技术软实力→信用硬通货'的跨越，服务于'投保贷'联动模式中的科技企业信用评估。"),
        ("维度1：专利存量得分",
         "基于各公司有效专利总数，采用行业内归一化（权重60%）+ 全样本归一化（权重40%）方式，"
         "消除不同行业规模差异带来的评分偏差。"),
        ("维度2：专利类型质量",
         "授权发明专利权重3.0，实用新型权重2.0，外观设计权重1.0。综合加权专利数（70%）"
         "与发明专利占比（30%），衡量专利组合技术深度。"),
        ("维度3：IPC热度分析",
         "解析企业专利IPC分类号，计算各大类热度指数（高价值专利占比50%+全市场规模30%+"
         "赛道竞争开放度20%），企业得分为其持有专利的IPC热度加权均值。"),
        ("维度4：NLP语义相似度",
         "使用jieba分词+TF-IDF向量化，计算企业专利文本与高价值专利库（分行业子空间）"
         "的余弦相似度，间接反映专利的技术影响力和商业价值潜力。\n"
         "【升级路径】可替换为BERT/PatentBERT等预训练模型，本模型接口已预留。"),
        ("维度5：关键词密度",
         "设置人工智能、半导体、新能源、纳米材料、通信、生物医药六大前沿技术关键词库，"
         "统计企业专利文本中的关键词密度（每百字出现次数），反映技术前沿度。"),
        ("行业权重乘数",
         "在6维度加权基础得分上，乘以行业权重系数（人工智能1.50×，半导体1.45×，…，"
         "建筑工程0.90×）。权重体现国家战略新兴产业导向，AI、半导体等高科技赛道获得更高评分。"),
        ("信用等级映射",
         "最终综合评分（0-100分）映射至信用等级：\n"
         "AAA(90+) AA(80-90) A(70-80) BBB(60-70) BB(50-60) B(40-50) CCC(<40)"),
        ("投保贷应用场景",
         "（1）银行：AAA/AA级企业可适度放宽抵押要求，给予利率优惠；"
         "BBB及以下需强化风险管控。\n"
         "（2）保险：科技保险风险定价参考专利质量分，高分企业保费可适当优惠。\n"
         "（3）投资：专利质量分可作为PE/VC投资尽调的量化补充指标。"),
        ("数据来源",
         "① 当前公司样本综合数据（财务+专利）\n"
         "② A股上市公司高价值专利清单（2023-2025，含IPC分类号）\n"
         "③ A股上市公司专利IPC分类数据"),
    ]

    ws.merge_cells("B1:C1")
    c = ws["B1"]
    c.value = "专利价值量化模型 — 方法论说明"
    c.font  = Font(name="Arial", size=16, bold=True, color=C_WHITE)
    c.fill  = PatternFill("solid", fgColor=C_HEADER_DARK)
    c.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 35

    for i, (title, body) in enumerate(content, start=3):
        ws[f"B{i}"].value = title
        ws[f"B{i}"].font  = Font(name="Arial", size=11, bold=True, color=C_WHITE)
        ws[f"B{i}"].fill  = PatternFill("solid", fgColor=C_HEADER_MID)
        ws[f"B{i}"].alignment = Alignment(vertical="top", indent=1)

        ws[f"C{i}"].value = body
        ws[f"C{i}"].font  = Font(name="Arial", size=10)
        ws[f"C{i}"].alignment = Alignment(wrap_text=True, vertical="top")
        ws[f"C{i}"].fill  = PatternFill("solid", fgColor=C_GRAY_LIGHT if i % 2 == 1 else C_WHITE)

        lines = body.count("\n") + 1
        ws.row_dimensions[i].height = max(30, 18 * lines)

    _set_col_widths(ws, [3, 22, 80, 3])


# ════════════════════════════════════════════════════════════════
# 工具函数
# ════════════════════════════════════════════════════════════════
def _write_header_row(ws, row, headers, start_col=1, cols=None,
                       bg=C_HEADER_DARK, fc=C_WHITE, row_height=20):
    for j, h in enumerate(headers, start=start_col):
        c = ws.cell(row=row, column=j, value=h)
        c.font      = Font(name="Arial", bold=True, color=fc, size=10)
        c.fill      = PatternFill("solid", fgColor=bg)
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[row].height = row_height


def _section_title(ws, cell_ref, title):
    c = ws[cell_ref]
    c.value = title
    c.font  = Font(name="Arial", size=12, bold=True, color=C_WHITE)
    c.fill  = PatternFill("solid", fgColor=C_HEADER_DARK)
    c.alignment = Alignment(horizontal="left", vertical="center", indent=1)


def _zebra(ws, row, col_letters, shade):
    if not shade:
        return
    for cl in col_letters:
        c = ws[f"{cl}{row}"] if isinstance(cl, str) else ws.cell(row=row, column=cl)
        if c.fill.fgColor.rgb in ("00000000", "FFFFFFFF", "00FFFFFF"):
            c.fill = PatternFill("solid", fgColor=C_GRAY_LIGHT)


def _set_col_widths(ws, widths):
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
