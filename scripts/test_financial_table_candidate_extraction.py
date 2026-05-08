from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.modules.financial_report.services.financial_table_candidate_service import (
    build_extraction_candidate_set,
)
from backend.app.modules.financial_report.services.parsed_document_registry import (
    list_registry_entries,
)


REPORT_PATH = PROJECT_ROOT / "docs" / "FINANCIAL_TABLE_CANDIDATE_EXTRACTION_TEST_REPORT.md"


def main() -> int:
    entries = list_registry_entries(limit=1)
    if not entries:
        print(json.dumps({"error": "parsed document registry is empty"}, ensure_ascii=False, indent=2))
        return 1

    document_id = entries[0]["document_id"]
    normal = build_extraction_candidate_set(document_id, allow_override=False)
    override = build_extraction_candidate_set(document_id, allow_override=True)

    statement_distribution = Counter(candidate.candidate_statement_type for candidate in override.candidates)
    source_distribution = Counter(candidate.source_type for candidate in override.candidates)
    merged_count = source_distribution.get("merged_cross_page_table", 0)

    result = {
        "document_id": document_id,
        "normal_eligible_for_extraction": normal.eligible_for_extraction,
        "normal_extraction_mode": normal.extraction_mode,
        "normal_candidates_count": len(normal.candidates),
        "normal_warnings": normal.warnings,
        "override_eligible_for_extraction": override.eligible_for_extraction,
        "override_extraction_mode": override.extraction_mode,
        "override_candidates_count": len(override.candidates),
        "override_warnings": override.warnings,
        "candidate_statement_type_distribution": dict(statement_distribution),
        "source_type_distribution": dict(source_distribution),
        "merged_cross_page_table_candidate_count": merged_count,
    }
    _write_report(result)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if normal.extraction_mode != "blocked" or normal.candidates:
        return 2
    if override.extraction_mode != "dry_run_override" or not override.candidates:
        return 3
    if "override_used" not in override.warnings:
        return 4
    return 0


def _write_report(result: dict[str, object]) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    report = f"""# Financial Table Candidate Extraction Test Report

Generated at: 2026-05-03

## Scope

This test validates a controlled financial table candidate extraction prototype.

Not performed:

- No PDF parse submission
- No parser execution
- No LLM call
- No final financial field extraction
- No metrics
- No forecast
- No backtest
- No report generation
- No frontend work
- No parse_lab changes

## Document

- `document_id`: `{result['document_id']}`
- `current_eligible_for_extraction`: `{result['normal_eligible_for_extraction']}`
- `normal_extraction_mode`: `{result['normal_extraction_mode']}`
- `normal_candidates_count`: `{result['normal_candidates_count']}`
- `normal_warnings`: `{result['normal_warnings']}`

Normal mode is blocked because the current review decision is not approved for extraction.

## Dry-Run Override

- `override_extraction_mode`: `{result['override_extraction_mode']}`
- `override_candidates_count`: `{result['override_candidates_count']}`
- `override_warnings`: `{result['override_warnings']}`
- `merged_cross_page_table_candidate_count`: `{result['merged_cross_page_table_candidate_count']}`

Candidate statement type distribution:

```json
{json.dumps(result['candidate_statement_type_distribution'], ensure_ascii=False, indent=2)}
```

Source type distribution:

```json
{json.dumps(result['source_type_distribution'], ensure_ascii=False, indent=2)}
```

## Readiness

This stage can proceed to statement-specific field mapping prototype design.

The dry-run override result is diagnostic only. It must not be treated as approved extraction output, and it must not feed metrics, forecast, backtest, or report generation.
"""
    REPORT_PATH.write_text(report, encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
