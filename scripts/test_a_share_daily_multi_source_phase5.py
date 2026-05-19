from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_a_share_daily_multi_source_phase5 import OUTPUT_ROOT, run_phase5  # noqa: E402


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_phase5_outputs() -> None:
    summary = run_phase5()
    assert summary["phase5_completed"] is True
    assert summary["no_full_download"] is True
    assert summary["no_openai_api_called"] is True
    assert summary["parse_lab_affected"] is False
    assert summary["trusted_consumption_affected"] is False
    for path in [
        OUTPUT_ROOT / "a_share_daily_baostock_results.json",
        OUTPUT_ROOT / "a_share_daily_akshare_tencent_results.json",
        OUTPUT_ROOT / "a_share_daily_field_coverage_matrix.json",
        OUTPUT_ROOT / "a_share_daily_cross_source_validation.json",
        OUTPUT_ROOT / "a_share_daily_quality_results.json",
        OUTPUT_ROOT / "a_share_daily_consumption_staging.json",
        OUTPUT_ROOT / "a_share_daily_source_status.json",
        PROJECT_ROOT / "docs" / "A_SHARE_DAILY_MULTI_SOURCE_PIPELINE_REPORT.md",
        PROJECT_ROOT / "docs" / "A_SHARE_DAILY_MULTI_SOURCE_SCHEMA.md",
    ]:
        assert path.exists(), f"missing output: {path}"


def test_source_results_and_quality() -> None:
    baostock = read_json(OUTPUT_ROOT / "a_share_daily_baostock_results.json")
    akshare = read_json(OUTPUT_ROOT / "a_share_daily_akshare_tencent_results.json")
    quality = read_json(OUTPUT_ROOT / "a_share_daily_quality_results.json")
    assert baostock["overall_status"] == "success"
    assert baostock["total_records"] >= 80
    assert Path(baostock["raw_output_path"]).exists()
    assert Path(baostock["structured_output_path"]).exists()
    assert akshare["overall_status"] in {"success", "partial_success"}
    assert akshare["total_records"] > 0
    assert Path(akshare["raw_output_path"]).exists()
    assert Path(akshare["structured_output_path"]).exists()
    assert quality["summary"]["quality_passed"] >= 2


def test_coverage_validation_and_staging() -> None:
    coverage = read_json(OUTPUT_ROOT / "a_share_daily_field_coverage_matrix.json")
    validation = read_json(OUTPUT_ROOT / "a_share_daily_cross_source_validation.json")
    staging = read_json(OUTPUT_ROOT / "a_share_daily_consumption_staging.json")
    matrix = {row["field"]: row for row in coverage["matrix"]}
    assert matrix["open"]["baostock"] == "available"
    assert matrix["open"]["akshare_tencent"] == "available"
    assert matrix["volume"]["akshare_tencent"] == "unit_difference"
    assert matrix["amount"]["akshare_tencent"] == "source_not_supported"
    assert validation["comparison_count"] > 0
    assert validation["formal_trusted_consumption"] is False
    assert staging["candidate_only"] is True
    assert staging["formal_trusted_consumption"] is False
    assert staging["counts"].get("market_daily_candidate_staging", 0) == 1
    assert staging["counts"].get("market_daily_secondary_candidate_staging", 0) == 1


def test_boundaries() -> None:
    parse_lab_status = subprocess.check_output(
        ["git", "-C", "D:/workspace/parse_lab", "status", "--short"],
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8",
    )
    assert not parse_lab_status.strip()


def main() -> int:
    test_phase5_outputs()
    test_source_results_and_quality()
    test_coverage_validation_and_staging()
    test_boundaries()
    print(json.dumps(read_json(OUTPUT_ROOT / "a_share_daily_consumption_staging.json"), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
