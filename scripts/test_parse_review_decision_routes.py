from __future__ import annotations

import json
import sys
from typing import Any
from urllib import request


BASE_URL = "http://127.0.0.1:8030"


def main() -> int:
    registry = _get("/api/financial-report/parse/registry")
    entries = registry.get("entries") or []
    if not entries:
        print(json.dumps({"error": "registry is empty"}, ensure_ascii=False, indent=2))
        return 1

    document_id = entries[0]["document_id"]
    initial_review = _get(f"/api/financial-report/parse/review-queue/{document_id}")
    initial_eligibility = _get(f"/api/financial-report/parse/extraction-eligibility/{document_id}")

    approved_response = _post(
        f"/api/financial-report/parse/review-decisions/{document_id}",
        {
            "review_decision": "approved_with_warnings",
            "reviewer": "local_user",
            "review_notes": "Approved for extraction test with cross-page table warning.",
        },
    )
    decision_after_approval = _get(f"/api/financial-report/parse/review-decisions/{document_id}")
    approved_eligibility = _get(f"/api/financial-report/parse/extraction-eligibility/{document_id}")

    reset_response = _post(
        f"/api/financial-report/parse/review-decisions/{document_id}",
        {
            "review_decision": "needs_reparse",
            "reviewer": "local_user",
            "review_notes": "Test reset to needs_reparse.",
        },
    )
    reset_eligibility = _get(f"/api/financial-report/parse/extraction-eligibility/{document_id}")

    result = {
        "document_id": document_id,
        "initial_review_status": (initial_review.get("item") or {}).get("review_status"),
        "initial_review_decision": (initial_review.get("item") or {}).get("current_review_decision"),
        "initial_eligible_for_extraction": initial_eligibility.get("eligible_for_extraction"),
        "approved_review_decision": (approved_response.get("decision") or {}).get("review_decision"),
        "decision_lookup_after_approval": (decision_after_approval.get("decision") or {}).get("review_decision"),
        "approved_eligible_for_extraction": approved_eligibility.get("eligible_for_extraction"),
        "reset_review_decision": (reset_response.get("decision") or {}).get("review_decision"),
        "reset_eligible_for_extraction": reset_eligibility.get("eligible_for_extraction"),
        "reset_eligibility_reason": reset_eligibility.get("reason"),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if initial_eligibility.get("eligible_for_extraction") is not False:
        return 2
    if approved_eligibility.get("eligible_for_extraction") is not True:
        return 3
    if reset_eligibility.get("eligible_for_extraction") is not False:
        return 4
    return 0


def _get(path: str) -> dict[str, Any]:
    with request.urlopen(f"{BASE_URL}{path}", timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        f"{BASE_URL}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


if __name__ == "__main__":
    sys.exit(main())
