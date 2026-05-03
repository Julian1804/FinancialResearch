from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.modules.financial_report.services.minimal_financial_extraction_service import (
    build_minimal_financial_extraction,
)
from backend.app.modules.financial_report.services.parsed_document_registry import (
    list_registry_entries,
)
from backend.app.modules.financial_report.services.parse_review_decision_service import (
    find_decision_by_document_id,
    get_extraction_eligibility,
)


REPORT_PATH = PROJECT_ROOT / "docs" / "MINIMAL_FINANCIAL_EXTRACTION_PROTOTYPE_REPORT.md"


def main() -> int:
    entries = list_registry_entries(limit=1)
    if not entries:
        print(json.dumps({"error": "parsed document registry is empty"}, ensure_ascii=False, indent=2))
        return 1

    document_id = entries[0]["document_id"]
    decision = find_decision_by_document_id(document_id) or {}
    eligibility = get_extraction_eligibility(document_id)
    normal = build_minimal_financial_extraction(document_id, allow_override=False)
    override = build_minimal_financial_extraction(document_id, allow_override=True)

    fields = [field for statement in override.statements for field in statement.fields]
    statement_distribution = Counter(statement.statement_type for statement in override.statements)
    field_statement_distribution = Counter(field.statement_type for field in fields)
    periods = sorted({period for statement in override.statements for period in statement.periods_detected})
    requires_review_field_count = sum(1 for field in fields if field.requires_review)
    requires_review_statement_count = sum(1 for statement in override.statements if statement.requires_review)

    result = {
        "document_id": document_id,
        "review_decision": decision.get("review_decision", "pending_review"),
        "eligible_for_extraction": eligibility.get("eligible_for_extraction", False),
        "normal_blocked": normal.extraction_mode == "blocked" and not normal.statements,
        "normal_warnings": normal.warnings,
        "override_extraction_mode": override.extraction_mode,
        "statement_count": len(override.statements),
        "field_count": len(fields),
        "statement_type_distribution": dict(statement_distribution),
        "field_statement_type_distribution": dict(field_statement_distribution),
        "requires_review_field_count": requires_review_field_count,
        "requires_review_statement_count": requires_review_statement_count,
        "periods_detected": periods,
        "warnings": override.warnings,
        "errors": override.errors,
        "sample_fields": [
            {
                "canonical_field_name": field.canonical_field_name,
                "statement_type": field.statement_type,
                "value": field.value,
                "normalized_value": field.normalized_value,
                "period_label": field.period_label,
                "source_pages": field.source_pages,
                "confidence": field.confidence,
                "requires_review": field.requires_review,
            }
            for field in fields[:10]
        ],
    }
    _write_report(result)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if not result["normal_blocked"]:
        return 2
    if override.extraction_mode != "dry_run_override":
        return 3
    return 0


def _write_report(result: dict[str, object]) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    report = f"""# Minimal Financial Extraction Prototype Report

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

- `document_id`: `{result['document_id']}`
- `current_review_decision`: `{result['review_decision']}`
- `current_eligible_for_extraction`: `{result['eligible_for_extraction']}`
- `normal_blocked`: `{result['normal_blocked']}`
- `normal_warnings`: `{result['normal_warnings']}`

## Dry-Run Override Extraction

- `override_extraction_mode`: `{result['override_extraction_mode']}`
- `statement_count`: `{result['statement_count']}`
- `field_count`: `{result['field_count']}`
- `requires_review_field_count`: `{result['requires_review_field_count']}`
- `requires_review_statement_count`: `{result['requires_review_statement_count']}`

Statement type distribution:

```json
{json.dumps(result['statement_type_distribution'], ensure_ascii=False, indent=2)}
```

Field statement type distribution:

```json
{json.dumps(result['field_statement_type_distribution'], ensure_ascii=False, indent=2)}
```

Periods detected:

```json
{json.dumps(result['periods_detected'], ensure_ascii=False, indent=2)}
```

Warnings:

```json
{json.dumps(result['warnings'], ensure_ascii=False, indent=2)}
```

Errors:

```json
{json.dumps(result['errors'], ensure_ascii=False, indent=2)}
```

Sample fields:

```json
{json.dumps(result['sample_fields'], ensure_ascii=False, indent=2)}
```

## Readiness

This stage can proceed to source traceability and review UI / CLI design.

The dry-run output is reviewable extraction evidence only. It must not feed metrics, forecast, backtest, or report generation until approval, traceability checks, and handoff schemas are implemented.
"""
    REPORT_PATH.write_text(report, encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
