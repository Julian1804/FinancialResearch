from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.modules.financial_report.services.document_role_detector import (
    detect_document_role_from_filename,
)


REPORT_PATH = PROJECT_ROOT / "docs" / "DOCUMENT_ROLE_GATE_TEST_REPORT.md"
SAMPLES = [
    "华钰矿业2025年一季报告.pdf",
    "华钰矿业2024年年报.pdf",
    "药明生物2024年报.pdf",
    "药明生物2021全年业绩新闻稿_En.pdf",
    "药明生物2025全年业绩简报.pdf",
    "泡泡玛特2025年业绩公告.pdf",
    "某公司电话会议纪要.pdf",
]


def main() -> int:
    results = []
    for name in SAMPLES:
        assessment = detect_document_role_from_filename(name)
        results.append(_dump_model(assessment))
    _write_report(results)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


def _write_report(results: list[dict[str, object]]) -> None:
    primary = [item["pdf_name"] for item in results if item["expects_three_statements"]]
    auxiliary = [item["pdf_name"] for item in results if not item["expects_three_statements"]]
    report = f"""# Document Role Gate Test Report

Generated at: 2026-05-03

## Why This Gate Exists

Only primary time-series financial reports should be expected to contain the three main financial statements.

Earnings releases, result announcements, performance briefings, conference call transcripts, and investor presentations often contain selected performance metrics, management commentary, or slides. They should not be penalized for missing balance sheet, income statement, or cash flow statement tables.

## Classification Results

```json
{json.dumps(results, ensure_ascii=False, indent=2)}
```

## Expects Three Statements

```json
{json.dumps(primary, ensure_ascii=False, indent=2)}
```

## Does Not Require Three Statements

```json
{json.dumps(auxiliary, ensure_ascii=False, indent=2)}
```

## Impact On Extraction Adapter

- `primary_financial_report` routes to `three_statement_extraction`.
- `auxiliary_material` routes to auxiliary performance or commentary extraction.
- `unknown` requires review before any formal extraction.
- Missing three statements should not be treated as a failure for auxiliary materials.

## Next Auxiliary Material Route

Future auxiliary extraction should handle:

- key performance metric snippets;
- management commentary;
- investor presentation tables;
- conference call transcript sections;
- source traceability separate from three-statement extraction.
"""
    REPORT_PATH.write_text(report, encoding="utf-8")


def _dump_model(model: object) -> dict[str, object]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return json.loads(model.json())


if __name__ == "__main__":
    sys.exit(main())
