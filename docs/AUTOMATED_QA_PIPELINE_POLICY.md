# Automated QA Pipeline Policy

Generated: 2026-05-21T07:18:45Z

QA is an automated format, logic, and anomaly detection layer. It keeps raw and normalized values, marks review flags, and does not silently delete anomalies.

Checks:
- required_fields_present
- date_parseable
- numeric_fields_parseable
- unit_currency_present_or_warning
- duplicate_entity_date_source
- non_negative_price_volume_aum_nav
- ohlc_rule_check
- pct_change_reasonable_range
- source_identifier_present
- entity_mapping_attempted
- revision_vintage_or_retrieval_snapshot_present
- license_storage_boundary_classified
