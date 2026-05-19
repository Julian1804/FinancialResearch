# Analysis Packet Data Contract

## Required Packet Fields

- `packet_id`
- `data_snapshot_id`
- `target_symbol`
- `market`
- `as_of_date`
- `analysis_scope`
- `data_layer_legend`
- `source_layers`
- `market_daily_summary`
- `macro_summary`
- `commodity_summary`
- `financial_report_metadata`
- `previous_reports_and_forecasts`
- `candidate_notes`
- `insufficient_evidence`
- `guardrails`

## Source Layer Fields

Every source layer item must preserve:

- `source_id`
- `source_name`
- `source_type`
- `quality_status`
- `trust_status`
- `staging_status`
- `retrieved_at`
- `raw_reference`
- `normalized_reference`
- `limitation_note`

## Trust Boundary

`trusted_by_real_external_candidate`, `market_daily_candidate_staging`, and `cross_validated_candidate` are not formal trusted facts. Formal trusted consumption remains unchanged in this phase.
