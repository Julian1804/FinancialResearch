# Field-Level Trust Contract

Generated: 2026-05-21T08:24:07Z

This contract keeps trust scoped to dataset, field, source, entity, and time window. It does not open formal trusted consumption.

- Dataset: `a_share_etf_daily_baostock_akshare_tencent_v4`
- Trusted candidate preview fields: `open, high, low, close`
- Limited fields: `amount, turnover_rate, pct_change, preclose`
- Preview records: `1216`
- Formal trusted consumption: `false`

The full daily table is not trusted as a whole. Only OHLC fields that exact-match across Baostock and AKShare Tencent are consumable in preview.
