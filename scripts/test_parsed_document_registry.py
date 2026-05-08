from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.modules.financial_report.services.parse_ingestion_service import ingest_and_register_parse_result  # noqa: E402
from backend.app.modules.financial_report.services.parsed_document_registry import (  # noqa: E402
    find_by_pdf_path,
    find_by_task_id,
    get_registry_path,
)


TASK_ID = "parse_v1_90d6c2ad4232"
PDF_PATH = "D:/workspace/parse_lab/test_data/" + "\u534e\u94b0\u77ff\u4e1a2025\u5e74\u4e00\u5b63\u62a5\u544a.pdf"


def main() -> int:
    entry = ingest_and_register_parse_result(TASK_ID, PDF_PATH)
    task_matches = find_by_task_id(TASK_ID)
    pdf_matches = find_by_pdf_path(PDF_PATH)
    result = {
        "document_id": entry["document_id"],
        "parse_task_id": entry["parse_task_id"],
        "parse_quality_level": entry["parse_quality_level"],
        "output_dir": entry["output_dir"],
        "registry_path": str(get_registry_path()),
        "found_by_task_id": bool(task_matches),
        "found_by_pdf_path": bool(pdf_matches),
        "task_match_count": len(task_matches),
        "pdf_match_count": len(pdf_matches),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["found_by_task_id"] and result["found_by_pdf_path"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
