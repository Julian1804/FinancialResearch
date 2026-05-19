# Eastmoney Direct Connector Fallback Report

## Scope

Small-sample A-share daily connector fallback only. No full download, no OpenAI API, no parse_lab change, and no formal trusted-consumption integration.

## Eastmoney Direct Connector

| Symbol | Status | Records | HTTP | Failure mode | Raw output |
|---|---:|---:|---|---|---|
| 600519 | failed | 0 |  | RuntimeError: curl: (56) schannel: server closed abruptly (missing close_notify)
 | Z:\data_lake_master\raw\api_responses\eastmoney_direct\20260519\eastmoney_push2his_600519_daily_30d_failure.json |
| 000001 | failed | 0 |  | RuntimeError: curl: (56) schannel: server closed abruptly (missing close_notify)
 | Z:\data_lake_master\raw\api_responses\eastmoney_direct\20260519\eastmoney_push2his_000001_daily_30d_failure.json |
| 300750 | failed | 0 |  | RuntimeError: curl: (56) schannel: server closed abruptly (missing close_notify)
 | Z:\data_lake_master\raw\api_responses\eastmoney_direct\20260519\eastmoney_push2his_300750_daily_30d_failure.json |

- total normalized records: 0
- normalized output: `Z:\data_lake_master\structured\market_data\a_share_daily\eastmoney_direct_daily_30d_sample.jsonl`
- runtime mirror: `D:\workspace\FinancialResearch\runtime\data_connector_phase4\eastmoney_direct_normalized_sample.jsonl`

## Kline Field Order

The connector requests `fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61` and parses:

1. f51 trade_date
2. f52 open
3. f53 close
4. f54 high
5. f55 low
6. f56 volume, original unit lots where 1 lot = 100 shares
7. f57 amount, CNY/yuan
8. f58 amplitude percent
9. f59 pct_change percent
10. f60 change_amount
11. f61 turnover_rate percent

## Baostock vs Eastmoney Validation

```json
{
  "missing_in_source": 90
}
```

- staging status: review_candidate
- unit note: Eastmoney f56 volume is lots; connector normalizes to shares by multiplying by 100 before comparison. Amount is treated as CNY/yuan in both sources.

## AKShare Final Status

- status: optional_retry_source
- role: non_blocking_optional_retry
- reason: Manual network diagnosis confirmed Eastmoney DIRECT routing but upstream still returns empty/remote-disconnected responses; AKShare depends on Eastmoney upstream and is not suitable as the sole A-share daily path.

## Trust Status

- Baostock: candidate_external_data / operational_fallback
- Eastmoney direct: candidate_external_data / secondary_validation_source
- AKShare: optional_retry_source
- Cross-validated data: consumption_grade_staging_candidate only, not formal trusted consumption
