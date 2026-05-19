# FRDataConnectors Phase 6 Runtime Report

Generated: 2026-05-19T13:28:16Z

## Scope

Phase 6 creates a unified connector runtime for candidate/staging data. It does not call OpenAI, does not modify parse_lab, and does not connect any output to formal trusted consumption.

## Connector Runs

- Unified run count: 9
- Success: 7
- Failed: 1
- Candidate-only: true

## A-share Controlled Expansion

- Symbols: 600519, 000001, 300750, 601318, 600036, 000858, 002594, 600276, 601899, 300760
- Window: recent 30 trading days
- Baostock role: operational source / primary fallback
- AKShare Tencent role: secondary candidate source
- Eastmoney push2his and AKShare Eastmoney-backed route: deferred

## Mismatch Review

```json
{
  "mismatch_count": 1,
  "primary_cause": "derived pct_change rounding/formula difference",
  "manual_value_edit_performed": false
}
```

## Incremental Update

```json
{
  "success": 7,
  "failed": 1
}
```

## Staging v2

```json
{
  "market_daily_candidate_staging": 1,
  "market_daily_secondary_candidate_staging": 1,
  "consumption_grade_candidate": 5,
  "blocked": 1,
  "not_used_in_current_pipeline": 1,
  "cross_validated_candidate": 1,
  "needs_review_candidate": 1
}
```

All staging records remain candidate-only and are not formal trusted facts.
