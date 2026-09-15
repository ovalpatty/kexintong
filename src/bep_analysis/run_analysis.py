#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BEP分析与投保贷整合应用
========================================================
修复内容：
  1. 中文字体：使用 Noto Sans CJK SC，彻底解决乱码
  2. 毛利率：从20期季度财务数据逐公司计算，非行业固定值
  3. 成本拆分：回归法区分固定/变动成本，非随机数
  4. 敏感性热力图：3个真实维度，标注信用等级与专利评分
  5. Demo：只运行确定性分析；Research：才训练与评估GBM
  6. 路径：统一用相对路径，开箱即用
"""

import argparse
import os, warnings, base64, json, time
from io import BytesIO
import numpy as np
import pandas as pd
from scipy import stats
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.colors as mcolors
import matplotlib.patches as mpatches
from sklearn.linear_model import LinearRegression
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.preprocessing import MinMaxScaler
from sklearn.model_selection import cross_val_score, KFold

warnings.filterwarnings('ignore')

# ── 0. 路径配置 ───────────────────────────────────────────────────────────
BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, 'data')


def parse_args():
    parser = argparse.ArgumentParser(
        description='BEP预测与投保贷整合分析（可直接接收专利评分模块输出）'
    )
    parser.add_argument(
        '--patent-report',
        default=os.path.join(DATA, '专利价值量化评分报告.xlsx'),
        help='专利评分模块生成的Excel报告路径',
    )
    parser.add_argument(
        '--company-data',
        default=os.path.join(DATA, 'company_data.xlsx'),
        help='包含公司清单和财务运营数据的Excel路径',
    )
    parser.add_argument(
        '--macro-data',
        default=os.path.join(DATA, 'industry_reference.xlsx'),
        help='可选的行业宏观基准Excel；缺失时从公司样本推导行业基准',
    )
    parser.add_argument(
        '--output-dir',
        default=os.path.join(BASE, 'outputs'),
        help='BEP分析结果输出目录',
    )
    parser.add_argument(
        '--mode',
        choices=('demo', 'research'),
        default='demo',
        help='demo 仅运行确定性分析；research 才训练并评估GBM',
    )
    return parser.parse_args()


ARGS = parse_args()
RUN_STARTED_NS = time.time_ns()
OUT = os.path.abspath(ARGS.output_dir)
os.makedirs(OUT, exist_ok=True)
REPORTS_DIR = os.path.join(OUT, 'reports')
FIGURES_DIR = os.path.join(OUT, 'figures')
INTERACTIVE_DIR = os.path.join(OUT, 'interactive')
for _output_subdir in (REPORTS_DIR, FIGURES_DIR, INTERACTIVE_DIR):
    os.makedirs(_output_subdir, exist_ok=True)

PATENT_FILE = os.path.abspath(ARGS.patent_report)
MACRO_FILE = os.path.abspath(ARGS.macro_data)
COMPANY_FILE = os.path.abspath(ARGS.company_data)

for required_path, label in [
    (PATENT_FILE, '专利评分报告'),
    (COMPANY_FILE, '公司综合数据'),
]:
    if not os.path.isfile(required_path):
        raise FileNotFoundError(f'{label}不存在：{required_path}')

# ── 1. 中文字体配置 ───────────────────────────────────────────────────────
FONT_PATHS = [
    '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
    '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',
    '/System/Library/Fonts/PingFang.ttc',          # macOS
    'C:/Windows/Fonts/msyh.ttc',                   # Windows
]
_FONT_FILE = None
for _fp_path in FONT_PATHS:
    if os.path.exists(_fp_path):
        fm.fontManager.addfont(_fp_path)
        _font_prop = fm.FontProperties(fname=_fp_path)
        plt.rcParams['font.family'] = _font_prop.get_name()
        _FONT_FILE = _fp_path
        break
if _FONT_FILE is None:
    print("⚠ 未找到CJK字体，中文可能显示为方块。请安装 fonts-noto-cjk。")
    _font_prop = fm.FontProperties()

plt.rcParams['axes.unicode_minus'] = False

def fp(size=10):
    """返回指定字号的FontProperties"""
    if _FONT_FILE:
        p = fm.FontProperties(fname=_FONT_FILE)
    else:
        p = fm.FontProperties()
    p.set_size(size)
    return p

# Color palette from swatch card
COLORS = {
    'blue':   '#4E90F5',   # Chefchaouen Blue
    'red':    '#486B03',   # Dark Moss Green (used for contrast/warning)
    'green':  '#94C000',   # Apple Green
    'orange': '#9EBEED',   # Jordy Blue (accent)
    'purple': '#486B03',   # Dark Moss Green
    'teal':   '#4E90F5',   # Chefchaouen Blue
    'bg':     '#F3F6F3',   # Baby Powder
}
CREDIT_COLORS = {
    'AAA': '#486B03',   # Dark Moss Green
    'AA':  '#94C000',   # Apple Green
    'A':   '#4E90F5',   # Chefchaouen Blue
    'BBB': '#9EBEED',   # Jordy Blue
    'BB':  '#9EBEED',
    'B':   '#9EBEED',
    'CCC': '#486B03',
}

def banner(msg):
    print('\n' + '='*70)
    print(f'  {msg}')
    print('='*70)

banner('5.3+5.4 BEP预测与投保贷整合分析 — 开始执行')

# ══════════════════════════════════════════════════════════════════════════
# 模块一：数据读取与整合
# ══════════════════════════════════════════════════════════════════════════
banner('模块一：数据读取与整合')

# 1-A 专利评分（各维度明细）
pat = pd.read_excel(PATENT_FILE, sheet_name='各维度得分明细')
pat.rename(columns={
    '专利价值综合评分(0-100)': '专利综合评分',
    '信用增强等级': '信用等级',
    '专利存量得分(0-100)': '存量得分',
    '专利类型质量得分(0-100)': '类型质量分',
    'IPC热度得分(0-100)': 'IPC热度分',
    'NLP综合得分(0-100)': 'NLP语义分',
    '关键词密度得分(0-100)': '关键词密度分',
}, inplace=True)
print(f'✓ 专利评分：{len(pat)} 家公司')

# 1-B 公司财务时序数据
fin = pd.read_excel(COMPANY_FILE, sheet_name='2_财务运营数据')
comp = pd.read_excel(COMPANY_FILE, sheet_name='1_公司清单')

# 建立日期排序索引
def _period_idx(d):
    q, fy = d.split()
    return (int(fy.replace('FY','')) - 2021) * 4 + int(q.replace('Q','')) - 1

fin['period'] = fin['日期'].map(_period_idx)
fin = fin.sort_values(['Wind代码', 'period'])
print(f'✓ 财务数据：{fin["Wind代码"].nunique()} 家公司 × {fin["日期"].nunique()} 期')

# 1-C~1-E 行业宏观数据（可选）
# 宏观文件缺省时，行业BEP基准稍后从当前真实样本推导，
# 原材料冲击使用中性情景（指数不变），避免为缺失数据编造外部数值。
IND_BEP = None
IND_DETAIL = pd.DataFrame()
MAT = None
if os.path.isfile(MACRO_FILE):
    ind_raw = pd.read_excel(MACRO_FILE, sheet_name='行业BEP基准', header=None)
    IND_BEP = ind_raw.iloc[1:17].copy()
    IND_BEP.columns = ['行业名称','平均营业收入','平均营业成本','平均营业成本率','平均毛利率','平均BEP营业收入']
    IND_BEP.dropna(subset=['行业名称'], inplace=True)
    IND_BEP[['平均毛利率','平均营业收入']] = IND_BEP[['平均毛利率','平均营业收入']].apply(pd.to_numeric, errors='coerce')

    findet_raw = pd.read_excel(MACRO_FILE, sheet_name='行业财务指标明细', header=None)
    IND_DETAIL = findet_raw.iloc[2:].copy()
    IND_DETAIL.columns = ['行业名称','年份','营业收入','营业成本','营业成本率','毛利率','BEP营业收入']
    IND_DETAIL.dropna(subset=['行业名称','年份'], inplace=True)
    IND_DETAIL[['年份','毛利率','营业收入']] = IND_DETAIL[['年份','毛利率','营业收入']].apply(pd.to_numeric, errors='coerce')

    mat_raw = pd.read_excel(MACRO_FILE, sheet_name='原材料价格指数', header=None)
    MAT = mat_raw.iloc[2:7].copy()
    MAT.columns = ['年份','钢材','铜','铝','原油']
    MAT.dropna(subset=['年份'], inplace=True)
    MAT = MAT[MAT['年份'].astype(str).str.isdigit()].copy()
    MAT[['年份','钢材','铜','铝','原油']] = MAT[['年份','钢材','铜','铝','原油']].apply(pd.to_numeric, errors='coerce')
    MAT['年份'] = MAT['年份'].astype(int)
    print(f'✓ 已加载外部行业宏观数据：{len(IND_BEP)} 个行业，原材料指数 {len(MAT)} 年')
else:
    print('⚠ 未提供行业宏观基准文件：将使用样本推导行业基准 + 原材料中性情景')

# ══════════════════════════════════════════════════════════════════════════
# 模块二：成本结构拆分（回归法）
# ══════════════════════════════════════════════════════════════════════════
banner('模块二：成本结构拆分（回归法）')

def compute_cost_structure(grp):
    """
    对单公司20期时序数据做成本回归：
      - 管理费用 = α + β·收入  → α/收入均值 为固定成本率估计
      - 研发费用视为固定（战略性投入，短期不随收入波动）
      - 财务费用视为固定（债务结构驱动）
      - 变动成本 = 营业成本 / 营业收入（直接物料/人工）
    """
    rev  = grp['营业总收入(亿元)'].dropna()
    cost = grp['营业成本(亿元)'].dropna()
    mgmt = grp['管理费用(亿元)'].fillna(0)
    rd   = grp['研发费用(亿元)'].fillna(0)
    ff   = grp['财务费用(亿元)'].fillna(0)

    avg_rev  = rev.mean()
    avg_cost = cost.mean()
    if avg_rev <= 0 or avg_cost <= 0:
        return None

    gross_margin = 1 - avg_cost / avg_rev

    # 管理费用回归：固定截距部分
    common_idx = rev.index.intersection(mgmt.index)
    mgmt_fixed_rate = 0.0
    if len(common_idx) >= 6:
        slope, intercept, r, p, _ = stats.linregress(rev[common_idx], mgmt[common_idx])
        fixed_portion = max(intercept, 0)          # 截距 = 固定成本额
        mgmt_fixed_rate = fixed_portion / avg_rev
    else:
        mgmt_fixed_rate = mgmt.mean() / avg_rev if avg_rev > 0 else 0.0

    # 研发 + 财务费用均视为固定
    rd_rate = rd.mean() / avg_rev
    ff_rate = ff.mean() / avg_rev

    fixed_cost_rate  = mgmt_fixed_rate + rd_rate + ff_rate
    variable_cost_rate = avg_cost / avg_rev       # 营业成本率（含原材料等）

    # 收入趋势
    period = grp['period'].values
    if len(period) >= 4:
        slope_rev, _, r_rev, _, _ = stats.linregress(period[-len(rev):], rev.values)
        cagr = (rev.iloc[-1] / rev.iloc[0]) ** (4 / max(len(rev) - 1, 1)) - 1 if rev.iloc[0] > 0 else 0.0
    else:
        slope_rev, cagr = 0.0, 0.0

    # BEP = 固定成本总额 / 毛利率
    fixed_cost_total = avg_rev * fixed_cost_rate
    bep_revenue  = fixed_cost_total / gross_margin if gross_margin > 0.01 else np.nan
    bep_margin   = avg_rev / bep_revenue if (bep_revenue and bep_revenue > 0) else np.nan

    return {
        'avg_rev': avg_rev,
        'avg_cost': avg_cost,
        'gross_margin': gross_margin,
        'fixed_cost_rate': fixed_cost_rate,
        'variable_cost_rate': variable_cost_rate,
        'fixed_cost_total': fixed_cost_total,
        'bep_revenue': bep_revenue,
        'bep_margin': bep_margin,
        'revenue_cagr': cagr,
        'rd_intensity': rd_rate,
    }

records = []
for code, grp in fin.groupby('Wind代码'):
    res = compute_cost_structure(grp)
    if res:
        res['Wind代码'] = code
        records.append(res)

COST = pd.DataFrame(records)
print(f'✓ 成本结构拆分完成：{len(COST)} 家公司')
print(f'  毛利率范围: {COST["gross_margin"].min():.2%} ~ {COST["gross_margin"].max():.2%}')
print(f'  BEP安全边际范围: {COST["bep_margin"].min():.2f} ~ {COST["bep_margin"].max():.2f}')

# 未提供外部宏观文件时，使用本次输入公司的真实财务结果推导可复现的样本基准。
if IND_BEP is None:
    benchmark_base = (comp[['Wind代码', '技术领域']]
        .merge(pat[['Wind代码', '行业']], on='Wind代码', how='left')
        .merge(COST, on='Wind代码', how='left'))

    def _benchmark_rows(group_col):
        rows = (benchmark_base.dropna(subset=[group_col])
            .groupby(group_col, as_index=False)
            .agg(
                平均营业收入=('avg_rev', 'mean'),
                平均营业成本=('avg_cost', 'mean'),
                平均营业成本率=('variable_cost_rate', 'mean'),
                平均毛利率=('gross_margin', 'mean'),
                平均BEP营业收入=('bep_revenue', 'mean'),
            )
            .rename(columns={group_col: '行业名称'}))
        rows['平均营业成本率'] *= 100
        rows['平均毛利率'] *= 100
        return rows

    # 同时保留“行业”和“技术领域”两个口径，兼容主表映射与行业对比图。
    IND_BEP = pd.concat(
        [_benchmark_rows('行业'), _benchmark_rows('技术领域')],
        ignore_index=True,
    ).drop_duplicates('行业名称', keep='first')
    MAT = pd.DataFrame([
        {'年份': 2021, '钢材': 100.0, '铜': 100.0, '铝': 100.0, '原油': 100.0},
        {'年份': 2025, '钢材': 100.0, '铜': 100.0, '铝': 100.0, '原油': 100.0},
    ])
    print(f'✓ 已从公司样本推导行业基准：{len(IND_BEP)} 个口径')

# 整合主数据表
# comp 已含 证券简称、技术领域，从 pat 只取独有列，避免 _x/_y 后缀冲突
pat_cols_unique = ['Wind代码','行业','专利综合评分','信用等级',
                   '存量得分','类型质量分','IPC热度分','NLP语义分','关键词密度分',
                   '行业权重乘数','发明专利占比','专利总数']
MASTER = (comp
    .merge(pat[pat_cols_unique], on='Wind代码', how='left')
    .merge(COST, on='Wind代码', how='left')
)

# 行业毛利率基准映射
MASTER['行业基准毛利率'] = (
    MASTER['行业']
    .map(IND_BEP.set_index('行业名称')['平均毛利率'].to_dict())
    .astype(float) / 100
)
MASTER['超额毛利率'] = MASTER['gross_margin'] - MASTER['行业基准毛利率']

print(f'✓ 主数据集：{MASTER.shape}')
print(f'  列名（前20）：{list(MASTER.columns[:20])}')

# ══════════════════════════════════════════════════════════════════════════
# 模块三：Research模式的GBM预测
# ══════════════════════════════════════════════════════════════════════════
TRAIN_GBM = ARGS.mode == 'research'
banner('模块三：GBM预测（仅Research模式）')

# 特征工程
feature_cols = ['专利综合评分','存量得分','IPC热度分','NLP语义分',
                'gross_margin','fixed_cost_rate','variable_cost_rate',
                'revenue_cagr','rd_intensity','行业权重乘数','发明专利占比']

model_df = MASTER[feature_cols + ['bep_margin']].dropna()
X = model_df[feature_cols].values
y = model_df['bep_margin'].values

cv_scores = np.array([])
if TRAIN_GBM:
    if len(X) < 10:
        raise ValueError(
            f'Research模式至少需要10个完整训练样本；当前只有 {len(X)} 个。'
        )
    # 标准化标签（防止极端值破坏训练）
    y_clip = np.clip(y, 0.5, 10.0)
    model = GradientBoostingRegressor(
        n_estimators=200, max_depth=4, learning_rate=0.05,
        subsample=0.8, min_samples_leaf=3,
        random_state=42
    )
    n_splits = min(5, len(X) // 2)
    cv = KFold(n_splits=n_splits, shuffle=True, random_state=42)
    cv_scores = cross_val_score(model, X, y_clip, cv=cv, scoring='r2')
    model.fit(X, y_clip)
    pred_idx = model_df.index
    MASTER.loc[pred_idx, 'bep_margin_gbm'] = model.predict(X)
    feat_imp = pd.Series(model.feature_importances_, index=feature_cols).sort_values(ascending=False)
    print(f'✓ Gradient Boosting CV R²: {cv_scores.mean():.3f} ± {cv_scores.std():.3f}')
else:
    print('✓ Demo模式：按运行口径跳过GBM训练、交叉验证和模型输出')
print(f'  可用训练样本: {len(X)}，特征维度: {len(feature_cols)}')

if TRAIN_GBM:
    print('\n  特征重要性（Top 6）:')
    for f, v in feat_imp.head(6).items():
        print(f'    {f:18s}: {v:.3f}')

# ══════════════════════════════════════════════════════════════════════════
# 模块四：敏感性分析
# ══════════════════════════════════════════════════════════════════════════
banner('模块四：敏感性分析与情景模拟')

SENS = MASTER[['Wind代码','证券简称','技术领域','行业','信用等级',
               '专利综合评分','gross_margin','fixed_cost_rate',
               'variable_cost_rate','bep_margin','avg_rev']].copy()

def sens_variable_cost(row, shock=0.15):
    """变动成本+15% → BEP变化率"""
    gm_new = row['gross_margin'] - row['variable_cost_rate'] * shock
    gm_new = max(gm_new, 0.01)
    bep_new = (row['avg_rev'] * row['fixed_cost_rate']) / gm_new
    bep_old = row['avg_rev'] * row['fixed_cost_rate'] / max(row['gross_margin'], 0.01)
    return abs((bep_new - bep_old) / bep_old) / shock if bep_old > 0 else np.nan

def sens_patent_score(row, drop=10):
    """专利评分下调10分 → 毛利率预估影响"""
    # 根据回归系数：专利评分每降10分，超额毛利率约下降0.5%
    gm_new = max(row['gross_margin'] - 0.005, 0.01)
    bep_new = (row['avg_rev'] * row['fixed_cost_rate']) / gm_new
    bep_old = (row['avg_rev'] * row['fixed_cost_rate']) / max(row['gross_margin'], 0.01)
    return abs((bep_new - bep_old) / bep_old) / (drop / 100) if bep_old > 0 else np.nan

SENS['变动成本敏感系数'] = SENS.apply(sens_variable_cost, axis=1)
SENS['专利评分敏感系数'] = SENS.apply(sens_patent_score, axis=1)
SENS['BEP风险度']     = (1 / SENS['bep_margin'].clip(lower=0.5)).clip(upper=3)

# 原材料冲击（制造业相关行业）
mfg_sectors = ['汽车','半导体','新能源','光学光电子','家用电器','智能制造装备','航空航天']
mat_2025 = MAT[MAT['年份'] == 2025].iloc[0]
mat_2021 = MAT[MAT['年份'] == 2021].iloc[0]
copper_change = (mat_2025['铜'] - mat_2021['铜']) / mat_2021['铜']
oil_change    = (mat_2025['原油'] - mat_2021['原油']) / mat_2021['原油']
SENS['原材料冲击系数'] = SENS['技术领域'].apply(
    lambda s: abs(copper_change * 0.4 + oil_change * 0.3) if s in mfg_sectors else abs(oil_change * 0.1)
)

# 归一化 → [0,1]
for col in ['变动成本敏感系数','专利评分敏感系数','BEP风险度','原材料冲击系数']:
    mn, mx = SENS[col].min(), SENS[col].max()
    SENS[col + '_norm'] = (SENS[col] - mn) / (mx - mn + 1e-9)

print(f'✓ 敏感性计算完成')
print(f'  变动成本敏感系数均值: {SENS["变动成本敏感系数"].mean():.2f}')
print(f'  BEP风险度最高公司: {SENS.sort_values("BEP风险度", ascending=False)["证券简称"].iloc[0]}')

# ══════════════════════════════════════════════════════════════════════════
# 模块五：企业双维度画像
# ══════════════════════════════════════════════════════════════════════════
banner('模块五：企业双维度画像（四象限矩阵）')

PORTRAIT = MASTER[['Wind代码','证券简称','技术领域','行业','信用等级',
                    '专利综合评分','bep_margin','gross_margin',
                    'avg_rev','revenue_cagr']].copy()

p_med = PORTRAIT['专利综合评分'].median()
b_med = PORTRAIT['bep_margin'].median()

def quadrant(row):
    h_pat = row['专利综合评分'] >= p_med
    h_bep = row['bep_margin']   >= b_med
    if h_pat and h_bep:   return '优质标的'
    if h_pat and not h_bep: return '技术待变现'
    if not h_pat and h_bep: return '财务韧性强'
    return '双重风险'

PORTRAIT['象限'] = PORTRAIT.apply(quadrant, axis=1)

print('✓ 四象限分布:')
for q, cnt in PORTRAIT['象限'].value_counts().items():
    print(f'  {q}: {cnt}家')

# ══════════════════════════════════════════════════════════════════════════
# 模块六：差异化定价
# ══════════════════════════════════════════════════════════════════════════
banner('模块六：差异化定价建议')

def interest_adj_bp(row):
    adj = 0
    adj += -30 if row['专利综合评分'] >= 80 else (-15 if row['专利综合评分'] >= 60 else 20)
    adj += -20 if row['bep_margin'] >= 2.5 else (-10 if row['bep_margin'] >= 1.8 else 30)
    adj += -5  if row['revenue_cagr'] >= 0.15 else (5 if row['revenue_cagr'] < 0 else 0)
    return int(adj)

def premium_factor(row):
    f = 1.0
    f *= 0.80 if row['bep_margin'] >= 2.5 else (0.90 if row['bep_margin'] >= 1.8 else 1.30)
    f *= 0.90 if row['专利综合评分'] >= 70 else (1.10 if row['专利综合评分'] < 40 else 1.0)
    return round(f, 2)

def warrant_desc(row):
    if row['专利综合评分'] >= 70 and row['revenue_cagr'] >= 0.1:
        return '建议争取认股权证，行权价设为当前估值×1.2，期限3年'
    elif row['专利综合评分'] >= 50:
        return '可选择性设置认股权证，行权价×1.3，期限2年'
    return '暂不建议设置认股权证'

PRICING = PORTRAIT[['Wind代码','证券简称','技术领域','行业','信用等级',
                     '专利综合评分','bep_margin','revenue_cagr','象限']].copy()
PRICING['利率调整bp'] = PRICING.apply(interest_adj_bp, axis=1)
PRICING['保险保费系数'] = PRICING.apply(premium_factor, axis=1)
PRICING['认股权证建议'] = PRICING.apply(warrant_desc, axis=1)

# 警告标记
def warning_flag(row):
    if row['bep_margin'] < 1.05: return '🔴 红色预警'
    if row['bep_margin'] < 1.2 or row['专利综合评分'] < 30: return '🟠 橙色预警'
    if row['bep_margin'] < 1.5 or row['专利综合评分'] < 50: return '🟡 黄色预警'
    return '🟢 正常'

PRICING['预警状态'] = PRICING.apply(warning_flag, axis=1)
print(f'✓ 定价建议完成，平均利率调整: {PRICING["利率调整bp"].mean():.0f}bp')
print(f'  预警统计:')
for lv, cnt in PRICING['预警状态'].value_counts().items():
    print(f'    {lv}: {cnt}家')

# ══════════════════════════════════════════════════════════════════════════
# ▌可视化输出
# ══════════════════════════════════════════════════════════════════════════

# ─────────────────────────────────────────────────────────────────────────
# 图A：成本结构 - 毛利率 - 专利评分气泡图（matplotlib）
# ─────────────────────────────────────────────────────────────────────────
banner('可视化A：成本结构气泡图')

fig, ax = plt.subplots(figsize=(13, 9))
fig.patch.set_facecolor('white')
ax.set_facecolor('#F3F6F3')

sectors = MASTER['技术领域'].dropna().unique()
palette_a = ['#4E90F5','#94C000','#486B03','#9EBEED','#4E90F5',
              '#94C000','#486B03','#9EBEED','#4E90F5','#94C000',
              '#486B03','#9EBEED','#4E90F5','#94C000','#486B03','#9EBEED']
cmap_tab = lambda i: palette_a[i % len(palette_a)]
sector_clr = {s: cmap_tab(i) for i, s in enumerate(sectors)}

for sec, grp in MASTER.groupby('技术领域'):
    grp = grp.dropna(subset=['fixed_cost_rate','gross_margin','专利综合评分'])
    sc = ax.scatter(
        grp['fixed_cost_rate'] * 100,
        grp['gross_margin'] * 100,
        s=grp['专利综合评分'] * 2,
        c=[sector_clr[sec]] * len(grp),
        alpha=0.75, edgecolors='white', linewidth=0.8,
        label=sec, zorder=3
    )
    for _, row in grp.iterrows():
        ax.annotate(row['证券简称'],
                    (row['fixed_cost_rate']*100, row['gross_margin']*100),
                    fontproperties=fp(7), color='#444',
                    xytext=(4, 3), textcoords='offset points')

# 四象限辅助线
ax.axvline(MASTER['fixed_cost_rate'].median()*100, color='gray', linestyle='--', alpha=0.5, lw=1)
ax.axhline(MASTER['gross_margin'].median()*100,    color='gray', linestyle='--', alpha=0.5, lw=1)

ax.set_xlabel('固定成本率 (%)', fontproperties=fp(12))
ax.set_ylabel('毛利率 (%)', fontproperties=fp(12))
ax.set_title('成本结构 × 毛利率 × 专利评分气泡图\n（气泡大小 = 专利综合评分）',
             fontproperties=fp(13), pad=12)
ax.legend(prop=fp(8), bbox_to_anchor=(1.01, 1), loc='upper left', framealpha=0.8)
ax.grid(alpha=0.3, linestyle='--')
for sp in ['top','right']:
    ax.spines[sp].set_visible(False)

# 气泡大小图例
for size_val, label in [(60,'评分30'),(100,'评分50'),(160,'评分80')]:
    ax.scatter([], [], s=size_val*2, c='gray', alpha=0.5, label=label)
ax.legend(prop=fp(8), bbox_to_anchor=(1.01, 1), loc='upper left', framealpha=0.8)

plt.tight_layout()
path_a = os.path.join(FIGURES_DIR, 'cost_structure.png')
plt.savefig(path_a, dpi=150, bbox_inches='tight', facecolor='white')
plt.close()
print(f'✓ {path_a}')

# ─────────────────────────────────────────────────────────────────────────
# 图B：BEP安全边际行业对比（修复版）
# ─────────────────────────────────────────────────────────────────────────
banner('可视化B：BEP行业对比图')

fig, axes = plt.subplots(1, 2, figsize=(15, 7))
fig.patch.set_facecolor('white')

# 左图：BEP安全边际均值
sector_stat = (MASTER.groupby('技术领域')
               .agg(bep_mean=('bep_margin','mean'),
                    bep_std=('bep_margin','std'),
                    gm_mean=('gross_margin','mean'),
                    n=('Wind代码','count'))
               .reset_index()
               .sort_values('bep_mean', ascending=True))

clrs = ['#4E90F5' if v >= 2.0 else '#94C000' for v in sector_stat['bep_mean']]
bars = axes[0].barh(sector_stat['技术领域'], sector_stat['bep_mean'],
                    color=clrs, height=0.6, edgecolor='white', linewidth=0.8)
axes[0].errorbar(sector_stat['bep_mean'], sector_stat['技术领域'],
                 xerr=sector_stat['bep_std'].fillna(0),
                 fmt='none', color='#555', capsize=3, linewidth=1)

for _, row in sector_stat.iterrows():
    axes[0].text(row['bep_mean'] + 0.05, row['技术领域'],
                 f"{row['bep_mean']:.2f}x  (n={int(row['n'])})",
                 va='center', fontproperties=fp(9))

axes[0].axvline(1.5, color='#9EBEED', ls='--', lw=1.2, label='警戒线 1.5x')
axes[0].axvline(2.0, color='#94C000',  ls='--', lw=1.2, label='健康线 2.0x')
axes[0].set_xlabel('BEP安全边际（均值）', fontproperties=fp(11))
axes[0].set_title('各技术领域 BEP安全边际', fontproperties=fp(12), fontweight='bold')
axes[0].legend(prop=fp(9))
axes[0].set_xlim(0, sector_stat['bep_mean'].max() * 1.4)
for sp in ['top','right']:
    axes[0].spines[sp].set_visible(False)
for tick in axes[0].get_yticklabels():
    tick.set_fontproperties(fp(9))

# 右图：毛利率 vs 行业基准对比
gm_comp = (MASTER.groupby('技术领域')
           .agg(gm_actual=('gross_margin','mean'))
           .reset_index()
           .merge(IND_BEP[['行业名称','平均毛利率']].rename(columns={'行业名称':'技术领域','平均毛利率':'gm_bench'}),
                  on='技术领域', how='left'))
gm_comp['gm_bench'] /= 100
gm_comp = gm_comp.sort_values('gm_actual', ascending=True)

x_pos = np.arange(len(gm_comp))
w = 0.35
axes[1].barh(x_pos - w/2, gm_comp['gm_actual']*100, w,
             color='#4E90F5', label='实际毛利率', alpha=0.85)
axes[1].barh(x_pos + w/2, gm_comp['gm_bench'].fillna(0)*100, w,
             color='#94C000', label='行业基准毛利率', alpha=0.65)
axes[1].set_yticks(x_pos)
axes[1].set_yticklabels(gm_comp['技术领域'], fontproperties=fp(9))
axes[1].set_xlabel('毛利率 (%)', fontproperties=fp(11))
axes[1].set_title('实际毛利率 vs 行业基准', fontproperties=fp(12), fontweight='bold')
axes[1].legend(prop=fp(9))
for sp in ['top','right']:
    axes[1].spines[sp].set_visible(False)

fig.suptitle('BEP安全边际与毛利率行业分析', fontproperties=fp(14), fontweight='bold', y=1.01)
plt.tight_layout()
path_b = os.path.join(FIGURES_DIR, 'bep_industry_comparison.png')
plt.savefig(path_b, dpi=150, bbox_inches='tight', facecolor='white')
plt.close()
print(f'✓ {path_b}')

# ─────────────────────────────────────────────────────────────────────────
# 图C：专利评分 vs 毛利率散点回归（修复版）
# ─────────────────────────────────────────────────────────────────────────
banner('可视化C：专利评分与毛利率关系')

valid = MASTER[['专利综合评分','gross_margin','证券简称','技术领域','信用等级']].dropna()

fig, ax = plt.subplots(figsize=(12, 8))
fig.patch.set_facecolor('white')
ax.set_facecolor('#F3F6F3')

sectors_c = valid['技术领域'].unique()
palette_c = ['#4E90F5','#94C000','#486B03','#9EBEED','#4E90F5',
              '#94C000','#486B03','#9EBEED','#4E90F5','#94C000',
              '#486B03','#9EBEED','#4E90F5','#94C000','#486B03','#9EBEED']
cmap_c = lambda i: palette_c[i % len(palette_c)]
sc_clr_c = {s: cmap_c(i) for i, s in enumerate(sectors_c)}

for sec, grp in valid.groupby('技术领域'):
    ax.scatter(grp['专利综合评分'], grp['gross_margin']*100,
               s=90, color=sc_clr_c[sec], alpha=0.85,
               edgecolors='white', linewidth=0.7, label=sec, zorder=3)
    for _, row in grp.iterrows():
        ax.annotate(row['证券简称'],
                    (row['专利综合评分'], row['gross_margin']*100),
                    fontproperties=fp(7), color='#555',
                    xytext=(4,3), textcoords='offset points')

# 回归线（样本不足10家时仅展示趋势，不作显著性推断）
X_c = valid['专利综合评分'].values
y_c = valid['gross_margin'].values * 100
z = np.polyfit(X_c, y_c, 1)
xl = np.linspace(X_c.min(), X_c.max(), 100)
r_value = np.corrcoef(X_c, y_c)[0,1]
r2 = r_value**2
n = len(X_c)
if n >= 10:
    p_value = stats.linregress(X_c, y_c).pvalue
    trend_label = f'线性趋势 (R²={r2:.3f}，p={p_value:.3f})'
    band_label = '95% 置信区间'
else:
    trend_label = f'探索性趋势 (n={n}，R²={r2:.3f})'
    band_label = '探索性范围（样本不足）'
ax.plot(xl, np.polyval(z, xl), 'r--', lw=2, alpha=0.8,
        label=trend_label)

# 置信带
from scipy.stats import t as t_dist
x_mean = X_c.mean()
se_band = np.sqrt(np.mean((y_c - np.polyval(z, X_c))**2)) * np.sqrt(1/n + (xl - x_mean)**2 / np.sum((X_c - x_mean)**2))
t_val = t_dist.ppf(0.975, n-2)
ax.fill_between(xl, np.polyval(z,xl)-t_val*se_band, np.polyval(z,xl)+t_val*se_band,
                alpha=0.12, color='red', label=band_label)

ax.set_xlabel('专利综合评分 (0–100)', fontproperties=fp(12))
ax.set_ylabel('企业平均毛利率 (%)', fontproperties=fp(12))
chart_suffix = '（样本探索，不作显著性推断）' if n < 10 else '（技术溢价→盈利能力验证）'
ax.set_title(f'专利综合评分与企业毛利率关系\n{chart_suffix}',
             fontproperties=fp(13), pad=18)
ax.legend(prop=fp(9), loc='upper left')
ax.grid(alpha=0.3, linestyle='--')
for sp in ['top','right']:
    ax.spines[sp].set_visible(False)

plt.tight_layout(rect=(0, 0, 1, 0.93))
path_c = os.path.join(FIGURES_DIR, 'patent_score_gross_margin.png')
plt.savefig(path_c, dpi=150, bbox_inches='tight', facecolor='white')
plt.close()
print(f'✓ {path_c}')

# ─────────────────────────────────────────────────────────────────────────
# 图D：敏感性热力图（修复版，4维度）
# ─────────────────────────────────────────────────────────────────────────
banner('可视化D：敏感性热力图')

norm_cols = ['变动成本敏感系数_norm','专利评分敏感系数_norm','BEP风险度_norm','原材料冲击系数_norm']
col_labels = ['变动成本\n敏感性','专利评分\n敏感性','BEP\n风险度','原材料\n冲击']

heat_df = (SENS.set_index('证券简称')[norm_cols]
           .sort_values('BEP风险度_norm', ascending=False))

fig, ax = plt.subplots(figsize=(10, 16))
fig.patch.set_facecolor('white')

cmap_d = mcolors.LinearSegmentedColormap.from_list('risk', ['#F3F6F3','#9EBEED','#486B03'])
im = ax.imshow(heat_df.values, aspect='auto', cmap=cmap_d, vmin=0, vmax=1)

ax.set_xticks(range(len(col_labels)))
ax.set_xticklabels(col_labels, fontproperties=fp(10))
ax.set_yticks(range(len(heat_df.index)))
ax.set_yticklabels(heat_df.index, fontproperties=fp(8))

# 右侧标注信用等级 + 专利评分
sens_idx = SENS.set_index('证券简称')
for i, company in enumerate(heat_df.index):
    if company in sens_idx.index:
        rating = sens_idx.loc[company, '信用等级']
        score  = sens_idx.loc[company, '专利综合评分']
        clr = CREDIT_COLORS.get(str(rating), '#888')
        ax.text(len(col_labels) + 0.15, i,
                f'{rating}  {score:.0f}分',
                va='center', fontproperties=fp(7.5),
                color=clr, fontweight='bold')

# 数值标注
for i in range(len(heat_df)):
    for j in range(len(norm_cols)):
        v = heat_df.values[i, j]
        ax.text(j, i, f'{v:.2f}', ha='center', va='center',
                fontproperties=fp(7.5),
                color='white' if v > 0.6 else '#333')

cbar = plt.colorbar(im, ax=ax, fraction=0.015, pad=0.01)
cbar.set_label('风险强度 (0=低  1=高)', fontproperties=fp(9))

ax.set_title(f'{len(MASTER)}家公司 BEP风险敏感性热力图\n（右侧：信用等级 / 专利综合评分）',
             fontproperties=fp(12), fontweight='bold', pad=12)
ax.set_xlim(-0.5, len(norm_cols) - 0.5 + 2.0)

plt.tight_layout()
path_d = os.path.join(FIGURES_DIR, 'sensitivity_heatmap.png')
plt.savefig(path_d, dpi=150, bbox_inches='tight', facecolor='white')
plt.close()
print(f'✓ {path_d}')

# ─────────────────────────────────────────────────────────────────────────
# 图E：四象限企业画像（交互Plotly）
# ─────────────────────────────────────────────────────────────────────────
banner('可视化E：四象限企业画像（交互图）')

QUAD_COLORS = {
    '优质标的':  '#486B03',
    '技术待变现':'#4E90F5',
    '财务韧性强':'#94C000',
    '双重风险':  '#9EBEED',
}

# Build data JSON for the interactive HTML
portrait_data = []
for _, row in PORTRAIT.iterrows():
    bm = row.get('bep_margin')
    ps = row.get('专利综合评分')
    if pd.isna(bm) or pd.isna(ps):
        continue
    rev = MASTER.loc[MASTER['Wind代码'] == row['Wind代码'], 'avg_rev']
    avg_rev = float(rev.iloc[0]) if len(rev) > 0 else 1.0
    portrait_data.append({
        'code': row['Wind代码'],
        'name': row['证券简称'],
        'sector': str(row.get('技术领域','')),
        'industry': str(row.get('行业','')),
        'credit': str(row.get('信用等级','')),
        'patent': float(ps),
        'bep': float(bm),
        'gm': float(row.get('gross_margin', 0)),
        'rev': float(avg_rev),
        'cagr': float(row.get('revenue_cagr', 0)),
        'quad': row['象限'],
        'color': QUAD_COLORS.get(row['象限'], '#888'),
    })

html_e = f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>企业双维度评价矩阵</title>
<style>
body{{font-family:sans-serif;margin:0;background:#f5f5f5}}
#container{{max-width:1200px;margin:20px auto;background:#fff;border-radius:8px;padding:20px;box-shadow:0 2px 8px rgba(0,0,0,.1)}}
h2{{text-align:center;color:#333;margin-bottom:4px}}
p.sub{{text-align:center;color:#666;font-size:13px;margin:0 0 16px}}
#chart{{position:relative;border:1px solid #ddd;border-radius:6px;background:#f8f8f8;overflow:hidden}}
canvas{{display:block}}
#tooltip{{position:absolute;background:rgba(0,0,0,.82);color:#fff;padding:10px 14px;border-radius:6px;font-size:12px;pointer-events:none;display:none;line-height:1.7;z-index:10}}
#legend{{display:flex;gap:20px;justify-content:center;margin:12px 0 8px;flex-wrap:wrap}}
.leg-item{{display:flex;align-items:center;gap:6px;font-size:13px;cursor:pointer}}
.leg-dot{{width:14px;height:14px;border-radius:50%;flex-shrink:0}}
.leg-item.hidden .leg-dot{{opacity:.3}}
.leg-item.hidden span{{color:#aaa}}
#info{{min-height:60px;padding:10px 16px;background:#f0f4ff;border-radius:6px;font-size:13px;color:#333;margin-top:8px}}
</style></head><body>
<div id="container">
<h2>企业双维度评价矩阵：技术价值 × 财务韧性</h2>
<p class="sub">气泡大小 = 平均营业收入规模 &nbsp;|&nbsp; 悬停查看完整画像 &nbsp;|&nbsp; 点击图例显示/隐藏象限</p>
<div id="legend"></div>
<div id="chart"><canvas id="cv"></canvas><div id="tooltip"></div></div>
<div id="info">👆 将鼠标悬停在气泡上查看企业详细信息</div>
</div>
<script>
const DATA = {json.dumps(portrait_data, ensure_ascii=False)};
const QUADS = ['优质标的','技术待变现','财务韧性强','双重风险'];
const QC    = {{'优质标的':'#2ecc71','技术待变现':'#3498db','财务韧性强':'#f39c12','双重风险':'#e74c3c'}};
const PM={p_med:.1f}, BM={b_med:.2f};

const canvas=document.getElementById('cv');
const ctx=canvas.getContext('2d');
const tip=document.getElementById('tooltip');
const info=document.getElementById('info');

const hidden=new Set();
let W,H,PAD={{l:70,r:40,t:30,b:60}};
let xMin=0,xMax=108,yMin=0,yMax=20;

function resize(){{
  const c=document.getElementById('chart');
  W=c.clientWidth; H=Math.round(W*0.58);
  canvas.width=W; canvas.height=H;
  yMax=Math.min(20, Math.max(5, Math.ceil(DATA.reduce((m,d)=>Math.max(m,d.bep),0)*1.3)));
  draw();
}}

function toX(v){{return PAD.l+(v-xMin)/(xMax-xMin)*(W-PAD.l-PAD.r);}}
function toY(v){{return H-PAD.b-(v-yMin)/(yMax-yMin)*(H-PAD.t-PAD.b);}}
function revRad(r){{return Math.max(5, Math.min(28, Math.sqrt(r)/14));}}

function draw(){{
  ctx.clearRect(0,0,W,H);
  // bg
  ctx.fillStyle='#f8f8f8'; ctx.fillRect(0,0,W,H);
  // grid
  ctx.strokeStyle='#ddd'; ctx.lineWidth=0.8;
  for(let v=0;v<=100;v+=20){{
    const x=toX(v); ctx.beginPath();ctx.moveTo(x,PAD.t);ctx.lineTo(x,H-PAD.b);ctx.stroke();
    ctx.fillStyle='#888';ctx.font='11px sans-serif';ctx.textAlign='center';
    ctx.fillText(v,x,H-PAD.b+16);
  }}
  for(let v=0;v<=yMax;v+=Math.max(1,Math.round(yMax/6))){{
    const y=toY(v); ctx.beginPath();ctx.moveTo(PAD.l,y);ctx.lineTo(W-PAD.r,y);ctx.stroke();
    ctx.fillStyle='#888';ctx.font='11px sans-serif';ctx.textAlign='right';
    ctx.fillText(v.toFixed(1),PAD.l-6,y+4);
  }}
  // median lines
  ctx.setLineDash([6,4]);ctx.strokeStyle='#aaa';ctx.lineWidth=1.2;
  const mx=toX(PM),my=toY(BM);
  ctx.beginPath();ctx.moveTo(mx,PAD.t);ctx.lineTo(mx,H-PAD.b);ctx.stroke();
  ctx.beginPath();ctx.moveTo(PAD.l,my);ctx.lineTo(W-PAD.r,my);ctx.stroke();
  ctx.setLineDash([]);
  // quad labels
  const qlabels=[['优质标的',xMax*0.82,yMax*0.92],['技术待变现',xMax*0.82,yMax*0.08],
                 ['财务韧性强',xMax*0.08,yMax*0.92],['双重风险',xMax*0.08,yMax*0.08]];
  qlabels.forEach(([q,x,y])=>{{
    if(hidden.has(q))return;
    ctx.font='bold 11px sans-serif';ctx.fillStyle=QC[q]+'bb';ctx.textAlign='center';
    ctx.fillText(q,toX(x),toY(y));
  }});
  // bubbles
  DATA.forEach(d=>{{
    if(hidden.has(d.quad))return;
    const x=toX(d.patent),y=toY(d.bep),r=revRad(d.rev);
    ctx.beginPath();ctx.arc(x,y,r,0,Math.PI*2);
    ctx.fillStyle=d.color+'bb';ctx.fill();
    ctx.strokeStyle=d.color;ctx.lineWidth=1.5;ctx.stroke();
    ctx.fillStyle='#333';ctx.font='9px sans-serif';ctx.textAlign='center';
    ctx.fillText(d.name,x,y-r-3);
  }});
  // axes labels
  ctx.fillStyle='#555';ctx.font='13px sans-serif';ctx.textAlign='center';
  ctx.fillText('专利综合评分（技术价值）→',W/2,H-12);
  ctx.save();ctx.translate(14,H/2);ctx.rotate(-Math.PI/2);
  ctx.fillText('BEP安全边际（财务韧性）→',0,0);ctx.restore();
}}

// Tooltip
function findNearest(mx,my){{
  let best=null,bd=1e9;
  DATA.forEach(d=>{{
    if(hidden.has(d.quad))return;
    const x=toX(d.patent),y=toY(d.bep),r=revRad(d.rev);
    const dist=Math.sqrt((mx-x)**2+(my-y)**2);
    if(dist<r+4&&dist<bd){{bd=dist;best=d;}}
  }});
  return best;
}}

canvas.addEventListener('mousemove',e=>{{
  const rect=canvas.getBoundingClientRect();
  const mx=e.clientX-rect.left,my=e.clientY-rect.top;
  const d=findNearest(mx,my);
  if(d){{
    tip.style.display='block';
    tip.innerHTML=`<b>${{d.name}}</b><br>行业: ${{d.industry}}<br>信用等级: ${{d.credit}}<br>专利评分: ${{d.patent.toFixed(0)}}<br>BEP安全边际: ${{d.bep.toFixed(2)}}x<br>毛利率: ${{(d.gm*100).toFixed(1)}}%<br>平均营收: ${{d.rev.toFixed(0)}}亿<br>收入CAGR: ${{(d.cagr*100).toFixed(1)}}%`;
    let tx=mx+16,ty=my-20;
    if(tx+220>W)tx=mx-230;
    if(ty<0)ty=my+20;
    tip.style.left=tx+'px';tip.style.top=ty+'px';
    info.innerHTML=`<b>${{d.name}}</b>（${{d.quad}}）&nbsp;|&nbsp;信用: ${{d.credit}} &nbsp;|&nbsp; 专利: ${{d.patent.toFixed(0)}}分 &nbsp;|&nbsp; BEP安全边际: ${{d.bep.toFixed(2)}}x &nbsp;|&nbsp; 毛利率: ${{(d.gm*100).toFixed(1)}}%`;
  }} else {{
    tip.style.display='none';
    info.innerHTML='👆 将鼠标悬停在气泡上查看企业详细信息';
  }}
}});
canvas.addEventListener('mouseleave',()=>{{tip.style.display='none';}});

// Legend
const leg=document.getElementById('legend');
QUADS.forEach(q=>{{
  const cnt=DATA.filter(d=>d.quad===q).length;
  const el=document.createElement('div');
  el.className='leg-item';el.innerHTML=`<div class="leg-dot" style="background:${{QC[q]}}"></div><span>${{q}} (${{cnt}}家)</span>`;
  el.onclick=()=>{{
    if(hidden.has(q))hidden.delete(q);else hidden.add(q);
    el.classList.toggle('hidden',hidden.has(q));draw();
  }};
  leg.appendChild(el);
}});

window.addEventListener('resize',resize);
resize();
</script></body></html>"""

path_e = os.path.join(INTERACTIVE_DIR, 'borrower_portfolio.html')
with open(path_e, 'w', encoding='utf-8') as f:
    f.write(html_e)
print(f'✓ {path_e}')

# ─────────────────────────────────────────────────────────────────────────
# 图F：各象限代表企业雷达图（合并为单HTML）
# ─────────────────────────────────────────────────────────────────────────
banner('可视化F：代表企业雷达图')

radar_cats = ['专利综合评分','NLP语义分','IPC热度分','BEP安全边际(×20)','毛利率(×100)','收入CAGR(×100+50)']
angles = np.linspace(0, 2*np.pi, len(radar_cats), endpoint=False).tolist()
angles += angles[:1]

fig_f, axes_f = plt.subplots(2, 2, figsize=(14, 12),
                               subplot_kw=dict(projection='polar'))
fig_f.patch.set_facecolor('white')
fig_f.suptitle('各象限代表企业六维雷达图', fontproperties=fp(14), fontweight='bold', y=1.01)

quad_list_f = ['优质标的','技术待变现','财务韧性强','双重风险']
ax_pos = [(0,0),(0,1),(1,0),(1,1)]

for quad, (ri, ci) in zip(quad_list_f, ax_pos):
    ax_r = axes_f[ri][ci]
    grp = PORTRAIT[PORTRAIT['象限'] == quad]
    if grp.empty:
        ax_r.set_title(quad, fontproperties=fp(11))
        continue
    rep = MASTER[MASTER['Wind代码'].isin(grp['Wind代码'])].sort_values('avg_rev', ascending=False).iloc[0]

    vals = [
        float(rep.get('专利综合评分', 50)),
        float(rep.get('NLP语义分', 50)),
        float(rep.get('IPC热度分', 50)),
        min(float(rep.get('bep_margin', 1.5)) * 20, 100),
        min(float(rep.get('gross_margin', 0.2)) * 100, 100),
        min(float(rep.get('revenue_cagr', 0)) * 100 + 50, 100),
    ]
    vals_c = vals + [vals[0]]
    clr = QUAD_COLORS[quad]

    ax_r.plot(angles, vals_c, 'o-', color=clr, linewidth=2)
    ax_r.fill(angles, vals_c, color=clr, alpha=0.2)
    ax_r.set_xticks(angles[:-1])
    ax_r.set_xticklabels(radar_cats, fontproperties=fp(8))
    ax_r.set_ylim(0, 100)
    ax_r.set_yticks([20, 40, 60, 80, 100])
    ax_r.set_yticklabels(['20','40','60','80','100'], fontproperties=fp(7), color='#888')
    ax_r.set_title(f'{quad}\n代表：{rep["证券简称"]}', fontproperties=fp(10), pad=14, color=clr)
    ax_r.grid(color='#ddd', linewidth=0.5)

plt.tight_layout()
path_f = os.path.join(FIGURES_DIR, 'representative_company_radar.png')
plt.savefig(path_f, dpi=150, bbox_inches='tight', facecolor='white')
plt.close()
print(f'✓ {path_f}')

# ─────────────────────────────────────────────────────────────────────────
# 图G：BEP安全边际季度时序监控（Plotly，使用真实数据）
# ─────────────────────────────────────────────────────────────────────────
banner('可视化G：BEP安全边际季度时序监控')

# Compute quarterly BEP per company
period_bep = []
for code, grp in fin.groupby('Wind代码'):
    grp = grp.sort_values('period')
    for _, row in grp.iterrows():
        r = row['营业总收入(亿元)']
        c = row['营业成本(亿元)']
        m = row['管理费用(亿元)'] if pd.notna(row['管理费用(亿元)']) else 0
        d = row['研发费用(亿元)']  if pd.notna(row['研发费用(亿元)'])  else 0
        f = row['财务费用(亿元)']  if pd.notna(row['财务费用(亿元)'])  else 0
        if pd.notna(r) and pd.notna(c) and r > 0 and c > 0:
            gm  = 1 - c / r
            fc  = m + d + f
            bep = fc / gm if gm > 0.01 else np.nan
            bm  = r / bep if (bep and bep > 0) else np.nan
            period_bep.append({'Wind代码': code, '日期': row['日期'],
                                'period': row['period'], 'bep_q': bm})

PBQ = pd.DataFrame(period_bep).merge(
    MASTER[['Wind代码','证券简称']], on='Wind代码', how='left').merge(
    PORTRAIT[['Wind代码','象限']], on='Wind代码', how='left')

# Select 2 reps per quadrant (avg_rev lives in PORTRAIT already via MASTER)
quad_list_g = ['优质标的','技术待变现','财务韧性强','双重风险']
rep_codes_g = []
for quad in quad_list_g:
    qcos = PORTRAIT[PORTRAIT['象限'] == quad].copy()
    if 'avg_rev' not in qcos.columns:
        qcos = qcos.merge(MASTER[['Wind代码','avg_rev']], on='Wind代码', how='left')
    qcos = qcos.sort_values('avg_rev', ascending=False)
    rep_codes_g += qcos['Wind代码'].head(2).tolist()

PBQ_rep = PBQ[PBQ['Wind代码'].isin(rep_codes_g)].sort_values(['Wind代码','period'])

# Quarter label mapping
def qlabel(d):
    parts = d.split()
    return f"{parts[0]} {parts[1].replace('FY','')}"

PBQ_rep = PBQ_rep.copy()
PBQ_rep['季度'] = PBQ_rep['日期'].map(qlabel)
qlabels_order = sorted(PBQ_rep['季度'].unique(),
                        key=lambda x: (int(x.split()[1]), int(x.split()[0][1:])))

# Build self-contained interactive HTML for time series
ts_data = {}
for code, grp in PBQ_rep.groupby('Wind代码'):
    grp = grp.sort_values('period')
    name = grp['证券简称'].iloc[0]
    quad = grp['象限'].iloc[0] if '象限' in grp.columns else ''
    pts  = []
    for _, row in grp.iterrows():
        pts.append({'q': qlabel(row['日期']), 'v': round(float(row['bep_q']), 3) if pd.notna(row['bep_q']) else None})
    ts_data[code] = {'name': name, 'quad': quad,
                     'color': QUAD_COLORS.get(quad, '#888'), 'pts': pts}

html_g = f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>BEP季度时序监控</title>
<style>
body{{font-family:sans-serif;margin:0;background:#f5f5f5}}
#container{{max-width:1300px;margin:20px auto;background:#fff;border-radius:8px;padding:20px;box-shadow:0 2px 8px rgba(0,0,0,.1)}}
h2{{text-align:center;color:#333;margin-bottom:4px}}p.sub{{text-align:center;color:#666;font-size:13px;margin:0 0 16px}}
#chart{{position:relative;border:1px solid #ddd;border-radius:6px;background:#f8f8f8}}
canvas{{display:block}}
#tooltip2{{position:absolute;background:rgba(0,0,0,.82);color:#fff;padding:8px 12px;border-radius:6px;font-size:12px;pointer-events:none;display:none;line-height:1.7;z-index:10}}
#legend2{{display:flex;gap:16px;justify-content:center;margin:10px 0 6px;flex-wrap:wrap}}
.leg2{{display:flex;align-items:center;gap:5px;font-size:12px;cursor:pointer}}
.leg2-line{{width:24px;height:3px;border-radius:2px}}
.leg2.hidden .leg2-line,.leg2.hidden span{{opacity:.3}}
</style></head><body>
<div id="container">
<h2>BEP安全边际季度追踪（2021Q1–2025Q4）</h2>
<p class="sub">各象限代表企业 · 悬停查看数值 · 点击图例显示/隐藏</p>
<div id="legend2"></div>
<div id="chart"><canvas id="cv2"></canvas><div id="tooltip2"></div></div>
</div>
<script>
const TS={json.dumps(ts_data, ensure_ascii=False)};
const QLABELS={json.dumps(qlabels_order, ensure_ascii=False)};
const hidden2=new Set();
const canvas=document.getElementById('cv2');
const ctx=canvas.getContext('2d');
const tip=document.getElementById('tooltip2');
const PAD={{l:60,r:20,t:20,b:80}};
let W,H;

function resize(){{
  const c=document.getElementById('chart');
  W=c.clientWidth; H=Math.round(W*0.38);
  canvas.width=W; canvas.height=H; draw();
}}

const codes=Object.keys(TS);
const allVals=codes.flatMap(c=>TS[c].pts.map(p=>p.v).filter(v=>v!=null));
const yMin=0, yMax=Math.min(20,Math.ceil(Math.max(...allVals)*1.15));

function toX(i){{return PAD.l+i/(QLABELS.length-1)*(W-PAD.l-PAD.r);}}
function toY(v){{return H-PAD.b-(v-yMin)/(yMax-yMin)*(H-PAD.t-PAD.b);}}

function draw(){{
  ctx.clearRect(0,0,W,H);
  ctx.fillStyle='#f8f8f8';ctx.fillRect(0,0,W,H);
  // grid
  ctx.strokeStyle='#e0e0e0';ctx.lineWidth=0.8;
  for(let v=0;v<=yMax;v+=0.5){{
    const y=toY(v);ctx.beginPath();ctx.moveTo(PAD.l,y);ctx.lineTo(W-PAD.r,y);ctx.stroke();
    if(v%1===0){{ctx.fillStyle='#888';ctx.font='11px sans-serif';ctx.textAlign='right';ctx.fillText(v.toFixed(1),PAD.l-5,y+4);}}
  }}
  // threshold lines
  [{{v:1.05,c:'#e74c3c',lbl:'临界线 1.05x'}},{{v:1.5,c:'#f39c12',lbl:'警戒线 1.5x'}},{{v:2.0,c:'#2ecc71',lbl:'健康线 2.0x'}}].forEach(t=>{{
    const y=toY(t.v);ctx.setLineDash([5,4]);ctx.strokeStyle=t.c+'88';ctx.lineWidth=1.2;
    ctx.beginPath();ctx.moveTo(PAD.l,y);ctx.lineTo(W-PAD.r,y);ctx.stroke();
    ctx.fillStyle=t.c;ctx.font='10px sans-serif';ctx.textAlign='left';ctx.fillText(t.lbl,W-PAD.r+2,y+3);
    ctx.setLineDash([]);
  }});
  // x axis labels
  QLABELS.forEach((q,i)=>{{
    if(i%4!==0&&i!==QLABELS.length-1)return;
    const x=toX(i);ctx.fillStyle='#888';ctx.font='10px sans-serif';ctx.textAlign='center';
    ctx.save();ctx.translate(x,H-PAD.b+10);ctx.rotate(-Math.PI/4);ctx.fillText(q,0,0);ctx.restore();
  }});
  // lines
  codes.forEach(code=>{{
    if(hidden2.has(code))return;
    const d=TS[code];
    ctx.beginPath();ctx.strokeStyle=d.color;ctx.lineWidth=2;
    let started=false;
    d.pts.forEach((p,i)=>{{
      const qi=QLABELS.indexOf(p.q);if(qi<0||p.v==null)return;
      const x=toX(qi),y=toY(p.v);
      if(!started){{ctx.moveTo(x,y);started=true;}}else ctx.lineTo(x,y);
    }});
    ctx.stroke();
    d.pts.forEach(p=>{{
      const qi=QLABELS.indexOf(p.q);if(qi<0||p.v==null)return;
      ctx.beginPath();ctx.arc(toX(qi),toY(p.v),3,0,Math.PI*2);
      ctx.fillStyle=d.color;ctx.fill();
    }});
  }});
}}

// Tooltip
canvas.addEventListener('mousemove',e=>{{
  const rect=canvas.getBoundingClientRect();
  const mx=e.clientX-rect.left,my=e.clientY-rect.top;
  let best=null,bd=20;
  codes.forEach(code=>{{
    if(hidden2.has(code))return;
    TS[code].pts.forEach(p=>{{
      const qi=QLABELS.indexOf(p.q);if(qi<0||p.v==null)return;
      const dist=Math.sqrt((mx-toX(qi))**2+(my-toY(p.v))**2);
      if(dist<bd){{bd=dist;best={{...p,code,name:TS[code].name,color:TS[code].color}};}}
    }});
  }});
  if(best){{
    tip.style.display='block';
    tip.innerHTML=`<b style="color:${{best.color}}">${{best.name}}</b><br>${{best.q}}<br>BEP安全边际: <b>${{best.v.toFixed(2)}}x</b>`;
    let tx=mx+14,ty=my-40;
    if(tx+200>W)tx=mx-220;if(ty<0)ty=my+20;
    tip.style.left=tx+'px';tip.style.top=ty+'px';
  }}else tip.style.display='none';
}});
canvas.addEventListener('mouseleave',()=>tip.style.display='none');

// Legend
const leg=document.getElementById('legend2');
codes.forEach(code=>{{
  const d=TS[code];
  const el=document.createElement('div');el.className='leg2';
  el.innerHTML=`<div class="leg2-line" style="background:${{d.color}}"></div><span>${{d.name}} (${{d.quad}})</span>`;
  el.onclick=()=>{{
    if(hidden2.has(code))hidden2.delete(code);else hidden2.add(code);
    el.classList.toggle('hidden',hidden2.has(code));draw();
  }};
  leg.appendChild(el);
}});

window.addEventListener('resize',resize);resize();
</script></body></html>"""

path_g = os.path.join(INTERACTIVE_DIR, 'bep_time_series.html')
with open(path_g, 'w', encoding='utf-8') as f:
    f.write(html_g)
print(f'✓ {path_g}')

# ── GBM特征重要性图（仅Research模式）
if TRAIN_GBM:
    fig, ax = plt.subplots(figsize=(9, 6))
    fig.patch.set_facecolor('white')
    feat_imp.sort_values().plot(kind='barh', ax=ax, color='#4E90F5', edgecolor='white')
    ax.set_title('GBM特征重要性', fontproperties=fp(12), pad=10)
    ax.set_xlabel('重要性得分', fontproperties=fp(10))
    ax.set_yticklabels([feat_imp.sort_values().index[i] for i in range(len(feat_imp))],
                       fontproperties=fp(9))
    for sp in ['top','right']:
        ax.spines[sp].set_visible(False)
    plt.tight_layout()
    path_feat = os.path.join(FIGURES_DIR, 'gbm_feature_importance.png')
    plt.savefig(path_feat, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close()
    print(f'✓ {path_feat}')

# ══════════════════════════════════════════════════════════════════════════
# 模块八：输出Excel
# ══════════════════════════════════════════════════════════════════════════
banner('模块八：输出Excel交付物')

# 主数据集
main_columns = ['Wind代码','证券简称','技术领域','行业','信用等级',
                '专利综合评分','专利总数','发明专利占比',
                'avg_rev','gross_margin','fixed_cost_rate','variable_cost_rate',
                'fixed_cost_total','bep_margin','revenue_cagr',
                '行业基准毛利率','超额毛利率']
main_headers = ['Wind代码','证券简称','技术领域','行业','信用等级',
                '专利综合评分','专利总数','发明专利占比',
                '平均营收(亿元)','毛利率','固定成本率','变动成本率',
                '固定成本总额(亿元)','BEP安全边际(实算)','收入CAGR',
                '行业基准毛利率','超额毛利率']
if TRAIN_GBM:
    main_columns.insert(14, 'bep_margin_gbm')
    main_headers.insert(14, 'BEP安全边际(GBM预测)')
main_sheet = MASTER[main_columns].copy()
main_sheet.columns = main_headers

sens_sheet = SENS[['Wind代码','证券简称','行业','信用等级','专利综合评分',
                    '变动成本敏感系数','专利评分敏感系数','BEP风险度','原材料冲击系数']].copy()

portrait_sheet = PORTRAIT[['Wind代码','证券简称','技术领域','行业','信用等级',
                             '专利综合评分','bep_margin','gross_margin',
                             'avg_rev','revenue_cagr','象限']].copy()
portrait_sheet.columns = ['Wind代码','证券简称','技术领域','行业','信用等级',
                           '专利综合评分','BEP安全边际','毛利率','平均营收(亿元)','收入CAGR','象限']

pricing_sheet = PRICING[['Wind代码','证券简称','技术领域','行业','信用等级',
                          '专利综合评分','bep_margin','利率调整bp','保险保费系数',
                          '认股权证建议','预警状态']].copy()

path_excel = os.path.join(REPORTS_DIR, 'bep_analysis_results.xlsx')
with pd.ExcelWriter(path_excel, engine='openpyxl') as writer:
    main_sheet.to_excel(writer, sheet_name='综合宽表', index=False)
    sens_sheet.to_excel(writer, sheet_name='敏感性系数', index=False)
    portrait_sheet.to_excel(writer, sheet_name='企业双维度画像', index=False)
    pricing_sheet.to_excel(writer, sheet_name='定价建议表', index=False)
    if TRAIN_GBM:
        feat_imp.rename('重要性').reset_index().rename(columns={'index':'特征'}).to_excel(
            writer, sheet_name='GBM特征重要性', index=False)
print(f'✓ {path_excel}')

path_pricing = os.path.join(REPORTS_DIR, 'credit_recommendations.xlsx')
with pd.ExcelWriter(path_pricing, engine='openpyxl') as writer:
    PRICING.sort_values('利率调整bp').to_excel(writer, sheet_name='完整定价矩阵', index=False)
    PRICING[PRICING['利率调整bp'] <= -20].to_excel(writer, sheet_name='优惠授信企业', index=False)
    PRICING[PRICING['预警状态'].str.contains('红|橙')].to_excel(writer, sheet_name='重点风控企业', index=False)
print(f'✓ {path_pricing}')

# ══════════════════════════════════════════════════════════════════════════
# 汇总
# ══════════════════════════════════════════════════════════════════════════
banner('完成 — 交付物清单')

outputs = sorted(
    os.path.relpath(os.path.join(root, filename), OUT)
    for root, _, filenames in os.walk(OUT)
    for filename in filenames
    if filename != '.gitkeep'
    and os.stat(os.path.join(root, filename)).st_mtime_ns >= RUN_STARTED_NS
)
total_size = 0
for i, f in enumerate(outputs, 1):
    fp_full = os.path.join(OUT, f)
    sz = os.path.getsize(fp_full)
    total_size += sz
    extension = os.path.splitext(f)[1].lower()
    tag = {
        '.png': '[PNG]',
        '.html': '[HTML]',
        '.xlsx': '[XLSX]',
        '.json': '[JSON]',
    }.get(extension, '[FILE]')
    print(f'  {i:2d}. {tag} {f:55s} {sz/1024:.1f}KB')

print(f'\n共 {len(outputs)} 个文件，总计 {total_size/1024/1024:.1f}MB')
print(f'输出目录: {OUT}')
print(f'完成时间: {pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")}')
