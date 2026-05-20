# Macro Asset Data Schema

Macro schema fields:

- dataset_id, source_id, provider_name, series_id, metric_name, country, frequency
- data_period_start, data_period_end, observation_date
- publish_date, publish_date_source
- value, unit, seasonal_adjustment
- vintage_date, revision_status
- retrieved_at, raw_path, checksum, quality_status, trust_status, candidate_only

Asset/commodity schema fields:

- dataset_id, source_id, provider_name, asset_class, commodity_group, instrument_name, metric_name, frequency
- data_period_start, data_period_end, observation_date
- publish_date, publish_date_source
- price, value, unit, currency
- vintage_date, revision_status
- retrieved_at, raw_path, checksum, quality_status, trust_status, candidate_only

No publish_date is fabricated. If no official release date is available, `publish_date=null` and `publish_date_source=unavailable`.
