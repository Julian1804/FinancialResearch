# Data Storage Architecture

## Layers

1. Raw layer: PDF originals, raw API responses, raw CSV/XLSX, source URL, retrieved_at, checksum.
2. Classification layer: source type, provider type, official source, data category, frequency.
3. Normalized layer: date, symbol, metric_name, value, unit, currency, source_id, as_of_date, data_frequency.
4. Quality layer: numeric/date/null/duplicate/unit/range/continuity/field mapping checks.
5. Trust layer: trusted_by_official_source, trusted_by_real_external, candidate_only, needs_review, trusted_source_but_quality_failed.
6. Consumption layer: dashboard_eligible, gpt_packet_eligible, backtest_eligible.

## Storage Recommendation

- DuckDB + Parquet: primary analytics and time-series store.
- SQLite: small metadata registry, ingestion status, report index.
- JSONL: append-only audit/event logs.
- NAS cold storage: PDFs, raw API response snapshots, parser raw output archives.

## Capacity Estimate

```json
{
  "a_share_daily_10y": {
    "rows": "about 12-16 million rows for all A-share symbols",
    "parquet_gb": "2-8 GB depending on fields/compression",
    "sqlite_duckdb_gb": "5-20 GB with indexes"
  },
  "macro_30y": {
    "rows": "usually below a few million rows for selected series",
    "parquet_gb": "<1 GB for curated series"
  },
  "asset_class_30y": {
    "rows": "daily/monthly selected commodities/rates/FX/indexes",
    "parquet_gb": "1-5 GB for curated coverage"
  },
  "financial_report_pdfs": {
    "a_share_10y": "hundreds of GB if all PDFs are retained",
    "targeted_company_set": "tens of GB"
  },
  "parser_raw_output": {
    "html_json_images_tables": "can exceed PDF size; keep hot subset and archive cold outputs"
  }
}
```

2TB desktop hot storage is enough for curated equities, macro, commodity, active report sets, and active parser outputs. 8TB NAS cold storage is enough for broader PDF/archive retention if deduplicated and compressed.
