# A-Share / AKShare Data Source Strategy

Generated: 2026-05-23T10:05:16Z

FR evaluates data sources by interface, field, upstream provenance and stability. AKShare is a wrapper, not the only source and not a platform-level trust object.

## Daily Market Data

- Tencent `stock_zh_a_hist_tx`: primary A-share daily market candidate.
- BaoStock: stable supplement, validation partner and historical source where available.
- Eastmoney `stock_zh_a_hist`: unstable for primary use; fallback/deferred with monitoring.

Tencent raw fields are `date`, `open`, `close`, `high`, `low`, `amount`. Stock code, exchange, source, upstream and adjustment type are supplemented from request context. Price change, pct change and amplitude can be derived only with `derivation_method` and `previous_close_source`.

Turnover amount and turnover rate must not be hard-calculated as consumption-grade fields.
