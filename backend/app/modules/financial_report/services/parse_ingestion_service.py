from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from backend.app.clients.parse_lab_client import ParseLabClient
from backend.app.modules.financial_report.schemas.parse_contract import ParseResultManifest
from backend.app.modules.financial_report.services.parsed_document_registry import register_parse_result
from backend.app.modules.financial_report.services.parse_quality_gate import assess_parse_quality


def submit_financial_report_parse(
    pdf_path: str,
    output_root: str | None = None,
    max_pages: int | None = None,
    client: ParseLabClient | None = None,
) -> dict[str, Any]:
    client = client or ParseLabClient()
    return client.submit_document_parse(
        pdf_path=pdf_path,
        output_root=output_root,
        max_pages=max_pages,
        profile="financial_report_v1_1",
        use_docling=False,
        enable_visual_table_route=True,
        enable_cross_page_table_detection=True,
        enable_open_source_enhancers=True,
    )


TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


def poll_parse_task(
    task_id: str,
    timeout_seconds: int = 1200,
    interval_seconds: int = 5,
    client: ParseLabClient | None = None,
) -> dict[str, Any]:
    client = client or ParseLabClient()
    deadline = time.monotonic() + timeout_seconds
    last_status: dict[str, Any] = {}
    while time.monotonic() <= deadline:
        last_status = client.get_task_status(task_id)
        if last_status.get("status") in TERMINAL_STATUSES:
            return last_status
        time.sleep(max(interval_seconds, 1))
    last_status["status"] = last_status.get("status") or "timeout"
    last_status["timeout"] = True
    last_status["timeout_seconds"] = timeout_seconds
    return last_status


def build_result_manifest(task_result: dict[str, Any]) -> ParseResultManifest:
    task = task_result.get("task") or {}
    output_files = task_result.get("output_files") or {}
    task_id = task.get("task_id") or task_result.get("task_id") or ""
    output_dir = task.get("output_dir") or output_files.get("output_dir") or ""
    return ParseResultManifest(
        task_id=task_id,
        output_dir=output_dir,
        summary_path=output_files.get("summary", str(Path(output_dir) / "summary.json")),
        pages_jsonl_path=output_files.get("pages", str(Path(output_dir) / "pages.jsonl")),
        merged_md_path=output_files.get("merged", str(Path(output_dir) / "merged.md")),
        tables_json_path=output_files.get("tables", str(Path(output_dir) / "tables.json")),
        merged_tables_json_path=output_files.get("merged_tables", str(Path(output_dir) / "merged_tables.json")),
        quality_flags_path=output_files.get("quality_flags", str(Path(output_dir) / "quality_flags.json")),
        cross_page_candidates_path=output_files.get(
            "cross_page_table_candidates",
            str(Path(output_dir) / "cross_page_table_candidates.jsonl"),
        ),
    )


def ingest_parse_result_manifest(task_id: str, client: ParseLabClient | None = None) -> dict[str, Any]:
    client = client or ParseLabClient()
    task_result = client.get_task_result(task_id)
    manifest = build_result_manifest(task_result)
    summary = task_result.get("summary") or _load_json_if_exists(manifest.summary_path)
    quality_flags = task_result.get("quality_flags") or _load_json_if_exists(manifest.quality_flags_path)
    pages_count = _count_jsonl_rows(manifest.pages_jsonl_path)
    assessment = assess_parse_quality(summary, quality_flags, pages_count, merged_md_path=manifest.merged_md_path)
    return {
        "manifest": manifest.model_dump(),
        "quality_assessment": assessment.model_dump(),
        "raw_task_result": task_result,
    }


def ingest_and_register_parse_result(
    task_id: str,
    pdf_path: str,
    client: ParseLabClient | None = None,
) -> dict[str, Any]:
    ingested = ingest_parse_result_manifest(task_id, client=client)
    registry_entry = register_parse_result(
        pdf_path=pdf_path,
        task_id=task_id,
        manifest=ingested["manifest"],
        quality_assessment=ingested["quality_assessment"],
        raw_task_result=ingested["raw_task_result"],
    )
    return registry_entry


def _load_json_if_exists(path: str) -> dict[str, Any]:
    file_path = Path(path)
    if not file_path.exists():
        return {}
    return json.loads(file_path.read_text(encoding="utf-8"))


def _count_jsonl_rows(path: str) -> int | None:
    file_path = Path(path)
    if not file_path.exists():
        return None
    with file_path.open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())
