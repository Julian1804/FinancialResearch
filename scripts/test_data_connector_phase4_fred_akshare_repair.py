from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_data_connector_phase4_fred_akshare_repair import (  # noqa: E402
    LOCAL_SECRETS_PATH,
    OUTPUT_ROOT,
    REPORT_PATH,
    load_fred_key,
    run_phase4,
)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_phase4_outputs_and_secret_safety() -> None:
    summary = run_phase4()
    assert summary["no_openai_api_called"] is True
    assert summary["parse_lab_affected"] is False
    assert summary["trusted_consumption_affected"] is False
    for path in [
        OUTPUT_ROOT / "fred_key_readiness_result.json",
        OUTPUT_ROOT / "fred_repair_results.json",
        OUTPUT_ROOT / "akshare_network_diagnosis.json",
        OUTPUT_ROOT / "akshare_repair_results.json",
        OUTPUT_ROOT / "market_daily_cross_source_validation_after_akshare.json",
        REPORT_PATH,
    ]:
        assert path.exists(), f"missing output: {path}"

    key = load_fred_key()
    assert key
    for path in [
        OUTPUT_ROOT / "fred_key_readiness_result.json",
        OUTPUT_ROOT / "fred_repair_results.json",
        OUTPUT_ROOT / "akshare_network_diagnosis.json",
        OUTPUT_ROOT / "akshare_repair_results.json",
        OUTPUT_ROOT / "market_daily_cross_source_validation_after_akshare.json",
        REPORT_PATH,
    ]:
        text = path.read_text(encoding="utf-8")
        assert key not in text, f"secret leaked in {path}"


def test_gitignore_and_tracking() -> None:
    gitignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
    for rule in ["config/local_secrets.json", "**/local_secrets.json", "*.key", "*.secret", ".env.local"]:
        assert rule in gitignore
    tracked = subprocess.check_output(
        ["git", "ls-files", "config/local_secrets.json"],
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8",
    )
    assert not tracked.strip()
    assert LOCAL_SECRETS_PATH.exists()


def test_fred_and_akshare_results() -> None:
    fred = read_json(OUTPUT_ROOT / "fred_repair_results.json")
    akshare = read_json(OUTPUT_ROOT / "akshare_repair_results.json")
    validation = read_json(OUTPUT_ROOT / "market_daily_cross_source_validation_after_akshare.json")
    assert fred["key_present"] is True
    assert fred["overall_status"] in {"success", "partial_success", "failed"}
    assert all(item["candidate_only"] is True for item in fred["items"])
    assert akshare["overall_status"] in {"success", "partial_success", "failed"}
    assert all(item["candidate_only"] is True for item in akshare["items"])
    assert validation["baostock_fallback_status"] == "success"
    assert validation["formal_trusted_consumption"] is False


def test_parse_lab_untouched() -> None:
    parse_lab_status = subprocess.check_output(
        ["git", "-C", "D:/workspace/parse_lab", "status", "--short"],
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8",
    )
    assert not parse_lab_status.strip()


def main() -> int:
    test_phase4_outputs_and_secret_safety()
    test_gitignore_and_tracking()
    test_fred_and_akshare_results()
    test_parse_lab_untouched()
    print(json.dumps(read_json(OUTPUT_ROOT / "fred_repair_results.json"), ensure_ascii=False, indent=2))
    print(json.dumps(read_json(OUTPUT_ROOT / "akshare_repair_results.json"), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
