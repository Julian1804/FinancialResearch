# Backtest Execution v1 Report

Generated: 2026-05-20T03:10:49Z

## Result Counts

```json
{
  "manual_review_required": 3
}
```

Backtest execution uses existing candidate/staging market data only. GPT-generated forecasts remain interpretation records and are not trusted facts.

## v1.1 Testable Forecast Support

`run-backtest --only-testable` filters to forecasts that carry a testable contract (`price_direction`, `price_range`, `volume_direction`, or `metric_direction`) and writes non-destructive outputs:

- `runtime/backtest_execution_v1/backtest_results_testable_only.json`
- `runtime/backtest_execution_v1/report_backtest_summary_testable_only.json`

Non-testable forecasts such as `qualitative` and `insufficient_evidence` remain in manual review.
