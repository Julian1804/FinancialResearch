# Financial Table Candidate Extraction Test Report

Generated at: 2026-05-03

## Scope

This test validates a controlled financial table candidate extraction prototype.

Not performed:

- No PDF parse submission
- No parser execution
- No LLM call
- No final financial field extraction
- No metrics
- No forecast
- No backtest
- No report generation
- No frontend work
- No parse_lab changes

## Document

- `document_id`: `parsed_doc_22687fab59b569de`
- `current_eligible_for_extraction`: `False`
- `normal_extraction_mode`: `blocked`
- `normal_candidates_count`: `0`
- `normal_warnings`: `['review_decision=needs_reparse; approved_for_extraction=false']`

Normal mode is blocked because the current review decision is not approved for extraction.

## Dry-Run Override

- `override_extraction_mode`: `dry_run_override`
- `override_candidates_count`: `45`
- `override_warnings`: `['override_used', 'eligibility_block_reason=review_decision=needs_reparse; approved_for_extraction=false']`
- `merged_cross_page_table_candidate_count`: `15`

Candidate statement type distribution:

```json
{
  "income_statement": 22,
  "shareholder_table": 4,
  "balance_sheet": 12,
  "cash_flow_statement": 7
}
```

Source type distribution:

```json
{
  "page_table": 30,
  "merged_cross_page_table": 15
}
```

## Readiness

This stage can proceed to statement-specific field mapping prototype design.

The dry-run override result is diagnostic only. It must not be treated as approved extraction output, and it must not feed metrics, forecast, backtest, or report generation.
