# Forecast Contract v2

Forecast categories:

- `price_direction`
- `price_range`
- `volume_direction`
- `metric_direction`
- `risk_trigger`
- `qualitative`
- `insufficient_evidence`

Every forecast item must include `forecast_type`, `target_metric`, `forecast_horizon`, `review_date`, `expected_direction`, `expected_range`, `expected_value`, `confidence`, `thesis`, `supporting_evidence`, `key_assumptions`, `invalidation_triggers`, `data_dependency`, and `testability_status`.

`testability_status` values:

- `testable`
- `manual_review_required`
- `insufficient_evidence`
- `not_backtestable`

GPT/manual forecasts remain interpretation records and never become trusted facts.
