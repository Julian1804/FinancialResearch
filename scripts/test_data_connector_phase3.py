from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.modules.financial_report.services.data_connector_phase3_service import OUTPUT_ROOT  # noqa: E402
from scripts.run_data_connector_phase3 import DOCS, main as run_phase3  # noqa: E402


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_phase3_run_outputs() -> None:
    assert run_phase3() == 0
    for path in [
        OUTPUT_ROOT / "curated_source_registry.json",
        OUTPUT_ROOT / "quality_remediation_results.json",
        OUTPUT_ROOT / "incremental_pipeline_run_results.json",
        OUTPUT_ROOT / "consumption_grade_staging.json",
        OUTPUT_ROOT / "storage_estimate_refresh.json",
        OUTPUT_ROOT / "phase3_summary.json",
        PROJECT_ROOT / "config" / "watchlist.json",
        PROJECT_ROOT / "config" / "metrics_registry.json",
        *DOCS.values(),
    ]:
        assert path.exists(), f"missing output: {path}"


def test_quality_remediation() -> None:
    remediation = read_json(OUTPUT_ROOT / "quality_remediation_results.json")
    items = {item["source_id"]: item for item in remediation["items"]}
    assert len(items) >= 8
    for source_id in ["cninfo_disclosure", "bls_public_api", "sec_edgar_companyfacts", "world_bank_pink_sheet"]:
        assert items[source_id]["after_status"] == "quality_passed"
        assert items[source_id]["remediation_action"].startswith("remediated")
        assert items[source_id]["forced_pass"] is False
    assert items["akshare_traceable_official"]["after_status"] == "quality_failed"
    assert items["fred_public_csv"]["after_status"] == "quality_failed"


def test_configs_and_registry() -> None:
    watchlist = read_json(PROJECT_ROOT / "config" / "watchlist.json")
    metrics = read_json(PROJECT_ROOT / "config" / "metrics_registry.json")
    registry = read_json(OUTPUT_ROOT / "curated_source_registry.json")
    assert any(item["symbol"] == "600519" for item in watchlist["items"])
    assert any(item["symbol"] == "AAPL" for item in watchlist["items"])
    metric_ids = {item["metric_id"] for item in metrics["metrics"]}
    assert {"open", "close", "volume", "cpi", "treasury_yield", "price"}.issubset(metric_ids)
    entries = {item["source_id"]: item for item in registry["entries"]}
    assert entries["sec_edgar_companyfacts"]["trust_eligibility"] == "trusted_by_real_external_candidate"
    assert entries["baostock_daily"]["trust_eligibility"] == "candidate_external_data"
    assert entries["akshare_traceable_official"]["current_phase_status"] == "defer"


def test_incremental_pipeline_and_staging() -> None:
    pipeline = read_json(OUTPUT_ROOT / "incremental_pipeline_run_results.json")
    items = pipeline["items"]
    success = [item for item in items if item["status"] == "success"]
    assert len(success) >= 5
    assert pipeline["no_full_download"] is True
    assert pipeline["no_openai_api_called"] is True
    assert pipeline["parse_lab_affected"] is False
    assert pipeline["trusted_consumption_affected"] is False
    assert pipeline["default_v1_1_replaced"] is False
    for item in success:
        assert item["candidate_only"] is True
        assert item["consumption_eligible"] is False
        assert item["raw_output_path"]
        assert item["normalized_output_path"]
        assert Path(item["raw_output_path"]).exists()
        assert Path(item["normalized_output_path"]).exists()

    staging = read_json(OUTPUT_ROOT / "consumption_grade_staging.json")
    assert staging["consumption_grade_candidate_count"] >= 4
    for item in staging["items"]:
        assert item["quality_status"] == "quality_passed"
        assert item["candidate_only"] is True
        assert item["formal_trusted_consumption"] is False
    excluded_statuses = [
        item["quality_status"]
        for group in [staging["review_candidates"], staging["deferred_items"]]
        for item in group
    ]
    assert "quality_warning" not in [item["quality_status"] for item in staging["items"]]
    assert "quality_failed" not in [item["quality_status"] for item in staging["items"]]
    assert excluded_statuses


def test_boundaries() -> None:
    parse_lab_status = subprocess.check_output(
        ["git", "-C", "D:/workspace/parse_lab", "status", "--short"],
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8",
    )
    assert not parse_lab_status.strip()


def main() -> int:
    test_phase3_run_outputs()
    test_quality_remediation()
    test_configs_and_registry()
    test_incremental_pipeline_and_staging()
    test_boundaries()
    summary = read_json(OUTPUT_ROOT / "phase3_summary.json")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
