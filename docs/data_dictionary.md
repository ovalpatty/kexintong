# Data dictionary

All public interfaces are UTF-8 CSV files. Monetary fields ending in `_cny_100m` are denominated in CNY 100 million. Percent fields ending in `_pct` use percentage points rather than decimals.

## `data/demo/companies.csv`

| Field | Meaning |
|---|---|
| `sample_order` | Stable display order within the five-company demo |
| `company_id` | Listed-company identifier used as the cross-table key |
| `company_name` | Company short name |
| `technology_field` | Technology-sector classification used by the scoring pipeline |

## `data/demo/financial_quarterly.csv`

| Field group | Meaning |
|---|---|
| `company_id`, `company_name` | Company identity |
| `reporting_period`, `fiscal_year`, `fiscal_quarter`, `period_end` | Reporting-period identity |
| `value_basis` | Accounting basis: `reported_cumulative_ytd` or `reported_single_quarter` |
| `revenue_cny_100m`, `operating_cost_cny_100m` | Revenue and operating cost |
| `selling_expense_cny_100m`, `management_expense_cny_100m`, `finance_expense_cny_100m`, `rd_expense_cny_100m` | Reported period expenses |
| `operating_cash_flow_cny_100m` | Net operating cash flow |

When `value_basis` is `reported_cumulative_ytd`, flow fields are differenced within each company and fiscal year before BEP analysis. Q1 is retained as the first-quarter flow.

## `data/demo/patent_records.csv`

| Field group | Meaning |
|---|---|
| `company_id`, `company_name`, `technology_field` | Company identity and classification |
| `patent_title`, `patent_abstract`, `abstract_available` | Patent text and abstract-availability marker |
| `assignee` | Recorded patent assignee |
| `application_number`, `grant_number` | Application and grant identifiers |
| `ipc_code` | IPC classification string; multiple codes may be delimited in one record |
| `patent_type` | Invention, utility-model, or design classification |
| `legal_status` | Legal status used by the active-patent filter |
| `publication_date` | Publication or grant announcement date |

## Reference assets

### `high_value_patent_corpus.csv`

Frozen text corpus used to fit the demo TF-IDF reference space. It contains record identity, company and assignee information, grant metadata, IPC classification, technology field, and patent text.

### `ipc_market_reference.csv`

Company-level IPC counts with fields `company_id`, `company_name`, `ipc_code`, and `patent_count`.

### `industry_bep_reference.csv`

Industry baseline table containing average revenue, operating cost, cost ratio, gross margin, and BEP revenue.

### `raw_material_price_index.csv`

Annual steel, copper, aluminium, and crude-oil reference series used in sensitivity scenarios.

## Validation resources

Machine-readable schemas are stored under `data/schema/`. Selection context, quality checks, and source notes are stored under `metadata/`. The schema files are authoritative for required fields and primitive data types.
