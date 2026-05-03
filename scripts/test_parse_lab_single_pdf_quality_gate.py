from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.modules.financial_report.services.parse_ingestion_service import (  # noqa: E402
    ingest_parse_result_manifest,
    poll_parse_task,
    submit_financial_report_parse,
)


TEST_PDF = Path("D:/workspace/parse_lab/test_data/" + "\u534e\u94b0\u77ff\u4e1a2025\u5e74\u4e00\u5b63\u62a5\u544a.pdf")


def main() -> int:
    submitted = submit_financial_report_parse(str(TEST_PDF))
    task_id = submitted["task_id"]
    final_status = poll_parse_task(task_id, timeout_seconds=1200, interval_seconds=10)
    payload = {
        "task_id": task_id,
        "status": final_status.get("status"),
        "output_dir": final_status.get("output_dir"),
        "elapsed_seconds": final_status.get("elapsed_seconds"),
    }

    if final_status.get("status") == "completed":
        ingested = ingest_parse_result_manifest(task_id)
        manifest = ingested["manifest"]
        assessment = ingested["quality_assessment"]
        payload.update(
            {
                "summary_path": manifest["summary_path"],
                "merged_md_path": manifest["merged_md_path"],
                "tables_json_path": manifest["tables_json_path"],
                "merged_tables_json_path": manifest["merged_tables_json_path"],
                "quality_flags_path": manifest["quality_flags_path"],
                "cross_page_candidates_path": manifest["cross_page_candidates_path"],
                "parse_quality_level": assessment["parse_quality_level"],
                "parse_quality_reasons": assessment["parse_quality_reasons"],
                "quality_assessment": assessment,
            }
        )
    else:
        payload["error_tail"] = final_status.get("error_tail", "")

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if final_status.get("status") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
