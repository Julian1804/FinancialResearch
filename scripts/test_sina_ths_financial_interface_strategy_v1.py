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
    comparison = read_json(PROJECT_ROOT / "runtime" / "a_share_data_source_policy" / "sina_ths_financial_interface_comparison_v1.json")
    duplicate = read_json(PROJECT_ROOT / "runtime" / "a_share_data_source_policy" / "duplicate_financial_field_resolution_policy_v1.json")
    metric_priority = read_json(PROJECT_ROOT / "config" / "financial_metric_source_priority.json")
    report_policy = read_json(PROJECT_ROOT / "runtime" / "a_share_data_source_policy" / "financial_report_consumption_policy_v1.json")

    interfaces = comparison["interfaces_to_continue_testing"]
    dims = set(comparison["comparison_dimensions"])
    metric_priorities = metric_priority["metric_priorities"]

    ck("sina_abstract_continue_testing", interfaces["sina_stock_financial_abstract"]["status"] == "continue_testing", failures)
    ck("sina_indicator_continue_testing", interfaces["sina_stock_financial_analysis_indicator"]["status"] == "continue_testing", failures)
    ck("ths_abstract_continue_testing", interfaces["ths_stock_financial_abstract"]["status"] == "continue_testing", failures)
    ck("stability_field_period_frequency_checked", {"stability", "field_completeness", "report_period_consistency", "update_frequency"}.issubset(dims), failures)
    ck("primary_rule_exists", "most stable interface" in comparison["primary_selection"], failures)

    resolution = duplicate["same_company_same_period_same_metric"]
    ck("primary_enters_consumption", resolution["primary_source_value"] == "enters consumption candidate field", failures)
    ck("secondary_validation_reference", "validation_reference" in resolution["secondary_source_value"], failures)
    ck("discrepancy_warning_no_default_manual_review", "discrepancy_warning" in resolution["large_discrepancy_behavior"], failures)
    ck("pdf_parse_no_override", duplicate["pdf_parse_override_allowed"] is False, failures)

    ck("roe_has_primary_fallback", metric_priorities["roe"]["primary"] == "akshare_ths_financial_abstract", failures)
    ck("gross_margin_has_sina_secondary", metric_priorities["gross_margin"]["secondary"] == "akshare_sina_financial_analysis_indicator", failures)
    ck("report_structured_mainline", "ths_stock_financial_abstract" in report_policy["structured_consumption_mainline"], failures)
    ck("pdf_parse_failure_not_block", report_policy["pdf_parse_failure_blocks_structured_consumption"] is False, failures)
    ck("pdf_role_explanation", "explain structured data" in report_policy["pdf_role"], failures)

    if failures:
        print(f"FAILED: {failures}")
        sys.exit(1)
    print("Results: Sina/THS financial interface strategy checks passed")


if __name__ == "__main__":
    main()
