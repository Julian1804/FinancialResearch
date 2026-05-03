# Financial Report Parse Registry And Review Queue Report

Generated at: 2026-05-03

## Scope

This stage adds local parsed document registry listing and review queue classification APIs.

Not performed:

- No PDF parse submission
- No extraction
- No metrics
- No forecast
- No backtest
- No report generation
- No frontend work
- No parse_lab changes
- No parser environment changes
- No commit or push

## Registry

Registry storage path:

```text
D:\workspace\FinancialResearch\runtime\financial_report\parsed_document_registry.jsonl
```

The registry remains local JSONL. Runtime outputs are ignored by git through `.gitignore`.

Current observed registry count:

```text
1
```

Parse quality distribution:

```json
{
  "pass_with_warnings": 1
}
```

## Review Queue

Current observed review queue count:

```text
1
```

Review status distribution:

```json
{
  "needs_review": 1
}
```

The existing registered document is classified as `needs_review` because it has `cross_page_table_candidate_count=16`. This is intentional: cross-page table candidates should be visible before any extraction adapter consumes the result.

## Tested Backend Routes

Tested with:

```text
scripts/test_financial_report_parse_registry_routes.py
```

Routes:

- `GET /api/health`
- `GET /api/financial-report/parse/registry`
- `GET /api/financial-report/parse/review-queue`
- `GET /api/financial-report/parse/registry/{task_id}`
- `GET /api/financial-report/parse/review-queue/{document_id}`

Route smoke result:

```json
{
  "registry_count": 1,
  "review_queue_count": 1,
  "first_document_id": "parsed_doc_22687fab59b569de",
  "first_parse_quality_level": "pass_with_warnings",
  "first_review_status": "needs_review"
}
```

## Readiness

This stage is ready for the next design step:

- FinancialReport parse ingestion UI or CLI
- extraction adapter design

Do not connect extraction, metrics, forecast, backtest, or report generation until review queue behavior and approval rules are explicitly designed.
