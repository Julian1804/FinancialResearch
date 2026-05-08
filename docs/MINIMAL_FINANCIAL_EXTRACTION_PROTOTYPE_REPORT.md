# Minimal Financial Extraction Prototype Report

Generated at: 2026-05-03

## Scope

This report covers a dry-run minimal financial statement extraction prototype from refined statement field candidates.

Not performed:

- No PDF parse submission
- No parser execution
- No LLM call
- No metrics
- No forecast
- No backtest
- No report generation
- No frontend work
- No parse_lab changes
- No formal database write

## Document

- `document_id`: `parsed_doc_22687fab59b569de`
- `current_review_decision`: `needs_reparse`
- `current_eligible_for_extraction`: `False`
- `normal_blocked`: `True`
- `normal_warnings`: `['review_decision=needs_reparse; approved_for_extraction=false']`

## Dry-Run Override Extraction

- `override_extraction_mode`: `dry_run_override`
- `statement_count`: `4`
- `field_count`: `20`
- `requires_review_field_count`: `17`
- `requires_review_statement_count`: `4`

Statement type distribution:

```json
{
  "balance_sheet": 1,
  "cash_flow_statement": 1,
  "income_statement": 1,
  "shareholder_table": 1
}
```

Field statement type distribution:

```json
{
  "balance_sheet": 5,
  "cash_flow_statement": 4,
  "income_statement": 10,
  "shareholder_table": 1
}
```

Periods detected:

```json
[
  "2025年3月31日",
  "2025年第一季度",
  "unknown_period",
  "本报告期",
  "本报告期比上年同\n期增减变动幅度\n(%)"
]
```

Warnings:

```json
[
  "override_used",
  "eligibility_block_reason=review_decision=needs_reparse; approved_for_extraction=false",
  "discarded_candidates_count=43",
  "override_used",
  "eligibility_block_reason=review_decision=needs_reparse; approved_for_extraction=false",
  "discarded_field_candidates_count=27"
]
```

Errors:

```json
[]
```

Sample fields:

```json
[
  {
    "canonical_field_name": "cash_and_cash_equivalents",
    "statement_type": "balance_sheet",
    "value": "366,423,449.67",
    "normalized_value": 366423449.67,
    "period_label": "2025年3月31日",
    "source_pages": [
      7,
      8
    ],
    "confidence": 0.83,
    "requires_review": true
  },
  {
    "canonical_field_name": "total_assets",
    "statement_type": "balance_sheet",
    "value": "5,653,743,362.58",
    "normalized_value": 5653743362.58,
    "period_label": "2025年3月31日",
    "source_pages": [
      7,
      8
    ],
    "confidence": 0.83,
    "requires_review": true
  },
  {
    "canonical_field_name": "cash_and_cash_equivalents",
    "statement_type": "balance_sheet",
    "value": "208,941,565.93",
    "normalized_value": 208941565.93,
    "period_label": "unknown_period",
    "source_pages": [
      13,
      14
    ],
    "confidence": 0.7,
    "requires_review": true
  },
  {
    "canonical_field_name": "total_assets",
    "statement_type": "balance_sheet",
    "value": "5,653,743,362.58",
    "normalized_value": 5653743362.58,
    "period_label": "unknown_period",
    "source_pages": [
      8,
      9
    ],
    "confidence": 0.7,
    "requires_review": true
  },
  {
    "canonical_field_name": "total_liabilities",
    "statement_type": "balance_sheet",
    "value": "1,517,483,288.58",
    "normalized_value": 1517483288.58,
    "period_label": "unknown_period",
    "source_pages": [
      8,
      9
    ],
    "confidence": 0.7,
    "requires_review": true
  },
  {
    "canonical_field_name": "operating_cash_flow",
    "statement_type": "cash_flow_statement",
    "value": "-104,186,266.67",
    "normalized_value": -104186266.67,
    "period_label": "2025年第一季度",
    "source_pages": [
      17
    ],
    "confidence": 0.86,
    "requires_review": true
  },
  {
    "canonical_field_name": "financing_cash_flow",
    "statement_type": "cash_flow_statement",
    "value": "28,776,952.08",
    "normalized_value": 28776952.08,
    "period_label": "unknown_period",
    "source_pages": [
      18
    ],
    "confidence": 0.73,
    "requires_review": true
  },
  {
    "canonical_field_name": "investing_cash_flow",
    "statement_type": "cash_flow_statement",
    "value": "47,591,827.60",
    "normalized_value": 47591827.6,
    "period_label": "unknown_period",
    "source_pages": [
      18
    ],
    "confidence": 0.73,
    "requires_review": true
  },
  {
    "canonical_field_name": "operating_cash_flow",
    "statement_type": "cash_flow_statement",
    "value": "23,000,841.80",
    "normalized_value": 23000841.8,
    "period_label": "unknown_period",
    "source_pages": [
      12,
      13
    ],
    "confidence": 0.7,
    "requires_review": true
  },
  {
    "canonical_field_name": "revenue",
    "statement_type": "income_statement",
    "value": "261,347,980.19",
    "normalized_value": 261347980.19,
    "period_label": "2025年第一季度",
    "source_pages": [
      9
    ],
    "confidence": 0.76,
    "requires_review": true
  }
]
```

## Readiness

This stage can proceed to source traceability and review UI / CLI design.

The dry-run output is reviewable extraction evidence only. It must not feed metrics, forecast, backtest, or report generation until approval, traceability checks, and handoff schemas are implemented.
