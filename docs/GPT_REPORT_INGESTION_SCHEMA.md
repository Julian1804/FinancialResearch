# GPT Report Ingestion Schema

## Raw Input

The user pastes the complete GPT Web report into FR. FR preserves:

- `raw_report_text`
- `packet_id`
- `data_snapshot_id`
- `created_at`
- `report_version`

## FINAL_REPORT_JSON

The pasted report must include a fenced JSON block after `FINAL_REPORT_JSON` with:

- `report_title`
- `as_of_date`
- `summary`
- `assumptions`
- `forecasts`
- `risks`
- `watchlist_signals`
- `confidence`
- `next_review_date`
- `insufficient_evidence`

## Forecast / Backtest Fields

Each forecast item stores:

- `forecast_item`
- `target_metric`
- `forecast_horizon`
- `expected_direction`
- `expected_range`
- `confidence`
- `thesis`
- `risk_trigger`
- `review_date`
- `actual_value_later`
- `backtest_result`
- `revision_note`
