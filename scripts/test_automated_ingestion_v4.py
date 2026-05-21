from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_v4_outputs() -> None:
    root = PROJECT_ROOT / "runtime" / "automated_ingestion_system" / "v4_trust_closure"
    summary = read_json(root / "automated_ingestion_v4_summary.json")
    assert_true(summary["automated_ingestion_v4_completed"] is True, "v4 summary completion flag missing")
    assert_true(summary["no_openai_api_called"] is True, "OpenAI API flag must remain false")
    assert_true(summary["trusted_consumption_affected"] is False, "trusted consumption must be unaffected")

    rules = read_json(PROJECT_ROOT / "config" / "trust_closure_rules_v4.json")
    statuses = {item["status"] for item in rules["states"]}
    assert_true("licensed_high_confidence_candidate" in statuses, "Morningstar licensed status missing")
    assert_true("historical_identifier_anchor" in statuses, "identifier anchor status missing")

    a_share = read_json(root / "a_share_etf_trust_closure_results.json")
    assert_true(a_share["summary"]["requested_total"] >= 16, "A-share/ETF controlled expansion did not request extended watchlist")
    assert_true(a_share["summary"]["candidate_only"] is True, "A-share/ETF must remain candidate only")
    assert_true(a_share["summary"]["formal_trusted_consumption"] is False, "A-share/ETF must not enter formal trusted consumption")

    release = read_json(root / "release_calendar_publish_date_closure.json")
    assert_true(release["summary"]["publish_date_not_fabricated"] is True, "publish_date fabrication guard failed")
    assert_true(release["summary"]["datasets_checked"] > 0, "release calendar closure did not inspect datasets")

    freshness = read_json(root / "macro_rates_fx_commodity_freshness_closure.json")
    assert_true(freshness["summary"]["no_definition_forced_match"] is True, "definition boundary guard failed")
    assert_true(freshness["summary"]["datasets_checked"] > 0, "freshness closure did not inspect datasets")

    morningstar = read_json(root / "morningstar_field_depth_v4.json")
    assert_true(morningstar["summary"]["large_download_performed"] is False, "Morningstar large download guard failed")
    assert_true(morningstar["summary"]["token_leaked"] is False, "Morningstar token leak flag failed")
    serialized = json.dumps(morningstar, ensure_ascii=False)
    assert_true("md_auth_token" not in serialized.lower(), "Morningstar token field leaked")

    entity = read_json(root / "entity_unresolved_v4.json")
    assert_true(entity["summary"]["correctness_preserved"] is True, "entity correctness flag missing")
    assert_true(entity["summary"]["rejected_fuzzy_match_count"] >= entity["summary"]["resolved_count"], "fuzzy merge guard failed")

    trust = read_json(root / "trust_closure_progress_v4.json")
    assert_true(trust["summary"]["trusted_candidate_count"] == 0, "trusted_candidate should not be forced")
    assert_true(len(trust["summary"]["trusted_candidate_zero_reason"]) >= 1, "trusted zero reasons missing")


def test_dashboard_markers() -> None:
    data = read_json(PROJECT_ROOT / "frontend_web" / "src" / "dashboard_v1" / "dashboard_v1_sample_data.json")
    html = (PROJECT_ROOT / "frontend_web" / "src" / "dashboard_v1" / "index.html").read_text(encoding="utf-8")
    markers = [
        "Automated Ingestion v4",
        "Trust Closure Progress",
        "Release Calendar Closure",
        "Publish Date Policy",
        "Ready for Trusted Candidate",
        "Licensed High Confidence Candidate",
    ]
    missing = [marker for marker in markers if marker not in html]
    assert_true(not missing, f"dashboard v4 markers missing: {missing}")
    assert_true(data["legacy_streamlit_used"] is False, "dashboard must not use Streamlit")


def test_repo_guards() -> None:
    status = subprocess.check_output(["git", "status", "--short"], cwd=PROJECT_ROOT, text=True)
    assert_true("parse_lab" not in status.lower(), "parse_lab appears in FinancialResearch worktree status")


def main() -> None:
    test_v4_outputs()
    test_dashboard_markers()
    test_repo_guards()
    print("automated_ingestion_v4_tests_passed")


if __name__ == "__main__":
    main()
