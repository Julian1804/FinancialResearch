from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

OUTPUT_ROOT = PROJECT_ROOT / "runtime" / "backtest_execution_v1"
WORKSPACE_ROOT = PROJECT_ROOT / "runtime" / "research_workspace"
BACKTEST_QUEUE_ROOT = PROJECT_ROOT / "runtime" / "backtest_queue"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_outputs() -> None:
    if not (OUTPUT_ROOT / "backtest_results.json").exists():
        from scripts.run_backtest_execution_v1 import run_backtest_execution_v1

        run_backtest_execution_v1()


def test_backtest_results_and_queue() -> None:
    ensure_outputs()
    results = load_json(OUTPUT_ROOT / "backtest_results.json")
    summary = load_json(OUTPUT_ROOT / "report_backtest_summary.json")
    updated_queue = load_json(OUTPUT_ROOT / "pending_backtest_queue_updated.json")
    backtest_queue_copy = load_json(BACKTEST_QUEUE_ROOT / "pending_backtest_queue_updated.json")

    assert len(results["items"]) >= 3
    assert summary["forecast_count"] == len(results["items"])
    assert summary["result_counts"].get("manual_review_required", 0) >= 1
    assert updated_queue["queue_count"] == backtest_queue_copy["queue_count"]
    for item in results["items"]:
        assert item["quality_status"] == "quality_passed"
        assert item["actual_value"] is not None
        assert "candidate/staging" in item["candidate_only_note"]


def test_revision_candidates_and_workspace() -> None:
    ensure_outputs()
    revisions = load_json(OUTPUT_ROOT / "revision_candidates.json")
    workspace = load_json(WORKSPACE_ROOT / "research_workspace_index.json")
    assert revisions["candidate_count"] >= 1
    assert all(item["requires_user_review"] is True for item in revisions["items"])
    symbols = {item["target_symbol"] for item in workspace["items"]}
    assert {"600519", "000001"}.issubset(symbols)
    for symbol in ["600519", "000001"]:
        symbol_workspace = load_json(WORKSPACE_ROOT / f"{symbol}_workspace.json")
        assert symbol_workspace["packets"]
        assert symbol_workspace["reports"]
        assert symbol_workspace["forecast_items"]
        assert symbol_workspace["backtest_results"]


def test_cli_helpers_and_docs() -> None:
    ensure_outputs()
    for path in [
        PROJECT_ROOT / "docs" / "BACKTEST_EXECUTION_V1_REPORT.md",
        PROJECT_ROOT / "docs" / "RESEARCH_WORKSPACE_INDEX.md",
        PROJECT_ROOT / "docs" / "FORECAST_REVISION_WORKFLOW.md",
    ]:
        assert path.exists()
        assert path.read_text(encoding="utf-8")


if __name__ == "__main__":
    test_backtest_results_and_queue()
    test_revision_candidates_and_workspace()
    test_cli_helpers_and_docs()
    print("backtest execution v1 tests passed")
