# Source provenance

| Output | Source workbook | Source sheet | Processing |
|---|---|---|---|
| `data/demo/companies.csv` | `50家A股上市公司综合数据_财务与专利_数据修复版.xlsx` | `1_公司清单` | Filtered to five selected company IDs; standardized headers. |
| `data/demo/patent_records.csv` | `50家A股上市公司专利数据_2021-2026_20260319.xlsx` | `专利数据` | Filtered to five company IDs; dates standardized; missing abstract placeholders converted to blank; technology field joined from company master. |
| `data/demo/financial_quarterly.csv` | `50家A股上市公司综合数据_财务与专利_数据修复版.xlsx` | `2_财务运营数据` | Filtered to five company IDs; reporting periods normalized; values otherwise preserved. |
| `data/reference/high_value_patent_corpus.csv` | `A股上市公司高价值专利清单_扩展版_2023-2025_含IPC分类号_20260319.xlsx` | `专利清单` | Full 198-row reference corpus; headers and dates standardized. |
| `data/reference/ipc_market_reference.csv` | `A股上市公司专利IPC分类数据_20260318.xlsx` | `IPC分类明细` | Full 1,593-row IPC reference; headers standardized. |
| `data/reference/industry_bep_reference.csv` | `16个行业宏观及行业基准数据_2021-2025.xlsx` | `行业BEP基准` | Removed title, blank, and explanatory rows; headers standardized. |
| `data/reference/raw_material_price_index.csv` | `16个行业宏观及行业基准数据_2021-2025.xlsx` | `原材料价格指数` | Retained five annual observations; removed explanatory rows. |
| `metadata/selection_metadata.csv` | `主数据集_BEP分析结果.xlsx` | `企业双维度画像` | Used only to document sample selection. |

Source files were supplied by the project owner. The package preserves source units and does not add externally researched observations.
