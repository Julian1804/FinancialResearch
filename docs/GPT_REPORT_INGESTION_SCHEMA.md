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

- `packet_id`
- `data_snapshot_id`
- `target_symbol`
- `as_of_date`
- `analysis_scope`
- `key_assumptions`
- `investment_view`
- `forecast_items`
- `risk_items`
- `watchlist_signals`
- `confidence`
- `next_review_date`
- `insufficient_evidence_items`
- `candidate_data_usage_note`

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

## Candidate Data Rule

Reports must not treat candidate/staging data as trusted final facts. Any use of candidate data must be explained in `candidate_data_usage_note`.
