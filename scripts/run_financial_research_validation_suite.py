from __future__ import annotations

import csv
import json
import py_compile
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib import request


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.clients.parse_lab_client import ParseLabClient, ParseLabClientError
from backend.app.modules.financial_report.services.financial_table_candidate_service import (
    build_extraction_candidate_set,
    summarize_candidate_set,
)
from backend.app.modules.financial_report.services.minimal_financial_extraction_service import (
    build_minimal_financial_extraction,
)
from backend.app.modules.financial_report.services.parse_quality_gate import assess_parse_quality
from backend.app.modules.financial_report.services.parse_review_decision_service import (
    get_extraction_eligibility,
    load_review_decisions,
)
from backend.app.modules.financial_report.services.parse_review_queue import build_review_queue
from backend.app.modules.financial_report.services.parsed_document_registry import (
    get_registry_path,
    load_registry_entries,
)
from backend.app.modules.financial_report.services.statement_field_mapping_service import (
    build_statement_mapping_result,
)
from backend.app.modules.financial_report.services.table_normalization_service import (
    normalize_parse_lab_tables,
)


OUTPUT_DIR = PROJECT_ROOT / "runtime" / "financial_report" / "validation_suite"
BACKEND_HEALTH_URL = "http://127.0.0.1:8030/api/health"


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    checks: list[dict[str, Any]] = []
    context: dict[str, Any] = {}

    checks.append(repository_hygiene_check())
    checks.append(python_compile_check())
    checks.append(backend_health_check())
    checks.append(parse_lab_connectivity_check())
    checks.append(registry_check(context))
    checks.append(quality_gate_check(context))
    checks.append(review_decision_eligibility_check(context))
    checks.append(table_normalization_check(context))
    checks.append(extraction_candidate_check(context))
    checks.append(statement_field_mapping_check(context))
    checks.append(minimal_extraction_check(context))

    status_counts = Counter(check["status"] for check in checks)
    failures = [check for check in checks if check["status"] == "failed"]
    high_risk_items_count = int(context.get("high_risk_items_count") or 0)
    results = {
        "generated_at": _now(),
        "checks": checks,
        "passed_count": status_counts.get("passed", 0),
        "failed_count": status_counts.get("failed", 0),
        "skipped_count": status_counts.get("skipped", 0),
        "warnings_count": status_counts.get("warning", 0),
        "registry_count": int(context.get("registry_count") or 0),
        "review_queue_count": int(context.get("review_queue_count") or 0),
        "eligible_documents_count": int(context.get("eligible_documents_count") or 0),
        "dry_run_documents_count": int(context.get("dry_run_documents_count") or 0),
        "high_risk_items_count": high_risk_items_count,
    }
    _write_outputs(results, failures, context)
    print(json.dumps({k: v for k, v in results.items() if k != "checks"}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


def repository_hygiene_check() -> dict[str, Any]:
    branch = _git(["branch", "--show-current"]).strip()
    status = _git(["status", "--porcelain=v1"]).splitlines()
    forbidden_patterns = ["runtime/", "__pycache__/", ".pyc", ".env", ".venv/"]
    forbidden = []
    for line in status:
        path = line[3:] if len(line) > 3 else line
        if any(pattern in path for pattern in forbidden_patterns):
            forbidden.append(line)
    return _check(
        "repository_hygiene",
        "failed" if forbidden else "passed",
        {
            "branch": branch,
            "forbidden_status_entries": forbidden,
            "status_entry_count": len(status),
        },
    )


def python_compile_check() -> dict[str, Any]:
    roots = [PROJECT_ROOT / "backend" / "app", PROJECT_ROOT / "scripts"]
    files = [
        path
        for root in roots
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts and "runtime" not in path.parts and ".venv" not in path.parts
    ]
    errors = []
    for path in files:
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            errors.append({"path": str(path), "error": str(exc)})
    return _check("python_compile", "failed" if errors else "passed", {"compiled_files": len(files), "errors": errors})


def backend_health_check() -> dict[str, Any]:
    try:
        with request.urlopen(BACKEND_HEALTH_URL, timeout=5) as response:
            body = json.loads(response.read().decode("utf-8"))
        status = "passed" if body.get("status") == "ok" else "warning"
        return _check("backend_health", status, {"url": BACKEND_HEALTH_URL, "response": body})
    except Exception as exc:
        return _check("backend_health", "skipped", {"url": BACKEND_HEALTH_URL, "reason": str(exc)})


def parse_lab_connectivity_check() -> dict[str, Any]:
    client = ParseLabClient(timeout_seconds=10)
    try:
        health = client.get_health()
        tasks = client.list_tasks()
        return _check(
            "parse_lab_connectivity",
            "passed",
            {"base_url": client.base_url, "health": health, "tasks_response_keys": sorted(tasks.keys())},
        )
    except ParseLabClientError as exc:
        return _check("parse_lab_connectivity", "skipped", {"base_url": client.base_url, "reason": str(exc)})


def registry_check(context: dict[str, Any]) -> dict[str, Any]:
    path = get_registry_path()
    errors: list[str] = []
    entries: list[dict[str, Any]] = []
    try:
        entries = load_registry_entries()
    except Exception as exc:
        errors.append(f"registry JSONL parse failed: {exc}")
    task_ids = [entry.get("parse_task_id") for entry in entries if entry.get("parse_task_id")]
    duplicates = [task_id for task_id, count in Counter(task_ids).items() if count > 1]
    if duplicates:
        errors.append(f"duplicate task_id: {duplicates}")
    required = ["summary_path", "pages_jsonl_path", "merged_md_path", "tables_json_path", "merged_tables_json_path", "quality_flags_path"]
    missing_by_doc = {}
    for entry in entries:
        missing = []
        if not entry.get("output_dir") or not Path(entry["output_dir"]).exists():
            missing.append("output_dir")
        for key in required:
            if not entry.get(key) or not Path(entry[key]).exists():
                missing.append(key)
        if missing:
            missing_by_doc[entry.get("document_id", "")] = missing
    if missing_by_doc:
        errors.append("missing output files")
    context["registry_entries"] = entries
    context["registry_count"] = len(entries)
    return _check(
        "registry",
        "failed" if errors else "passed",
        {"registry_path": str(path), "registry_count": len(entries), "duplicates": duplicates, "missing_by_doc": missing_by_doc, "errors": errors},
    )


def quality_gate_check(context: dict[str, Any]) -> dict[str, Any]:
    details = []
    errors = []
    for entry in context.get("registry_entries", []):
        summary = _load_json(entry.get("summary_path", ""))
        quality_flags = _load_json(entry.get("quality_flags_path", ""))
        pages_count = _count_jsonl(entry.get("pages_jsonl_path", ""))
        assessment = assess_parse_quality(summary, quality_flags, pages_count, entry.get("merged_md_path"))
        merged_non_empty = Path(entry.get("merged_md_path", "")).exists() and bool(Path(entry.get("merged_md_path", "")).read_text(encoding="utf-8", errors="ignore").strip())
        if not assessment.parse_quality_level:
            errors.append(f"{entry.get('document_id')}: missing parse_quality_level")
        if pages_count != int(summary.get("total_pages") or -1):
            errors.append(f"{entry.get('document_id')}: pages_count mismatch")
        if not merged_non_empty:
            errors.append(f"{entry.get('document_id')}: merged.md empty or missing")
        details.append({"document_id": entry.get("document_id"), "pages_count": pages_count, "summary_total_pages": summary.get("total_pages"), "assessment": _dump_model(assessment), "merged_non_empty": merged_non_empty})
    return _check("quality_gate", "failed" if errors else "passed", {"documents": details, "errors": errors})


def review_decision_eligibility_check(context: dict[str, Any]) -> dict[str, Any]:
    queue = build_review_queue(limit=1000)
    decisions = load_review_decisions()
    errors = []
    eligible_count = 0
    details = []
    for item in queue:
        document_id = item["document_id"]
        eligibility = get_extraction_eligibility(document_id)
        decision = eligibility.get("review_decision")
        eligible = bool(eligibility.get("eligible_for_extraction"))
        if eligible:
            eligible_count += 1
        if decision in {"pending_review", "needs_reparse", "rejected", "ignored"} and eligible:
            errors.append(f"{document_id}: {decision} must not be eligible")
        if decision in {"approved_for_extraction", "approved_with_warnings"} and not eligible and eligibility.get("required_files_present"):
            errors.append(f"{document_id}: approved decision should be eligible when files are present")
        details.append({"document_id": document_id, "review_decision": decision, "eligible": eligible, "reason": eligibility.get("reason")})
    context["review_queue_count"] = len(queue)
    context["eligible_documents_count"] = eligible_count
    return _check("review_decision_eligibility", "failed" if errors else "passed", {"review_queue_count": len(queue), "decision_count": len(decisions), "eligible_documents_count": eligible_count, "documents": details, "errors": errors})


def table_normalization_check(context: dict[str, Any]) -> dict[str, Any]:
    docs = []
    errors = []
    for entry in context.get("registry_entries", []):
        manifest = _manifest(entry)
        result = normalize_parse_lab_tables(manifest)
        source_pages_missing = sum(1 for table in result.tables if not table.source.source_pages)
        table_group_count = sum(1 for table in result.tables if table.source.table_group_id)
        if result.errors:
            errors.extend([f"{entry.get('document_id')}: {error}" for error in result.errors])
        docs.append({"document_id": entry.get("document_id"), "canonical_tables_count": len(result.tables), "source_pages_missing": source_pages_missing, "table_group_id_count": table_group_count, "warnings": result.warnings, "errors": result.errors})
    return _check("table_normalization", "failed" if errors else "passed", {"documents": docs, "errors": errors})


def extraction_candidate_check(context: dict[str, Any]) -> dict[str, Any]:
    docs = []
    errors = []
    dry_run_count = 0
    for entry in context.get("registry_entries", []):
        document_id = entry.get("document_id", "")
        normal = build_extraction_candidate_set(document_id, allow_override=False)
        eligibility = get_extraction_eligibility(document_id)
        if not eligibility.get("eligible_for_extraction") and normal.extraction_mode != "blocked":
            errors.append(f"{document_id}: non-eligible normal candidate set must be blocked")
        dry = build_extraction_candidate_set(document_id, allow_override=True)
        dry_run_count += 1
        docs.append({"document_id": document_id, "normal_mode": normal.extraction_mode, "dry_run": summarize_candidate_set(dry)})
    context["dry_run_documents_count"] = dry_run_count
    return _check("extraction_candidates", "failed" if errors else "passed", {"documents": docs, "errors": errors})


def statement_field_mapping_check(context: dict[str, Any]) -> dict[str, Any]:
    docs = []
    high_risk = 0
    for entry in context.get("registry_entries", []):
        result = build_statement_mapping_result(entry.get("document_id", ""), allow_override=True)
        fields = result.fields
        avg_conf = round(sum(field.confidence for field in fields) / len(fields), 4) if fields else 0.0
        canonical_counts = Counter(field.canonical_field_name for field in fields)
        unknown_unit = sum(1 for field in fields if field.unit == "unknown")
        unknown_period = sum(1 for field in fields if field.period_label == "unknown_period")
        requires_review = sum(1 for field in fields if field.requires_review)
        high_risk += requires_review
        docs.append({"document_id": result.document_id, "fields_count": len(fields), "canonical_field_name_distribution": dict(canonical_counts), "unknown_unit_count": unknown_unit, "unknown_period_count": unknown_period, "requires_review_count": requires_review, "average_confidence": avg_conf, "warnings": result.warnings, "errors": result.errors})
    context["high_risk_items_count"] = high_risk
    return _check("statement_field_mapping_refinement", "passed", {"documents": docs})


def minimal_extraction_check(context: dict[str, Any]) -> dict[str, Any]:
    docs = []
    errors = []
    for entry in context.get("registry_entries", []):
        result = build_minimal_financial_extraction(entry.get("document_id", ""), allow_override=True)
        fields = [field for statement in result.statements for field in statement.fields]
        docs.append({"document_id": result.document_id, "extraction_mode": result.extraction_mode, "statement_count": len(result.statements), "field_count": len(fields), "periods_detected": sorted({period for statement in result.statements for period in statement.periods_detected}), "requires_review_field_count": sum(1 for field in fields if field.requires_review), "warnings": result.warnings, "errors": result.errors})
        errors.extend([f"{result.document_id}: {error}" for error in result.errors])
    return _check("minimal_extraction_dry_run", "failed" if errors else "passed", {"documents": docs, "errors": errors})


def _write_outputs(results: dict[str, Any], failures: list[dict[str, Any]], context: dict[str, Any]) -> None:
    (OUTPUT_DIR / "validation_suite_results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUT_DIR / "validation_suite_failures.json").write_text(json.dumps(failures, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_md(results)
    with (OUTPUT_DIR / "validation_suite_summary.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["check_name", "status", "machine_determined"])
        writer.writeheader()
        for check in results["checks"]:
            writer.writerow({"check_name": check["check_name"], "status": check["status"], "machine_determined": check["machine_determined"]})


def _write_md(results: dict[str, Any]) -> None:
    lines = [
        "# FinancialResearch Validation Suite Results",
        "",
        f"Generated at: {results['generated_at']}",
        "",
        f"- passed: {results['passed_count']}",
        f"- failed: {results['failed_count']}",
        f"- skipped: {results['skipped_count']}",
        f"- warnings: {results['warnings_count']}",
        f"- registry_count: {results['registry_count']}",
        f"- review_queue_count: {results['review_queue_count']}",
        f"- eligible_documents_count: {results['eligible_documents_count']}",
        f"- dry_run_documents_count: {results['dry_run_documents_count']}",
        f"- high_risk_items_count: {results['high_risk_items_count']}",
        "",
        "## Checks",
        "",
    ]
    for check in results["checks"]:
        lines.extend([f"### {check['check_name']}", "", f"- status: {check['status']}", f"- machine_determined: {check['machine_determined']}", ""])
    (OUTPUT_DIR / "validation_suite_results.md").write_text("\n".join(lines), encoding="utf-8")


def _check(name: str, status: str, details: dict[str, Any]) -> dict[str, Any]:
    return {"check_name": name, "status": status, "details": details, "machine_determined": True}


def _git(args: list[str]) -> str:
    return subprocess.run(["git", *args], cwd=PROJECT_ROOT, text=True, capture_output=True, check=True).stdout


def _load_json(path: str) -> dict[str, Any]:
    if not path or not Path(path).exists():
        return {}
    with Path(path).open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def _count_jsonl(path: str) -> int:
    if not path or not Path(path).exists():
        return 0
    with Path(path).open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def _manifest(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "document_id": entry.get("document_id", ""),
        "task_id": entry.get("parse_task_id", ""),
        "pdf_name": entry.get("pdf_name", ""),
        "pages_jsonl_path": entry.get("pages_jsonl_path", ""),
        "tables_json_path": entry.get("tables_json_path", ""),
        "merged_tables_json_path": entry.get("merged_tables_json_path", ""),
        "quality_flags_path": entry.get("quality_flags_path", ""),
    }


def _dump_model(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return json.loads(model.json())


def _now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


if __name__ == "__main__":
    sys.exit(main())
