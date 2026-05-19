from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_eastmoney_direct_connector_fallback import OUTPUT_ROOT, REPORT_PATH, run_eastmoney_direct_fallback  # noqa: E402


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_eastmoney_outputs() -> None:
    summary = run_eastmoney_direct_fallback()
    assert summary["no_full_download"] is True
    assert summary["no_openai_api_called"] is True
    assert summary["parse_lab_affected"] is False
    assert summary["trusted_consumption_affected"] is False
    for path in [
        OUTPUT_ROOT / "eastmoney_direct_connector_results.json",
        OUTPUT_ROOT / "eastmoney_direct_normalized_sample.json",
        OUTPUT_ROOT / "market_daily_cross_source_validation_eastmoney_baostock.json",
        OUTPUT_ROOT / "akshare_final_status.json",
        REPORT_PATH,
    ]:
        assert path.exists(), f"missing output: {path}"
    result = read_json(OUTPUT_ROOT / "eastmoney_direct_connector_results.json")
    assert result["source_role"] == "secondary_validation_source"
    assert result["candidate_only"] is True
    assert len(result["items"]) == 3
    for item in result["items"]:
        assert item["symbol"] in {"600519", "000001", "300750"}
        assert item["status"] in {"success", "failed"}
        if item["status"] == "success":
            assert item["raw_output_path"]
            assert Path(item["raw_output_path"]).exists()


def test_validation_and_akshare_status() -> None:
    validation = read_json(OUTPUT_ROOT / "market_daily_cross_source_validation_eastmoney_baostock.json")
    akshare = read_json(OUTPUT_ROOT / "akshare_final_status.json")
    assert validation["baostock_status"] == "success"
    assert validation["candidate_only"] is True
    assert validation["formal_trusted_consumption"] is False
    assert "Eastmoney f56 volume is lots" in validation["unit_difference_note"]
    assert akshare["status"] == "optional_retry_source"
    assert akshare["blocks_a_share_daily_pipeline"] is False


def test_parse_lab_untouched() -> None:
    parse_lab_status = subprocess.check_output(
        ["git", "-C", "D:/workspace/parse_lab", "status", "--short"],
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8",
    )
    assert not parse_lab_status.strip()


def main() -> int:
    test_eastmoney_outputs()
    test_validation_and_akshare_status()
    test_parse_lab_untouched()
    print(json.dumps(read_json(OUTPUT_ROOT / "eastmoney_direct_connector_results.json"), ensure_ascii=False, indent=2))
    print(json.dumps(read_json(OUTPUT_ROOT / "market_daily_cross_source_validation_eastmoney_baostock.json"), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
