from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(r"D:\workspace\FinancialResearch")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def ck(name: str, cond: bool, failures: list[str]) -> None:
    if cond:
        print(f"PASS: {name}")
    else:
        print(f"FAIL: {name}")
        failures.append(name)


def main() -> None:
    failures: list[str] = []
    policy = read_json(PROJECT_ROOT / "config" / "storage_retention_policy.json")
    impact = read_json(PROJECT_ROOT / "runtime" / "a_share_data_source_policy" / "storage_retention_impact_review_v1.json")

    long_term = set(policy["long_term_keep"])
    short_term = set(policy["short_term_keep"])
    cleanup = set(policy["auto_cleanup_candidates"])
    principles = " ".join(policy["retention_principles"])

    ck("no_direct_delete", policy["no_direct_delete"] is True, failures)
    ck("cleanup_plan_only", policy["cleanup_plan_only"] is True, failures)
    ck("structured_long_term", "consumption-ready structured data" in long_term, failures)
    ck("qa_provenance_manifest_long_term", {"manifest", "QA summary", "provenance summary"}.issubset(long_term), failures)
    ck("raw_short_term", "raw API responses" in short_term, failures)
    ck("parser_intermediate_short_term", "parser intermediates" in short_term, failures)
    ck("duplicate_raw_cleanup_candidate", "duplicate raw" in cleanup, failures)
    ck("no_raw_parsed_normalized_forever", "raw, parsed and normalized full-size copies forever" in principles, failures)
    ck("nas_not_deleted", impact["nas_deletion_performed"] is False, failures)
    ck("cleanup_plan_not_action", impact["cleanup_plan_only"] is True, failures)

    if failures:
        print(f"FAILED: {failures}")
        sys.exit(1)
    print("Results: storage retention policy checks passed")


if __name__ == "__main__":
    main()
