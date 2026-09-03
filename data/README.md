# Data contract

## Demo inputs

- `companies.csv`: company master and technology-field mapping.
- `patent_records.csv`: patent-level records for the same five companies.
- `financial_quarterly.csv`: reported financial statement observations for the same five companies.

## Reference inputs

- `high_value_patent_corpus.csv`: reference corpus for technology-field NLP benchmarks.
- `ipc_market_reference.csv`: broader-company IPC counts used as a market reference.
- `industry_bep_reference.csv`: four-year average industry financial and BEP statistics.
- `raw_material_price_index.csv`: annual steel, copper, aluminum, and crude-oil series.

## Join keys and units

- Company-level joins: `company_id`.
- Financial table key: `company_id + reporting_period`.
- Patent recommended key: `company_id + application_number`.
- Financial amount unit: CNY 100 million.
- Percent fields ending in `_pct` are expressed on a 0–100 scale.
- Dates use ISO `YYYY-MM-DD`.

## Missing text

The original company-level patent source uses `[数据未提供]` for abstracts and technology fields. This package converts unavailable abstracts to blank values and adds `abstract_available`. Technology fields are enriched from `companies.csv`.
