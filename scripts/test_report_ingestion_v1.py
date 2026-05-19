from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
OUTPUT_ROOT = PROJECT_ROOT / "runtime" / "report_ingestion_v1"
REPORT_ROOT = PROJECT_ROOT / "runtime" / "analysis_reports"
BACKTEST_ROOT = PROJECT_ROOT / "runtime" / "backtest_queue"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_outputs() -> None:
    if not (OUTPUT_ROOT / "sample_ingestion_results.json").exists():
        from scripts.run_report_ingestion_v1 import run_report_ingestion_v1

        run_report_ingestion_v1()


def test_sample_reports_ingested_and_versioned() -> None:
    ensure_outputs()
    results = load_json(OUTPUT_ROOT / "sample_ingestion_results.json")
    history = load_json(OUTPUT_ROOT / "report_version_history.json")

    assert all(item["ingestion_status"] == "success" for item in results["items"])
    assert len(results["items"]) >= 3
    versions_600519 = [
        item for item in history["items"]
        if item["target_symbol"] == "600519" and item["packet_id"] == "packet_554b196c683dca80"
    ]
    assert len(versions_600519) >= 2
    assert any(item["previous_report_id"] for item in versions_600519 if item["version"] > 1)

    for item in results["items"]:
        report_dir = Path(item["report_dir"])
        assert (report_dir / "raw_report.md").exists()
        assert (report_dir / "structured_report.json").exists()
        assert (report_dir / "forecast_items.json").exists()
        structured = load_json(report_dir / "structured_report.json")
        assert structured["source"] == "gpt_web_manual"
        assert structured["formal_trusted_consumption"] is False
        assert structured["trusted_fact_status"] == "analysis_report_only_not_trusted_fact"


def test_forecast_backtest_queue() -> None:
    ensure_outputs()
    queue = load_json(BACKTEST_ROOT / "pending_backtest_queue.json")
    summary = load_json(BACKTEST_ROOT / "backtest_readiness_summary.json")
    assert queue["queue_count"] >= 3
    assert summary["counts"].get("ready_for_backtest", 0) >= 1
    for item in queue["items"]:
        assert item["candidate_only_forecast"] is True
        assert item["gpt_content_not_trusted_fact"] is True


def test_failed_draft_is_preserved() -> None:
    ensure_outputs()
    from scripts.run_report_ingestion_v1 import ingest_report

    bad_report = OUTPUT_ROOT / "bad_report_for_test.md"
    bad_report.write_text("# Bad report\n\nNo JSON block here.\n", encoding="utf-8")
    result = ingest_report(bad_report)
    assert result["ingestion_status"] == "ingestion_failed"
    failed_dir = OUTPUT_ROOT / "failed_drafts" / result["failed_id"]
    assert (failed_dir / "raw_report.md").exists()
    assert (failed_dir / "ingestion_error.json").exists()


def test_cli_docs_exist() -> None:
    ensure_outputs()
    for path in [
        PROJECT_ROOT / "docs" / "HUMAN_IN_THE_LOOP_REPORT_INGESTION_WORKFLOW.md",
        PROJECT_ROOT / "docs" / "FORECAST_BACKTEST_SCHEMA_V1.md",
        PROJECT_ROOT / "docs" / "REPORT_VERSIONING_AND_STORAGE.md",
    ]:
        assert path.exists()
        assert path.read_text(encoding="utf-8")


if __name__ == "__main__":
    test_sample_reports_ingested_and_versioned()
    test_forecast_backtest_queue()
    test_failed_draft_is_preserved()
    test_cli_docs_exist()
    print("report ingestion v1 tests passed")
