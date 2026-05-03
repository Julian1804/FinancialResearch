# Statement Field Mapping Prototype Report

Generated at: 2026-05-03

## Scope

This report covers a no-LLM, rule-based dry-run statement field mapping prototype.

Not performed:

- No PDF parse submission
- No parser execution
- No LLM call
- No final financial field database write
- No metrics
- No forecast
- No backtest
- No report generation
- No frontend work
- No parse_lab changes

## Document

- `document_id`: `parsed_doc_22687fab59b569de`
- `normal_extraction_mode`: `blocked`
- `normal_blocked`: `True`
- `normal_fields_count`: `0`
- `normal_warnings`: `['review_decision=needs_reparse; approved_for_extraction=false']`

The current review decision remains blocked for formal extraction. Dry-run override is diagnostic only.

## Dry-Run Override Mapping

- `override_extraction_mode`: `dry_run_override`
- `override_fields_count`: `350`
- `requires_review_count`: `350`
- `unknown_unit_count`: `156`
- `unknown_period_count`: `262`

Canonical field distribution:

```json
{
  "revenue": 234,
  "net_profit": 38,
  "shareholder_name": 4,
  "total_assets": 6,
  "total_liabilities": 33,
  "operating_profit": 4,
  "operating_cash_flow": 4,
  "investing_cash_flow": 5,
  "financing_cash_flow": 5,
  "cash_end_period": 5,
  "cash_and_cash_equivalents": 12
}
```

Statement type distribution:

```json
{
  "income_statement": 276,
  "shareholder_table": 4,
  "balance_sheet": 51,
  "cash_flow_statement": 19
}
```

Warnings:

```json
[
  "override_used",
  "eligibility_block_reason=review_decision=needs_reparse; approved_for_extraction=false"
]
```

Errors:

```json
[]
```

## Findings

- Normal mode is correctly blocked by the extraction eligibility gate.
- Dry-run override can produce rule-based statement field candidates from canonical tables.
- Unknown period and unit counts remain high; period detection, unit/currency normalization, and source-text context need improvement.
- Cross-page and suspicious numeric fields remain review-gated.

## Readiness

This stage can proceed to financial statement extraction controlled prototype design, still behind review approval and source traceability checks.
