# Analysis Packet Schema

## Required Fields

- `packet_id`
- `data_snapshot_id`
- `company`
- `ticker`
- `as_of_date`
- `analysis_scope`
- `selected_financial_reports`
- `trusted_facts`
- `candidate_facts_summary`
- `price_data_placeholder`
- `macro_data_placeholder`
- `asset_class_data_placeholder`
- `sentiment_management_commentary_placeholder`
- `previous_reports_forecasts`
- `insufficient_trusted_evidence`

## Trusted Fact Requirements

Each trusted fact must include source provenance:

- `fact_id`
- `canonical_field` or `field_name`
- `value`
- `unit`
- `currency`
- `period`
- `source_id`
- `source_url`
- `retrieved_at`
- `trust_status`
- `quality_status`
- `provenance`

Only facts that have passed trust resolution and data quality checks can enter `trusted_facts`.
