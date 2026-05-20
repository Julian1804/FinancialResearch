# Market Data Foundation Phase 2 Report

Generated: 2026-05-20T08:31:49Z

Phase 2 is catalog-driven. It reused existing Phase 1 historical macro/asset datasets,
ingested additional official FRED series where the catalog had a safe connector path,
and left unsupported China/Japan/Euro/UK/futures sources as explicit missing or
future_connector items.

## Scope

- Catalog items updated: 48
- Dashboard-ready items: 24
- Records loaded across updated catalog: 141719
- Phase 2 fresh successful datasets: 24
- Deferred / future connector items in this run: 15

## Successful Phase 2 Ingestion

[
  {
    "domain": "macro",
    "metric_id": "us_cpi",
    "source_id": "fred_public_api",
    "records_normalized": 951,
    "qa_status": "quality_passed"
  },
  {
    "domain": "macro",
    "metric_id": "us_ppi",
    "source_id": "fred_public_api",
    "records_normalized": 1360,
    "qa_status": "quality_passed"
  },
  {
    "domain": "macro",
    "metric_id": "us_unemployment_rate",
    "source_id": "fred_public_api",
    "records_normalized": 939,
    "qa_status": "quality_passed"
  },
  {
    "domain": "macro",
    "metric_id": "us_nonfarm_payrolls",
    "source_id": "fred_public_api",
    "records_normalized": 1048,
    "qa_status": "quality_passed"
  },
  {
    "domain": "macro",
    "metric_id": "fed_funds_effective",
    "source_id": "fred_public_api",
    "records_normalized": 26255,
    "qa_status": "quality_passed"
  },
  {
    "domain": "rates_bonds",
    "metric_id": "us_2y_yield",
    "source_id": "fred_public_api",
    "records_normalized": 12487,
    "qa_status": "quality_passed"
  },
  {
    "domain": "rates_bonds",
    "metric_id": "us_10y_yield",
    "source_id": "fred_public_api",
    "records_normalized": 16079,
    "qa_status": "quality_passed"
  },
  {
    "domain": "rates_bonds",
    "metric_id": "us_30y_yield",
    "source_id": "fred_public_api",
    "records_normalized": 12309,
    "qa_status": "quality_passed"
  },
  {
    "domain": "rates_bonds",
    "metric_id": "sofr",
    "source_id": "fred_public_api",
    "records_normalized": 2029,
    "qa_status": "quality_passed"
  },
  {
    "domain": "fx",
    "metric_id": "trade_weighted_usd",
    "source_id": "fred_public_api",
    "records_normalized": 5107,
    "qa_status": "quality_passed"
  },
  {
    "domain": "fx",
    "metric_id": "usd_cny",
    "source_id": "fred_public_api",
    "records_normalized": 11325,
    "qa_status": "quality_passed"
  },
  {
    "domain": "fx",
    "metric_id": "usd_jpy",
    "source_id": "fred_public_api",
    "records_normalized": 13879,
    "qa_status": "quality_passed"
  },
  {
    "domain": "fx",
    "metric_id": "eur_usd",
    "source_id": "fred_public_api",
    "records_normalized": 6864,
    "qa_status": "quality_passed"
  },
  {
    "domain": "fx",
    "metric_id": "gbp_usd",
    "source_id": "fred_public_api",
    "records_normalized": 13885,
    "qa_status": "quality_passed"
  },
  {
    "domain": "commodity",
    "metric_id": "gold_benchmark",
    "source_id": "world_bank_pink_sheet",
    "records_normalized": 796,
    "qa_status": "quality_passed"
  },
  {
    "domain": "commodity",
    "metric_id": "silver_benchmark",
    "source_id": "world_bank_pink_sheet",
    "records_normalized": 796,
    "qa_status": "quality_passed"
  },
  {
    "domain": "commodity",
    "metric_id": "wti_oil",
    "source_id": "fred_public_api",
    "records_normalized": 10158,
    "qa_status": "quality_passed"
  },
  {
    "domain": "commodity",
    "metric_id": "brent_oil",
    "source_id": "world_bank_pink_sheet",
    "records_normalized": 796,
    "qa_status": "quality_passed"
  },
  {
    "domain": "commodity",
    "metric_id": "copper_benchmark",
    "source_id": "world_bank_pink_sheet",
    "records_normalized": 796,
    "qa_status": "quality_passed"
  },
  {
    "domain": "commodity",
    "metric_id": "aluminum_benchmark",
    "source_id": "world_bank_pink_sheet",
    "records_normalized": 796,
    "qa_status": "quality_passed"
  },
  {
    "domain": "commodity",
    "metric_id": "iron_ore_benchmark",
    "source_id": "world_bank_pink_sheet",
    "records_normalized": 796,
    "qa_status": "quality_passed"
  },
  {
    "domain": "commodity",
    "metric_id": "soybeans_benchmark",
    "source_id": "world_bank_pink_sheet",
    "records_normalized": 796,
    "qa_status": "quality_passed"
  },
  {
    "domain": "commodity",
    "metric_id": "wheat_benchmark",
    "source_id": "world_bank_pink_sheet",
    "records_normalized": 796,
    "qa_status": "quality_passed"
  },
  {
    "domain": "commodity",
    "metric_id": "coal_benchmark",
    "source_id": "world_bank_pink_sheet",
    "records_normalized": 676,
    "qa_status": "quality_passed"
  }
]

## Deferred / Missing

[
  {
    "domain": "macro",
    "metric_id": "china_cpi",
    "error_message": "official China source feasibility required for NBS official; non-official scraping not used"
  },
  {
    "domain": "macro",
    "metric_id": "china_ppi",
    "error_message": "official China source feasibility required for NBS official; non-official scraping not used"
  },
  {
    "domain": "macro",
    "metric_id": "china_money_supply",
    "error_message": "official China source feasibility required for PBOC official; non-official scraping not used"
  },
  {
    "domain": "macro",
    "metric_id": "china_fx_reserves",
    "error_message": "official China source feasibility required for SAFE/PBOC official; non-official scraping not used"
  },
  {
    "domain": "rates_bonds",
    "metric_id": "china_1y_gov_yield",
    "error_message": "official China source feasibility required for ChinaBond/CFETS; non-official scraping not used"
  },
  {
    "domain": "rates_bonds",
    "metric_id": "china_10y_gov_yield",
    "error_message": "official China source feasibility required for ChinaBond/CFETS; non-official scraping not used"
  },
  {
    "domain": "rates_bonds",
    "metric_id": "shibor",
    "error_message": "official interbank source feasibility required for SHIBOR official; not mixed with Treasury/FRED data"
  },
  {
    "domain": "rates_bonds",
    "metric_id": "dr007",
    "error_message": "official interbank source feasibility required for CFETS/PBOC; not mixed with Treasury/FRED data"
  },
  {
    "domain": "futures",
    "metric_id": "comex_gold_futures",
    "error_message": "futures schema ready, but CME DataMine/authorized requires source-specific connector and authorization/terms review before ingestion"
  },
  {
    "domain": "futures",
    "metric_id": "nymex_wti_futures",
    "error_message": "futures schema ready, but CME DataMine/authorized requires source-specific connector and authorization/terms review before ingestion"
  },
  {
    "domain": "futures",
    "metric_id": "lme_copper",
    "error_message": "futures schema ready, but LME licensed requires source-specific connector and authorization/terms review before ingestion"
  },
  {
    "domain": "futures",
    "metric_id": "shfe_copper",
    "error_message": "futures schema ready, but SHFE official requires source-specific connector and authorization/terms review before ingestion"
  },
  {
    "domain": "futures",
    "metric_id": "ine_crude",
    "error_message": "futures schema ready, but INE official requires source-specific connector and authorization/terms review before ingestion"
  },
  {
    "domain": "futures",
    "metric_id": "dce_iron_ore",
    "error_message": "futures schema ready, but DCE official requires source-specific connector and authorization/terms review before ingestion"
  },
  {
    "domain": "futures",
    "metric_id": "czce_agri",
    "error_message": "futures schema ready, but CZCE official requires source-specific connector and authorization/terms review before ingestion"
  }
]

## QA

```json
{
  "quality_passed": 6
}
```

## Revision / Vintage

- revision_count: 0
- FRED realtime fields are preserved when present.
- Sources without release/vintage data are marked `vintage_support_limited`.
- `publish_date` is not fabricated from observation_date.

## Output Paths

```json
{
  "run_records": "D:\\workspace\\FinancialResearch\\runtime\\market_data_foundation_phase2\\phase2_run_records.json",
  "raw_artifact_index": "D:\\workspace\\FinancialResearch\\runtime\\market_data_foundation_phase2\\raw_artifact_index.json",
  "normalized_records": "D:\\workspace\\FinancialResearch\\runtime\\market_data_foundation_phase2\\normalized_phase2_records.jsonl",
  "normalized_paths": "D:\\workspace\\FinancialResearch\\runtime\\market_data_foundation_phase2\\normalized_paths.json",
  "quality_results": "D:\\workspace\\FinancialResearch\\runtime\\market_data_foundation_phase2\\quality_results.json",
  "revision_log": "D:\\workspace\\FinancialResearch\\runtime\\market_data_foundation_phase2\\revision_log.json",
  "vintage_summary": "D:\\workspace\\FinancialResearch\\runtime\\market_data_foundation_phase2\\vintage_summary.json",
  "foundation_catalog_update": "D:\\workspace\\FinancialResearch\\runtime\\market_data_foundation_phase2\\foundation_catalog_update.json",
  "source_availability_audit": "D:\\workspace\\FinancialResearch\\runtime\\market_data_foundation_phase2\\source_availability_audit.json",
  "dashboard_market_data_summary": "D:\\workspace\\FinancialResearch\\runtime\\market_data_foundation_phase2\\dashboard_market_data_summary.json",
  "metadata_db": "D:\\workspace\\FinancialResearch\\runtime\\market_data_foundation_phase2\\market_data_foundation_metadata.sqlite"
}
```

All outputs remain candidate/staging evidence. Formal trusted consumption was not modified.
No OpenAI API was called.
