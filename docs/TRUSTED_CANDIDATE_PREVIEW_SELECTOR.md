# Trusted Candidate Preview Selector

The selector reads the controlled Baostock and AKShare Tencent normalized samples and emits only field-level trusted candidate OHLC rows.

Selection rule:

1. Match on `symbol + trade_date`.
2. Require exact match for `open`, `high`, `low`, and `close`.
3. Export only OHLC plus provenance and field trust metadata.
4. Exclude `amount`, `turnover_rate`, `pct_change`, and `preclose` from trusted candidate preview.
5. Keep formal trusted consumption off.

Output path: `runtime/field_level_trusted_preview/a_share_etf_ohlc_trusted_candidate_preview.jsonl`.
