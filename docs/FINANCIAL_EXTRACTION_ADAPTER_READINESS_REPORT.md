# Financial Extraction Adapter Readiness Report

Generated at: 2026-05-03

## Scope

This is a read-only analysis of existing Parse Lab API v1 output for extraction adapter readiness.

Not performed:

- No PDF parse submission
- No parser execution
- No financial field extraction
- No LLM call
- No metrics
- No forecast
- No backtest
- No report generation
- No frontend work
- No parse_lab changes

## Document

- `document_id`: `parsed_doc_22687fab59b569de`
- `current_review_decision`: `needs_reparse`
- `eligible_for_extraction`: `False`
- `eligibility_reason`: `review_decision=needs_reparse; approved_for_extraction=false`

The current document is not extracted by this stage. Read-only normalization is allowed even when eligibility is false.

## Table Normalization

- `total_tables`: `54`
- `canonical_tables_count`: `54`
- `merged_cross_page_tables_count`: `16`
- `source_pages_count`: `17`
- `table_group_id_count`: `31`
- `pages_count`: `18`
- `summary_total_pages`: `18`

Candidate statement type distribution:

```json
{
  "income_statement": 22,
  "unknown": 9,
  "shareholder_table": 4,
  "balance_sheet": 12,
  "cash_flow_statement": 7
}
```

Source type distribution:

```json
{
  "page_table": 38,
  "merged_cross_page_table": 16
}
```

Warnings:

```json
[]
```

Errors:

```json
[]
```

## Findings

- Parse Lab output can be transformed into canonical table objects without running extraction.
- Cross-page table groups are preserved through `table_group_id` and `source_pages`.
- Current candidate statement classification is intentionally conservative; unidentified tables remain `unknown`.
- The current review decision is `needs_reparse`, so the document must not enter extraction until explicitly approved.

## Next Step

The project can proceed to extraction adapter controlled prototype design, gated by `eligible_for_extraction=true`.
