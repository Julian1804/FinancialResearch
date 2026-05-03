from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[5]
REGISTRY_PATH = PROJECT_ROOT / "runtime" / "financial_report" / "parsed_document_registry.jsonl"


def get_registry_path() -> Path:
    return REGISTRY_PATH


def load_registry_entries() -> list[dict[str, Any]]:
    path = get_registry_path()
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def append_registry_entry(entry: dict[str, Any]) -> dict[str, Any]:
    path = get_registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def list_registry_entries(limit: int = 100, parse_quality_level: str | None = None) -> list[dict[str, Any]]:
    entries = load_registry_entries()
    if parse_quality_level:
        entries = [entry for entry in entries if entry.get("parse_quality_level") == parse_quality_level]
    entries = sorted(entries, key=lambda item: item.get("registered_at", ""), reverse=True)
    return entries[: max(limit, 0)]


def upsert_registry_entry(entry: dict[str, Any]) -> dict[str, Any]:
    path = get_registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = load_registry_entries()
    task_id = entry.get("parse_task_id")
    replaced = False
    next_entries: list[dict[str, Any]] = []
    for existing in entries:
        if task_id and existing.get("parse_task_id") == task_id:
            next_entries.append(entry)
            replaced = True
        else:
            next_entries.append(existing)
    if not replaced:
        next_entries.append(entry)
    _write_registry_entries(next_entries)
    return entry


def find_by_pdf_path(pdf_path: str) -> list[dict[str, Any]]:
    normalized = str(Path(pdf_path))
    return [entry for entry in load_registry_entries() if entry.get("pdf_path") == normalized]


def find_by_task_id(task_id: str) -> list[dict[str, Any]]:
    return [entry for entry in load_registry_entries() if entry.get("parse_task_id") == task_id]


def register_parse_result(
    pdf_path: str,
    task_id: str,
    manifest: dict[str, Any],
    quality_assessment: dict[str, Any],
    raw_task_result: dict[str, Any],
) -> dict[str, Any]:
    pdf = Path(pdf_path)
    task = raw_task_result.get("task") or {}
    summary = raw_task_result.get("summary") or {}
    document_id = _document_id(pdf_path, task_id)
    entry = {
        "document_id": document_id,
        "pdf_path": str(pdf),
        "pdf_name": pdf.name,
        "parse_task_id": task_id,
        "parse_status": task.get("status") or raw_task_result.get("status") or "",
        "parse_quality_level": quality_assessment.get("parse_quality_level", ""),
        "parse_quality_reasons": quality_assessment.get("parse_quality_reasons", []),
        "output_dir": manifest.get("output_dir", ""),
        "summary_path": manifest.get("summary_path", ""),
        "pages_jsonl_path": manifest.get("pages_jsonl_path", ""),
        "merged_md_path": manifest.get("merged_md_path", ""),
        "tables_json_path": manifest.get("tables_json_path", ""),
        "merged_tables_json_path": manifest.get("merged_tables_json_path", ""),
        "quality_flags_path": manifest.get("quality_flags_path", ""),
        "cross_page_candidates_path": manifest.get("cross_page_candidates_path", ""),
        "total_pages": quality_assessment.get("total_pages", summary.get("total_pages", 0)),
        "failed_pages_count": quality_assessment.get("failed_pages_count", 0),
        "empty_pages_count": quality_assessment.get("empty_pages_count", 0),
        "heavy_parser_ratio": quality_assessment.get("heavy_parser_ratio", 0.0),
        "ocr_ratio": quality_assessment.get("ocr_ratio", 0.0),
        "visual_table_route_pages_count": quality_assessment.get("visual_table_route_pages_count", 0),
        "cross_page_table_candidate_count": quality_assessment.get("cross_page_table_candidate_count", 0),
        "merged_table_count": quality_assessment.get("merged_table_count", 0),
        "registered_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }
    return upsert_registry_entry(entry)


def _document_id(pdf_path: str, task_id: str) -> str:
    digest = hashlib.sha1(f"{pdf_path}|{task_id}".encode("utf-8", errors="ignore")).hexdigest()[:16]
    return f"parsed_doc_{digest}"


def _write_registry_entries(entries: list[dict[str, Any]]) -> None:
    path = get_registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
