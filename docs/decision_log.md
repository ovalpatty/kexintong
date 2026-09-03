# Decision log

## Public v1 decisions

1. The public repository provides a five-company reproducibility demo of the broader Kexintong technology-credit assessment framework.
2. Demo and research execution are selected explicitly by separate entry points.
3. Demo mode never trains GBM, regardless of sample size.
4. `GradientBoostingRegressor` is identified consistently as GBM.
5. Six-factor weights use a single configuration source.
6. Explicit `value_basis` metadata takes precedence over heuristic inference.
7. Demo and research outputs use separate directories and schemas.
8. Historical full-sample outputs and machine-specific paths are not public-demo artifacts.
