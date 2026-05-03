# Financial Extraction Adapter Design

Generated at: 2026-05-03

## Scope

This document designs the pre-extraction adapter between Parse Lab API v1 outputs and future FinancialResearch financial field extraction.

This stage does not run extraction, metrics, forecast, backtest, report generation, parser execution, or LLM calls.

## Why `merged.md` Alone Is Not Enough

`merged.md` is useful for reading, summarization, section understanding, and broad Q&A. It is not sufficient as the only source for financial field extraction because:

- Markdown may flatten table structure and lose row/column boundaries.
- Cross-page tables can be split or repeated in text.
- Visual table recovery pages need explicit quality context.
- Source page traceability is weaker if values are read only from prose.
- Numeric values require table coordinates, units, periods, and parser quality signals.

The adapter should therefore treat `merged.md` as narrative context, not as the primary structured table source.

## Required Parse Lab Inputs

The adapter consumes these files by reference from the parsed document registry:

- `summary.json`: parse status, parser usage, route quality, failed pages, table recovery counts.
- `merged.md`: narrative context and section-level reading.
- `pages.jsonl`: page-level traceability, parser source, quality flags, visual table route flags, table intent scores.
- `tables.json`: normal page-level table output.
- `merged_tables.json`: cross-page table groups and continuation confidence.
- `quality_flags.json`: global and page-level quality risk signals.
- `cross_page_table_candidates.jsonl`: audit trail for cross-page merge decisions.

The adapter must not modify Parse Lab output files.

## Eligibility Gate

The extraction eligibility gate sits before adapter execution:

1. Parse Lab completes and FinancialResearch registers the parsed document.
2. Review queue classifies parse quality.
3. A human or controlled workflow writes a review decision.
4. `GET /api/financial-report/parse/extraction-eligibility/{document_id}` returns `eligible_for_extraction=true`.
5. Only then may extraction adapter output be passed to field extraction.

Read-only adapter readiness analysis may run even when eligibility is false.

## Adapter Output Contract

The adapter produces a canonical table normalization result:

- `document_id`
- `task_id`
- `pdf_name`
- `tables`
- `warnings`
- `errors`

Each canonical table keeps:

- table identity
- source file
- source pages
- parser source
- table group id
- source type
- normalized cells
- raw text and markdown
- quality metrics
- candidate statement type

This output is an intermediate extraction input, not final financial data.

## Canonical Table Schema

The canonical schema is defined in:

```text
backend/app/modules/financial_report/schemas/table_contract.py
```

Core objects:

- `CanonicalCell`
- `CanonicalTableSource`
- `CanonicalTableQuality`
- `CanonicalTable`
- `TableNormalizationResult`

The schema preserves table coordinates, text, header hints, source pages, cross-page confidence, parser source, and table intent score.

## Financial Statement Template Mapping

Template mapping should be separate from table normalization.

The mapping layer should:

- classify likely balance sheet, income statement, cash flow statement, shareholder table, and segment revenue table;
- identify unit and currency;
- identify period columns;
- distinguish consolidated and parent-company statements;
- map candidate rows to canonical financial fields;
- preserve uncertainty and source references.

The first version should use explainable rules and reviewable evidence before adding LLM-based extraction.

## Cross-Page Tables

For `merged_tables.json`, the adapter should:

- create `source_type=merged_cross_page_table`;
- preserve `table_group_id`;
- preserve `source_pages`;
- preserve `continuation_confidence`;
- keep the source table fragments traceable;
- avoid silently overwriting page-level tables.

Downstream extraction should prefer merged cross-page tables for fields spanning pages, but keep page-level tables available for audit.

## Visual Table Route Pages

For pages with visual table route or table recovery:

- keep `table_intent_score`;
- preserve page-level quality flags;
- mark source type as `visual_table` when Parse Lab emits that distinction;
- require review when table intent remains unresolved.

Future versions may compare Marker/MinerU validation outputs before accepting values from visual tables.

## Needs Review And Needs Reparse

Documents with:

- `review_decision=pending_review`
- `review_decision=needs_reparse`
- `review_decision=rejected`
- `review_decision=ignored`
- `parse_quality_level=failed`
- missing required output files

must not enter automatic extraction.

They may still be inspected through read-only readiness scripts for diagnosis.

## Downstream Integration

Future stages should proceed in this order:

1. Canonical table schema review.
2. Table normalization quality checks.
3. Financial statement template mapping prototype.
4. Controlled extraction prototype behind eligibility gate.
5. LLM extraction prompt design with table evidence references.
6. Extraction regression tests.
7. Metrics, forecast, backtest, and report integration behind separate gates.
