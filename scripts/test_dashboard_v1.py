from __future__ import annotations

import json
import sys
import threading
import urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_dashboard_v1 import (  # noqa: E402
    CONFIG_ROOT,
    FRONTEND_ROOT,
    RUNTIME_ROOT,
    classify_report_text,
    default_snapshot_request,
    generate_asof_snapshot,
    run_dashboard_v1,
)
from scripts.run_dashboard_v1_acceptance import run_acceptance  # noqa: E402


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_outputs() -> None:
    if not (RUNTIME_ROOT / "dashboard_v1_summary.json").exists():
        run_dashboard_v1()


def test_config_loads_and_contracts() -> None:
    ensure_outputs()
    taxonomy = load_json(CONFIG_ROOT / "data_taxonomy.json")
    time_semantics = load_json(CONFIG_ROOT / "time_semantics.json")
    research_objects = load_json(CONFIG_ROOT / "research_object_types.json")
    category_ids = {item["id"] for item in taxonomy["data_categories"]}
    time_modes = {item["id"] for item in time_semantics["modes"]}
    object_types = {item["id"] for item in research_objects["types"]}

    assert "market_daily" in category_ids
    assert "capital_flow" in category_ids
    assert time_semantics["default_time_mode"] == "publish_date"
    assert time_semantics["default_as_of_check_enabled"] is True
    assert {"fiscal_year", "reporting_period", "event_date", "announcement_date"}.issubset(time_modes)
    assert {"company", "sector", "asset_class", "macro_theme", "black_swan_event", "custom_topic"}.issubset(object_types)


def test_asof_snapshot_publish_date_rules() -> None:
    ensure_outputs()
    summary = load_json(RUNTIME_ROOT / "dashboard_v1_summary.json")
    counts = summary["snapshot_counts"]
    assert counts["included"] > 0
    assert counts["missing_publish_date_review"] > 0
    assert counts["excluded_due_to_future_publish_date"] > 0


def test_fiscal_year_and_reporting_period_modes() -> None:
    mock_items = [
        {
            "item_id": "report_2025fy",
            "category": "financial_report",
            "title": "2025 annual report",
            "symbol": "000001",
            "source_id": "cninfo_disclosure",
            "source_name": "CNINFO",
            "quality_status": "quality_passed",
            "trust_status": "trusted_by_official_source_candidate",
            "staging_status": "consumption_grade_candidate",
            "candidate_only": True,
            "formal_trusted_consumption": False,
            "publish_date": "2026-03-21",
            "data_period": "2025-12-31",
            "fiscal_year": "2025",
            "reporting_period": "2025FY",
            "announcement_date": "2026-03-21",
            "event_date": None,
            "analysis_time": None,
            "ingestion_time": "2026-05-18",
            "source_ref": "mock",
            "limitation_note": "unit test",
            "payload": {},
        },
        {
            "item_id": "future_report_2025fy",
            "category": "financial_report",
            "title": "future report",
            "symbol": "000001",
            "source_id": "cninfo_disclosure",
            "source_name": "CNINFO",
            "quality_status": "quality_passed",
            "trust_status": "trusted_by_official_source_candidate",
            "staging_status": "consumption_grade_candidate",
            "candidate_only": True,
            "formal_trusted_consumption": False,
            "publish_date": "2026-06-01",
            "data_period": "2025-12-31",
            "fiscal_year": "2025",
            "reporting_period": "2025FY",
            "announcement_date": "2026-06-01",
            "event_date": None,
            "analysis_time": None,
            "ingestion_time": "2026-06-01",
            "source_ref": "mock",
            "limitation_note": "unit test",
            "payload": {},
        },
        {
            "item_id": "missing_publish_report",
            "category": "financial_report",
            "title": "missing publish date report",
            "symbol": "000001",
            "source_id": "manual",
            "source_name": "manual",
            "quality_status": "unknown",
            "trust_status": "candidate_external_data",
            "staging_status": "needs_review_candidate",
            "candidate_only": True,
            "formal_trusted_consumption": False,
            "publish_date": None,
            "data_period": "2025-12-31",
            "fiscal_year": "2025",
            "reporting_period": "2025FY",
            "announcement_date": None,
            "event_date": None,
            "analysis_time": None,
            "ingestion_time": "2026-05-18",
            "source_ref": "mock",
            "limitation_note": "unit test",
            "payload": {},
        },
    ]
    request = default_snapshot_request()
    request.update(
        {
            "selected_data_categories": ["financial_report"],
            "selected_symbols": ["000001"],
            "time_mode": "fiscal_year",
            "fiscal_year": "2025",
            "window_start": "2026-01-01",
            "window_end": "2026-05-18",
            "as_of_check_enabled": True,
        }
    )
    snapshot = generate_asof_snapshot(request, mock_items, "unit_fiscal_year")
    assert snapshot["counts"]["included"] == 1
    assert snapshot["counts"]["excluded_due_to_future_publish_date"] == 1
    assert snapshot["counts"]["missing_publish_date_review"] == 1

    request["time_mode"] = "reporting_period"
    request["reporting_period"] = "2025FY"
    snapshot = generate_asof_snapshot(request, mock_items, "unit_reporting_period")
    assert snapshot["counts"]["included"] == 1
    assert snapshot["counts"]["excluded_due_to_future_publish_date"] == 1
    assert snapshot["counts"]["missing_publish_date_review"] == 1


def test_report_upload_classification_stub() -> None:
    sample = """# Report

FINAL_REPORT_JSON
```json
{
  "packet_id": "p1",
  "data_snapshot_id": "s1",
  "as_of_date": "2026-05-18",
  "analysis_scope": "unit",
  "investment_view": "insufficient_evidence",
  "forecast_items": [],
  "risk_items": [],
  "watchlist_signals": [],
  "insufficient_evidence_items": ["missing macro"],
  "candidate_data_usage_note": "candidate only"
}
```
"""
    result = classify_report_text(sample)
    assert result["schema_valid"] is True
    assert result["analysis_zone"]["investment_view"] == "insufficient_evidence"
    assert result["forecast_zone"]["forecast_items"] == []
    assert result["evidence_zone"]["candidate_data_usage_note"] == "candidate only"
    assert result["gpt_report_not_trusted_fact"] is True


def test_ui_smoke_markers_and_http_serving() -> None:
    ensure_outputs()
    smoke = load_json(RUNTIME_ROOT / "ui_smoke_results.json")
    assert smoke["status"] == "passed"
    assert smoke["legacy_streamlit_used"] is False
    assert smoke["old_ui_false_positive_guard"] is True
    assert not smoke["missing_new_ui_markers"]

    handler = partial(SimpleHTTPRequestHandler, directory=str(FRONTEND_ROOT))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/"
        html = urllib.request.urlopen(url, timeout=5).read().decode("utf-8")
    finally:
        server.shutdown()
        thread.join(timeout=5)

    for marker in [
        "FR Dashboard v1",
        "Research Workspace",
        "Commodity Dashboard",
        "Macro Snapshot",
        "Rates / Bond Snapshot",
        "FX / Currency Snapshot",
        "Commodity Snapshot",
        "Asset Class Snapshot",
        "Macro Overview Cards",
        "Macro Category Sections",
        "Asset Overview Cards",
        "FX / Currency",
        "Rates / Bonds",
        "Futures Framework",
        "Category View",
        "Exchange View",
        "Custom Chart Builder",
        "line",
        "bar",
        "pie",
        "Macro & Asset Mini Charts",
        "Recent Event Ticker",
        "Research Object Type",
        "Time Mode",
        "publish_date",
        "as_of_check_enabled",
        "Generate Statistical Report",
        "Download Markdown Report",
        "Download JSON Report",
        "Download GPT Prompt",
        "Download Evidence Boundary",
        "Report Upload",
        "Analysis Zone",
        "Forecast Zone",
        "Evidence Zone",
    ]:
        assert marker in html
    assert "category-checkbox" in html
    assert html.count('data-target="console">Research Workspace</button>') == 1
    assert "legacy_streamlit_used = false" in html


def test_acceptance_dynamic_action_outputs() -> None:
    summary = run_acceptance()
    assert summary["dashboard_dynamic_hardening_completed"] is True
    assert summary["ui_operability_level"] == "semi_dynamic_local_action_layer"
    assert summary["backend_local_action_layer_completed"] is True
    assert summary["e2e_600519"]["status"] == "success"
    assert summary["e2e_custom_topic"]["status"] == "success"
    assert summary["report_upload_smoke"]["status"] == "success"
    assert summary["ui_smoke"]["status"] == "passed"
    assert summary["ui_smoke"]["duplicate_research_workspace_count"] == 1
    assert summary["legacy_streamlit_used"] is False
    assert summary["no_openai_api_called"] is True
    assert summary["trusted_consumption_affected"] is False
    for output_path in summary["e2e_600519"]["outputs"].values():
        assert Path(output_path).exists()
    for output_path in summary["e2e_custom_topic"]["outputs"].values():
        assert Path(output_path).exists()
    assert Path(summary["report_upload_smoke"]["classification_path"]).exists()
    assert not summary["ui_smoke"]["missing_actions"]


if __name__ == "__main__":
    run_dashboard_v1()
    test_config_loads_and_contracts()
    test_asof_snapshot_publish_date_rules()
    test_fiscal_year_and_reporting_period_modes()
    test_report_upload_classification_stub()
    test_ui_smoke_markers_and_http_serving()
    test_acceptance_dynamic_action_outputs()
    print("dashboard v1 tests passed")
