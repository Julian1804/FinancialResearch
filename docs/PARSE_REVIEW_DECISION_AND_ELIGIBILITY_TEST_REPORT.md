# Parse Review Decision And Eligibility Test Report

Generated at: 2026-05-03

## Scope

This stage adds a local review decision layer on top of the parsed document registry and review queue.

Not performed:

- No PDF parse submission
- No parser execution
- No extraction
- No metrics
- No forecast
- No backtest
- No report generation
- No frontend work
- No parse_lab changes
- No parser environment changes
- No commit or push

## Decision Storage

Review decisions are stored locally as JSONL:

```text
D:\workspace\FinancialResearch\runtime\financial_report\parse_review_decisions.jsonl
```

Only the latest decision is retained per `document_id`.

## Route Smoke Test

Test script:

```text
scripts/test_parse_review_decision_routes.py
```

Tested routes:

- `GET /api/financial-report/parse/registry`
- `GET /api/financial-report/parse/review-queue/{document_id}`
- `GET /api/financial-report/parse/extraction-eligibility/{document_id}`
- `POST /api/financial-report/parse/review-decisions/{document_id}`
- `GET /api/financial-report/parse/review-decisions/{document_id}`

Observed result:

```json
{
  "document_id": "parsed_doc_22687fab59b569de",
  "initial_review_status": "needs_review",
  "initial_eligible_for_extraction": false,
  "approved_review_decision": "approved_with_warnings",
  "approved_eligible_for_extraction": true,
  "reset_review_decision": "needs_reparse",
  "reset_eligible_for_extraction": false
}
```

The final test state intentionally resets the document to `needs_reparse`, so it is not currently eligible for extraction.

## Readiness

This stage is ready for the next design step: extraction adapter design.

The adapter must still be gated by `eligible_for_extraction=true`; pending, rejected, ignored, needs-reparse, failed, or missing-output documents must not enter extraction automatically.
