from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from backend.app.modules.financial_report.schemas.provisional_fact_contract import (
    CandidateOnlyIngestionResult,
    CandidateOnlyIngestionSummary,
    CandidateOnlyReviewQueueItem,
    ProvisionalFinancialFact,
)


PROJECT_ROOT = Path(__file__).resolve().parents[5]
DEFAULT_PARSE_LAB_EXPORT_DIR = Path(
    r"D:\workspace\runtime\parse_lab\financialresearch_exports\round3_field_candidates"
)
PROVISIONAL_FACT_OUTPUT_DIR = (
    PROJECT_ROOT / "runtime" / "financial_report" / "provisional_facts" / "parse_lab_round3"
)

PROVISIONAL_STATUSES = {"matched", "partially_matched"}
REVIEW_ONLY_STATUSES = {"table_value_missing", "needs_human_review", "conflict"}


def ingest_parse_lab_round3_field_candidates(
    source_dir: Path | str = DEFAULT_PARSE_LAB_EXPORT_DIR,
    output_dir: Path | str = PROVISIONAL_FACT_OUTPUT_DIR,
) -> CandidateOnlyIngestionResult:
    source_dir = Path(source_dir)
    output_dir = Path(output_dir)
    raw_candidates = _load_field_candidates(source_dir)
    raw_review_queue = _load_review_queue(source_dir)

    warnings: list[str] = []
    errors: list[str] = []
    provisional_facts: list[ProvisionalFinancialFact] = []
    review_queue: list[CandidateOnlyReviewQueueItem] = []

    for index, row in enumerate(raw_candidates, start=1):
        status = row.get("validation_status", "")
        if status not in PROVISIONAL_STATUSES:
            warnings.append(f"field_candidate_not_ingested_status={status}: {row.get('field_candidate_id', index)}")
            continue
        fact = _provisional_fact_from_row(row, index)
        validation_errors = _validate_fact(fact)
        if validation_errors:
            errors.extend(validation_errors)
            continue
        provisional_facts.append(fact)

    for index, row in enumerate(raw_review_queue, start=1):
        item = _review_item_from_row(row, index)
        if item.validation_status not in REVIEW_ONLY_STATUSES:
            warnings.append(f"unexpected_review_queue_status={item.validation_status}: {item.review_item_id}")
        review_queue.append(item)

    summary = _build_summary(source_dir, output_dir, provisional_facts, review_queue, warnings, errors)
    result = CandidateOnlyIngestionResult(
        summary=summary,
        provisional_facts=provisional_facts,
        review_queue=review_queue,
    )
    _write_outputs(output_dir, result)
    return result


def summarize_ingestion_result(result: CandidateOnlyIngestionResult) -> dict[str, Any]:
    return _model_dump(result.summary)


def _load_field_candidates(source_dir: Path) -> list[dict[str, Any]]:
    json_path = source_dir / "financialresearch_field_candidates.json"
    jsonl_path = source_dir / "financialresearch_field_candidates.jsonl"
    if json_path.exists():
        payload = _read_json(json_path, {})
        return list(payload.get("items") or [])
    if jsonl_path.exists():
        return _read_jsonl(jsonl_path)
    raise FileNotFoundError(f"field candidates export not found under {source_dir}")


def _load_review_queue(source_dir: Path) -> list[dict[str, Any]]:
    json_path = source_dir / "financialresearch_review_queue.json"
    if not json_path.exists():
        raise FileNotFoundError(f"review queue export not found: {json_path}")
    payload = _read_json(json_path, {})
    return list(payload.get("items") or [])


def _provisional_fact_from_row(row: dict[str, Any], index: int) -> ProvisionalFinancialFact:
    source_page = int(row.get("source_page") or 0)
    provenance = {
        "parse_lab_field_candidate_id": row.get("field_candidate_id", ""),
        "evidence_id": row.get("evidence_id", ""),
        "table_candidate_id": row.get("table_candidate_id", ""),
        "review_id": row.get("review_id", ""),
        "best_candidate_by_text_validation": bool(row.get("best_candidate_by_text_validation")),
        "matched_value_variants": row.get("matched_value_variants") or [],
        "matched_item_tokens": row.get("matched_item_tokens") or [],
        "match_reason": row.get("match_reason", ""),
    }
    return ProvisionalFinancialFact(
        fact_id=f"parse_lab_round3_fact_{index:04d}",
        field_name=str(row.get("field_name") or ""),
        value=row.get("value"),
        unit=str(row.get("unit") or ""),
        currency=str(row.get("currency") or ""),
        period=str(row.get("period") or ""),
        source_pdf=str(row.get("source_pdf") or ""),
        source_page=source_page,
        source_type=str(row.get("source_type") or ""),
        evidence_text=str(row.get("evidence_text") or ""),
        table_id=str(row.get("table_id") or ""),
        engine_name=str(row.get("engine_name") or ""),
        validation_status=str(row.get("validation_status") or ""),
        confidence=float(row.get("confidence") or 0.0),
        candidate_only_reason=str(row.get("candidate_only_reason") or ""),
        candidate_only=True,
        trusted=False,
        provenance=provenance,
    )


def _review_item_from_row(row: dict[str, Any], index: int) -> CandidateOnlyReviewQueueItem:
    provenance = {
        "parse_lab_review_item_id": row.get("review_item_id", ""),
        "review_id": row.get("review_id", ""),
    }
    return CandidateOnlyReviewQueueItem(
        review_item_id=f"parse_lab_round3_review_{index:04d}",
        field_name=str(row.get("field_name") or ""),
        value=row.get("value"),
        source_pdf=str(row.get("source_pdf") or ""),
        source_page=int(row.get("source_page") or 0),
        source_type=str(row.get("source_type") or "text"),
        evidence_text=str(row.get("evidence_text") or ""),
        table_id=str(row.get("table_id") or ""),
        engine_name=str(row.get("engine_name") or ""),
        validation_status=str(row.get("validation_status") or ""),
        candidate_only_reason=str(row.get("candidate_only_reason") or ""),
        recommended_next_action=str(row.get("recommended_next_action") or "needs_human_review"),
        candidate_only=True,
        trusted=False,
        provenance=provenance,
    )


def _validate_fact(fact: ProvisionalFinancialFact) -> list[str]:
    errors = []
    if not fact.source_pdf:
        errors.append(f"{fact.fact_id}: missing source_pdf")
    if not fact.source_page:
        errors.append(f"{fact.fact_id}: missing source_page")
    if not fact.validation_status:
        errors.append(f"{fact.fact_id}: missing validation_status")
    if fact.trusted:
        errors.append(f"{fact.fact_id}: trusted must remain false")
    if not fact.candidate_only:
        errors.append(f"{fact.fact_id}: candidate_only must remain true")
    if not fact.candidate_only_reason:
        errors.append(f"{fact.fact_id}: missing candidate_only_reason")
    return errors


def _build_summary(
    source_dir: Path,
    output_dir: Path,
    provisional_facts: list[ProvisionalFinancialFact],
    review_queue: list[CandidateOnlyReviewQueueItem],
    warnings: list[str],
    errors: list[str],
) -> CandidateOnlyIngestionSummary:
    return CandidateOnlyIngestionSummary(
        ingestion_id="parse_lab_round3_candidate_only",
        source_dir=str(source_dir),
        output_dir=str(output_dir),
        provisional_fact_count=len(provisional_facts),
        review_queue_count=len(review_queue),
        trusted_fact_count=sum(1 for fact in provisional_facts if fact.trusted),
        validation_status_distribution=dict(Counter(fact.validation_status for fact in provisional_facts)),
        review_queue_status_distribution=dict(Counter(item.validation_status for item in review_queue)),
        source_pdf_distribution=dict(Counter(fact.source_pdf for fact in provisional_facts)),
        source_type_distribution=dict(Counter(fact.source_type for fact in provisional_facts)),
        candidate_only=True,
        warnings=warnings,
        errors=errors,
    )


def _write_outputs(output_dir: Path, result: CandidateOnlyIngestionResult) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    provisional_facts = [_model_dump(fact) for fact in result.provisional_facts]
    review_queue = [_model_dump(item) for item in result.review_queue]
    summary = _model_dump(result.summary)
    _write_json(output_dir / "provisional_facts.json", {"items": provisional_facts, "count": len(provisional_facts)})
    _write_jsonl(output_dir / "provisional_facts.jsonl", provisional_facts)
    _write_json(output_dir / "candidate_only_review_queue.json", {"items": review_queue, "count": len(review_queue)})
    _write_json(output_dir / "ingestion_summary.json", summary)


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    text = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
    path.write_text(text + ("\n" if text else ""), encoding="utf-8")


def _model_dump(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return json.loads(model.json())
