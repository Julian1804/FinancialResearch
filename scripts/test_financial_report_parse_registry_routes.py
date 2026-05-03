from __future__ import annotations

import json
import urllib.request


BASE_URL = "http://127.0.0.1:8030"


def get_json(path: str) -> dict:
    with urllib.request.urlopen(BASE_URL + path, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    health = get_json("/api/health")
    registry = get_json("/api/financial-report/parse/registry")
    review_queue = get_json("/api/financial-report/parse/review-queue")

    registry_entries = registry.get("entries") or []
    review_items = review_queue.get("items") or []
    first_entry = registry_entries[0] if registry_entries else {}
    first_item = review_items[0] if review_items else {}

    registry_by_task = {}
    review_by_document = {}
    if first_entry.get("parse_task_id"):
        registry_by_task = get_json(f"/api/financial-report/parse/registry/{first_entry['parse_task_id']}")
    if first_item.get("document_id"):
        review_by_document = get_json(f"/api/financial-report/parse/review-queue/{first_item['document_id']}")

    result = {
        "health": health,
        "registry_count": registry.get("count", 0),
        "review_queue_count": review_queue.get("count", 0),
        "first_document_id": first_item.get("document_id") or first_entry.get("document_id", ""),
        "first_parse_quality_level": first_item.get("parse_quality_level") or first_entry.get("parse_quality_level", ""),
        "first_review_status": first_item.get("review_status", ""),
        "registry_by_task_count": registry_by_task.get("count", 0) if registry_by_task else 0,
        "review_by_document_found": review_by_document.get("found", False) if review_by_document else False,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
