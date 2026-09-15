# Methodology scope

## Two explicit modes

`demo` and `research` describe different analytical purposes. The selected mode controls whether a model is trained; sample size never changes the mode automatically.

### Demo

- Dataset: bundled five-company public sample.
- Normalization scope: the current five-company demo universe.
- BEP measure: analytical BEP safety margin.
- Machine learning: disabled unconditionally.
- Intended use: deterministic workflow and data-interface reproduction.

### Research

- Dataset: prepared private full research sample.
- Normalization scope: the research universe.
- Machine learning: Gradient Boosting (GBM) enabled explicitly.
- Intended use: model training, cross-validation, evaluation, and feature analysis.

## Financial value basis

The authoritative column is `value_basis`.

- `reported_cumulative_ytd`: flow columns are differenced within each company and fiscal year; Q1 is retained as the first-quarter flow.
- `reported_single_quarter`: values are retained as reported.
- Missing, incomplete, mixed, or unsupported metadata: the compatibility heuristic is used and the fallback is logged.

The heuristic is not the primary accounting rule.

## Patent scoring

The authoritative six-factor weights are stored once in `src/patent_scoring/config.py`. The configuration validates at import time that they sum to one. CAGR clipping boundaries are also configured there because they alter the scoring methodology.

## Output semantics

Public-demo workbooks expose the analytical BEP measure only. Research workbooks additionally expose `BEP安全边际(GBM预测)`. The demo does not create empty model columns, model sheets, feature-importance placeholders, R² values, or model files.

Every completed run writes `run_metadata.json`, including the selected mode, dataset label, normalization scope, score version, model-training flag, and generated file list. A completed demo run also exports `public/company_assessments.json` under its output directory; this file contains derived company-level assessments only and is intended for the separate public website.
