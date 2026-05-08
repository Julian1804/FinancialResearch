from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.modules.financial_report.services.parse_review_decision_service import (
    find_decision_by_document_id,
    get_extraction_eligibility,
)
from backend.app.modules.financial_report.services.parsed_document_registry import (
    list_registry_entries,
)
from backend.app.modules.financial_report.services.table_normalization_service import (
    normalize_parse_lab_tables,
)


REPORT_PATH = Path("docs") / "FINANCIAL_EXTRACTION_ADAPTER_READINESS_REPORT.md"


def main() -> int:
    entries = list_registry_entries(limit=1)
    if not entries:
        print(json.dumps({"error": "parsed document registry is empty"}, ensure_ascii=False, indent=2))
        return 1

    entry = entries[0]
    document_id = entry.get("document_id", "")
    eligibility = get_extraction_eligibility(document_id)
    decision = find_decision_by_document_id(document_id) or {}

    manifest = {
        "document_id": document_id,
        "task_id": entry.get("parse_task_id", ""),
        "pdf_name": entry.get("pdf_name", ""),
        "summary_path": entry.get("summary_path", ""),
        "pages_jsonl_path": entry.get("pages_jsonl_path", ""),
        "merged_md_path": entry.get("merged_md_path", ""),
        "tables_json_path": entry.get("tables_json_path", ""),
        "merged_tables_json_path": entry.get("merged_tables_json_path", ""),
        "quality_flags_path": entry.get("quality_flags_path", ""),
        "cross_page_candidates_path": entry.get("cross_page_candidates_path", ""),
    }

    summary = _load_json(manifest["summary_path"])
    quality_flags = _load_json(manifest["quality_flags_path"])
    pages_count = _count_jsonl(manifest["pages_jsonl_path"])
    normalization = normalize_parse_lab_tables(manifest)
    tables = normalization.tables

    source_type_distribution = Counter(table.source.source_type for table in tables)
    statement_distribution = Counter(table.candidate_statement_type for table in tables)
    source_pages = sorted({page for table in tables for page in table.source.source_pages})
    table_group_ids = sorted({table.source.table_group_id for table in tables if table.source.table_group_id})
    merged_cross_page_tables = source_type_distribution.get("merged_cross_page_table", 0)

    result = {
        "document_id": document_id,
        "review_decision": decision.get("review_decision", "pending_review"),
        "eligible_for_extraction": eligibility.get("eligible_for_extraction", False),
        "eligibility_reason": eligibility.get("reason", ""),
        "total_tables": len(tables),
        "canonical_tables_count": len(tables),
        "merged_cross_page_tables_count": merged_cross_page_tables,
        "candidate_statement_type_distribution": dict(statement_distribution),
        "source_type_distribution": dict(source_type_distribution),
        "source_pages": source_pages,
        "source_pages_count": len(source_pages),
        "table_group_id_count": len(table_group_ids),
        "table_group_ids": table_group_ids,
        "pages_count": pages_count,
        "summary_total_pages": summary.get("total_pages"),
        "quality_flag_counts": quality_flags.get("flag_counts", {}) if isinstance(quality_flags, dict) else {},
        "warnings": normalization.warnings,
        "errors": normalization.errors,
    }

    _write_report(result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not normalization.errors else 2


def _load_json(path: str) -> dict[str, Any]:
    if not path or not Path(path).exists():
        return {}
    with Path(path).open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def _count_jsonl(path: str) -> int:
    if not path or not Path(path).exists():
        return 0
    count = 0
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                count += 1
    return count


def _write_report(result: dict[str, Any]) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    report = f"""# Financial Extraction Adapter Readiness Report

Generated at: 2026-05-03

## Scope

This is a read-only analysis of existing Parse Lab API v1 output for extraction adapter readiness.

Not performed:

- No PDF parse submission
- No parser execution
- No financial field extraction
- No LLM call
- No metrics
- No forecast
- No backtest
- No report generation
- No frontend work
- No parse_lab changes

## Document

- `document_id`: `{result['document_id']}`
- `current_review_decision`: `{result['review_decision']}`
- `eligible_for_extraction`: `{result['eligible_for_extraction']}`
- `eligibility_reason`: `{result['eligibility_reason']}`

The current document is not extracted by this stage. Read-only normalization is allowed even when eligibility is false.

## Table Normalization

- `total_tables`: `{result['total_tables']}`
- `canonical_tables_count`: `{result['canonical_tables_count']}`
- `merged_cross_page_tables_count`: `{result['merged_cross_page_tables_count']}`
- `source_pages_count`: `{result['source_pages_count']}`
- `table_group_id_count`: `{result['table_group_id_count']}`
- `pages_count`: `{result['pages_count']}`
- `summary_total_pages`: `{result['summary_total_pages']}`

Candidate statement type distribution:

```json
{json.dumps(result['candidate_statement_type_distribution'], ensure_ascii=False, indent=2)}
```

Source type distribution:

```json
{json.dumps(result['source_type_distribution'], ensure_ascii=False, indent=2)}
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

- Parse Lab output can be transformed into canonical table objects without running extraction.
- Cross-page table groups are preserved through `table_group_id` and `source_pages`.
- Current candidate statement classification is intentionally conservative; unidentified tables remain `unknown`.
- The current review decision is `needs_reparse`, so the document must not enter extraction until explicitly approved.

## Next Step

The project can proceed to extraction adapter controlled prototype design, gated by `eligible_for_extraction=true`.
"""
    REPORT_PATH.write_text(report, encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
