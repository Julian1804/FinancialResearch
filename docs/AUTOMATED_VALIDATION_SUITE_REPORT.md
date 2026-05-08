# Automated Validation Suite Report

Generated at: 2026-05-04

## Why Machine Checks Belong To Automation

Objective conditions should not be delegated to manual review. The system can reliably check repository hygiene, Python compilation, API health, JSON parsing, output file existence, page-count consistency, registry integrity, and eligibility rules.

Human attention should be reserved for semantic and numeric verification against the original PDF.

## Automated Check Scope

The validation suite covers:

- repository hygiene
- Python compile checks for `backend/app` and `scripts`
- backend health check
- Parse Lab connectivity through the FinancialResearch HTTP client
- parsed document registry integrity
- parse quality gate recomputation
- review queue / review decision / eligibility consistency
- canonical table normalization
- extraction candidate dry-run
- refined statement field mapping dry-run
- minimal extraction dry-run

The suite does not run parser jobs, submit PDFs, call LLMs, run metrics, forecast, backtest, or report generation.

## Latest Result Location

Runtime outputs are written to:

```text
runtime/financial_report/validation_suite
```

Files:

- `validation_suite_results.json`
- `validation_suite_results.md`
- `validation_suite_failures.json`
- `validation_suite_summary.csv`

## Latest Summary

Latest run:

```text
runtime/financial_report/validation_suite/validation_suite_results.json
```

Observed counts:

- passed: 11
- failed: 0
- skipped: 0
- warnings: 0
- registry_count: 1
- review_queue_count: 1
- eligible_documents_count: 0
- dry_run_documents_count: 1
- high_risk_items_count: 44

The expected interpretation is:

- `failed`: must be fixed before progressing.
- `warning`: machine-detected issue that may be acceptable but should be reviewed.
- `skipped`: external dependency not running, such as backend or Parse Lab API.
- `passed`: objective condition satisfied.

## Registry / Review / Eligibility

The suite verifies that:

- registry JSONL is parseable;
- task ids are not duplicated;
- Parse Lab output references exist;
- quality gate can be recomputed;
- pending, rejected, ignored, and needs-reparse decisions are not eligible for extraction;
- approved decisions are eligible only when required outputs are present.

Latest result:

- registry JSONL parseable
- duplicate task ids: none
- missing output references: none
- current registered document review decision: `needs_reparse`
- current eligible documents: 0

## Dry-Run Extraction

The suite runs dry-run candidate extraction, refined statement mapping, and minimal extraction against registered documents.

These outputs remain runtime artifacts and are not formal financial field ingestion.

Latest dry-run result:

- financial table candidates: 45
- refined statement field candidates: 47
- minimal extracted statements: 4
- minimal extracted fields: 20
- high-risk field mapping items requiring review: 44

## Issues Found

No machine-check failures were found.

The high-risk item count is not a machine failure. It means semantic/numeric review is required before any formal extraction approval.

## Next Stage

If the validation suite has no failed checks, the project can proceed to human semantic review or the next controlled prototype stage.
