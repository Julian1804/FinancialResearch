# A-share Daily Multi-source Pipeline Report

## Scope

Small-sample A-share daily multi-source candidate pipeline. No full download, no OpenAI API, no parse_lab change, and no formal trusted consumption change.

## Source Results

- Baostock: success, records: 90
- AKShare Tencent: success, records: 90

## Field Coverage

| Field | Baostock | AKShare Tencent |
|---|---|---|
| open | available | available |
| high | available | available |
| low | available | available |
| close | available | available |
| preclose | available | available |
| volume | available | unit_difference |
| amount | available | source_not_supported |
| turnover_rate | available | source_not_supported |
| pct_change | available | available |
| trade_status | available | source_not_supported |
| adjust_flag | available | missing |
| is_st | available | source_not_supported |

Conclusion: Baostock has fuller market daily metadata. AKShare Tencent covers OHLC and amount, with preclose/pct_change derivable, but lacks volume/turnover/trade status/ST flags.

## Cross-source Validation

```json
{
  "numeric_tolerance_match": 89,
  "mismatch": 1
}
```

Unit note: Baostock volume is shares. AKShare Tencent dataframe column named amount behaves like volume in lots; this pipeline normalizes it to shares by multiplying by 100. Differences within one lot (100 shares) are treated as unit_normalized_match because Tencent lot values are rounded. AKShare Tencent does not provide transaction amount/CNY in this tested interface.

## Quality Gate

```json
{
  "quality_passed": 2,
  "quality_failed": 0
}
```

## Consumption Staging

```json
{
  "market_daily_candidate_staging": 1,
  "market_daily_secondary_candidate_staging": 1,
  "needs_review_candidate": 1
}
```

All staging outputs remain candidate-only and do not enter formal trusted consumption.

## Source Status

| Source | Status | Role | Reason |
|---|---|---|---|
| baostock_daily | operational_source | primary_fallback |  |
| akshare_tencent_daily | secondary_candidate_source | useful_for_cross_validation |  |
| akshare_eastmoney_stock_zh_a_hist | deferred_optional_source |  | Eastmoney push2his upstream/TLS instability |
| eastmoney_direct | deferred_secondary_validation_source |  | schannel / remote disconnect instability |
