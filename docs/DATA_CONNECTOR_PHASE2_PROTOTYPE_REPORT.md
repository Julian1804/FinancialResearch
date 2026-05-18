# Data Connector Phase 2 Prototype Report

## Scope

Small-sample connector prototype only. No full download, no paid/point data source, no OpenAI API, no parse_lab change, and no trusted-consumption integration.

## Run Summary

- connector count: 8
- success: 6
- failed: 2
- skipped: 0
- metadata DB: `D:\workspace\FinancialResearch\runtime\data_connector_phase2\connector_phase2_metadata.sqlite`

| Connector | Source | Status | Records | Quality | Trust status | Error |
|---|---|---:|---:|---|---|---|
| run_akshare_a_share_daily | akshare_traceable_official | failed | 0 | quality_failed | candidate_external_quality_failed | ProxyError: HTTPSConnectionPool(host='push2his.eastmoney.com', port=443): Max retries exceeded with url: /api/qt/stock/kline/get?fields1=f1%2Cf2%2Cf3%2Cf4%2Cf5%2Cf6&fields2=f51%2Cf52%2Cf53%2Cf54%2Cf55%2Cf56%2Cf57%2Cf58%2Cf59%2Cf60%2Cf61%2Cf116&ut=7eea3edcaed734bea9cbfc24409ed989&klt=101&fqt=0&secid=0.000001&beg=20260309&end=20260518 (Caused by ProxyError('Unable to connect to proxy', RemoteDisconnected('Remote end closed connection without response'))) |
| baostock_a_share_daily_sh600000 | baostock_daily | success | 30 | quality_passed | candidate_external_data |  |
| cninfo_financial_report_discovery_000001 | cninfo_disclosure | success | 2 | quality_warning | trusted_source_quality_warning_candidate |  |
| bls_cpi_public_api | bls_public_api | success | 24 | quality_warning | trusted_source_quality_warning_candidate |  |
| treasury_debt_to_penny | treasury_fiscaldata | success | 10 | quality_passed | trusted_by_real_external_candidate |  |
| sec_aapl_revenue_companyconcept | sec_edgar_companyfacts | success | 5 | quality_warning | trusted_source_quality_warning_candidate |  |
| world_bank_pink_sheet_monthly_sample | world_bank_pink_sheet | success | 36 | quality_warning | trusted_source_quality_warning_candidate |  |
| fred_dgs10_probe | fred_public_csv | failed | 0 | quality_failed | trusted_source_but_quality_failed | TimeoutError: The read operation timed out |

## Failed / Skipped

- run_akshare_a_share_daily: ProxyError: HTTPSConnectionPool(host='push2his.eastmoney.com', port=443): Max retries exceeded with url: /api/qt/stock/kline/get?fields1=f1%2Cf2%2Cf3%2Cf4%2Cf5%2Cf6&fields2=f51%2Cf52%2Cf53%2Cf54%2Cf55%2Cf56%2Cf57%2Cf58%2Cf59%2Cf60%2Cf61%2Cf116&ut=7eea3edcaed734bea9cbfc24409ed989&klt=101&fqt=0&secid=0.000001&beg=20260309&end=20260518 (Caused by ProxyError('Unable to connect to proxy', RemoteDisconnected('Remote end closed connection without response')))
- fred_dgs10_probe: TimeoutError: The read operation timed out

## Trust Distribution

```json
{
  "candidate_external_quality_failed": 1,
  "candidate_external_data": 1,
  "trusted_source_quality_warning_candidate": 4,
  "trusted_by_real_external_candidate": 1,
  "trusted_source_but_quality_failed": 1
}
```

## Outputs

- Connector run results: `D:\workspace\FinancialResearch\runtime\data_connector_phase2\connector_run_results.json`
- Quality check results: `D:\workspace\FinancialResearch\runtime\data_connector_phase2\quality_check_results.json`
- Trust resolution results: `D:\workspace\FinancialResearch\runtime\data_connector_phase2\trust_resolution_results.json`
- Storage estimate refresh: `D:\workspace\FinancialResearch\runtime\data_connector_phase2\storage_estimate_refresh.json`
