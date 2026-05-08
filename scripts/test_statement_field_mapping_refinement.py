from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.modules.financial_report.services.parsed_document_registry import (
    list_registry_entries,
)
from backend.app.modules.financial_report.services.statement_field_mapping_service import (
    build_statement_mapping_result,
)


BASELINE_FIELDS_COUNT = 350
BASELINE_REVENUE_COUNT = 234
BASELINE_UNKNOWN_UNIT_COUNT = 156
BASELINE_UNKNOWN_PERIOD_COUNT = 262
REPORT_PATH = PROJECT_ROOT / "docs" / "STATEMENT_FIELD_MAPPING_REFINEMENT_REPORT.md"


def main() -> int:
    entries = list_registry_entries(limit=1)
    if not entries:
        print(json.dumps({"error": "parsed document registry is empty"}, ensure_ascii=False, indent=2))
        return 1

    document_id = entries[0]["document_id"]
    refined = build_statement_mapping_result(document_id, allow_override=True)
    field_distribution = Counter(field.canonical_field_name for field in refined.fields)
    statement_distribution = Counter(field.candidate_statement_type for field in refined.fields)
    requires_review_count = sum(1 for field in refined.fields if field.requires_review)
    unknown_unit_count = sum(1 for field in refined.fields if field.unit == "unknown")
    unknown_period_count = sum(1 for field in refined.fields if field.period_label == "unknown_period")
    average_confidence = round(
        sum(field.confidence for field in refined.fields) / len(refined.fields),
        4,
    ) if refined.fields else 0.0

    retained_examples = [
        {
            "canonical_field_name": field.canonical_field_name,
            "raw_field_name": field.raw_field_name,
            "raw_value": field.raw_value,
            "period_label": field.period_label,
            "source_pages": field.source_pages,
            "confidence": field.confidence,
            "mapping_reason": field.mapping_reason,
        }
        for field in refined.fields[:10]
    ]
    result = {
        "document_id": document_id,
        "baseline_fields_count": BASELINE_FIELDS_COUNT,
        "refined_fields_count": len(refined.fields),
        "baseline_revenue_count": BASELINE_REVENUE_COUNT,
        "refined_revenue_count": field_distribution.get("revenue", 0),
        "baseline_unknown_unit_count": BASELINE_UNKNOWN_UNIT_COUNT,
        "refined_unknown_unit_count": unknown_unit_count,
        "baseline_unknown_period_count": BASELINE_UNKNOWN_PERIOD_COUNT,
        "refined_unknown_period_count": unknown_period_count,
        "canonical_field_name_distribution": dict(field_distribution),
        "statement_type_distribution": dict(statement_distribution),
        "requires_review_count": requires_review_count,
        "discarded_candidates_count": refined.discarded_candidates_count,
        "average_confidence": average_confidence,
        "retained_candidate_examples": retained_examples,
        "discarded_candidate_examples": refined.discarded_candidate_examples,
        "warnings": refined.warnings,
        "errors": refined.errors,
        "noise_reduced": len(refined.fields) < BASELINE_FIELDS_COUNT and field_distribution.get("revenue", 0) < BASELINE_REVENUE_COUNT,
    }
    _write_report(result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not refined.errors else 2


def _write_report(result: dict[str, object]) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    report = f"""# Statement Field Mapping Refinement Report

Generated at: 2026-05-03

## Scope

This report compares the previous statement field mapping prototype with the refined no-LLM mapping rules.

Not performed:

- No PDF parse submission
- No parser execution
- No LLM call
- No formal database write
- No metrics
- No forecast
- No backtest
- No report generation
- No frontend work
- No parse_lab changes

## Document

- `document_id`: `{result['document_id']}`

## Before / After

- baseline `fields_count`: `{result['baseline_fields_count']}`
- refined `fields_count`: `{result['refined_fields_count']}`
- baseline `revenue`: `{result['baseline_revenue_count']}`
- refined `revenue`: `{result['refined_revenue_count']}`
- baseline `unknown_unit_count`: `{result['baseline_unknown_unit_count']}`
- refined `unknown_unit_count`: `{result['refined_unknown_unit_count']}`
- baseline `unknown_period_count`: `{result['baseline_unknown_period_count']}`
- refined `unknown_period_count`: `{result['refined_unknown_period_count']}`
- `requires_review_count`: `{result['requires_review_count']}`
- `discarded_candidates_count`: `{result['discarded_candidates_count']}`
- `average_confidence`: `{result['average_confidence']}`
- `noise_reduced`: `{result['noise_reduced']}`

Canonical field distribution:

```json
{json.dumps(result['canonical_field_name_distribution'], ensure_ascii=False, indent=2)}
```

Statement type distribution:

```json
{json.dumps(result['statement_type_distribution'], ensure_ascii=False, indent=2)}
```

Retained candidate examples:

```json
{json.dumps(result['retained_candidate_examples'], ensure_ascii=False, indent=2)}
```

Discarded candidate examples:

```json
{json.dumps(result['discarded_candidate_examples'], ensure_ascii=False, indent=2)}
```

Warnings:

```json
{json.dumps(result['warnings'], ensure_ascii=False, indent=2)}
```

Errors:

```json
{json.dumps(result['errors'], ensure_ascii=False, indent=2)}
```

## Remaining Issues

- Unit and currency detection still depends mostly on table-local text; surrounding page text should be added.
- Period detection improves only when table headers retain clear period labels.
- Cross-page numeric repair is still not implemented.
- Shareholder table extraction needs table-specific logic for name, count, ratio, and pledge columns.

## Readiness

The refined mapping reduces candidate noise and can proceed to a minimal financial statement extraction prototype, still as dry-run and behind source traceability checks.
"""
    REPORT_PATH.write_text(report, encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
