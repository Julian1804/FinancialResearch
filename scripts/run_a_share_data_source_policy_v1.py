from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_ROOT = PROJECT_ROOT / "config"
DOCS_ROOT = PROJECT_ROOT / "docs"
RUNTIME_ROOT = PROJECT_ROOT / "runtime" / "a_share_data_source_policy"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build_a_share_policy() -> dict[str, Any]:
    return {
        "version": "a_share_data_source_policy_v1",
        "generated_at": utc_now(),
        "principles": [
            "Data source trust is interface-level, not platform-level.",
            "AKShare is a wrapper, not the sole data source.",
            "Stable FRED, SEC, BaoStock, Tencent, CNINFO and other sources remain active by data domain.",
            "Candidate consumption must retain upstream provenance and field-level limitations.",
            "Formal trusted consumption is not opened by this policy.",
        ],
        "a_share_daily_market_data_source_policy": {
            "default_primary_candidate": "akshare_tencent_a_share_daily",
            "validation_partner": "akshare_baostock_a_share_daily",
            "deferred_fallback": "akshare_eastmoney_stock_zh_a_hist",
            "future_specific_connector": "eastmoney_specific_future_connector",
            "primary_reason": "Tencent daily line interface is currently stable and provides date/open/close/high/low/amount.",
            "baostock_role": "stable_supplement_validation_partner_historical_source",
            "eastmoney_daily_role": "unstable_for_primary_fallback_or_deferred_monitor_required",
            "formal_trusted_consumption": False,
        },
        "a_share_daily_field_derivation_policy": {
            "raw_fields_from_tencent": ["date", "open", "close", "high", "low", "amount"],
            "supplemented_fields": {
                "stock_code": "parse from sh/sz/bj-prefixed symbol parameter",
                "exchange": "parse from sh/sz/bj-prefixed symbol parameter",
                "adjust_type": "qfq/hfq/raw request parameter",
                "source": "akshare_tencent",
                "upstream": "tencent",
            },
            "derived_fields": {
                "price_change": "close_t - close_t_minus_1",
                "pct_change": "close_t / close_t_minus_1 - 1",
                "amplitude": "(high - low) / close_t_minus_1",
            },
            "derivation_requirements": [
                "record derivation_method",
                "record previous_close_source",
                "set price_change/pct_change/amplitude to null for first observation without previous close",
                "do not mix raw/qfq/hfq adjustment modes",
                "derived fields inherit the original adjustment basis",
            ],
            "not_consumption_grade_hard_calculation": {
                "turnover_amount": "Do not compute from OHLC and volume; exact turnover amount needs source-provided transaction value.",
                "turnover_rate": "Do not compute without stable float/free-float share base.",
            },
        },
        "a_share_daily_missing_field_policy": {
            "amount": "source_provided_only_or_missing",
            "turnover_amount": "missing_until_stable_source_provides",
            "turnover_rate": "missing_until_float_share_source_available",
            "pct_change": "derived_candidate_with_method_and_previous_close_source",
            "amplitude": "derived_candidate_with_method_and_previous_close_source",
        },
        "source_priority_by_field": {
            "open": ["akshare_tencent_a_share_daily", "akshare_baostock_a_share_daily"],
            "high": ["akshare_tencent_a_share_daily", "akshare_baostock_a_share_daily"],
            "low": ["akshare_tencent_a_share_daily", "akshare_baostock_a_share_daily"],
            "close": ["akshare_tencent_a_share_daily", "akshare_baostock_a_share_daily"],
            "amount": ["akshare_tencent_a_share_daily", "eastmoney_specific_future_connector"],
            "turnover_rate": ["eastmoney_specific_future_connector", "future_float_share_connector"],
            "pct_change": ["derived_from_close_with_previous_close_source", "source_provided_fallback"],
            "preclose": ["source_provided_or_derived_from_prior_close_with_adjustment_policy"],
        },
    }


def build_akshare_interface_policy() -> dict[str, Any]:
    return {
        "version": "akshare_interface_trust_policy_v1",
        "generated_at": utc_now(),
        "wrapper_policy": "AKShare is evaluated interface-by-interface by upstream provenance, stability, field quality and QA evidence.",
        "interfaces": {
            "stock_zh_a_hist_tx": {
                "upstream": "tencent",
                "domain": "a_share_daily_market_data",
                "status": "primary_candidate",
                "consumer_status": "production_candidate",
                "known_fields": ["date", "open", "close", "high", "low", "amount"],
                "trust_role": "institutional_proxy_source",
                "default_chain": True,
                "notes": "Use as A-share daily primary candidate while recording adjustment mode and derivation policy.",
            },
            "stock_zh_a_hist": {
                "upstream": "eastmoney",
                "domain": "a_share_daily_market_data",
                "status": "unstable_for_primary",
                "consumer_status": "fallback_or_deferred",
                "default_chain": False,
                "monitor_required": True,
                "notes": "Eastmoney daily history endpoint remains unstable and must not be the default primary chain.",
            },
            "stock_balance_sheet_by_yearly_em": {
                "upstream": "eastmoney",
                "domain": "financial_statement_balance_sheet",
                "status": "available_keep",
                "consumer_status": "production_candidate",
                "trust_role": "institutional_proxy_source",
            },
            "stock_profit_sheet_by_yearly_em": {
                "upstream": "eastmoney",
                "domain": "financial_statement_income",
                "status": "available_keep",
                "consumer_status": "production_candidate",
                "trust_role": "institutional_proxy_source",
            },
            "stock_cash_flow_sheet_by_yearly_em": {
                "upstream": "eastmoney",
                "domain": "financial_statement_cash_flow",
                "status": "available_keep",
                "consumer_status": "production_candidate",
                "trust_role": "institutional_proxy_source",
            },
            "stock_yjbb_em": {
                "upstream": "eastmoney",
                "domain": "earnings_report_table",
                "status": "available_keep",
                "consumer_status": "production_candidate",
            },
            "stock_news_em": {
                "upstream": "eastmoney",
                "domain": "company_news_event_sentiment",
                "status": "available_keep",
                "consumer_status": "event_sentiment_candidate",
            },
            "stock_notice_report": {
                "upstream": "eastmoney",
                "domain": "announcement_metadata",
                "status": "available_keep",
                "consumer_status": "announcement_candidate_supplement",
                "authority_note": "CNINFO remains preferred authority for formal disclosure metadata and PDFs.",
            },
            "stock_financial_abstract": {
                "upstream": "sina",
                "domain": "financial_abstract",
                "status": "continue_testing",
                "consumer_status": "production_candidate_if_stability_passes",
            },
            "stock_financial_analysis_indicator": {
                "upstream": "sina",
                "domain": "financial_analysis_indicator",
                "status": "continue_testing",
                "consumer_status": "production_candidate_if_stability_passes",
            },
            "stock_financial_abstract_ths": {
                "upstream": "ths",
                "domain": "financial_abstract",
                "status": "continue_testing",
                "consumer_status": "production_candidate_if_stability_passes",
            },
        },
        "eastmoney_large_run_stability_metrics": [
            "success_rate",
            "failure_rate",
            "timeout_count",
            "anti_scraping_error",
            "field_missing_rate",
            "schema_drift",
            "last_successful_run",
            "last_failure_reason",
        ],
        "formal_trusted_consumption": False,
    }


def build_data_source_priority_policy() -> dict[str, Any]:
    return {
        "version": "data_source_priority_policy_v1",
        "generated_at": utc_now(),
        "multi_source_principles": [
            "FR does not use one universal data source.",
            "Choose primary sources by data domain, stability, provenance and field completeness.",
            "Keep source_priority and upstream provenance at field level.",
            "Do not use PDF parsing output to overwrite authoritative structured interfaces.",
        ],
        "domains": {
            "macro_rates_inflation_employment": {
                "primary_sources": ["fred_macro", "treasury_fiscaldata"],
                "retained_sources": ["FRED", "U.S. Treasury FiscalData", "BLS deferred retry"],
            },
            "us_regulatory_filings": {
                "primary_sources": ["sec_filings"],
                "retained_sources": ["SEC EDGAR"],
            },
            "a_share_daily_market": {
                "primary_sources": ["akshare_tencent_a_share_daily"],
                "secondary_sources": ["akshare_baostock_a_share_daily"],
                "deferred_sources": ["akshare_eastmoney_stock_zh_a_hist"],
            },
            "a_share_structured_financials": {
                "primary_sources": ["akshare_eastmoney_financial_statements", "akshare_ths_financial_abstract"],
                "secondary_sources": ["akshare_sina_financial_abstract"],
                "authority_metadata": ["cninfo_report_pdf"],
            },
            "announcements_and_reports": {
                "primary_sources": ["cninfo_report_pdf"],
                "supplemental_sources": ["eastmoney_notice_report"],
            },
        },
        "fallback_policy": "Fallback sources are used when primary is missing or unavailable; they do not silently overwrite primary values.",
    }


def build_financial_metric_priority() -> dict[str, Any]:
    metrics = [
        "revenue",
        "net_profit",
        "gross_margin",
        "net_margin",
        "roe",
        "roa",
        "eps",
        "debt_to_asset",
        "cash_flow_from_operations",
    ]
    return {
        "version": "financial_metric_source_priority_v1",
        "generated_at": utc_now(),
        "primary_selection_rule": "Select the most stable interface with the clearest field definition, consistent reporting period and timely updates.",
        "duplicate_financial_field_resolution_policy": {
            "same_company_same_period_same_metric": {
                "primary_source_value": "enters consumption candidate field",
                "secondary_source_value": "stored as validation_reference or fallback only",
                "fallback_behavior": "use secondary only when primary missing and provenance is retained",
                "large_discrepancy_behavior": "mark discrepancy_warning; do not start default manual review and do not let PDF parse overwrite structured interface",
            }
        },
        "metric_priorities": {
            metric: {
                "primary": "akshare_ths_financial_abstract",
                "secondary": "akshare_sina_financial_analysis_indicator",
                "fallback": "akshare_sina_financial_abstract",
                "statement_fallback": "akshare_eastmoney_financial_statements",
            }
            for metric in metrics
        },
        "comparison_targets": [
            "sina_stock_financial_abstract",
            "sina_stock_financial_analysis_indicator",
            "ths_stock_financial_abstract",
        ],
    }


def build_storage_retention_policy() -> dict[str, Any]:
    return {
        "version": "storage_retention_policy_v1",
        "generated_at": utc_now(),
        "no_direct_delete": True,
        "cleanup_plan_only": True,
        "long_term_keep": [
            "consumption-ready structured data",
            "production_candidate structured data",
            "financial abstracts",
            "balance sheet / income statement / cash flow structured tables",
            "daily market structured data",
            "announcement metadata",
            "PDF URL / local path / hash",
            "AI-consumable report summaries",
            "analysis reports",
            "forecast reports",
            "backtest results",
            "manifest",
            "QA summary",
            "provenance summary",
            "data product panel",
        ],
        "short_term_keep": [
            "raw API responses",
            "smoke test output",
            "temporary snapshots",
            "parser intermediates",
            "candidate validation samples",
            "cross-source validation samples",
            "debug output",
        ],
        "auto_cleanup_candidates": [
            "probe/debug files",
            "duplicate raw",
            "expired smoke tests",
            "temporary parser output",
            "useless cross-validation intermediate after summary retained",
            "large raw/parsed/normalized duplicate layers after validated product created",
            "temporary runtime files",
            "duplicate snapshots",
        ],
        "retention_principles": [
            "Keep the most important AI/research/forecast/backtest-ready structured data.",
            "After intermediate validation, keep summary / manifest / QA / provenance rather than all large layers.",
            "Do not keep raw, parsed and normalized full-size copies forever unless audit requires it.",
            "PDF handling may keep file or URL + hash; parser intermediates are not full-retention artifacts.",
            "This policy generates a cleanup plan only and does not delete NAS data.",
        ],
    }


def build_manual_update_stubs() -> dict[str, Any]:
    common = {
        "lookback_effective_days": 3,
        "upsert_policy": "latest_collected_wins",
        "full_backfill_policy": "disabled_until_explicit_backfill_plan",
    }
    stubs = [
        {
            **common,
            "source_id": "akshare_tencent_a_share_daily",
            "upstream": "tencent",
            "wrapper": "AKShare",
            "source_type": "institutional_proxy_source",
            "data_domain": "a_share_daily_market",
            "update_mode": "incremental",
            "effective_day_calendar_policy": "china_trading_day_weekday_stub",
            "latest_data_date": None,
            "retention_policy": "structured_long_term_raw_short_term",
            "consumer_status": "production_candidate",
            "default_update_mode": "manual_or_scheduled_incremental",
            "source_priority": 1,
            "fallback_source": "akshare_baostock_a_share_daily",
        },
        {
            **common,
            "source_id": "akshare_baostock_a_share_daily",
            "upstream": "baostock",
            "wrapper": "BaoStock",
            "source_type": "open_source_api_wrapper_candidate",
            "data_domain": "a_share_daily_market",
            "update_mode": "incremental",
            "effective_day_calendar_policy": "china_trading_day_weekday_stub",
            "latest_data_date": None,
            "retention_policy": "structured_long_term_raw_short_term",
            "consumer_status": "secondary_stable_validation_partner",
            "default_update_mode": "manual_or_scheduled_incremental",
            "source_priority": 2,
            "fallback_source": None,
        },
        {
            **common,
            "source_id": "akshare_sina_financial_abstract",
            "upstream": "sina",
            "wrapper": "AKShare",
            "source_type": "authoritative_third_party_candidate",
            "data_domain": "financial_abstract",
            "update_mode": "report_period_refresh",
            "effective_day_calendar_policy": "report_period_or_announcement_date",
            "latest_data_date": None,
            "retention_policy": "structured_long_term_raw_short_term",
            "consumer_status": "production_candidate",
            "default_update_mode": "manual_report_period_refresh",
            "source_priority": 3,
            "fallback_source": "akshare_ths_financial_abstract",
        },
        {
            **common,
            "source_id": "akshare_ths_financial_abstract",
            "upstream": "ths",
            "wrapper": "AKShare",
            "source_type": "institutional_proxy_source",
            "data_domain": "financial_abstract",
            "update_mode": "report_period_refresh",
            "effective_day_calendar_policy": "report_period_or_announcement_date",
            "latest_data_date": None,
            "retention_policy": "structured_long_term_raw_short_term",
            "consumer_status": "production_candidate",
            "default_update_mode": "manual_report_period_refresh",
            "source_priority": 2,
            "fallback_source": "akshare_sina_financial_abstract",
        },
        {
            **common,
            "source_id": "akshare_eastmoney_financial_statements",
            "upstream": "eastmoney",
            "wrapper": "AKShare",
            "source_type": "institutional_proxy_source",
            "data_domain": "financial_statements",
            "update_mode": "report_period_refresh",
            "effective_day_calendar_policy": "report_period_or_announcement_date",
            "latest_data_date": None,
            "retention_policy": "structured_long_term_raw_short_term",
            "consumer_status": "production_candidate",
            "default_update_mode": "manual_report_period_refresh",
            "source_priority": 1,
            "fallback_source": "akshare_ths_financial_abstract",
        },
        {
            **common,
            "source_id": "cninfo_report_pdf",
            "upstream": "cninfo",
            "wrapper": "AKShare_or_direct",
            "source_type": "official_or_authoritative_source",
            "data_domain": "announcement_financial_report_pdf",
            "update_mode": "announcement_date_refresh",
            "effective_day_calendar_policy": "announcement_date",
            "latest_data_date": None,
            "retention_policy": "keep_pdf_or_url_hash_only",
            "consumer_status": "official_or_authoritative_source",
            "default_update_mode": "manual_or_scheduled_announcement_refresh",
            "source_priority": 1,
            "fallback_source": "eastmoney_notice_report",
        },
        {
            **common,
            "source_id": "fred_macro",
            "upstream": "FRED",
            "wrapper": "FRED API",
            "source_type": "official_source",
            "data_domain": "macro_rates_inflation_employment",
            "update_mode": "release_date_incremental",
            "effective_day_calendar_policy": "release_date_or_observation_date",
            "latest_data_date": None,
            "retention_policy": "structured_long_term_raw_short_term",
            "consumer_status": "official_or_authoritative_source",
            "default_update_mode": "scheduled_incremental",
            "source_priority": 1,
            "fallback_source": None,
        },
        {
            **common,
            "source_id": "sec_filings",
            "upstream": "SEC",
            "wrapper": "SEC EDGAR",
            "source_type": "official_source",
            "data_domain": "us_company_filings",
            "update_mode": "filing_date_incremental",
            "effective_day_calendar_policy": "filing_date_or_accepted_date",
            "latest_data_date": None,
            "retention_policy": "structured_long_term_raw_short_term",
            "consumer_status": "official_or_authoritative_source",
            "default_update_mode": "scheduled_incremental",
            "source_priority": 1,
            "fallback_source": None,
        },
        {
            **common,
            "source_id": "eastmoney_specific_future_connector",
            "upstream": "eastmoney",
            "wrapper": "direct_or_AKShare_specific",
            "source_type": "institutional_proxy_source",
            "data_domain": "eastmoney_unique_fields",
            "update_mode": "deferred",
            "effective_day_calendar_policy": "field_specific",
            "latest_data_date": None,
            "retention_policy": "structured_if_validated",
            "consumer_status": "deferred",
            "default_update_mode": "disabled",
            "source_priority": 99,
            "fallback_source": None,
            "use_case": "only_for_fields_unavailable_elsewhere",
        },
    ]
    return {
        "version": "manual_update_framework_source_stubs_v1",
        "generated_at": utc_now(),
        "sources": stubs,
        "formal_trusted_consumption": False,
    }


def build_runtime_outputs(
    a_share_policy: dict[str, Any],
    akshare_policy: dict[str, Any],
    financial_metric_priority: dict[str, Any],
    storage_policy: dict[str, Any],
    manual_stubs: dict[str, Any],
) -> dict[str, Any]:
    tencent_derivation = {
        "version": "tencent_daily_field_derivation_v1",
        "generated_at": utc_now(),
        "raw_fields": a_share_policy["a_share_daily_field_derivation_policy"]["raw_fields_from_tencent"],
        "supplemented_fields": a_share_policy["a_share_daily_field_derivation_policy"]["supplemented_fields"],
        "derived_fields": a_share_policy["a_share_daily_field_derivation_policy"]["derived_fields"],
        "not_consumption_grade_hard_calculation": a_share_policy["a_share_daily_field_derivation_policy"]["not_consumption_grade_hard_calculation"],
    }
    eastmoney_policy = {
        "version": "eastmoney_interface_stability_policy_v1",
        "generated_at": utc_now(),
        "daily_history": akshare_policy["interfaces"]["stock_zh_a_hist"],
        "financial_statements": {
            key: value
            for key, value in akshare_policy["interfaces"].items()
            if key in {"stock_balance_sheet_by_yearly_em", "stock_profit_sheet_by_yearly_em", "stock_cash_flow_sheet_by_yearly_em"}
        },
        "earnings_news_notice": {
            key: value
            for key, value in akshare_policy["interfaces"].items()
            if key in {"stock_yjbb_em", "stock_news_em", "stock_notice_report"}
        },
        "required_large_run_metrics": akshare_policy["eastmoney_large_run_stability_metrics"],
    }
    sina_ths_comparison = {
        "version": "sina_ths_financial_interface_comparison_v1",
        "generated_at": utc_now(),
        "interfaces_to_continue_testing": {
            "sina_stock_financial_abstract": akshare_policy["interfaces"]["stock_financial_abstract"],
            "sina_stock_financial_analysis_indicator": akshare_policy["interfaces"]["stock_financial_analysis_indicator"],
            "ths_stock_financial_abstract": akshare_policy["interfaces"]["stock_financial_abstract_ths"],
        },
        "comparison_dimensions": [
            "stability",
            "field_completeness",
            "report_period_consistency",
            "update_frequency",
            "field_definition_clarity",
        ],
        "primary_selection": financial_metric_priority["primary_selection_rule"],
    }
    duplicate_policy = {
        "version": "duplicate_financial_field_resolution_policy_v1",
        "generated_at": utc_now(),
        **financial_metric_priority["duplicate_financial_field_resolution_policy"],
        "pdf_parse_override_allowed": False,
    }
    financial_report_policy = {
        "version": "financial_report_consumption_policy_v1",
        "generated_at": utc_now(),
        "structured_consumption_mainline": [
            "sina_stock_financial_abstract",
            "sina_stock_financial_analysis_indicator",
            "ths_stock_financial_abstract",
            "eastmoney_balance_sheet",
            "eastmoney_profit_sheet",
            "eastmoney_cash_flow_sheet",
            "eastmoney_yjbb",
            "cninfo_disclosure_metadata",
            "eastmoney_notice_report",
            "eastmoney_stock_news",
        ],
        "pdf_role": [
            "explain structured data",
            "support report summary",
            "support forecast logic",
            "source original management discussion and risk disclosure text",
        ],
        "pdf_parse_core_metric_source": False,
        "pdf_parse_failure_blocks_structured_consumption": False,
        "pdf_parse_overwrites_structured_interface": False,
        "long_term_metadata_fields": [
            "report_title",
            "report_type",
            "report_period",
            "announcement_date",
            "publish_date",
            "source",
            "pdf_url",
            "local_pdf_path",
            "file_hash",
            "downloaded_at",
            "source_interface",
            "announcement_id",
            "provenance",
        ],
    }
    retention_impact = {
        "version": "storage_retention_impact_review_v1",
        "generated_at": utc_now(),
        "cleanup_plan_only": True,
        "nas_deletion_performed": False,
        "recommended_actions": [
            "retain structured consumption candidates and manifests",
            "keep raw API responses short-term unless audit requires long-term raw retention",
            "keep PDF URL/hash or selected raw PDF but not all parser intermediates",
            "collapse duplicate raw/parsed/normalized layers after data product validation",
        ],
    }
    next_priority = {
        "version": "next_data_source_priority_v1",
        "generated_at": utc_now(),
        "priority_order": [
            "akshare_tencent_a_share_daily",
            "akshare_baostock_a_share_daily",
            "akshare_eastmoney_financial_statements",
            "akshare_ths_financial_abstract",
            "akshare_sina_financial_abstract",
            "cninfo_report_pdf",
            "fred_macro",
            "sec_filings",
            "eastmoney_specific_future_connector",
        ],
    }
    return {
        "akshare_interface_review_v1": akshare_policy,
        "tencent_daily_field_derivation_v1": tencent_derivation,
        "eastmoney_interface_stability_policy_v1": eastmoney_policy,
        "sina_ths_financial_interface_comparison_v1": sina_ths_comparison,
        "duplicate_financial_field_resolution_policy_v1": duplicate_policy,
        "financial_report_consumption_policy_v1": financial_report_policy,
        "storage_retention_impact_review_v1": retention_impact,
        "next_data_source_priority_v1": next_priority,
        "manual_update_framework_source_stubs_v1": manual_stubs,
    }


def write_docs(
    a_share_policy: dict[str, Any],
    akshare_policy: dict[str, Any],
    data_source_priority: dict[str, Any],
    financial_metric_priority: dict[str, Any],
    storage_policy: dict[str, Any],
    runtime_outputs: dict[str, Any],
) -> None:
    write_text(
        DOCS_ROOT / "A_SHARE_AKSHARE_DATA_SOURCE_STRATEGY.md",
        f"""# A-Share / AKShare Data Source Strategy

Generated: {a_share_policy['generated_at']}

FR evaluates data sources by interface, field, upstream provenance and stability. AKShare is a wrapper, not the only source and not a platform-level trust object.

## Daily Market Data

- Tencent `stock_zh_a_hist_tx`: primary A-share daily market candidate.
- BaoStock: stable supplement, validation partner and historical source where available.
- Eastmoney `stock_zh_a_hist`: unstable for primary use; fallback/deferred with monitoring.

Tencent raw fields are `date`, `open`, `close`, `high`, `low`, `amount`. Stock code, exchange, source, upstream and adjustment type are supplemented from request context. Price change, pct change and amplitude can be derived only with `derivation_method` and `previous_close_source`.

Turnover amount and turnover rate must not be hard-calculated as consumption-grade fields.
""",
    )
    write_text(
        DOCS_ROOT / "FINANCIAL_REPORT_STRUCTURED_DATA_POLICY.md",
        f"""# Financial Report Structured Data Policy

Generated: {runtime_outputs['financial_report_consumption_policy_v1']['generated_at']}

Structured financial interfaces are the consumption-candidate mainline. Sina, THS, Eastmoney financial statements, Eastmoney earnings tables, CNINFO disclosure metadata, Eastmoney notices and Eastmoney company news can be retained according to interface-level QA.

PDFs remain original report evidence for explanation, narrative, risk disclosure, management discussion and strategy context. PDF parsing does not overwrite structured interface metrics and parser failure does not block structured financial data consumption.
""",
    )
    write_text(
        DOCS_ROOT / "STORAGE_RETENTION_POLICY_V1.md",
        f"""# Storage Retention Policy v1

Generated: {storage_policy['generated_at']}

This policy creates a cleanup plan only. It does not delete NAS data.

Long-term retention favors consumption-ready structured data, production candidates, manifests, QA summaries, provenance summaries, analysis reports, forecasts, backtests and key PDF metadata. Short-term retention covers raw API responses, smoke outputs, parser intermediates and validation samples.

FR should not retain raw, parsed and normalized full-size duplicate layers forever unless audit requirements justify it.
""",
    )
    write_text(
        DOCS_ROOT / "DATA_SOURCE_PRIORITY_AND_FALLBACK_POLICY.md",
        f"""# Data Source Priority And Fallback Policy

Generated: {data_source_priority['generated_at']}

FR keeps FRED, SEC, BaoStock, Tencent, Sina, THS, CNINFO and Eastmoney by data domain. It does not collapse onto AKShare or any other universal source.

Fallback sources are used when primary values are unavailable. Fallback values do not silently overwrite primary values and always retain source provenance.
""",
    )
    write_text(
        DOCS_ROOT / "SINA_THS_FINANCIAL_INTERFACE_COMPARISON.md",
        f"""# Sina / THS Financial Interface Comparison

Generated: {runtime_outputs['sina_ths_financial_interface_comparison_v1']['generated_at']}

Interfaces under continued testing:

- Sina `stock_financial_abstract`
- Sina `stock_financial_analysis_indicator`
- THS `stock_financial_abstract_ths`

Comparison dimensions: stability, field completeness, reporting period consistency, update frequency and field definition clarity.

Duplicate financial fields resolve to primary / fallback / validation-reference roles. PDF parse output does not override structured financial interface values.
""",
    )


def run_policy_builder() -> dict[str, Any]:
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    a_share_policy = build_a_share_policy()
    akshare_policy = build_akshare_interface_policy()
    data_source_priority = build_data_source_priority_policy()
    financial_metric_priority = build_financial_metric_priority()
    storage_policy = build_storage_retention_policy()
    manual_stubs = build_manual_update_stubs()
    runtime_outputs = build_runtime_outputs(
        a_share_policy,
        akshare_policy,
        financial_metric_priority,
        storage_policy,
        manual_stubs,
    )

    config_outputs = {
        "a_share_data_source_policy.json": a_share_policy,
        "storage_retention_policy.json": storage_policy,
        "akshare_interface_trust_policy.json": akshare_policy,
        "data_source_priority_policy.json": data_source_priority,
        "financial_metric_source_priority.json": financial_metric_priority,
    }
    for name, payload in config_outputs.items():
        write_json(CONFIG_ROOT / name, payload)
    for name, payload in runtime_outputs.items():
        write_json(RUNTIME_ROOT / f"{name}.json", payload)
    write_docs(a_share_policy, akshare_policy, data_source_priority, financial_metric_priority, storage_policy, runtime_outputs)

    summary = {
        "generated_at": utc_now(),
        "codex_executed": True,
        "akshare_interface_report_included": True,
        "akshare_not_only_source": True,
        "stable_sources_retained": ["FRED", "SEC", "BaoStock", "Tencent", "CNINFO"],
        "formal_trusted_consumption": False,
        "openai_api_called": False,
        "parse_lab_affected": False,
        "config_outputs": sorted(config_outputs),
        "runtime_outputs": sorted(f"{key}.json" for key in runtime_outputs),
        "docs_outputs": [
            "docs/A_SHARE_AKSHARE_DATA_SOURCE_STRATEGY.md",
            "docs/FINANCIAL_REPORT_STRUCTURED_DATA_POLICY.md",
            "docs/STORAGE_RETENTION_POLICY_V1.md",
            "docs/DATA_SOURCE_PRIORITY_AND_FALLBACK_POLICY.md",
            "docs/SINA_THS_FINANCIAL_INTERFACE_COMPARISON.md",
        ],
    }
    write_json(RUNTIME_ROOT / "a_share_data_source_policy_summary_v1.json", summary)
    return summary


if __name__ == "__main__":
    print(json.dumps(run_policy_builder(), ensure_ascii=False, indent=2))
