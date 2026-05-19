# Forecast Backtest Schema v1

Each forecast item includes:

- `forecast_id`
- `report_id`
- `packet_id`
- `target_symbol`
- `as_of_date`
- `forecast_horizon`
- `target_metric`
- `expected_direction`
- `expected_range_low`
- `expected_range_high`
- `expected_value`
- `confidence`
- `thesis`
- `supporting_evidence`
- `key_assumptions`
- `risk_triggers`
- `review_date`
- `actual_value_later`
- `backtest_status`
- `backtest_result`
- `revision_note`

Statuses:

- `pending_review`
- `ready_for_backtest`
- `backtested_hit`
- `backtested_miss`
- `inconclusive`
- `revised`

Phase v1 only prepares the queue and attaches actual values when existing A-share daily data is available.
