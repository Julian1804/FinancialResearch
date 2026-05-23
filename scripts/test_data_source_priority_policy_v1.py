from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(r"D:\workspace\FinancialResearch")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def ck(name: str, cond: bool, failures: list[str]) -> None:
    if cond:
        print(f"PASS: {name}")
    else:
        print(f"FAIL: {name}")
        failures.append(name)


def main() -> None:
    failures: list[str] = []
    priority = read_json(PROJECT_ROOT / "config" / "data_source_priority_policy.json")
    akshare = read_json(PROJECT_ROOT / "config" / "akshare_interface_trust_policy.json")
    financial_policy = read_json(PROJECT_ROOT / "runtime" / "a_share_data_source_policy" / "financial_report_consumption_policy_v1.json")
    stubs = read_json(PROJECT_ROOT / "runtime" / "a_share_data_source_policy" / "manual_update_framework_source_stubs_v1.json")

    domains = priority["domains"]
    source_ids = {item["source_id"] for item in stubs["sources"]}

    ck("fred_retained_macro", "fred_macro" in domains["macro_rates_inflation_employment"]["primary_sources"], failures)
    ck("sec_retained_filings", "sec_filings" in domains["us_regulatory_filings"]["primary_sources"], failures)
    ck("baostock_retained_a_share", "akshare_baostock_a_share_daily" in domains["a_share_daily_market"]["secondary_sources"], failures)
    ck("tencent_primary_a_share", domains["a_share_daily_market"]["primary_sources"] == ["akshare_tencent_a_share_daily"], failures)
    ck("eastmoney_daily_deferred", "akshare_eastmoney_stock_zh_a_hist" in domains["a_share_daily_market"]["deferred_sources"], failures)
    ck("cninfo_authority_metadata", "cninfo_report_pdf" in domains["a_share_structured_financials"]["authority_metadata"], failures)
    ck("fallback_no_silent_overwrite", "do not silently overwrite" in priority["fallback_policy"], failures)

    ck("eastmoney_balance_keep", akshare["interfaces"]["stock_balance_sheet_by_yearly_em"]["consumer_status"] == "production_candidate", failures)
    ck("eastmoney_profit_keep", akshare["interfaces"]["stock_profit_sheet_by_yearly_em"]["consumer_status"] == "production_candidate", failures)
    ck("eastmoney_cashflow_keep", akshare["interfaces"]["stock_cash_flow_sheet_by_yearly_em"]["consumer_status"] == "production_candidate", failures)
    ck("eastmoney_yjbb_keep", akshare["interfaces"]["stock_yjbb_em"]["consumer_status"] == "production_candidate", failures)
    ck("eastmoney_news_event_candidate", akshare["interfaces"]["stock_news_em"]["consumer_status"] == "event_sentiment_candidate", failures)
    ck("eastmoney_notice_supplement", akshare["interfaces"]["stock_notice_report"]["consumer_status"] == "announcement_candidate_supplement", failures)

    ck("structured_mainline", "eastmoney_balance_sheet" in financial_policy["structured_consumption_mainline"], failures)
    ck("pdf_no_override", financial_policy["pdf_parse_overwrites_structured_interface"] is False, failures)
    ck("manual_update_stubs_include_core_sources", {"akshare_tencent_a_share_daily", "fred_macro", "sec_filings", "cninfo_report_pdf"}.issubset(source_ids), failures)
    ck("formal_trusted_consumption_off", stubs["formal_trusted_consumption"] is False, failures)

    if failures:
        print(f"FAILED: {failures}")
        sys.exit(1)
    print("Results: data source priority policy checks passed")


if __name__ == "__main__":
    main()
