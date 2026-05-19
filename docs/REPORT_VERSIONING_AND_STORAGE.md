# Report Versioning and Storage

Rules:

1. First report for a packet is `v1`.
2. Re-ingesting the same `packet_id` creates `v2`, `v3`, and so on.
3. Existing reports are never overwritten.
4. `report_version_history.json` tracks report lineage.

Per-version files:

- `raw_report.md`
- `structured_report.json`
- `report_manifest.json`
- `forecast_items.json`
- `risk_items.json`
- `watchlist_signals.json`
- `insufficient_evidence_items.json`

Reports are stored locally under `runtime/analysis_reports` and copied to `Z:\data_lake_master\exports\analysis_reports`.
