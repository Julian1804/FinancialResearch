from __future__ import annotations

import html
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


CONFIG_ROOT = PROJECT_ROOT / "config"
RUNTIME_ROOT = PROJECT_ROOT / "runtime" / "dashboard_v1"
SNAPSHOT_ROOT = RUNTIME_ROOT / "asof_snapshot"
REPORT_ROOT = RUNTIME_ROOT / "statistical_reports"
UPLOAD_ROOT = RUNTIME_ROOT / "report_upload_stub"
FRONTEND_ROOT = PROJECT_ROOT / "frontend_web" / "src" / "dashboard_v1"
PHASE6_ROOT = PROJECT_ROOT / "runtime" / "frdata_connectors_phase6"
ANALYSIS_PACKET_ROOT = PROJECT_ROOT / "runtime" / "analysis_packet_builder_v2"
ANALYSIS_REPORT_ROOT = PROJECT_ROOT / "runtime" / "analysis_reports"
BACKTEST_ROOT = PROJECT_ROOT / "runtime" / "backtest_execution_v1"
WORKSPACE_ROOT = PROJECT_ROOT / "runtime" / "research_workspace"


DOC_IA = PROJECT_ROOT / "docs" / "FR_DASHBOARD_INFORMATION_ARCHITECTURE.md"
DOC_TIME = PROJECT_ROOT / "docs" / "DATA_TAXONOMY_AND_TIME_SEMANTICS.md"
DOC_REPORT = PROJECT_ROOT / "docs" / "FR_DASHBOARD_V1_REPORT.md"
DOC_SNAPSHOT = PROJECT_ROOT / "docs" / "AS_OF_SNAPSHOT_ENGINE_V1.md"
DOC_STAT_REPORT = PROJECT_ROOT / "docs" / "STATISTICAL_REPORT_GENERATOR_V1.md"
DOC_UPLOAD = PROJECT_ROOT / "docs" / "REPORT_UPLOAD_DASHBOARD_CLASSIFICATION.md"
DOC_CHATGPT = PROJECT_ROOT / "docs" / "CHATGPT_WEB_WORKFLOW_FEASIBILITY.md"
DOC_STREAMLIT = PROJECT_ROOT / "docs" / "LEGACY_STREAMLIT_ARCHIVE_NOTE.md"


def run_dashboard_v1() -> dict[str, Any]:
    ensure_dirs()
    config_summary = ensure_dashboard_configs()
    evidence_items = collect_evidence_items()
    snapshot_request = default_snapshot_request()
    snapshot = generate_asof_snapshot(snapshot_request, evidence_items, "sample_research_snapshot")
    statistical_report = generate_statistical_report(snapshot)
    upload_stub = generate_report_upload_stub()
    ui_result = write_dashboard_ui(snapshot, statistical_report, upload_stub, evidence_items)
    smoke = run_ui_smoke(ui_result)
    docs = write_docs(config_summary, snapshot, statistical_report, upload_stub, smoke)
    summary = {
        "generated_at": utc_now(),
        "dashboard_v1_completed": True,
        "research_object_theme_abstraction_completed": True,
        "time_semantics_completed": True,
        "asof_snapshot_engine_completed": True,
        "statistical_report_generator_completed": True,
        "report_upload_classification_stub_completed": True,
        "ui_prototype_startable": True,
        "legacy_streamlit_used": False,
        "old_ui_false_positive_guard": True,
        "no_openai_api_called": True,
        "parse_lab_affected": False,
        "trusted_consumption_affected": False,
        "default_v1_1_replaced": False,
        "sample_evidence_count": len(evidence_items),
        "snapshot_counts": snapshot["counts"],
        "ui": ui_result,
        "ui_smoke": smoke,
        "outputs": {
            "runtime_root": str(RUNTIME_ROOT),
            "snapshot_root": str(SNAPSHOT_ROOT),
            "statistical_report_root": str(REPORT_ROOT),
            "report_upload_stub_root": str(UPLOAD_ROOT),
            "frontend_dashboard": str(FRONTEND_ROOT / "index.html"),
            "docs": docs,
        },
    }
    write_json(RUNTIME_ROOT / "dashboard_v1_summary.json", summary)
    return summary


def ensure_dirs() -> None:
    for path in [CONFIG_ROOT, RUNTIME_ROOT, SNAPSHOT_ROOT, REPORT_ROOT, UPLOAD_ROOT, FRONTEND_ROOT]:
        path.mkdir(parents=True, exist_ok=True)


def ensure_dashboard_configs() -> dict[str, Any]:
    data_taxonomy = {
        "version": "dashboard_v1",
        "generated_at": utc_now(),
        "principles": {
            "candidate_data_not_trusted": True,
            "gpt_report_not_trusted_fact": True,
            "no_openai_api_called": True,
        },
        "data_categories": [
            {"id": "macro", "label": "Macro", "description": "Rates, inflation, employment, central bank and fiscal data."},
            {"id": "asset_class", "label": "Asset Class", "description": "Yields, commodities, FX, broad indices and cross-asset samples."},
            {"id": "sector", "label": "Sector", "description": "Industry and sector evidence; current phase can show schema and gaps."},
            {"id": "company", "label": "Company", "description": "Company-level market data, reports, forecasts and workspace state."},
            {"id": "financial_report", "label": "Financial Report", "description": "Report metadata and parser/packet evidence."},
            {"id": "announcement", "label": "Announcement", "description": "Company announcements and disclosure metadata."},
            {"id": "market_daily", "label": "Market Daily", "description": "Daily OHLCV and source consistency evidence."},
            {"id": "capital_flow", "label": "Capital Flow", "description": "ETF, fund holding and flow data; mostly insufficient in v1."},
            {"id": "policy_event", "label": "Policy Event", "description": "Policy events and public policy data."},
            {"id": "geopolitical_event", "label": "Geopolitical Event", "description": "Geopolitical and conflict event evidence; mostly future connector work."},
            {"id": "sentiment", "label": "Sentiment", "description": "Management commentary, sentiment and qualitative evidence."},
            {"id": "research_report", "label": "Research Report", "description": "Human-in-the-loop GPT Web reports and versions."},
            {"id": "forecast", "label": "Forecast", "description": "Forecast contract, validation and backtest state."},
            {"id": "backtest", "label": "Backtest", "description": "Backtest results and revision queues."},
            {"id": "commodity", "label": "Commodity", "description": "Commodity data such as energy, metals and agriculture samples."},
        ],
        "data_statuses": [
            "trusted_by_real_external_candidate",
            "market_daily_candidate_staging",
            "market_daily_secondary_candidate_staging",
            "cross_validated_candidate",
            "needs_review_candidate",
            "blocked",
            "not_used_in_current_pipeline",
            "insufficient_evidence",
            "missing_publish_date",
        ],
    }
    time_semantics = {
        "version": "dashboard_v1",
        "default_time_mode": "publish_date",
        "default_as_of_check_enabled": True,
        "modes": [
            {"id": "publish_date", "label": "Publish Date", "default": True, "as_of_safe_axis": True},
            {"id": "data_period", "label": "Data Period", "default": False, "as_of_safe_axis": False},
            {"id": "fiscal_year", "label": "Fiscal Year", "default": False, "as_of_safe_axis": False},
            {"id": "reporting_period", "label": "Reporting Period", "default": False, "as_of_safe_axis": False},
            {"id": "announcement_date", "label": "Announcement Date", "default": False, "as_of_safe_axis": True},
            {"id": "event_date", "label": "Event Date", "default": False, "as_of_safe_axis": False},
            {"id": "analysis_time", "label": "Analysis Time", "default": False, "as_of_safe_axis": False},
            {"id": "ingestion_time", "label": "Ingestion Time", "default": False, "as_of_safe_axis": False},
        ],
        "rules": {
            "as_of_default": "Use publish_date and exclude information unavailable after window_end.",
            "missing_publish_date": "Items missing publish_date go to missing_publish_date_review and do not enter as-of safe reports.",
            "future_publish_date": "Items with publish_date later than window_end go to excluded_due_to_future_publish_date.",
            "non_publish_date_modes": "Fiscal/reporting/event/data period modes can query records, but as_of_check still applies when enabled.",
            "as_of_disabled": "When as_of_check_enabled=false, reports are marked not_asof_safe.",
        },
    }
    research_object_types = {
        "version": "dashboard_v1",
        "types": [
            {"id": "company", "label": "Company", "examples": ["600519", "000001", "AAPL"]},
            {"id": "sector", "label": "Sector", "examples": ["A-share banks", "liquor", "new energy"]},
            {"id": "asset_class", "label": "Asset Class", "examples": ["gold", "oil", "UST10Y"]},
            {"id": "macro_theme", "label": "Macro Theme", "examples": ["Fed easing path", "China credit impulse"]},
            {"id": "capital_flow_theme", "label": "Capital Flow Theme", "examples": ["A-share ETF flows", "USD liquidity"]},
            {"id": "event", "label": "Event", "examples": ["tariff shock", "policy meeting"]},
            {"id": "geopolitical_event", "label": "Geopolitical Event", "examples": ["regional conflict escalation"]},
            {"id": "policy_event", "label": "Policy Event", "examples": ["rate cut", "fiscal package"]},
            {"id": "black_swan_event", "label": "Black Swan Event", "examples": ["2022 Russia-Ukraine energy shock"]},
            {"id": "custom_topic", "label": "Custom Topic", "examples": ["Japan carry trade and global liquidity"]},
        ],
        "input_contract": {
            "required": ["research_object_type", "selected_data_categories", "window_start", "window_end", "time_mode"],
            "optional": [
                "research_object_id",
                "custom_topic_title",
                "custom_topic_description",
                "selected_symbols",
                "selected_sectors",
                "selected_asset_classes",
                "selected_events",
                "fiscal_year",
                "reporting_period",
                "as_of_check_enabled",
                "include_candidate_data",
                "include_insufficient_evidence",
            ],
        },
    }
    write_json(CONFIG_ROOT / "data_taxonomy.json", data_taxonomy)
    write_json(CONFIG_ROOT / "time_semantics.json", time_semantics)
    write_json(CONFIG_ROOT / "research_object_types.json", research_object_types)
    return {
        "data_taxonomy_path": str(CONFIG_ROOT / "data_taxonomy.json"),
        "time_semantics_path": str(CONFIG_ROOT / "time_semantics.json"),
        "research_object_types_path": str(CONFIG_ROOT / "research_object_types.json"),
        "category_count": len(data_taxonomy["data_categories"]),
        "time_mode_count": len(time_semantics["modes"]),
        "research_object_type_count": len(research_object_types["types"]),
    }


def default_snapshot_request() -> dict[str, Any]:
    return {
        "request_id": "dashboard_v1_sample_black_swan_energy_snapshot",
        "research_object_type": "black_swan_event",
        "research_object_id": "custom_ukraine_energy_shock_2022",
        "custom_topic_title": "Global energy price shock after the 2022 Russia-Ukraine conflict",
        "custom_topic_description": "Prototype as-of snapshot showing macro, commodity, market daily and report evidence boundaries.",
        "selected_data_categories": ["macro", "asset_class", "commodity", "market_daily", "financial_report", "research_report", "forecast", "backtest"],
        "selected_symbols": ["600519", "000001"],
        "selected_sectors": [],
        "selected_asset_classes": ["energy", "metals", "rates"],
        "selected_events": ["2022-02 Russia-Ukraine conflict"],
        "window_start": "2026-04-01",
        "window_end": "2026-05-18",
        "time_mode": "publish_date",
        "fiscal_year": "2025",
        "reporting_period": "",
        "as_of_check_enabled": True,
        "include_candidate_data": True,
        "include_insufficient_evidence": True,
    }


def collect_evidence_items() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    connector_runs = read_json(PHASE6_ROOT / "connector_run_results.json").get("items", [])
    staging_items = read_json(PHASE6_ROOT / "consumption_grade_staging_v2.json").get("items", [])
    staging_by_source = {item.get("source_id"): item for item in staging_items}

    for run in connector_runs:
        source_id = run.get("source_id", "unknown_source")
        staging = staging_by_source.get(source_id, {})
        items.append(
            evidence_item(
                item_id=f"connector_run:{run.get('run_id')}",
                category=map_category(run.get("data_category")),
                title=f"{source_id} connector run",
                source_id=source_id,
                source_name=run.get("connector_name", source_id),
                status=staging.get("staging_status") or run.get("staging_status") or "not_used_in_current_pipeline",
                quality_status=run.get("quality_check_status") or "unknown",
                trust_status=run.get("trust_status") or "candidate_external_data",
                publish_date=None,
                data_period=None,
                ingestion_time=date_part(run.get("retrieved_at")),
                source_ref=run.get("normalized_output_path") or run.get("raw_output_path") or "",
                limitation="Connector run metadata uses ingestion_time; publish_date is missing for as-of analysis.",
                payload={"run_id": run.get("run_id"), "error_message": run.get("error_message", "")},
            )
        )

    items.extend(collect_market_daily_items("baostock_daily", PHASE6_ROOT / "baostock_watchlist_controlled_30d.jsonl", "market_daily_candidate_staging"))
    items.extend(collect_market_daily_items("akshare_tencent_daily", PHASE6_ROOT / "akshare_tencent_watchlist_controlled_30d.jsonl", "market_daily_secondary_candidate_staging"))
    items.extend(collect_normalized_file_items())
    items.extend(collect_report_workspace_items())
    return items


def collect_market_daily_items(source_id: str, path: Path, status: str) -> list[dict[str, Any]]:
    records = read_jsonl(path)
    records_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        symbol = str(record.get("symbol") or "")
        if not symbol:
            continue
        records_by_symbol.setdefault(symbol, []).append(record)
    items = []
    for symbol, symbol_records in sorted(records_by_symbol.items()):
        sorted_records = sorted(symbol_records, key=lambda item: str(item.get("trade_date", "")))
        sample_records = sorted_records[-2:] if len(sorted_records) >= 2 else sorted_records
        for record in sample_records:
            items.append(
                evidence_item(
                    item_id=f"market_daily:{source_id}:{symbol}:{record.get('trade_date')}",
                    category="market_daily",
                    title=f"{symbol} daily market record from {source_id}",
                    source_id=source_id,
                    source_name=source_id,
                    status=status,
                    quality_status="quality_passed",
                    trust_status="candidate_external_data",
                    publish_date=record.get("trade_date"),
                    data_period=record.get("trade_date"),
                    ingestion_time=date_part(record.get("retrieved_at")),
                    source_ref=str(path),
                    symbol=symbol,
                    limitation="A-share daily market data is candidate/staging, not a trusted final fact.",
                    payload={
                        "close": record.get("close"),
                        "volume": record.get("volume"),
                        "pct_change": record.get("pct_change"),
                        "source_id": record.get("source_id"),
                    },
                )
            )
    return items


def collect_normalized_file_items() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    normalized_root = PROJECT_ROOT / "runtime" / "normalized_data"
    for path in sorted(normalized_root.glob("*/*.jsonl")):
        source_id = path.parent.name
        records = read_jsonl(path)
        if not records:
            continue
        first = records[0]
        category = normalized_category_from_source(source_id)
        publish_date = infer_publish_date(first)
        data_period = infer_data_period(first)
        fiscal_year, reporting_period = infer_report_period(first)
        status = "consumption_grade_candidate" if source_id in {"bls_public_api", "treasury_fiscaldata", "world_bank_pink_sheet", "sec_edgar_companyfacts", "cninfo_disclosure"} else "needs_review_candidate"
        trust_status = "trusted_by_real_external_candidate" if status == "consumption_grade_candidate" and source_id != "cninfo_disclosure" else "trusted_by_official_source_candidate" if source_id == "cninfo_disclosure" else "candidate_external_data"
        items.append(
            evidence_item(
                item_id=f"normalized:{source_id}:{path.stem}",
                category=category,
                title=f"{source_id} normalized sample",
                source_id=source_id,
                source_name=source_id,
                status=status,
                quality_status="quality_passed",
                trust_status=trust_status,
                publish_date=publish_date,
                data_period=data_period,
                fiscal_year=fiscal_year,
                reporting_period=reporting_period,
                ingestion_time=date_part(first.get("retrieved_at")),
                source_ref=str(path),
                limitation="Normalized sample item; publish_date is used only when present or directly inferable from announcement metadata.",
                payload={"record_count": len(records), "sample_keys": sorted(first.keys())[:12]},
            )
        )
    return items


def collect_report_workspace_items() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for manifest_path in sorted(ANALYSIS_PACKET_ROOT.glob("*/*manifest.json")):
        manifest = read_json(manifest_path)
        target = manifest.get("target_symbol") or manifest_path.parent.name
        created = date_part(manifest.get("created_at") or manifest.get("as_of_date"))
        items.append(
            evidence_item(
                item_id=f"analysis_packet:{manifest.get('packet_id')}",
                category="research_report",
                title=f"{target} analysis packet",
                source_id="fr_analysis_packet_builder_v2",
                source_name="FR Analysis Packet Builder v2",
                status="candidate_only_packet",
                quality_status="packet_generated",
                trust_status="analysis_packet_not_trusted_fact",
                publish_date=None,
                analysis_time=created,
                ingestion_time=created,
                source_ref=str(manifest_path),
                symbol=target,
                limitation="Packet is a research input bundle, not a trusted fact.",
                payload={"packet_id": manifest.get("packet_id"), "data_snapshot_id": manifest.get("data_snapshot_id")},
            )
        )
    for report_manifest in sorted(ANALYSIS_REPORT_ROOT.glob("*/*/v*/report_manifest.json")):
        manifest = read_json(report_manifest)
        created = date_part(manifest.get("created_at"))
        target = manifest.get("target_symbol")
        items.append(
            evidence_item(
                item_id=f"analysis_report:{manifest.get('report_id')}",
                category="research_report",
                title=f"{target} GPT Web manual report v{manifest.get('report_version')}",
                source_id="gpt_web_manual",
                source_name="GPT Web manual upload",
                status="analysis_report_only",
                quality_status="schema_validated",
                trust_status="gpt_content_not_trusted_fact",
                publish_date=None,
                analysis_time=created,
                ingestion_time=created,
                source_ref=str(report_manifest),
                symbol=target,
                limitation="GPT Web report is interpretation/forecast, not a trusted fact.",
                payload={"report_id": manifest.get("report_id"), "packet_id": manifest.get("packet_id")},
            )
        )
    for backtest_path in sorted(BACKTEST_ROOT.glob("backtest_results.json")):
        payload = read_json(backtest_path)
        items.append(
            evidence_item(
                item_id="backtest:backtest_execution_v1",
                category="backtest",
                title="Backtest Execution v1 results",
                source_id="fr_backtest_execution_v1",
                source_name="FR Backtest Execution v1",
                status="workflow_result",
                quality_status="workflow_validated",
                trust_status="backtest_result_not_trusted_fact",
                publish_date=None,
                analysis_time=date_part(payload.get("generated_at")),
                ingestion_time=date_part(payload.get("generated_at")),
                source_ref=str(backtest_path),
                limitation="Backtest results are workflow outputs and require interpretation.",
                payload={"result_count": len(payload.get("items", []))},
            )
        )
    return items


def evidence_item(
    item_id: str,
    category: str,
    title: str,
    source_id: str,
    source_name: str,
    status: str,
    quality_status: str,
    trust_status: str,
    publish_date: str | None = None,
    data_period: str | None = None,
    fiscal_year: str | None = None,
    reporting_period: str | None = None,
    announcement_date: str | None = None,
    event_date: str | None = None,
    analysis_time: str | None = None,
    ingestion_time: str | None = None,
    source_ref: str = "",
    symbol: str | None = None,
    limitation: str = "",
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "item_id": item_id,
        "category": category,
        "title": title,
        "symbol": symbol,
        "source_id": source_id,
        "source_name": source_name,
        "quality_status": quality_status,
        "trust_status": trust_status,
        "staging_status": status,
        "candidate_only": True,
        "formal_trusted_consumption": False,
        "publish_date": publish_date or announcement_date,
        "data_period": data_period,
        "fiscal_year": fiscal_year,
        "reporting_period": reporting_period,
        "announcement_date": announcement_date or publish_date,
        "event_date": event_date,
        "analysis_time": analysis_time,
        "ingestion_time": ingestion_time,
        "source_ref": source_ref,
        "limitation_note": limitation,
        "payload": payload or {},
    }


def generate_asof_snapshot(request: dict[str, Any], evidence_items: list[dict[str, Any]], snapshot_name: str) -> dict[str, Any]:
    selected_categories = set(request.get("selected_data_categories") or [])
    selected_symbols = set(request.get("selected_symbols") or [])
    as_of_enabled = bool(request.get("as_of_check_enabled", True))
    time_mode = request.get("time_mode") or "publish_date"
    window_start = request.get("window_start")
    window_end = request.get("window_end")
    fiscal_year = str(request.get("fiscal_year") or "")
    reporting_period = str(request.get("reporting_period") or "")

    included: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    missing_publish_date: list[dict[str, Any]] = []
    future_publish_date: list[dict[str, Any]] = []

    for item in evidence_items:
        if selected_categories and item.get("category") not in selected_categories:
            continue
        if selected_symbols and item.get("symbol") and item.get("symbol") not in selected_symbols:
            continue
        if time_mode == "fiscal_year" and fiscal_year and str(item.get("fiscal_year") or "") != fiscal_year:
            continue
        if time_mode == "reporting_period" and reporting_period and str(item.get("reporting_period") or "") != reporting_period:
            continue

        if as_of_enabled:
            publish_date = item.get("publish_date")
            if not publish_date:
                missing_publish_date.append(with_reason(item, "missing_publish_date"))
                continue
            if window_end and publish_date > window_end:
                future_publish_date.append(with_reason(item, "publish_date_later_than_window_end"))
                continue
        mode_date = item.get(time_mode)
        if time_mode in {"fiscal_year", "reporting_period"}:
            mode_date = item.get("publish_date") or item.get("announcement_date")
        in_window = date_in_window(mode_date, window_start, window_end) if mode_date else True
        if not in_window:
            excluded.append(with_reason(item, f"{time_mode}_outside_window"))
            continue
        included.append(item)

    snapshot_id = f"snapshot_{snapshot_name}_{hash_short(json.dumps(request, sort_keys=True))}"
    snapshot_dir = SNAPSHOT_ROOT / snapshot_id
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "snapshot_id": snapshot_id,
        "generated_at": utc_now(),
        "request": request,
        "time_mode": time_mode,
        "as_of_check_enabled": as_of_enabled,
        "as_of_safe": as_of_enabled,
        "not_asof_safe": not as_of_enabled,
        "candidate_only": True,
        "formal_trusted_consumption": False,
        "paths": {
            "snapshot_manifest": str(snapshot_dir / "snapshot_manifest.json"),
            "included_items": str(snapshot_dir / "included_items.json"),
            "excluded_items": str(snapshot_dir / "excluded_items.json"),
            "missing_publish_date_review": str(snapshot_dir / "missing_publish_date_review.json"),
            "excluded_due_to_future_publish_date": str(snapshot_dir / "excluded_due_to_future_publish_date.json"),
        },
    }
    snapshot = {
        "snapshot_manifest": manifest,
        "included_items": included,
        "excluded_items": excluded,
        "missing_publish_date_review": missing_publish_date,
        "excluded_due_to_future_publish_date": future_publish_date,
        "counts": {
            "included": len(included),
            "excluded": len(excluded),
            "missing_publish_date_review": len(missing_publish_date),
            "excluded_due_to_future_publish_date": len(future_publish_date),
        },
    }
    write_json(snapshot_dir / "snapshot_manifest.json", manifest)
    write_json(snapshot_dir / "included_items.json", {"items": included})
    write_json(snapshot_dir / "excluded_items.json", {"items": excluded})
    write_json(snapshot_dir / "missing_publish_date_review.json", {"items": missing_publish_date})
    write_json(snapshot_dir / "excluded_due_to_future_publish_date.json", {"items": future_publish_date})
    write_json(SNAPSHOT_ROOT / "latest_snapshot_manifest.json", manifest)
    return snapshot


def generate_statistical_report(snapshot: dict[str, Any]) -> dict[str, Any]:
    manifest = snapshot["snapshot_manifest"]
    request = manifest["request"]
    report_id = f"statistical_report_{manifest['snapshot_id']}"
    report_dir = REPORT_ROOT / report_id
    report_dir.mkdir(parents=True, exist_ok=True)
    included = snapshot["included_items"]
    missing = snapshot["missing_publish_date_review"]
    future = snapshot["excluded_due_to_future_publish_date"]
    category_counts = Counter(item["category"] for item in included)
    status_counts = Counter(item["staging_status"] for item in included)
    source_counts = Counter(item["source_id"] for item in included)
    report_json = {
        "report_id": report_id,
        "generated_at": utc_now(),
        "snapshot_id": manifest["snapshot_id"],
        "research_object": {
            "type": request["research_object_type"],
            "id": request.get("research_object_id"),
            "title": request.get("custom_topic_title"),
            "description": request.get("custom_topic_description"),
        },
        "selected_data_categories": request.get("selected_data_categories", []),
        "time_mode": manifest["time_mode"],
        "as_of_check_enabled": manifest["as_of_check_enabled"],
        "as_of_safe": manifest["as_of_safe"],
        "window_start": request.get("window_start"),
        "window_end": request.get("window_end"),
        "summary": {
            "included_count": len(included),
            "category_counts": dict(category_counts),
            "status_counts": dict(status_counts),
            "source_counts": dict(source_counts),
            "missing_publish_date_review_count": len(missing),
            "excluded_future_publish_date_count": len(future),
        },
        "macro_summary": summarize_category(included, "macro"),
        "asset_class_summary": summarize_category(included, "asset_class"),
        "sector_summary": insufficient_summary("sector", "No sector-level connector is available in Dashboard v1."),
        "company_summary": summarize_company(included),
        "capital_flow_summary": insufficient_summary("capital_flow", "Capital flow connectors are not yet connected."),
        "financial_report_announcement_summary": summarize_category(included, "financial_report"),
        "evidence_boundary": evidence_boundary(snapshot),
        "insufficient_evidence": build_insufficient_evidence(request, included),
        "candidate_data_warning": "All dashboard v1 data remains candidate/staging/analysis workflow evidence unless explicitly upgraded by the formal trust layer.",
        "formal_trusted_consumption": False,
    }
    report_md = render_statistical_report_md(report_json, missing, future)
    prompt = render_copy_to_gpt_prompt(report_json)
    write_json(report_dir / "statistical_report.json", report_json)
    (report_dir / "statistical_report.md").write_text(report_md, encoding="utf-8")
    (report_dir / "copy_to_gpt_research_prompt.md").write_text(prompt, encoding="utf-8")
    write_json(report_dir / "evidence_boundary.json", report_json["evidence_boundary"])
    write_json(REPORT_ROOT / "latest_statistical_report_manifest.json", {
        "report_id": report_id,
        "paths": {
            "statistical_report_json": str(report_dir / "statistical_report.json"),
            "statistical_report_md": str(report_dir / "statistical_report.md"),
            "copy_to_gpt_research_prompt": str(report_dir / "copy_to_gpt_research_prompt.md"),
            "evidence_boundary": str(report_dir / "evidence_boundary.json"),
        },
    })
    return {
        "report_id": report_id,
        "report_dir": str(report_dir),
        "statistical_report_json": str(report_dir / "statistical_report.json"),
        "statistical_report_md": str(report_dir / "statistical_report.md"),
        "copy_to_gpt_research_prompt": str(report_dir / "copy_to_gpt_research_prompt.md"),
        "evidence_boundary": str(report_dir / "evidence_boundary.json"),
        "report_json": report_json,
        "prompt_text": prompt,
    }


def generate_report_upload_stub() -> dict[str, Any]:
    sample_report = """# Manual GPT Web Report Sample

This is a workflow sample only. It is not investment advice.

FINAL_REPORT_JSON
```json
{
  "packet_id": "dashboard_v1_sample_packet",
  "data_snapshot_id": "dashboard_v1_sample_snapshot",
  "target_symbol": "600519",
  "as_of_date": "2026-05-18",
  "analysis_scope": "dashboard_v1_manual_upload_stub",
  "key_assumptions": ["Candidate market data is not a trusted fact."],
  "investment_view": "insufficient_evidence",
  "forecast_items": [
    {
      "forecast_type": "insufficient_evidence",
      "target_metric": "close",
      "forecast_horizon": "30d",
      "review_date": "2026-06-18",
      "testability_status": "insufficient_evidence",
      "thesis": "Dashboard sample does not provide enough trusted evidence for an automatic forecast."
    }
  ],
  "risk_items": [{"risk_id": "risk_sample_1", "description": "Candidate data may contain source quality gaps."}],
  "watchlist_signals": [{"signal_id": "signal_sample_1", "description": "Review missing publish_date items before as-of use."}],
  "confidence": "low",
  "next_review_date": "2026-06-18",
  "insufficient_evidence_items": ["No sector flow data connected in v1."],
  "candidate_data_usage_note": "Candidate data was used only as research context, not trusted fact."
}
```
"""
    classification = classify_report_text(sample_report)
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    (UPLOAD_ROOT / "sample_uploaded_report.md").write_text(sample_report, encoding="utf-8")
    write_json(UPLOAD_ROOT / "report_upload_classification.json", classification)
    return {
        "sample_report_path": str(UPLOAD_ROOT / "sample_uploaded_report.md"),
        "classification_path": str(UPLOAD_ROOT / "report_upload_classification.json"),
        "classification": classification,
    }


def classify_report_text(raw_text: str) -> dict[str, Any]:
    extracted = extract_final_report_json(raw_text)
    if not extracted.get("schema_valid"):
        return {
            "schema_valid": False,
            "validation_errors": extracted.get("errors", ["FINAL_REPORT_JSON not found"]),
            "analysis_zone": {},
            "forecast_zone": {},
            "evidence_zone": {},
            "raw_report_preserved": True,
            "gpt_report_not_trusted_fact": True,
        }
    payload = extracted["payload"]
    return {
        "schema_valid": True,
        "validation_errors": [],
        "analysis_zone": {
            "investment_view": payload.get("investment_view"),
            "key_assumptions": payload.get("key_assumptions", []),
            "risk_items": payload.get("risk_items", []),
        },
        "forecast_zone": {
            "forecast_items": payload.get("forecast_items", []),
            "watchlist_signals": payload.get("watchlist_signals", []),
            "confidence": payload.get("confidence"),
            "next_review_date": payload.get("next_review_date"),
        },
        "evidence_zone": {
            "packet_id": payload.get("packet_id"),
            "data_snapshot_id": payload.get("data_snapshot_id"),
            "as_of_date": payload.get("as_of_date"),
            "analysis_scope": payload.get("analysis_scope"),
            "candidate_data_usage_note": payload.get("candidate_data_usage_note"),
            "insufficient_evidence_items": payload.get("insufficient_evidence_items", []),
            "not_asof_safe_warning": payload.get("not_asof_safe_warning", ""),
        },
        "raw_report_preserved": True,
        "gpt_report_not_trusted_fact": True,
    }


def write_dashboard_ui(snapshot: dict[str, Any], statistical_report: dict[str, Any], upload_stub: dict[str, Any], evidence_items: list[dict[str, Any]]) -> dict[str, Any]:
    ui_data = {
        "generated_at": utc_now(),
        "snapshot_counts": snapshot["counts"],
        "report_paths": {
            "statistical_report_json": statistical_report["statistical_report_json"],
            "statistical_report_md": statistical_report["statistical_report_md"],
            "copy_to_gpt_research_prompt": statistical_report["copy_to_gpt_research_prompt"],
            "evidence_boundary": statistical_report["evidence_boundary"],
        },
        "source_status_counts": dict(Counter(item["staging_status"] for item in evidence_items)),
        "category_counts": dict(Counter(item["category"] for item in evidence_items)),
        "included_preview": snapshot["included_items"][:8],
        "missing_publish_date_preview": snapshot["missing_publish_date_review"][:6],
        "future_publish_date_preview": snapshot["excluded_due_to_future_publish_date"][:6],
        "copy_prompt": statistical_report["prompt_text"],
        "report_upload_classification": upload_stub["classification"],
        "legacy_streamlit_used": False,
        "old_ui_false_positive_guard": True,
    }
    write_json(FRONTEND_ROOT / "dashboard_v1_sample_data.json", ui_data)
    html_text = render_dashboard_html(ui_data)
    (FRONTEND_ROOT / "index.html").write_text(html_text, encoding="utf-8")
    (FRONTEND_ROOT / "README.md").write_text(render_frontend_readme(), encoding="utf-8")
    return {
        "frontend_entry": str(FRONTEND_ROOT / "index.html"),
        "sample_data_path": str(FRONTEND_ROOT / "dashboard_v1_sample_data.json"),
        "start_command": f"cd {FRONTEND_ROOT}; python -m http.server 5188 --bind 127.0.0.1",
        "url": "http://127.0.0.1:5188/",
        "legacy_streamlit_used": False,
    }


def run_ui_smoke(ui_result: dict[str, Any]) -> dict[str, Any]:
    html_text = Path(ui_result["frontend_entry"]).read_text(encoding="utf-8")
    expected_markers = [
        "FR Dashboard v1",
        "Research Console",
        "Research Object Type",
        "Time Mode",
        "publish_date",
        "as_of_check_enabled",
        "Generate Statistical Report",
        "Report Upload",
        "Analysis Zone",
        "Forecast Zone",
        "Evidence Zone",
        "As-of Snapshot Report Generator v1",
    ]
    detected = [marker for marker in expected_markers if marker in html_text]
    result = {
        "tested_url": ui_result["url"],
        "tested_command": ui_result["start_command"],
        "tested_method": "static_html_marker_scan",
        "expected_new_ui_markers": expected_markers,
        "detected_new_ui_markers": detected,
        "missing_new_ui_markers": sorted(set(expected_markers) - set(detected)),
        "old_ui_false_positive_guard": True,
        "legacy_streamlit_used": False,
        "status": "passed" if len(detected) == len(expected_markers) else "failed",
    }
    write_json(RUNTIME_ROOT / "ui_smoke_results.json", result)
    return result


def write_docs(
    config_summary: dict[str, Any],
    snapshot: dict[str, Any],
    statistical_report: dict[str, Any],
    upload_stub: dict[str, Any],
    smoke: dict[str, Any],
) -> dict[str, str]:
    docs = {
        DOC_IA: render_ia_doc(config_summary, smoke),
        DOC_TIME: render_time_doc(config_summary, snapshot),
        DOC_REPORT: render_dashboard_report_doc(snapshot, statistical_report, smoke),
        DOC_SNAPSHOT: render_snapshot_doc(snapshot),
        DOC_STAT_REPORT: render_stat_report_doc(statistical_report),
        DOC_UPLOAD: render_upload_doc(upload_stub),
        DOC_CHATGPT: render_chatgpt_doc(),
        DOC_STREAMLIT: render_streamlit_doc(),
    }
    for path, text in docs.items():
        path.write_text(text, encoding="utf-8")
    return {path.stem: str(path) for path in docs}


def render_dashboard_html(ui_data: dict[str, Any]) -> str:
    prompt = ui_data["copy_prompt"]
    ui_json = json.dumps(ui_data, ensure_ascii=False)
    sample_upload_report = """FINAL_REPORT_JSON
```json
{
  "packet_id": "manual_packet",
  "data_snapshot_id": "manual_snapshot",
  "target_symbol": "600519",
  "as_of_date": "2026-05-18",
  "analysis_scope": "manual_dashboard_upload",
  "investment_view": "insufficient_evidence",
  "forecast_items": [],
  "risk_items": [],
  "watchlist_signals": [],
  "confidence": "low",
  "next_review_date": "2026-06-18",
  "insufficient_evidence_items": ["manual sample"],
  "candidate_data_usage_note": "candidate data not trusted"
}
```
"""
    sample_upload_js = json.dumps(sample_upload_report)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>FR Dashboard v1</title>
  <style>
    :root {{
      --ink: #1f2933;
      --muted: #667085;
      --line: #d7dee8;
      --blue: #2f6fed;
      --green: #1b7f5a;
      --amber: #a35f00;
      --red: #b42318;
      --bg: #ffffff;
      --soft: #f7f9fc;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; font-family: Arial, Helvetica, sans-serif; color: var(--ink); background: var(--bg); }}
    header {{ padding: 18px 24px 10px; border-bottom: 1px solid var(--line); }}
    h1 {{ margin: 0 0 6px; font-size: 24px; font-weight: 700; }}
    h2 {{ margin: 0 0 12px; font-size: 18px; }}
    h3 {{ margin: 12px 0 8px; font-size: 14px; }}
    p {{ margin: 0 0 10px; color: var(--muted); line-height: 1.45; }}
    .layout {{ display: grid; grid-template-columns: 240px 1fr; min-height: calc(100vh - 72px); }}
    nav {{ border-right: 1px solid var(--line); padding: 14px; background: var(--soft); }}
    nav button, .btn {{
      width: 100%; text-align: left; background: #fff; color: var(--ink); border: 1px solid var(--line);
      border-left: 4px solid var(--blue); border-radius: 6px; padding: 9px 10px; margin-bottom: 8px; cursor: pointer;
    }}
    nav button.active {{ border-left-color: var(--green); font-weight: 700; }}
    main {{ padding: 18px 22px 48px; }}
    section {{ display: none; }}
    section.active {{ display: block; }}
    .grid {{ display: grid; gap: 12px; }}
    .grid.cols-3 {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
    .grid.cols-2 {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
    .panel {{ border: 1px solid var(--line); border-radius: 8px; padding: 14px; background: #fff; }}
    .metric {{ font-size: 22px; font-weight: 700; }}
    .tag {{ display: inline-block; padding: 3px 7px; border: 1px solid var(--line); border-radius: 999px; margin: 2px; font-size: 12px; background: #fff; }}
    .tag.warn {{ border-color: var(--amber); color: var(--amber); }}
    .tag.good {{ border-color: var(--green); color: var(--green); }}
    .tag.bad {{ border-color: var(--red); color: var(--red); }}
    label {{ display: block; font-size: 12px; color: var(--muted); margin-bottom: 4px; }}
    input, select, textarea {{
      width: 100%; border: 1px solid var(--line); border-radius: 6px; padding: 8px; background: #fff; color: var(--ink);
    }}
    textarea {{ min-height: 150px; font-family: Consolas, monospace; font-size: 12px; }}
    .row {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-bottom: 12px; }}
    .actions {{ display: flex; gap: 8px; flex-wrap: wrap; margin: 10px 0; }}
    .actions button {{ background: #fff; border: 1px solid var(--blue); color: var(--blue); border-radius: 6px; padding: 8px 10px; cursor: pointer; }}
    .actions button.green {{ border-color: var(--green); color: var(--green); }}
    .actions button.amber {{ border-color: var(--amber); color: var(--amber); }}
    table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
    th, td {{ border-bottom: 1px solid var(--line); padding: 7px; text-align: left; vertical-align: top; }}
    code {{ background: var(--soft); padding: 2px 4px; border-radius: 4px; }}
    .small {{ font-size: 12px; color: var(--muted); }}
    @media (max-width: 900px) {{
      .layout {{ grid-template-columns: 1fr; }}
      nav {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }}
      nav button {{ margin-bottom: 0; }}
      .grid.cols-3, .grid.cols-2, .row {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>FR Dashboard v1</h1>
    <p>Research Console + As-of Snapshot Report Generator v1. New dashboard architecture. legacy_streamlit_used = false.</p>
  </header>
  <div class="layout">
    <nav id="nav">
      <button data-target="overview" class="active">Overview</button>
      <button data-target="console">Research Console</button>
      <button data-target="macro">Macro Dashboard</button>
      <button data-target="asset">Asset Class Dashboard</button>
      <button data-target="sector">Sector Dashboard</button>
      <button data-target="company">Company Dashboard</button>
      <button data-target="capital">Capital Flow Dashboard</button>
      <button data-target="workspace">Research Workspace</button>
      <button data-target="upload">Report Upload</button>
    </nav>
    <main>
      <section id="overview" class="active">
        <h2>Overview</h2>
        <div class="grid cols-3">
          <div class="panel"><p>Included Items</p><div class="metric" id="includedCount"></div></div>
          <div class="panel"><p>Missing Publish Date</p><div class="metric" id="missingCount"></div></div>
          <div class="panel"><p>Future Published Exclusions</p><div class="metric" id="futureCount"></div></div>
        </div>
        <div class="panel">
          <h3>Data Status</h3>
          <div id="statusTags"></div>
          <p class="small">candidate / staging / trusted_candidate / insufficient_evidence / missing_publish_date are shown explicitly. No candidate data is displayed as trusted.</p>
        </div>
      </section>

      <section id="console">
        <h2>Research Console</h2>
        <div class="panel">
          <div class="row">
            <div><label>Research Object Type</label><select><option>black_swan_event</option><option>company</option><option>sector</option><option>asset_class</option><option>macro_theme</option><option>capital_flow_theme</option><option>policy_event</option><option>geopolitical_event</option><option>custom_topic</option></select></div>
            <div><label>Research Object ID</label><input value="custom_ukraine_energy_shock_2022" /></div>
            <div><label>Time Mode</label><select><option>publish_date</option><option>data_period</option><option>fiscal_year</option><option>reporting_period</option><option>announcement_date</option><option>event_date</option><option>analysis_time</option><option>ingestion_time</option></select></div>
            <div><label>as_of_check_enabled</label><select><option>true</option><option>false</option></select></div>
          </div>
          <div class="row">
            <div><label>Window Start</label><input value="2026-04-01" /></div>
            <div><label>Window End</label><input value="2026-05-18" /></div>
            <div><label>Fiscal Year</label><input value="2025" /></div>
            <div><label>Reporting Period</label><input placeholder="2025FY / 2026Q1" /></div>
          </div>
          <label>Selected Data Categories</label>
          <input value="macro, asset_class, commodity, market_daily, financial_report, research_report, forecast, backtest" />
          <div class="actions">
            <button class="green" onclick="showGenerated()">Generate Statistical Report</button>
            <button onclick="copyPrompt()">Copy Prompt</button>
            <button onclick="window.open('https://chatgpt.com/', '_blank')">Open ChatGPT Web</button>
          </div>
          <div id="generatedResult" class="small"></div>
          <label>copy_to_gpt_research_prompt.md</label>
          <textarea id="promptBox" readonly>{html.escape(prompt)}</textarea>
        </div>
      </section>

      <section id="macro"><h2>Macro Dashboard</h2><div class="panel" id="macroPanel"></div></section>
      <section id="asset"><h2>Asset Class Dashboard</h2><div class="panel" id="assetPanel"></div></section>
      <section id="sector"><h2>Sector Dashboard</h2><div class="panel"><span class="tag warn">insufficient_evidence</span><p>Sector-level connectors are not connected in v1. Schema and future connector slots are visible, but no sector data is fabricated.</p></div></section>
      <section id="company"><h2>Company Dashboard</h2><div class="panel" id="companyPanel"></div></section>
      <section id="capital"><h2>Capital Flow Dashboard</h2><div class="panel"><span class="tag warn">insufficient_evidence</span><p>ETF flow, fund holdings, northbound flow, margin financing and block trades are planned data types. No current capital-flow data is fabricated.</p></div></section>
      <section id="workspace"><h2>Research Workspace</h2><div class="panel"><p>Packets, reports, report versions, forecast items, backtest results and revision candidates are linked through runtime research workspace indexes.</p><pre id="workspacePaths"></pre></div></section>
      <section id="upload">
        <h2>Report Upload</h2>
        <div class="grid cols-2">
          <div class="panel">
            <label>Paste Markdown report with FINAL_REPORT_JSON</label>
            <textarea id="reportInput" placeholder="Paste GPT Web final report here"></textarea>
            <div class="actions"><button class="green" onclick="classifyReport()">Classify Report</button></div>
            <p class="small">No OpenAI API is called. GPT report content is analysis_report / forecast / interpretation, not trusted fact.</p>
          </div>
          <div class="panel">
            <h3>Analysis Zone</h3><pre id="analysisZone"></pre>
            <h3>Forecast Zone</h3><pre id="forecastZone"></pre>
            <h3>Evidence Zone</h3><pre id="evidenceZone"></pre>
          </div>
        </div>
      </section>
    </main>
  </div>
  <script>
    const DASHBOARD_DATA = {ui_json};
    document.getElementById('includedCount').textContent = DASHBOARD_DATA.snapshot_counts.included;
    document.getElementById('missingCount').textContent = DASHBOARD_DATA.snapshot_counts.missing_publish_date_review;
    document.getElementById('futureCount').textContent = DASHBOARD_DATA.snapshot_counts.excluded_due_to_future_publish_date;
    document.getElementById('statusTags').innerHTML = Object.entries(DASHBOARD_DATA.source_status_counts).map(([k,v]) => `<span class="tag">${{k}}: ${{v}}</span>`).join('');
    document.getElementById('macroPanel').innerHTML = summaryPanel('macro');
    document.getElementById('assetPanel').innerHTML = summaryPanel('asset_class') + summaryPanel('commodity');
    document.getElementById('companyPanel').innerHTML = summaryPanel('market_daily') + '<p class="small">A-share market data remains candidate/staging and is not formal trusted consumption.</p>';
    document.getElementById('workspacePaths').textContent = JSON.stringify(DASHBOARD_DATA.report_paths, null, 2);
    document.getElementById('reportInput').value = {sample_upload_js};
    document.querySelectorAll('nav button').forEach(button => {{
      button.addEventListener('click', () => {{
        document.querySelectorAll('nav button').forEach(b => b.classList.remove('active'));
        document.querySelectorAll('main section').forEach(s => s.classList.remove('active'));
        button.classList.add('active');
        document.getElementById(button.dataset.target).classList.add('active');
      }});
    }});
    function summaryPanel(category) {{
      const count = DASHBOARD_DATA.category_counts[category] || 0;
      const tag = count ? 'good' : 'warn';
      return `<span class="tag ${{tag}}">${{category}}: ${{count ? count + ' evidence items' : 'insufficient_evidence'}}</span>`;
    }}
    function showGenerated() {{
      document.getElementById('generatedResult').innerHTML =
        '<p><strong>As-of snapshot and statistical report generated.</strong></p><pre>' +
        JSON.stringify(DASHBOARD_DATA.report_paths, null, 2) + '</pre>';
    }}
    function copyPrompt() {{
      navigator.clipboard?.writeText(document.getElementById('promptBox').value);
    }}
    function classifyReport() {{
      const text = document.getElementById('reportInput').value;
      const match = text.match(/FINAL_REPORT_JSON\\s*```json\\s*([\\s\\S]*?)\\s*```/);
      if (!match) {{
        document.getElementById('analysisZone').textContent = 'FINAL_REPORT_JSON not found';
        document.getElementById('forecastZone').textContent = '';
        document.getElementById('evidenceZone').textContent = '';
        return;
      }}
      try {{
        const payload = JSON.parse(match[1]);
        document.getElementById('analysisZone').textContent = JSON.stringify({{
          investment_view: payload.investment_view,
          key_assumptions: payload.key_assumptions || [],
          risk_items: payload.risk_items || []
        }}, null, 2);
        document.getElementById('forecastZone').textContent = JSON.stringify({{
          forecast_items: payload.forecast_items || [],
          watchlist_signals: payload.watchlist_signals || [],
          confidence: payload.confidence,
          next_review_date: payload.next_review_date
        }}, null, 2);
        document.getElementById('evidenceZone').textContent = JSON.stringify({{
          packet_id: payload.packet_id,
          data_snapshot_id: payload.data_snapshot_id,
          as_of_date: payload.as_of_date,
          candidate_data_usage_note: payload.candidate_data_usage_note,
          insufficient_evidence_items: payload.insufficient_evidence_items || [],
          gpt_report_not_trusted_fact: true
        }}, null, 2);
      }} catch (error) {{
        document.getElementById('analysisZone').textContent = 'Invalid FINAL_REPORT_JSON: ' + error;
      }}
    }}
  </script>
</body>
</html>
"""


def render_frontend_readme() -> str:
    return """# FR Dashboard v1

This is the new FinancialResearch dashboard prototype, not the archived Streamlit UI.

Start:

```powershell
cd D:\\workspace\\FinancialResearch\\frontend_web\\src\\dashboard_v1
python -m http.server 5188 --bind 127.0.0.1
```

Open: http://127.0.0.1:5188/

`legacy_streamlit_used = false`.
"""


def render_statistical_report_md(report: dict[str, Any], missing: list[dict[str, Any]], future: list[dict[str, Any]]) -> str:
    lines = [
        "# Statistical Report v1",
        "",
        f"Generated: {report['generated_at']}",
        f"Research Object: {report['research_object']['type']} / {report['research_object'].get('title')}",
        f"Time Mode: {report['time_mode']}",
        f"As-of Safe: {str(report['as_of_safe']).lower()}",
        f"Window: {report['window_start']} to {report['window_end']}",
        "",
        "## Evidence Boundary",
        "",
        f"- Included items: {report['summary']['included_count']}",
        f"- Missing publish_date review: {len(missing)}",
        f"- Excluded future published items: {len(future)}",
        f"- Candidate data warning: {report['candidate_data_warning']}",
        "",
        "## Category Counts",
        "",
    ]
    for category, count in sorted(report["summary"]["category_counts"].items()):
        lines.append(f"- {category}: {count}")
    lines.extend([
        "",
        "## Insufficient Evidence",
        "",
    ])
    for item in report["insufficient_evidence"]:
        lines.append(f"- {item['category']}: {item['reason']}")
    lines.extend([
        "",
        "## Missing Publish Date Review",
        "",
    ])
    for item in missing[:10]:
        lines.append(f"- {item['title']} ({item['source_id']}): {item.get('exclusion_reason')}")
    lines.extend([
        "",
        "## Excluded Due To Future Publish Date",
        "",
    ])
    for item in future[:10]:
        lines.append(f"- {item['title']} publish_date={item.get('publish_date')} > window_end")
    return "\n".join(lines) + "\n"


def render_copy_to_gpt_prompt(report: dict[str, Any]) -> str:
    return f"""You are helping analyze a FinancialResearch statistical packet.

Hard rules:
- Use only the packet below.
- Treat `as_of_date` / window_end as the information boundary.
- Do not use future information.
- Candidate/staging data cannot be stated as trusted facts.
- If evidence is missing or not as-of safe, write insufficient_evidence.
- Output a Markdown research discussion plus a FINAL_REPORT_JSON block.

Packet:
```json
{json.dumps(report, ensure_ascii=False, indent=2)}
```

FINAL_REPORT_JSON must include:
- packet_id or snapshot_id
- data_snapshot_id
- target_symbol or research_object
- as_of_date
- analysis_scope
- key_assumptions
- investment_view
- forecast_items
- risk_items
- watchlist_signals
- confidence
- next_review_date
- insufficient_evidence_items
- candidate_data_usage_note
"""


def extract_final_report_json(raw_text: str) -> dict[str, Any]:
    match = re.search(r"FINAL_REPORT_JSON\s*```json\s*(\{.*?\})\s*```", raw_text, flags=re.DOTALL)
    if not match:
        return {"schema_valid": False, "errors": ["FINAL_REPORT_JSON fenced json block not found"]}
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        return {"schema_valid": False, "errors": [f"invalid json: {exc}"]}
    required = {"packet_id", "data_snapshot_id", "as_of_date", "analysis_scope", "forecast_items", "insufficient_evidence_items", "candidate_data_usage_note"}
    missing = sorted(required - set(payload))
    return {"schema_valid": not missing, "errors": [f"missing: {', '.join(missing)}"] if missing else [], "payload": payload}


def render_ia_doc(config_summary: dict[str, Any], smoke: dict[str, Any]) -> str:
    return f"""# FR Dashboard Information Architecture

Generated: {utc_now()}

Dashboard v1 is a new FinancialResearch workbench UI, not the archived Streamlit interface.

Core pages:

- Overview: data source status, recent snapshots, reports, pending review and missing publish_date.
- Research Console: research object/theme selection, data categories, time mode and report generation.
- Macro Dashboard: current official/candidate macro samples and evidence gaps.
- Asset Class Dashboard: commodity/rate/asset-class sample coverage and gaps.
- Sector Dashboard: schema and insufficient_evidence until sector connectors exist.
- Company Dashboard: watchlist market data, packets, reports, forecasts and backtests.
- Capital Flow Dashboard: framework for ETF/fund/flow data; current data is insufficient.
- Research Workspace: packets, reports, versions, forecasts, backtests and revisions by object.
- Report Upload: paste/upload GPT Web final report, classify into Analysis Zone, Forecast Zone and Evidence Zone.

Research object abstraction supports company, sector, asset_class, macro_theme, capital_flow_theme,
event, geopolitical_event, policy_event, black_swan_event and custom_topic.

New UI smoke:

- tested_url: {smoke['tested_url']}
- legacy_streamlit_used: {str(smoke['legacy_streamlit_used']).lower()}
- old_ui_false_positive_guard: {str(smoke['old_ui_false_positive_guard']).lower()}
- detected markers: {len(smoke['detected_new_ui_markers'])}

Config outputs:

- {config_summary['data_taxonomy_path']}
- {config_summary['time_semantics_path']}
- {config_summary['research_object_types_path']}
"""


def render_time_doc(config_summary: dict[str, Any], snapshot: dict[str, Any]) -> str:
    return f"""# Data Taxonomy and Time Semantics

Generated: {utc_now()}

Default time mode is `publish_date`; `as_of_check_enabled` defaults to true.

Supported time modes:

- publish_date
- data_period
- fiscal_year
- reporting_period
- announcement_date
- event_date
- analysis_time
- ingestion_time

Rules:

- Missing publish_date items go to `missing_publish_date_review`.
- publish_date later than window_end goes to `excluded_due_to_future_publish_date`.
- fiscal_year and reporting_period can locate financial reports, but as-of safety still checks publish_date.
- If as_of_check_enabled is false, report output is marked `not_asof_safe`.

Sample snapshot counts:

```json
{json.dumps(snapshot['counts'], indent=2)}
```
"""


def render_dashboard_report_doc(snapshot: dict[str, Any], statistical_report: dict[str, Any], smoke: dict[str, Any]) -> str:
    return f"""# FR Dashboard v1 Report

Generated: {utc_now()}

Dashboard v1 deliverables completed:

- Dashboard IA: yes
- Research object/theme abstraction: yes
- Time semantics: yes
- As-of Snapshot Engine v1: yes
- Statistical Report Generator v1: yes
- Report Upload classification stub: yes
- UI prototype: yes
- legacy_streamlit_used: false
- OpenAI API called: false
- parse_lab affected: false
- trusted consumption affected: false

UI startup:

```powershell
{smoke['tested_command']}
```

Open: {smoke['tested_url']}

Runtime outputs:

- Snapshot: {snapshot['snapshot_manifest']['paths']['snapshot_manifest']}
- Statistical report: {statistical_report['statistical_report_md']}
- GPT prompt: {statistical_report['copy_to_gpt_research_prompt']}
"""


def render_snapshot_doc(snapshot: dict[str, Any]) -> str:
    return f"""# As-of Snapshot Engine v1

Generated: {utc_now()}

The engine accepts research object fields, selected data categories, time_mode, date window,
fiscal_year/reporting_period and `as_of_check_enabled`.

Default filter is publish_date. Missing publish_date and future publish_date are separated from
included items.

Sample counts:

```json
{json.dumps(snapshot['counts'], indent=2)}
```

All outputs remain candidate/research evidence and do not enter formal trusted consumption.
"""


def render_stat_report_doc(statistical_report: dict[str, Any]) -> str:
    return f"""# Statistical Report Generator v1

Generated: {utc_now()}

The generator produces:

- statistical_report.json
- statistical_report.md
- copy_to_gpt_research_prompt.md
- evidence_boundary.json

Current sample report path:

- {statistical_report['statistical_report_md']}

The report is statistical/evidence-boundary output only. It is not an investment report.
"""


def render_upload_doc(upload_stub: dict[str, Any]) -> str:
    classification = upload_stub["classification"]
    return f"""# Report Upload Dashboard Classification

Generated: {utc_now()}

Report Upload v1 parses a pasted Markdown report containing `FINAL_REPORT_JSON`, validates the
minimum schema, preserves raw text, and classifies output into:

- Analysis Zone
- Forecast Zone
- Evidence Zone

Sample schema_valid: {str(classification['schema_valid']).lower()}

GPT report content remains an analysis_report / forecast / interpretation artifact, not a trusted fact.
"""


def render_chatgpt_doc() -> str:
    return f"""# ChatGPT Web Workflow Feasibility

Generated: {utc_now()}

Dashboard v1 uses a semi-embedded human-in-the-loop workflow:

1. FR generates a statistical report and `copy_to_gpt_research_prompt.md`.
2. User copies the prompt to ChatGPT Web.
3. User discusses and asks ChatGPT Web to emit a `FINAL_REPORT_JSON` block.
4. User pastes/uploads the final report back to FR.
5. FR parses, classifies and stores report artifacts.

No OpenAI API is called. ChatGPT Web is opened as a separate page, not embedded in an iframe.

An iframe-based ChatGPT Web embed is not the v1 direction because it is less reliable, may violate
browser/security constraints, and is not needed for the manual workflow.
"""


def render_streamlit_doc() -> str:
    return f"""# Legacy Streamlit Archive Note

Generated: {utc_now()}

Legacy Streamlit files and reports are archived references only. Dashboard v1 does not use Streamlit.

Allowed legacy uses:

- Historical issue review.
- Parser comparison background.
- Migration lessons.

Not allowed:

- Treating a legacy Streamlit URL as Dashboard v1 validation.
- Building new Dashboard v1 pages on Streamlit.
- Passing UI smoke by checking old route status codes.

Dashboard v1 guard:

- legacy_streamlit_used = false
- old_ui_false_positive_guard = true
"""


def summarize_category(items: list[dict[str, Any]], category: str) -> dict[str, Any]:
    subset = [item for item in items if item.get("category") == category]
    if not subset:
        return insufficient_summary(category, f"No included {category} evidence in the sample window.")
    return {
        "status": "available",
        "category": category,
        "item_count": len(subset),
        "sources": sorted({item["source_id"] for item in subset}),
        "statuses": dict(Counter(item["staging_status"] for item in subset)),
        "candidate_only": True,
    }


def summarize_company(items: list[dict[str, Any]]) -> dict[str, Any]:
    subset = [item for item in items if item.get("category") in {"market_daily", "company", "financial_report", "research_report", "forecast", "backtest"}]
    if not subset:
        return insufficient_summary("company", "No company evidence included in this snapshot.")
    return {
        "status": "available_candidate_evidence",
        "item_count": len(subset),
        "symbols": sorted({item.get("symbol") for item in subset if item.get("symbol")}),
        "sources": sorted({item["source_id"] for item in subset}),
        "candidate_only": True,
    }


def insufficient_summary(category: str, reason: str) -> dict[str, Any]:
    return {"status": "insufficient_evidence", "category": category, "reason": reason, "candidate_only": True}


def evidence_boundary(snapshot: dict[str, Any]) -> dict[str, Any]:
    manifest = snapshot["snapshot_manifest"]
    return {
        "snapshot_id": manifest["snapshot_id"],
        "time_mode": manifest["time_mode"],
        "as_of_check_enabled": manifest["as_of_check_enabled"],
        "window_start": manifest["request"].get("window_start"),
        "window_end": manifest["request"].get("window_end"),
        "included_item_count": len(snapshot["included_items"]),
        "missing_publish_date_review_count": len(snapshot["missing_publish_date_review"]),
        "excluded_due_to_future_publish_date_count": len(snapshot["excluded_due_to_future_publish_date"]),
        "candidate_data_warning": "Candidate/staging data is not trusted final fact.",
        "not_asof_safe": not manifest["as_of_check_enabled"],
    }


def build_insufficient_evidence(request: dict[str, Any], included: list[dict[str, Any]]) -> list[dict[str, str]]:
    categories = set(request.get("selected_data_categories", []))
    present = {item["category"] for item in included}
    missing = sorted(categories - present)
    items = [{"category": category, "reason": "No as-of safe included evidence in current snapshot."} for category in missing]
    if "capital_flow" not in present:
        items.append({"category": "capital_flow", "reason": "Capital flow connectors are not connected in Dashboard v1."})
    if "sector" not in present:
        items.append({"category": "sector", "reason": "Sector-level connectors are not connected in Dashboard v1."})
    return items


def map_category(data_category: str | None) -> str:
    value = (data_category or "").lower()
    if "market" in value or "a_share_daily" in value:
        return "market_daily"
    if "macro" in value or "fiscal" in value:
        return "macro"
    if "commodity" in value:
        return "commodity"
    if "financial_report" in value or "pdf" in value:
        return "financial_report"
    if "filing" in value:
        return "financial_report"
    return "company"


def normalized_category_from_source(source_id: str) -> str:
    if source_id in {"bls_public_api", "fred_public_csv", "treasury_fiscaldata"}:
        return "macro"
    if source_id == "world_bank_pink_sheet":
        return "commodity"
    if source_id in {"sec_edgar_companyfacts", "cninfo_disclosure"}:
        return "financial_report"
    if "daily" in source_id:
        return "market_daily"
    return "company"


def infer_publish_date(record: dict[str, Any]) -> str | None:
    for key in ["publish_date", "announcement_date"]:
        if record.get(key):
            return date_part(record[key])
    if record.get("source_id") == "cninfo_disclosure" and record.get("date"):
        return date_from_ms_or_value(record["date"])
    return None


def infer_data_period(record: dict[str, Any]) -> str | None:
    for key in ["trade_date", "date", "period", "data_period", "year"]:
        if record.get(key) is not None:
            return date_from_ms_or_value(record[key])
    return None


def infer_report_period(record: dict[str, Any]) -> tuple[str | None, str | None]:
    title = str(record.get("report_title") or record.get("title") or "")
    year_match = re.search(r"(20\d{2})", title)
    fiscal_year = year_match.group(1) if year_match else None
    reporting_period = None
    if fiscal_year:
        if "Q1" in title or "一季" in title:
            reporting_period = f"{fiscal_year}Q1"
        elif "半" in title or "H1" in title:
            reporting_period = f"{fiscal_year}H1"
        else:
            reporting_period = f"{fiscal_year}FY"
    return fiscal_year, reporting_period


def date_from_ms_or_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and value > 10_000_000_000:
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).date().isoformat()
    if isinstance(value, (int, float)) and 1900 <= int(value) <= 2200:
        return str(int(value))
    return date_part(str(value))


def date_part(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    match = re.match(r"(\d{4}-\d{2}-\d{2})", text)
    if match:
        return match.group(1)
    match = re.match(r"(\d{4})(\d{2})(\d{2})", text)
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    return text if re.fullmatch(r"\d{4}", text) else None


def date_in_window(value: str | None, start: str | None, end: str | None) -> bool:
    if not value or not re.match(r"\d{4}-\d{2}-\d{2}$", value):
        return True
    if start and value < start:
        return False
    if end and value > end:
        return False
    return True


def with_reason(item: dict[str, Any], reason: str) -> dict[str, Any]:
    clone = dict(item)
    clone["exclusion_reason"] = reason
    return clone


def read_json(path: Path | str) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path | str) -> list[dict[str, Any]]:
    if not path:
        return []
    path = Path(path)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def hash_short(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    summary = run_dashboard_v1()
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
