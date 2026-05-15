# Parse Lab Round3 Candidate-Only Ingestion Report

## Scope

This prototype ingests Parse Lab's Round3 FinancialResearch-facing field candidate export into FinancialResearch as provisional facts only.

Not performed:

- No Parse Lab code change.
- No parser optimization.
- No cross-page merge work.
- No PaddleOCR processing.
- No default V1.1 replacement.
- No trusted final fact creation.
- No architecture-wide FinancialResearch refactor.

## Input

Parse Lab export directory:

`D:\workspace\runtime\parse_lab\financialresearch_exports\round3_field_candidates`

Consumed files:

- `financialresearch_field_candidates.json`
- `financialresearch_review_queue.json`

## Output

FinancialResearch provisional output directory:

`D:\workspace\FinancialResearch\runtime\financial_report\provisional_facts\parse_lab_round3`

Generated files:

- `provisional_facts.json`
- `provisional_facts.jsonl`
- `candidate_only_review_queue.json`
- `ingestion_summary.json`

## Result

- Provisional facts read and saved: 273
- Review queue items read and saved: 60
- Trusted facts created: 0
- Validation status distribution:
  - `matched`: 257
  - `partially_matched`: 16
- Review queue distribution:
  - `table_value_missing`: 31
  - `needs_human_review`: 29
- Source PDF distribution:
  - `泡泡玛特2025年中报.pdf`: 163
  - `华钰矿业2025年半年报.pdf`: 110
- Source type distribution:
  - `text_table_validated`: 273

## Data Contract

Every provisional fact keeps:

- `field_name`
- `value`
- `unit`
- `currency`
- `period`
- `source_pdf`
- `source_page`
- `source_type`
- `evidence_text`
- `table_id`
- `engine_name`
- `validation_status`
- `confidence`
- `candidate_only_reason`

All ingested facts are explicitly:

- `candidate_only = true`
- `trusted = false`

Rows with `table_value_missing`, `needs_human_review`, or `conflict` do not enter provisional facts. They are preserved only in the candidate-only review queue.

## Recommendation

This is ready for a candidate-only FinancialResearch display or review workflow. It should not feed metrics, forecasts, reports, or trusted final fact tables until a separate approval and promotion step exists.

