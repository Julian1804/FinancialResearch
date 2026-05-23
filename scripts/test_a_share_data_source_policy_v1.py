from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(r"D:\workspace\FinancialResearch")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def check(name: str, condition: bool, failures: list[str]) -> None:
    if condition:
        print(f"PASS: {name}")
    else:
        print(f"FAIL: {name}")
        failures.append(name)


def main() -> None:
    failures: list[str] = []
    policy = read_json(PROJECT_ROOT / "config" / "a_share_data_source_policy.json")
    akshare = read_json(PROJECT_ROOT / "config" / "akshare_interface_trust_policy.json")
    stubs = read_json(PROJECT_ROOT / "runtime" / "a_share_data_source_policy" / "manual_update_framework_source_stubs_v1.json")

    daily = policy["a_share_daily_market_data_source_policy"]
    derivation = policy["a_share_daily_field_derivation_policy"]
    missing = policy["a_share_daily_missing_field_policy"]
    sources = {item["source_id"]: item for item in stubs["sources"]}

    check("codex_policy_no_formal_trusted_consumption", policy.get("principles") is not None and daily["default_primary_candidate"] == "akshare_tencent_a_share_daily", failures)
    check("tencent_primary_candidate", daily["default_primary_candidate"] == "akshare_tencent_a_share_daily", failures)
    check("baostock_retained_validation_partner", daily["validation_partner"] == "akshare_baostock_a_share_daily", failures)
    check("eastmoney_daily_deferred", daily["deferred_fallback"] == "akshare_eastmoney_stock_zh_a_hist", failures)
    check("akshare_not_only_source", any("not the sole data source" in item for item in policy["principles"]), failures)
    check("fred_sec_baostock_stubs_present", {"fred_macro", "sec_filings", "akshare_baostock_a_share_daily"}.issubset(sources), failures)

    check("tencent_raw_fields", set(["date", "open", "close", "high", "low", "amount"]).issubset(derivation["raw_fields_from_tencent"]), failures)
    check("stock_code_exchange_supplemented", {"stock_code", "exchange"}.issubset(derivation["supplemented_fields"]), failures)
    check("pct_change_derivable", "pct_change" in derivation["derived_fields"], failures)
    check("amplitude_derivable", "amplitude" in derivation["derived_fields"], failures)
    check("derivation_method_required", "record derivation_method" in derivation["derivation_requirements"], failures)
    check("previous_close_required", "record previous_close_source" in derivation["derivation_requirements"], failures)
    check("amount_not_hard_calc_consumption", "turnover_amount" in derivation["not_consumption_grade_hard_calculation"], failures)
    check("turnover_rate_missing_policy", missing["turnover_rate"] == "missing_until_float_share_source_available", failures)

    check("tencent_interface_production_candidate", akshare["interfaces"]["stock_zh_a_hist_tx"]["consumer_status"] == "production_candidate", failures)
    check("eastmoney_hist_not_default", akshare["interfaces"]["stock_zh_a_hist"]["default_chain"] is False, failures)
    check("manual_update_tencent_stub", sources["akshare_tencent_a_share_daily"]["consumer_status"] == "production_candidate", failures)
    check("trusted_consumption_off", stubs["formal_trusted_consumption"] is False, failures)

    parse_lab_status = subprocess.run(["git", "-C", r"D:\workspace\parse_lab", "status", "--short"], check=True, text=True, capture_output=True).stdout.strip()
    check("parse_lab_unchanged", parse_lab_status == "", failures)

    if failures:
        print(f"FAILED: {failures}")
        sys.exit(1)
    print("Results: all A-share data source policy checks passed")


if __name__ == "__main__":
    main()
