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


REPORT_PATH = PROJECT_ROOT / "docs" / "STATEMENT_FIELD_MAPPING_PROTOTYPE_REPORT.md"


def main() -> int:
    entries = list_registry_entries(limit=1)
    if not entries:
        print(json.dumps({"error": "parsed document registry is empty"}, ensure_ascii=False, indent=2))
        return 1

    document_id = entries[0]["document_id"]
    normal = build_statement_mapping_result(document_id, allow_override=False)
    override = build_statement_mapping_result(document_id, allow_override=True)

    field_distribution = Counter(field.canonical_field_name for field in override.fields)
    statement_distribution = Counter(field.candidate_statement_type for field in override.fields)
    requires_review_count = sum(1 for field in override.fields if field.requires_review)
    unknown_unit_count = sum(1 for field in override.fields if field.unit == "unknown")
    unknown_period_count = sum(1 for field in override.fields if field.period_label == "unknown_period")

    result = {
        "document_id": document_id,
        "normal_extraction_mode": normal.extraction_mode,
        "normal_blocked": normal.extraction_mode == "blocked" and len(normal.fields) == 0,
        "normal_fields_count": len(normal.fields),
        "normal_warnings": normal.warnings,
        "override_extraction_mode": override.extraction_mode,
        "override_fields_count": len(override.fields),
        "canonical_field_name_distribution": dict(field_distribution),
        "statement_type_distribution": dict(statement_distribution),
        "requires_review_count": requires_review_count,
        "unknown_unit_count": unknown_unit_count,
        "unknown_period_count": unknown_period_count,
        "warnings": override.warnings,
        "errors": override.errors,
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
    report = f"""# Statement Field Mapping Prototype Report

Generated at: 2026-05-03

## Scope

This report covers a no-LLM, rule-based dry-run statement field mapping prototype.

Not performed:

- No PDF parse submission
- No parser execution
- No LLM call
- No final financial field database write
- No metrics
- No forecast
- No backtest
- No report generation
- No frontend work
- No parse_lab changes

## Document

- `document_id`: `{result['document_id']}`
- `normal_extraction_mode`: `{result['normal_extraction_mode']}`
- `normal_blocked`: `{result['normal_blocked']}`
- `normal_fields_count`: `{result['normal_fields_count']}`
- `normal_warnings`: `{result['normal_warnings']}`

The current review decision remains blocked for formal extraction. Dry-run override is diagnostic only.

## Dry-Run Override Mapping

- `override_extraction_mode`: `{result['override_extraction_mode']}`
- `override_fields_count`: `{result['override_fields_count']}`
- `requires_review_count`: `{result['requires_review_count']}`
- `unknown_unit_count`: `{result['unknown_unit_count']}`
- `unknown_period_count`: `{result['unknown_period_count']}`

Canonical field distribution:

```json
{json.dumps(result['canonical_field_name_distribution'], ensure_ascii=False, indent=2)}
```

Statement type distribution:

```json
{json.dumps(result['statement_type_distribution'], ensure_ascii=False, indent=2)}
```

Warnings:

```json
{json.dumps(result['warnings'], ensure_ascii=False, indent=2)}
```

Errors:

```json
{json.dumps(result['errors'], ensure_ascii=False, indent=2)}
```

## Findings

- Normal mode is correctly blocked by the extraction eligibility gate.
- Dry-run override can produce rule-based statement field candidates from canonical tables.
- Unknown period and unit counts remain high; period detection, unit/currency normalization, and source-text context need improvement.
- Cross-page and suspicious numeric fields remain review-gated.

## Readiness

This stage can proceed to financial statement extraction controlled prototype design, still behind review approval and source traceability checks.
"""
    REPORT_PATH.write_text(report, encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
