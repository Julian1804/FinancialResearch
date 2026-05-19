from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_akshare_deep_diagnosis import OUTPUT_ROOT, run_diagnosis  # noqa: E402


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_akshare_diagnosis_outputs() -> None:
    summary = run_diagnosis()
    assert summary["akshare_deep_diagnosis_completed"] is True
    assert summary["no_full_download"] is True
    assert summary["no_openai_api_called"] is True
    assert summary["parse_lab_affected"] is False
    assert summary["trusted_consumption_affected"] is False
    for path in [
        OUTPUT_ROOT / "akshare_environment_audit.json",
        OUTPUT_ROOT / "akshare_source_inspection.json",
        OUTPUT_ROOT / "minimal_reproduction_matrix.json",
        OUTPUT_ROOT / "akshare_patch_attempt_results.json",
        OUTPUT_ROOT / "fr_custom_connector_design.json",
        PROJECT_ROOT / "docs" / "AKSHARE_DEEP_DIAGNOSIS_REPORT.md",
        PROJECT_ROOT / "docs" / "FR_CUSTOM_CONNECTOR_LAYER_DESIGN.md",
        PROJECT_ROOT / "docs" / "A_SHARE_DAILY_MULTI_SOURCE_STRATEGY.md",
    ]:
        assert path.exists(), f"missing output: {path}"


def test_source_and_matrix() -> None:
    source = read_json(OUTPUT_ROOT / "akshare_source_inspection.json")
    matrix = read_json(OUTPUT_ROOT / "minimal_reproduction_matrix.json")
    patch = read_json(OUTPUT_ROOT / "akshare_patch_attempt_results.json")
    assert source["actual_url"].endswith("/api/qt/stock/kline/get")
    assert source["uses_session"] is False
    assert matrix["item_count"] >= 20
    assert matrix["failed_count"] + matrix["success_count"] == matrix["item_count"]
    assert patch["repair_status"] in {"not_repaired", "partially_repaired"}
    assert patch["akshare_eastmoney_stock_zh_a_hist_stable"] is False
    assert patch["akshare_stable_for_a_share_daily"] in {"partial_alternative_only", "no"}
    assert patch["candidate_only"] is True


def test_connector_design_and_boundaries() -> None:
    design = read_json(OUTPUT_ROOT / "fr_custom_connector_design.json")
    assert design["name"] == "FRDataConnectors"
    adapters = {item["adapter"] for item in design["adapters"]}
    assert {"BaostockDailyAdapter", "AKShareAdapter", "EastmoneyDirectAdapter", "FREDAdapter"}.issubset(adapters)
    parse_lab_status = subprocess.check_output(
        ["git", "-C", "D:/workspace/parse_lab", "status", "--short"],
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8",
    )
    assert not parse_lab_status.strip()


def main() -> int:
    test_akshare_diagnosis_outputs()
    test_source_and_matrix()
    test_connector_design_and_boundaries()
    print(json.dumps(read_json(OUTPUT_ROOT / "akshare_patch_attempt_results.json"), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
