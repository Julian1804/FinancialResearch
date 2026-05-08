from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.app.modules.financial_report.services.parsed_document_registry import (
    load_registry_entries,
)


PROJECT_ROOT = Path(__file__).resolve().parents[5]
REVIEW_DECISION_PATH = PROJECT_ROOT / "runtime" / "financial_report" / "parse_review_decisions.jsonl"

VALID_REVIEW_DECISIONS = {
    "pending_review",
    "approved_for_extraction",
    "approved_with_warnings",
    "rejected",
    "needs_reparse",
    "ignored",
}


def get_review_decision_path() -> Path:
    return REVIEW_DECISION_PATH


def load_review_decisions() -> list[dict[str, Any]]:
    path = get_review_decision_path()
    if not path.exists():
        return []
    decisions: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                decisions.append(json.loads(line))
    return decisions


def upsert_review_decision(decision: dict[str, Any]) -> dict[str, Any]:
    path = get_review_decision_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    normalized = _normalize_decision(decision)
    document_id = normalized["document_id"]
    decisions = load_review_decisions()
    next_decisions = [item for item in decisions if item.get("document_id") != document_id]
    next_decisions.append(normalized)

    with path.open("w", encoding="utf-8") as handle:
        for item in next_decisions:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    return normalized


def find_decision_by_document_id(document_id: str) -> dict[str, Any] | None:
    for decision in reversed(load_review_decisions()):
        if decision.get("document_id") == document_id:
            return decision
    return None


def list_review_decisions(limit: int = 100, status: str | None = None) -> list[dict[str, Any]]:
    decisions = load_review_decisions()
    if status:
        decisions = [decision for decision in decisions if decision.get("review_decision") == status]
    decisions = sorted(decisions, key=lambda item: item.get("updated_at", ""), reverse=True)
    return decisions[: max(limit, 0)]


def create_or_update_review_decision(
    document_id: str,
    review_decision: str,
    reviewer: str | None = None,
    review_notes: str | None = None,
) -> dict[str, Any]:
    entry = _find_registry_entry_by_document_id(document_id)
    if not entry:
        raise ValueError(f"document_id not found in parsed document registry: {document_id}")

    existing = find_decision_by_document_id(document_id)
    now = _utc_now()
    decision = {
        "decision_id": existing.get("decision_id") if existing else _decision_id(document_id),
        "document_id": document_id,
        "parse_task_id": entry.get("parse_task_id", ""),
        "pdf_name": entry.get("pdf_name", ""),
        "review_decision": review_decision,
        "reviewer": reviewer or "local_user",
        "review_notes": review_notes or "",
        "approved_for_extraction": review_decision in {"approved_for_extraction", "approved_with_warnings"},
        "requires_manual_check": review_decision in {"pending_review", "rejected", "needs_reparse", "ignored"},
        "decided_at": existing.get("decided_at") if existing else now,
        "updated_at": now,
    }
    return upsert_review_decision(decision)


def get_extraction_eligibility(document_id: str) -> dict[str, Any]:
    entry = _find_registry_entry_by_document_id(document_id)
    decision = find_decision_by_document_id(document_id)
    missing_files = _missing_required_files(entry) if entry else ["registry_entry"]
    parse_quality_level = entry.get("parse_quality_level", "") if entry else ""
    review_decision = decision.get("review_decision", "pending_review") if decision else "pending_review"

    eligible = True
    reasons: list[str] = []
    if not entry:
        eligible = False
        reasons.append("registry entry not found")
    if parse_quality_level == "failed":
        eligible = False
        reasons.append("parse_quality_level=failed")
    if review_decision in {"pending_review", "rejected", "needs_reparse", "ignored"}:
        eligible = False
        reasons.append(f"review_decision={review_decision}")
    if not decision or not decision.get("approved_for_extraction"):
        eligible = False
        reasons.append("approved_for_extraction=false")
    if missing_files:
        eligible = False
        reasons.append(f"missing_required_files={missing_files}")

    return {
        "document_id": document_id,
        "eligible_for_extraction": eligible,
        "reason": "; ".join(reasons) if reasons else "approved for extraction",
        "parse_quality_level": parse_quality_level,
        "review_decision": review_decision,
        "output_dir": entry.get("output_dir", "") if entry else "",
        "required_files_present": not missing_files,
        "missing_required_files": missing_files,
    }


def _normalize_decision(decision: dict[str, Any]) -> dict[str, Any]:
    review_decision = decision.get("review_decision") or "pending_review"
    if review_decision not in VALID_REVIEW_DECISIONS:
        raise ValueError(f"invalid review_decision: {review_decision}")

    document_id = decision.get("document_id")
    if not document_id:
        raise ValueError("document_id is required")

    now = _utc_now()
    return {
        "decision_id": decision.get("decision_id") or _decision_id(document_id),
        "document_id": document_id,
        "parse_task_id": decision.get("parse_task_id", ""),
        "pdf_name": decision.get("pdf_name", ""),
        "review_decision": review_decision,
        "reviewer": decision.get("reviewer") or "local_user",
        "review_notes": decision.get("review_notes") or "",
        "approved_for_extraction": review_decision in {"approved_for_extraction", "approved_with_warnings"},
        "requires_manual_check": review_decision in {"pending_review", "rejected", "needs_reparse", "ignored"},
        "decided_at": decision.get("decided_at") or now,
        "updated_at": decision.get("updated_at") or now,
    }


def _find_registry_entry_by_document_id(document_id: str) -> dict[str, Any] | None:
    for entry in load_registry_entries():
        if entry.get("document_id") == document_id:
            return entry
    return None


def _missing_required_files(entry: dict[str, Any] | None) -> list[str]:
    if not entry:
        return ["registry_entry"]
    keys = [
        "summary_path",
        "pages_jsonl_path",
        "merged_md_path",
        "tables_json_path",
        "merged_tables_json_path",
        "quality_flags_path",
    ]
    missing = []
    for key in keys:
        value = entry.get(key)
        if not value or not Path(value).exists():
            missing.append(key)
    return missing


def _decision_id(document_id: str) -> str:
    digest = hashlib.sha1(document_id.encode("utf-8", errors="ignore")).hexdigest()[:16]
    return f"parse_review_decision_{digest}"


def _utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"
