# External Data Quality and Trust Gate

## Quality Checks

Common:

- numeric_format_ok
- date_format_ok
- missing_value_check
- duplicate_check
- source_id_present
- retrieved_at_present
- checksum_present
- field_mapping_ok

Time series:

- date_order_ok
- duplicate_date_check
- frequency_consistency_check
- suspicious_gap_check

Financial:

- price_non_negative
- volume_non_negative
- rate_reasonable_range
- currency_present_if_required
- unit_present_if_required

## Trust Rules

- Official / regulator / exchange / official public APIs with quality passed: `trusted_by_real_external_candidate`.
- AKShare / Baostock: `candidate_external_data` unless a specific dataset has documented official upstream provenance.
- Non-official crawler/web data: candidate only.
- Trusted source with failed quality: `trusted_source_but_quality_failed`.

Phase 2 does not make data consumption-grade. All outputs remain outside the formal trusted consumption layer.
