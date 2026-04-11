from pathlib import Path
from typing import Dict, List

from config.settings import SCHEMA_VERSION
from services.period_service import period_sort_tuple
from services.sqlite_index_service import initialize_sqlite, replace_company_chunks, upsert_company_document
from utils.file_utils import (
    build_forecast_registry_path,
    build_index_json_path,
    build_metric_registry_path,
    build_qa_chunks_path,
    build_timeline_json_path,
    get_extracted_json_files_in_company_folder,
    get_forecast_snapshot_files_in_company_folder,
    get_pdf_files_in_company_folder,
    get_report_json_files_in_company_folder,
    load_json_file,
    save_json_file,
    sort_paths_by_year_and_name,
)


SOURCE_TYPE_ORDER = {
    "extracted": 1,
    "report": 2,
    "forecast_snapshot": 3,
    "forecast_check": 4,
    "parsed": 5,
    "unknown": 9,
}


def _safe_load_json(path: str) -> dict:
    try:
        return load_json_file(path)
    except Exception:
        return {}


def _build_source_doc_id(source_type: str, source_file: str, period_key: str, material_timestamp: str = "") -> str:
    source_file = source_file or "unknown"
    period_key = period_key or "NO_PERIOD"
    material_timestamp = material_timestamp or "NO_TS"
    return f"{source_type}::{period_key}::{material_timestamp}::{source_file}"


def _detect_source_type_from_name(file_name: str) -> str:
    lower = file_name.lower()
    if lower.startswith("parsed_"):
        return "parsed"
    if lower.startswith("extracted_"):
        return "extracted"
    if lower.startswith("report_") or lower.startswith("delta_") or lower.startswith("master_report"):
        return "report"
    if lower.startswith("forecast_check_"):
        return "forecast_check"
    if lower.startswith("forecast_snapshot_"):
        return "forecast_snapshot"
    return "unknown"


def _flatten_for_chunk(obj, prefix="") -> List[str]:
    results: List[str] = []

    if isinstance(obj, dict):
        for key, value in obj.items():
            next_prefix = f"{prefix}.{key}" if prefix else str(key)
            results.extend(_flatten_for_chunk(value, next_prefix))
        return results

    if isinstance(obj, list):
        for idx, item in enumerate(obj):
            next_prefix = f"{prefix}[{idx}]"
            results.extend(_flatten_for_chunk(item, next_prefix))
        return results

    if obj is None:
        return results

    text = str(obj).strip()
    if text:
        results.append(f"{prefix}: {text}" if prefix else text)
    return results


def _chunk_text(text: str, chunk_size: int = 900, overlap: int = 120) -> List[str]:
    text = (text or "").strip()
    if not text:
        return []

    chunks = []
    start = 0
    length = len(text)

    while start < length:
        end = min(length, start + chunk_size)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= length:
            break
        start = max(end - overlap, start + 1)

    return chunks


def _build_chunks_from_artifact(company_name: str, source_type: str, file_path: str, data: dict) -> List[dict]:
    source_file = data.get("source_file") or data.get("company_name") or Path(file_path).name
    period_key = data.get("period_key", "") or data.get("forecast_as_of_period", "")
    report_type = data.get("report_type", "") or data.get("anchor_report_type", "")
    document_type = data.get("document_type", "") or ("forecast_snapshot" if source_type == "forecast_snapshot" else "")
    material_timestamp = data.get("material_timestamp", "") or data.get("generated_at", "")
    source_doc_id = _build_source_doc_id(source_type, source_file, period_key, material_timestamp)

    title = source_file
    if source_type == "forecast_snapshot":
        title = f"{data.get('metric_name', '')} | {data.get('forecast_as_of_period', '')} -> {data.get('forecast_target_period', '')}"

    text_candidates: List[str] = []
    if source_type == "parsed":
        text_candidates.append(data.get("full_text", ""))
    else:
        text_candidates.append("\n".join(_flatten_for_chunk(data)))

    merged_text = "\n".join([item for item in text_candidates if item]).strip()
    split_chunks = _chunk_text(merged_text)

    chunks = []
    for idx, chunk_text in enumerate(split_chunks):
        chunks.append({
            "company_name": company_name,
            "source_doc_id": source_doc_id,
            "chunk_id": f"{source_doc_id}::chunk_{idx + 1}",
            "title": title,
            "source_type": source_type,
            "report_type": report_type,
            "period_key": period_key,
            "document_type": document_type,
            "chunk_text": chunk_text,
            "meta": {
                "source_file": source_file,
                "json_path": str(file_path),
                "chunk_index": idx + 1,
                "material_timestamp": material_timestamp,
                "material_timestamp_precision": data.get("material_timestamp_precision", ""),
                "report_date": data.get("report_date", ""),
            },
            "updated_at": data.get("generated_at", ""),
        })
    return chunks


def _build_document_record(company_name: str, source_type: str, file_path: str, data: dict) -> dict:
    source_file = data.get("source_file") or data.get("company_name") or Path(file_path).name
    period_key = data.get("period_key", "") or data.get("forecast_as_of_period", "")
    material_timestamp = data.get("material_timestamp", "") or data.get("generated_at", "")
    return {
        "company_name": company_name,
        "source_doc_id": _build_source_doc_id(source_type, source_file, period_key, material_timestamp),
        "source_file": source_file,
        "title": source_file,
        "source_type": source_type,
        "report_type": data.get("report_type", "") or data.get("anchor_report_type", ""),
        "period_key": period_key,
        "document_type": data.get("document_type", "") or ("forecast_snapshot" if source_type == "forecast_snapshot" else ""),
        "report_date": data.get("report_date", "") or data.get("generated_at", ""),
        "material_timestamp": material_timestamp,
        "material_timestamp_precision": data.get("material_timestamp_precision", ""),
        "is_primary_financial_report": data.get("is_primary_financial_report", False),
        "can_adjust_forecast": data.get("can_adjust_forecast", False),
        "json_path": str(file_path),
        "updated_at": data.get("generated_at", ""),
    }


def _timeline_sort_key(row: dict):
    return (
        period_sort_tuple(row.get("period_key", "")),
        row.get("material_timestamp", "") or "",
        SOURCE_TYPE_ORDER.get(row.get("source_type", "unknown"), 99),
        row.get("source_file", "") or "",
    )


def _extract_timeline_rows(extracted_files: List[str], report_files: List[str], forecast_snapshot_files: List[str]) -> List[dict]:
    rows: List[dict] = []

    for file_path in extracted_files:
        data = _safe_load_json(file_path)
        rows.append({
            "source_type": "extracted",
            "source_file": data.get("source_file", Path(file_path).name),
            "period_key": data.get("period_key", ""),
            "report_type": data.get("report_type", ""),
            "document_type": data.get("document_type", ""),
            "material_timestamp": data.get("material_timestamp", ""),
            "material_timestamp_precision": data.get("material_timestamp_precision", ""),
            "report_date": data.get("report_date", ""),
            "is_primary_financial_report": data.get("is_primary_financial_report", False),
            "forecast_as_of_period": data.get("forecast_as_of_period", ""),
            "forecast_target_period": data.get("forecast_target_period", ""),
            "json_path": str(file_path),
        })

    for file_path in report_files:
        data = _safe_load_json(file_path)
        rows.append({
            "source_type": "report",
            "source_file": data.get("source_file", Path(file_path).name),
            "period_key": data.get("period_key", ""),
            "report_type": data.get("report_type", ""),
            "document_type": data.get("document_type", ""),
            "material_timestamp": data.get("material_timestamp", "") or data.get("generated_at", ""),
            "material_timestamp_precision": data.get("material_timestamp_precision", ""),
            "report_date": data.get("report_date", "") or data.get("generated_at", ""),
            "is_primary_financial_report": data.get("is_primary_financial_report", False),
            "forecast_as_of_period": data.get("forecast_as_of_period", ""),
            "forecast_target_period": data.get("forecast_target_period", ""),
            "json_path": str(file_path),
        })

    for file_path in forecast_snapshot_files:
        data = _safe_load_json(file_path)
        rows.append({
            "source_type": "forecast_snapshot",
            "source_file": f"{data.get('metric_name', '')} | {data.get('forecast_as_of_period', '')}->{data.get('forecast_target_period', '')}",
            "period_key": data.get("forecast_as_of_period", ""),
            "report_type": data.get("anchor_report_type", ""),
            "document_type": "forecast_snapshot",
            "material_timestamp": data.get("generated_at", ""),
            "material_timestamp_precision": "day",
            "report_date": data.get("generated_at", ""),
            "is_primary_financial_report": False,
            "forecast_as_of_period": data.get("forecast_as_of_period", ""),
            "forecast_target_period": data.get("forecast_target_period", ""),
            "json_path": str(file_path),
        })

    rows.sort(key=_timeline_sort_key)
    return rows


def refresh_company_repository(company_folder: str | Path) -> Dict:
    initialize_sqlite()

    company_folder = Path(company_folder)
    company_name = company_folder.name

    raw_pdfs = sort_paths_by_year_and_name(get_pdf_files_in_company_folder(company_folder))
    parsed_files = []
    extracted_files = sort_paths_by_year_and_name(get_extracted_json_files_in_company_folder(company_folder))
    report_files = sort_paths_by_year_and_name(get_report_json_files_in_company_folder(company_folder))
    forecast_snapshot_files = sort_paths_by_year_and_name(get_forecast_snapshot_files_in_company_folder(company_folder))

    forecast_check_files = []
    analysis_folder = company_folder / "年报分析"
    if analysis_folder.exists():
        forecast_check_files = sorted(str(p) for p in analysis_folder.glob("forecast_check_*.json"))
        parsed_files = sorted(str(p) for p in (company_folder / "年报解析").glob("parsed_*.json")) if (company_folder / "年报解析").exists() else []

    all_json_files = [
        *parsed_files,
        *extracted_files,
        *report_files,
        *forecast_check_files,
        *forecast_snapshot_files,
    ]

    chunk_payload = []
    for file_path in all_json_files:
        data = _safe_load_json(file_path)
        source_type = _detect_source_type_from_name(Path(file_path).name)
        doc_record = _build_document_record(company_name, source_type, file_path, data)
        upsert_company_document(doc_record)
        chunk_payload.extend(_build_chunks_from_artifact(company_name, source_type, file_path, data))

    replace_company_chunks(company_name, chunk_payload)

    save_json_file(
        {
            "schema_version": SCHEMA_VERSION,
            "company_name": company_name,
            "chunk_count": len(chunk_payload),
            "chunks": chunk_payload,
        },
        build_qa_chunks_path(company_folder),
    )

    timeline_rows = _extract_timeline_rows(extracted_files, report_files, forecast_snapshot_files)
    save_json_file(
        {
            "schema_version": SCHEMA_VERSION,
            "company_name": company_name,
            "timeline": timeline_rows,
        },
        build_timeline_json_path(company_folder),
    )

    standardized_metrics_exists = (company_folder / "年报分析" / "standardized_metrics.json").exists()
    metric_extraction_registry_exists = (company_folder / "年报分析" / "metric_extraction_registry.json").exists()
    actual_metrics_registry_exists = (company_folder / "年报分析" / "actual_metrics_registry.json").exists()

    index_payload = {
        "schema_version": SCHEMA_VERSION,
        "company_name": company_name,
        "summary": {
            "raw_pdfs": len(raw_pdfs),
            "parsed_json": len(parsed_files),
            "extracted_json": len(extracted_files),
            "report_json": len(report_files),
            "forecast_check_json": len(forecast_check_files),
            "forecast_snapshot_json": len(forecast_snapshot_files),
            "metric_registry_exists": Path(build_metric_registry_path(company_folder)).exists(),
            "forecast_registry_exists": Path(build_forecast_registry_path(company_folder)).exists(),
            "standardized_metrics_exists": standardized_metrics_exists,
            "metric_extraction_registry_exists": metric_extraction_registry_exists,
            "actual_metrics_registry_exists": actual_metrics_registry_exists,
            "retrieval_chunks": len(chunk_payload),
            "documents": len(all_json_files),
        },
        "files": {
            "raw_pdfs": raw_pdfs,
            "parsed_json": parsed_files,
            "extracted_json": extracted_files,
            "report_json": report_files,
            "forecast_check_json": forecast_check_files,
            "forecast_snapshot_json": forecast_snapshot_files,
        },
        "timeline": timeline_rows,
    }
    save_json_file(index_payload, build_index_json_path(company_folder))
    return index_payload


def load_company_repository_snapshot(company_folder: str | Path) -> Dict:
    company_folder = Path(company_folder)
    index_path = build_index_json_path(company_folder)
    timeline_path = build_timeline_json_path(company_folder)

    index_data = _safe_load_json(index_path) if Path(index_path).exists() else {}
    timeline_data = _safe_load_json(timeline_path) if Path(timeline_path).exists() else {}

    return {
        "company_name": company_folder.name,
        "summary": index_data.get("summary", {}),
        "files": index_data.get("files", {}),
        "timeline": timeline_data.get("timeline", index_data.get("timeline", [])),
    }
