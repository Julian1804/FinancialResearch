# A-share Daily Multi-source Schema

## Normalized Schema

- `trade_date`
- `symbol`
- `market`
- `open`
- `high`
- `low`
- `close`
- `preclose`
- `volume`
- `amount`
- `turnover_rate`
- `pct_change`
- `trade_status`
- `adjust_flag`
- `is_st`
- `source_id`
- `retrieved_at`
- `raw_checksum`
- `volume_unit`
- `amount_unit`

## Unit Notes

- Baostock volume is normalized as shares.
- Baostock amount is normalized as CNY.
- AKShare Tencent exposes OHLC and an `amount` field in the returned dataframe; in the tested data this field matches Baostock volume after multiplying by 100, so this pipeline treats it as source volume in lots and normalizes it to shares.
- AKShare Tencent volume differences within one lot (100 shares) are treated as `unit_normalized_match` because the source lot value can be rounded.
- AKShare Tencent does not provide transaction amount/CNY, turnover rate, trade status, or ST flag through this tested interface.

## Trust Rule

Baostock and AKShare Tencent are candidate external data. Cross-source agreement can become `cross_validated_candidate` in staging, not formal trusted consumption.
