from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.app.clients.parse_lab_client import ParseLabClient
from backend.app.modules.financial_report.services.parsed_document_registry import (
    find_by_task_id,
    list_registry_entries,
)
from backend.app.modules.financial_report.services.parse_ingestion_service import (
    poll_parse_task,
    submit_financial_report_parse,
)
from backend.app.modules.financial_report.services.parse_review_queue import (
    build_review_queue,
    get_review_item_by_document_id,
)
from backend.app.modules.financial_report.services.parse_review_decision_service import (
    create_or_update_review_decision,
    find_decision_by_document_id,
    get_extraction_eligibility,
    list_review_decisions,
)


router = APIRouter(prefix="/api/financial-report/parse", tags=["financial-report-parse"])


class ParseSubmitRequest(BaseModel):
    pdf_path: str
    output_root: str | None = None
    max_pages: int | None = None


class ReviewDecisionRequest(BaseModel):
    review_decision: str
    reviewer: str | None = "local_user"
    review_notes: str | None = ""


@router.post("/submit")
def submit_parse(request: ParseSubmitRequest) -> dict[str, Any]:
    return submit_financial_report_parse(
        pdf_path=request.pdf_path,
        output_root=request.output_root,
        max_pages=request.max_pages,
    )


@router.get("/tasks/{task_id}")
def get_parse_task(task_id: str) -> dict[str, Any]:
    return poll_parse_task(task_id)


@router.get("/tasks/{task_id}/result")
def get_parse_result(task_id: str) -> dict[str, Any]:
    return ParseLabClient().get_task_result(task_id)


@router.post("/tasks/{task_id}/cancel")
def cancel_parse_task(task_id: str) -> dict[str, Any]:
    return ParseLabClient().cancel_task(task_id)


@router.get("/registry")
def get_registry(limit: int = 100, parse_quality_level: str | None = None) -> dict[str, Any]:
    entries = list_registry_entries(limit=limit, parse_quality_level=parse_quality_level)
    return {"entries": entries, "count": len(entries)}


@router.get("/registry/{task_id}")
def get_registry_by_task_id(task_id: str) -> dict[str, Any]:
    entries = find_by_task_id(task_id)
    return {"task_id": task_id, "entries": entries, "count": len(entries)}


@router.get("/review-queue")
def get_review_queue(limit: int = 100) -> dict[str, Any]:
    items = build_review_queue(limit=limit)
    return {"items": items, "count": len(items)}


@router.get("/review-queue/{document_id}")
def get_review_queue_item(document_id: str) -> dict[str, Any]:
    item = get_review_item_by_document_id(document_id)
    return {"document_id": document_id, "item": item, "found": item is not None}


@router.get("/review-decisions")
def get_review_decisions(limit: int = 100, status: str | None = None) -> dict[str, Any]:
    decisions = list_review_decisions(limit=limit, status=status)
    return {"decisions": decisions, "count": len(decisions)}


@router.get("/review-decisions/{document_id}")
def get_review_decision(document_id: str) -> dict[str, Any]:
    decision = find_decision_by_document_id(document_id)
    return {"document_id": document_id, "decision": decision, "found": decision is not None}


@router.post("/review-decisions/{document_id}")
def update_review_decision(document_id: str, request: ReviewDecisionRequest) -> dict[str, Any]:
    try:
        decision = create_or_update_review_decision(
            document_id=document_id,
            review_decision=request.review_decision,
            reviewer=request.reviewer,
            review_notes=request.review_notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "decision": decision,
        "review_item": get_review_item_by_document_id(document_id),
    }


@router.get("/extraction-eligibility/{document_id}")
def get_document_extraction_eligibility(document_id: str) -> dict[str, Any]:
    return get_extraction_eligibility(document_id)
