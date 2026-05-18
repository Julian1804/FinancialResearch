# Data Connector Phase 3 Curated Pipeline Report

## Scope

Phase 3 adds quality remediation, a curated source registry, a watchlist-driven incremental connector prototype, and consumption-grade staging. It does not perform full downloads and does not connect staged data to the formal trusted consumption layer.

## Quality Remediation

| Source | Before | After | Action | Owner | Reason |
|---|---|---|---|---|---|
| akshare_traceable_official | quality_failed | quality_failed | defer_source | upstream_or_network | Eastmoney upstream/proxy disconnect remains a source availability issue; do not force pass |
| baostock_daily | quality_passed | quality_passed | unchanged | none | quality gate already passed or failure is not safely remediable |
| cninfo_disclosure | quality_warning | quality_passed | remediated_quality_gate_rule | quality_gate_over_strict | multiple reports can share the same announcement date; uniqueness is report_title + download_url, not date alone |
| bls_public_api | quality_warning | quality_passed | remediated_normalization_contract | normalization_contract | BLS CPI normalized records carry value/unit/date; missing_value warning came from a generic gate that did not treat CPI index records as complete macro observations |
| treasury_fiscaldata | quality_passed | quality_passed | unchanged | none | quality gate already passed or failure is not safely remediable |
| sec_edgar_companyfacts | quality_warning | quality_passed | remediated_quality_gate_rule | quality_gate_over_strict | SEC companyconcept can contain multiple frames or forms with the same end date; uniqueness is date + fiscal_year + form + metric_name |
| world_bank_pink_sheet | quality_warning | quality_passed | remediated_quality_gate_rule | quality_gate_over_strict | World Bank commodity sample is a multi-metric panel; duplicate dates and global date order must be evaluated per metric_name |
| fred_public_csv | quality_failed | quality_failed | defer_source | network_timeout | FRED public CSV timed out; retry/defer without blocking curated pipeline |

Before status counts:

```json
{
  "quality_failed": 2,
  "quality_passed": 2,
  "quality_warning": 4
}
```

After status counts:

```json
{
  "quality_failed": 2,
  "quality_passed": 6
}
```

## Incremental Pipeline

| Connector | Source | Status | Records | Quality | Trust | Error |
|---|---|---:|---:|---|---|---|
| baostock_watchlist_daily_30d | baostock_daily | success | 90 | quality_passed | candidate_external_data |  |
| cninfo_financial_report_discovery_000001 | cninfo_disclosure | success | 2 | quality_passed | trusted_by_official_source_candidate |  |
| bls_cpi_public_api | bls_public_api | success | 24 | quality_passed | trusted_by_real_external_candidate |  |
| treasury_debt_to_penny | treasury_fiscaldata | success | 10 | quality_passed | trusted_by_real_external_candidate |  |
| sec_aapl_revenue_companyconcept | sec_edgar_companyfacts | success | 5 | quality_passed | trusted_by_real_external_candidate |  |
| world_bank_pink_sheet_monthly_sample | world_bank_pink_sheet | success | 36 | quality_passed | trusted_by_real_external_candidate |  |
| fred_dgs10_probe | fred_public_csv | failed | 0 | quality_failed | trusted_source_but_quality_failed | TimeoutError: The read operation timed out |
| run_akshare_a_share_daily | akshare_traceable_official | failed | 0 | quality_failed | candidate_external_quality_failed | ProxyError: HTTPSConnectionPool(host='push2his.eastmoney.com', port=443): Max retries exceeded with url: /api/qt/stock/kline/get?fields1=f1%2Cf2%2Cf3%2Cf4%2Cf5%2Cf6&fields2=f51%2Cf52%2Cf53%2Cf54%2Cf55%2Cf56%2Cf57%2Cf58%2Cf59%2Cf60%2Cf61%2Cf116&ut=7eea3edcaed734bea9cbfc24409ed989&klt=101&fqt=0&secid=0.000001&beg=20260309&end=20260518 (Caused by ProxyError('Unable to connect to proxy', RemoteDisconnected('Remote end closed connection without response'))) |

Status counts:

```json
{
  "success": 6,
  "failed": 2
}
```

Quality counts:

```json
{
  "quality_passed": 6,
  "quality_failed": 2
}
```

## Consumption-grade Staging

- consumption-grade candidates: 5
- review candidates: 1
- deferred: 2

Only official/authoritative sources with `quality_passed` can enter `consumption_grade_candidate`. `quality_warning` and `quality_failed` are excluded.

## Outputs

- Curated source registry: `D:\workspace\FinancialResearch\runtime\data_connector_phase3\curated_source_registry.json`
- Quality remediation: `D:\workspace\FinancialResearch\runtime\data_connector_phase3\quality_remediation_results.json`
- Incremental pipeline: `D:\workspace\FinancialResearch\runtime\data_connector_phase3\incremental_pipeline_run_results.json`
- Consumption-grade staging: `D:\workspace\FinancialResearch\runtime\data_connector_phase3\consumption_grade_staging.json`
- Storage estimate refresh: `D:\workspace\FinancialResearch\runtime\data_connector_phase3\storage_estimate_refresh.json`
