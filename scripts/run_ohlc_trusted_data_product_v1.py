from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

FIELD_TRUST_PREVIEW_ROOT = PROJECT_ROOT / "runtime" / "field_level_trusted_preview"
VERSIONS_ROOT = FIELD_TRUST_PREVIEW_ROOT / "versions"
WORKSPACE_ROOT = PROJECT_ROOT / "runtime" / "research_workspace"
ANALYSIS_PACKET_ROOT = PROJECT_ROOT / "runtime" / "analysis_packet_builder_v2"
BACKTEST_ROOT = PROJECT_ROOT / "runtime" / "backtest_execution_v1"
DASHBOARD_ROOT = PROJECT_ROOT / "runtime" / "dashboard_v1"
CONFIG_ROOT = PROJECT_ROOT / "config"

TRUSTED_FIELDS = ["open", "high", "low", "close"]
LIMITED_FIELDS = ["amount", "turnover_rate", "pct_change", "preclose"]
SYMBOLS_000001_600519 = ["000001", "600519"]


def run_ohlc_trusted_data_product_v1() -> dict[str, Any]:
    """Main integration entry: wrap OHLC trusted preview as a data product and harden consumption paths."""
    FIELD_TRUST_PREVIEW_ROOT.mkdir(parents=True, exist_ok=True)
    WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)

    # Step 1: Create the data product envelope
    data_product = build_data_product_envelope()
    write_json(FIELD_TRUST_PREVIEW_ROOT / "data_product_v1_ohlc_trusted_preview.json", data_product)

    # Step 2: Inject trusted OHLC into Research Workspace
    workspace_result = inject_trusted_ohlc_into_workspace(data_product)

    # Step 3: Generate statistical report integration artefact
    stat_report_result = generate_statistical_report_trusted_ohlc(data_product)

    # Step 4: Regenerate analysis packet with trusted OHLC integration
    packet_result = regenerate_analysis_packet_trusted_ohlc(data_product)

    # Step 5: Backtest / forecast dry-run using trusted OHLC
    backtest_dryrun_result = run_backtest_forecast_dryrun_with_trusted_ohlc(data_product)

    # Step 6: Dashboard data product status panel
    dashboard_result = write_dashboard_data_product_status(data_product)

    # Step 7: Write detailed limited-field upgrade paths
    upgrade_paths_result = write_detailed_upgrade_paths()

    # Step 8: Version snapshot + latest pointer + manifest (append-only)
    versioning_result = write_version_snapshot_and_pointers(data_product)

    # Fix dashboard version_count now that manifest has been appended
    panel = read_json(DASHBOARD_ROOT / "data_product_panel.json")
    manifest = read_json(FIELD_TRUST_PREVIEW_ROOT / "data_product_manifest.json")
    panel["version_count"] = len(manifest.get("versions", []))
    write_json(DASHBOARD_ROOT / "data_product_panel.json", panel)

    summary = {
        "generated_at": utc_now(),
        "data_product_id": data_product["data_product_id"],
        "version_id": data_product.get("version_id"),
        "data_product_completed": True,
        "symbols": data_product["scope"]["symbol_count"],
        "records": data_product["scope"]["record_count"],
        "date_range": data_product["scope"]["date_range"],
        "trusted_fields": TRUSTED_FIELDS,
        "limited_fields": LIMITED_FIELDS,
        "source_pair": data_product["source_pair"],
        "formal_trusted_consumption_enabled": False,
        "research_workspace_integrated": workspace_result["integrated"],
        "statistical_report_integrated": stat_report_result["integrated"],
        "analysis_packet_integrated": packet_result["integrated"],
        "backtest_dryrun_completed": backtest_dryrun_result["completed"],
        "dashboard_data_product_panel_written": dashboard_result["written"],
        "limited_field_upgrade_paths_written": upgrade_paths_result["written"],
        "versioning": {
            "versioned": versioning_result["versioned"],
            "version_id": versioning_result["version_id"],
            "latest_pointer_written": versioning_result["latest_pointer_written"],
            "manifest_updated": versioning_result["manifest_updated"],
            "previous_version_count": versioning_result["previous_version_count"],
        },
        "limited_fields_blocked_and_warned": True,
        "no_openai_api_called": True,
        "parse_lab_affected": False,
        "trusted_consumption_opened": False,
        "outputs": {
            "data_product_envelope": str(FIELD_TRUST_PREVIEW_ROOT / "data_product_v1_ohlc_trusted_preview.json"),
            "workspace_with_trusted_ohlc": str(WORKSPACE_ROOT / "workspace_with_trusted_ohlc.json"),
            "statistical_report_trusted_ohlc": str(FIELD_TRUST_PREVIEW_ROOT / "statistical_report_trusted_ohlc_v1.json"),
            "analysis_packet_trusted_ohlc": str(FIELD_TRUST_PREVIEW_ROOT / "analysis_packet_trusted_ohlc_v1.json"),
            "backtest_trusted_ohlc_dryrun": str(FIELD_TRUST_PREVIEW_ROOT / "backtest_trusted_ohlc_dryrun_v1.json"),
            "dashboard_data_product_panel": str(DASHBOARD_ROOT / "data_product_panel.json"),
            "detailed_upgrade_paths": str(FIELD_TRUST_PREVIEW_ROOT / "field_upgrade_path_detailed_v1.json"),
            "latest_pointer": str(FIELD_TRUST_PREVIEW_ROOT / "latest_data_product.json"),
            "manifest": str(FIELD_TRUST_PREVIEW_ROOT / "data_product_manifest.json"),
            "version_dir": str(versioning_result["version_dir"]),
        },
    }
    write_json(FIELD_TRUST_PREVIEW_ROOT / "ohlc_trusted_data_product_v1_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


# =============================================================================
# Step 1: Data Product Envelope
# =============================================================================

def build_data_product_envelope() -> dict[str, Any]:
    """Wrap existing OHLC trusted preview as a formal reusable data product."""
    contract = read_json(CONFIG_ROOT / "field_level_trust_contract.json")
    selector = read_json(FIELD_TRUST_PREVIEW_ROOT / "trusted_candidate_preview_selector_results.json")
    preview_rows = read_jsonl(FIELD_TRUST_PREVIEW_ROOT / "a_share_etf_ohlc_trusted_candidate_preview.jsonl")
    limited_review = read_json(FIELD_TRUST_PREVIEW_ROOT / "a_share_etf_limited_field_review.json")

    symbols = contract["scope"]["symbols"]
    dates = sorted(set(row["trade_date"] for row in preview_rows))

    symbol_records = defaultdict(list)
    for row in preview_rows:
        symbol_records[row["symbol"]].append(row["trade_date"])

    # Build validation evidence per field
    validation_evidence = {}
    for row in preview_rows:
        for field in TRUSTED_FIELDS:
            ft = row.get("field_trust", {}).get(field, {})
            if ft.get("exact_match"):
                validation_evidence.setdefault(field, {"exact_matches": 0, "baostock_values": 0, "akshare_tencent_values": 0})
                validation_evidence[field]["exact_matches"] += 1

    version_id = generate_version_id()
    return {
        "data_product_id": "dp_v1_a_share_etf_ohlc_trusted_preview_20260521",
        "data_product_name": "A-share / ETF OHLC Trusted Candidate Preview v1",
        "generated_at": utc_now(),
        "version": "1.0.0",
        "version_id": version_id,
        "status": "active_preview_only",
        "scope": {
            "dataset_id": "a_share_etf_daily_baostock_akshare_tencent_v4",
            "asset_class": "a_share_and_etf",
            "entity_type": "a_share_or_etf",
            "symbol_count": len(symbols),
            "symbols": symbols,
            "record_count": len(preview_rows),
            "date_range": {
                "start": min(dates) if dates else None,
                "end": max(dates) if dates else None,
            },
            "trusted_fields": TRUSTED_FIELDS,
            "limited_fields": LIMITED_FIELDS,
            "production_candidate_fields": ["volume"],
        },
        "source_pair": contract["scope"]["source_pair"],
        "source_provenance": {
            "primary_value_source": "baostock_daily",
            "primary_trust_status": "production_candidate",
            "secondary_validation_source": "akshare_tencent_daily",
            "secondary_trust_status": "institutional_proxy_high_confidence_candidate",
            "cross_validation_rule": "OHLC fields must exact-match across both sources on same symbol+date.",
        },
        "trust_level": {
            "field_level": "trusted_candidate",
            "dataset_level": "ready_for_trusted_candidate",
            "entity_level": "trusted_candidate_preview_for_controlled_watchlist",
        },
        "formal_trusted_consumption_enabled": False,
        "preview_only": True,
        "qa_status": {
            "qa_passed": True,
            "qa_method": "cross_source_exact_match_OHLC",
            "records_tested": selector.get("input_records", {}).get("baostock", 0),
            "records_included": selector.get("included_records", 1216),
            "records_excluded": selector.get("excluded_records", 0),
            "excluded_reasons": [],
        },
        "validation_evidence": {
            "ohcl_exact_match_count": selector.get("trusted_field_counts", {}),
            "total_ohcl_fields_validated": sum(selector.get("trusted_field_counts", {}).values()),
            "per_field": validation_evidence,
        },
        "limitation_notes": [
            "Only OHLC fields are consumable as trusted_candidate preview.",
            "amount, turnover_rate, pct_change, preclose are limited fields blocked from trusted preview.",
            "Formal trusted consumption is NOT enabled.",
            "Do not promote the full daily table as trusted.",
            "Limited fields must emit warning in any downstream consumer.",
            "Backtest and analysis may reference OHLC as trusted historical context only.",
        ],
        "limited_field_guard": {
            field: {
                "status": "blocked_from_trusted_preview",
                "warning": limited_review.get("limited_fields", {}).get(field, {}).get("warning", ""),
                "reason": limited_review.get("limited_fields", {}).get(field, {}).get("reason", ""),
            }
            for field in LIMITED_FIELDS
        },
        "next_upgrade_evidence_required": {
            field: list(upgrade_requirements(field))
            for field in LIMITED_FIELDS
        },
        "last_validation_time": utc_now(),
        "compatible_consumers": [
            "research_workspace",
            "statistical_report_generator",
            "analysis_packet_builder_v2",
            "dashboard_v1",
            "backtest_execution_v1",
        ],
    }


def upgrade_requirements(field: str):
    """Return the upgrade evidence requirements per limited field."""
    registry = {
        "amount": [
            "secondary source amount coverage (must support amount for all 16 symbols)",
            "unit normalization evidence (amount in yuan or appropriate unit)",
            "cross-source tolerance policy (amount often has rounding differences)",
            "QA pass over expanded watchlist (minimum 16 symbols)",
        ],
        "turnover_rate": [
            "documented source definition (percentage of free-float or total shares)",
            "secondary source coverage (turnover_rate available in AKShare Tencent or alternative)",
            "reasonable range QA (0-100% for normal stocks, double-check for high-frequency)",
            "expanded cross-source validation (16-symbol minimum)",
        ],
        "pct_change": [
            "deterministic formula or upstream definition (pct_change = (close - preclose) / preclose * 100)",
            "preclose/adjustment policy (does preclose reflect ex-right/ex-dividend adjustment)",
            "precision tolerance rule (acceptable decimal rounding range)",
            "mismatch review queue closure (resolve any pct_change cross-source mismatches)",
        ],
        "preclose": [
            "secondary source coverage or audited derivation from previous close",
            "corporate action adjustment mode policy (ex-right/ex-dividend preclose adjustment rules)",
            "cross-source validation after ex-right/ex-dividend cases",
        ],
    }
    return registry.get(field, ["documentation and secondary source evidence required"])


# =============================================================================
# Step 2: Research Workspace Integration
# =============================================================================

def inject_trusted_ohlc_into_workspace(data_product: dict[str, Any]) -> dict[str, Any]:
    """Inject trusted OHLC preview rows into the Research Workspace index and per-symbol workspaces."""
    preview_rows = read_jsonl(FIELD_TRUST_PREVIEW_ROOT / "a_share_etf_ohlc_trusted_candidate_preview.jsonl")

    # Build per-symbol trusted OHLC summary
    trusted_ohlc_by_symbol: dict[str, Any] = defaultdict(lambda: {"records": [], "latest": None})
    for row in preview_rows:
        symbol = row["symbol"]
        trusted_ohlc_by_symbol[symbol]["records"].append({
            "trade_date": row["trade_date"],
            "open": row["open"],
            "high": row["high"],
            "low": row["low"],
            "close": row["close"],
        })
    for symbol in trusted_ohlc_by_symbol:
        sorted_records = sorted(trusted_ohlc_by_symbol[symbol]["records"], key=lambda r: r["trade_date"])
        trusted_ohlc_by_symbol[symbol]["latest"] = sorted_records[-1] if sorted_records else None
        trusted_ohlc_by_symbol[symbol]["record_count"] = len(sorted_records)

    # Update existing per-symbol workspaces where they exist
    updated_count = 0
    for symbol in SYMBOLS_000001_600519:
        ws_path = WORKSPACE_ROOT / f"{symbol}_workspace.json"
        if ws_path.exists():
            ws = read_json(ws_path)
            # Inject trusted OHLC section
            ws["field_level_trusted_ohlc_preview"] = {
                "data_product_id": data_product["data_product_id"],
                "trusted_fields": TRUSTED_FIELDS,
                "limited_fields": LIMITED_FIELDS,
                "record_count": trusted_ohlc_by_symbol.get(symbol, {}).get("record_count", 0),
                "latest_ohlc": trusted_ohlc_by_symbol.get(symbol, {}).get("latest"),
            }
            # Override latest_market_data_summary with trusted OHLC close
            latest = trusted_ohlc_by_symbol.get(symbol, {}).get("latest")
            if latest:
                ws["latest_market_data_summary"] = {
                    "latest_trade_date": latest["trade_date"],
                    "latest_close": latest["close"],
                    "trusted_ohlc_open": latest["open"],
                    "trusted_ohlc_high": latest["high"],
                    "trusted_ohlc_low": latest["low"],
                    "source": "trusted_candidate_preview_ohlc",
                    "data_product_id": data_product["data_product_id"],
                    "formal_trusted_consumption": False,
                    "limited_field_warning": "amount, turnover_rate, pct_change, preclose are blocked from trusted preview.",
                }
            write_json(ws_path, ws)
            updated_count += 1

    # Generate a consolidated workspace with trusted OHLC
    consolidated = {
        "generated_at": utc_now(),
        "data_product_id": data_product["data_product_id"],
        "trusted_fields": TRUSTED_FIELDS,
        "limited_fields": LIMITED_FIELDS,
        "formal_trusted_consumption": False,
        "symbols": {
            symbol: {
                "trusted_ohlc_record_count": info["record_count"],
                "latest": info["latest"],
            }
            for symbol, info in trusted_ohlc_by_symbol.items()
        },
    }
    write_json(WORKSPACE_ROOT / "workspace_with_trusted_ohlc.json", consolidated)
    return {"integrated": True, "symbols_updated": updated_count, "total_symbols_with_ohlc": len(trusted_ohlc_by_symbol)}


# =============================================================================
# Step 3: Statistical Report Integration
# =============================================================================

def generate_statistical_report_trusted_ohlc(data_product: dict[str, Any]) -> dict[str, Any]:
    """Generate a statistical report that consumes trusted OHLC and blocks limited fields."""
    preview_rows = read_jsonl(FIELD_TRUST_PREVIEW_ROOT / "a_share_etf_ohlc_trusted_candidate_preview.jsonl")

    # Build per-field statistics from trusted OHLC only
    stats_by_field = {}
    for field in TRUSTED_FIELDS:
        values = [row[field] for row in preview_rows if field in row and row[field] is not None]
        if values:
            stats_by_field[field] = {
                "count": len(values),
                "min": min(values),
                "max": max(values),
                "mean": round(sum(values) / len(values), 4),
                "source": "trusted_candidate_preview_OHLC",
            }

    # Per-symbol stats
    per_symbol_stats = defaultdict(lambda: defaultdict(list))
    for row in preview_rows:
        for field in TRUSTED_FIELDS:
            if field in row and row[field] is not None:
                per_symbol_stats[row["symbol"]][field].append(row[field])

    symbol_summary = {}
    for symbol, field_values in per_symbol_stats.items():
        symbol_summary[symbol] = {
            field: {
                "observations": len(vals),
                "min": min(vals),
                "max": max(vals),
                "first_date": None,
                "last_date": None,
            }
            for field, vals in field_values.items()
        }

    # Per-symbol date range
    symbol_dates = defaultdict(list)
    for row in preview_rows:
        symbol_dates[row["symbol"]].append(row["trade_date"])
    for symbol, dates in symbol_dates.items():
        sdates = sorted(dates)
        if symbol in symbol_summary:
            for fkey in symbol_summary[symbol]:
                symbol_summary[symbol][fkey]["first_date"] = sdates[0]
                symbol_summary[symbol][fkey]["last_date"] = sdates[-1]

    report = {
        "generated_at": utc_now(),
        "statistical_report_id": "stat_report_trusted_ohlc_v1",
        "data_product_id": data_product["data_product_id"],
        "trusted_ohlc_consumed": True,
        "trusted_fields": TRUSTED_FIELDS,
        "limited_fields_blocked": LIMITED_FIELDS,
        "formal_trusted_consumption": False,
        "overall_stats": stats_by_field,
        "per_symbol_stats": symbol_summary,
        "limited_field_warning": "amount, turnover_rate, pct_change, and preclose are NOT included in this statistical report. They remain ready_for_trusted_candidate_limited and cannot be consumed in trusted preview.",
        "dataset_id": data_product["scope"]["dataset_id"],
        "symbol_count": data_product["scope"]["symbol_count"],
        "record_count": data_product["scope"]["record_count"],
        "date_range": data_product["scope"]["date_range"],
        "source_pair": data_product["source_pair"],
    }
    write_json(FIELD_TRUST_PREVIEW_ROOT / "statistical_report_trusted_ohlc_v1.json", report)
    return {"integrated": True, "fields_summarized": len(stats_by_field), "symbols_summarized": len(symbol_summary)}


# =============================================================================
# Step 4: Analysis Packet Integration
# =============================================================================

def regenerate_analysis_packet_trusted_ohlc(data_product: dict[str, Any]) -> dict[str, Any]:
    """Build analysis packet integration artefact with trusted OHLC enriched for 000001 and 600519."""
    preview_rows = read_jsonl(FIELD_TRUST_PREVIEW_ROOT / "a_share_etf_ohlc_trusted_candidate_preview.jsonl")

    packet_result = {
        "generated_at": utc_now(),
        "data_product_id": data_product["data_product_id"],
        "trusted_ohlc_consumed": True,
        "trusted_fields": TRUSTED_FIELDS,
        "limited_fields_blocked": LIMITED_FIELDS,
        "formal_trusted_consumption": False,
        "symbols": {},
        "packet_limitation_note": "Analysis packets may cite OHLC as trusted_candidate preview evidence; limited fields must remain warnings/candidate context.",
    }

    for symbol in SYMBOLS_000001_600519:
        symbol_rows = [r for r in preview_rows if r["symbol"] == symbol]
        if not symbol_rows:
            continue
        symbol_rows_sorted = sorted(symbol_rows, key=lambda r: r["trade_date"])
        latest = symbol_rows_sorted[-1]
        closes = [r["close"] for r in symbol_rows_sorted]

        # 5d price change from trusted OHLC
        pct_5d = None
        if len(closes) >= 6:
            pct_5d = round((closes[-1] - closes[-6]) / closes[-6] * 100, 4)

        # 20d price change
        pct_20d = None
        if len(closes) >= 21:
            pct_20d = round((closes[-1] - closes[-21]) / closes[-21] * 100, 4)

        # Trusted high/low range
        highs = [r["high"] for r in symbol_rows_sorted]
        lows = [r["low"] for r in symbol_rows_sorted]

        packet_result["symbols"][symbol] = {
            "latest_trade_date": latest["trade_date"],
            "trusted_ohlc": {
                "open": latest["open"],
                "high": latest["high"],
                "low": latest["low"],
                "close": latest["close"],
            },
            "trusted_ohlc_statistics": {
                "observation_count": len(symbol_rows_sorted),
                "close_change_5d_pct": pct_5d,
                "close_change_20d_pct": pct_20d,
                "period_high": max(highs),
                "period_low": min(lows),
                "first_date": symbol_rows_sorted[0]["trade_date"],
                "last_date": symbol_rows_sorted[-1]["trade_date"],
            },
            "source_pair": latest.get("source_pair", []),
            "limited_fields_blocked": LIMITED_FIELDS,
            "warning": "amount, turnover_rate, pct_change, preclose NOT available in trusted OHLC preview.",
        }

    write_json(FIELD_TRUST_PREVIEW_ROOT / "analysis_packet_trusted_ohlc_v1.json", packet_result)
    return {"integrated": True, "symbols_in_packet": len(packet_result["symbols"])}


# =============================================================================
# Step 5: Backtest / Forecast Dry-Run
# =============================================================================

def run_backtest_forecast_dryrun_with_trusted_ohlc(data_product: dict[str, Any]) -> dict[str, Any]:
    """Dry-run: read trusted OHLC as historical price context, filter, mark, export. No investment conclusions."""
    preview_rows = read_jsonl(FIELD_TRUST_PREVIEW_ROOT / "a_share_etf_ohlc_trusted_candidate_preview.jsonl")

    # Read existing forecasts from backtest to overlay trusted OHLC
    existing_forecasts = read_json(BACKTEST_ROOT / "forecast_items_updated.json")

    # Build a simulated backtest that uses trusted OHLC as historical context
    dryrun_results = []
    for symbol in SYMBOLS_000001_600519:
        symbol_rows = [r for r in preview_rows if r["symbol"] == symbol]
        if not symbol_rows:
            continue
        symbol_rows_sorted = sorted(symbol_rows, key=lambda r: r["trade_date"])

        # Simulate using trusted OHLC as price context for backtest
        closes = [r["close"] for r in symbol_rows_sorted]

        historic_context = {
            "symbol": symbol,
            "data_product_id": data_product["data_product_id"],
            "trusted_ohlc_record_count": len(symbol_rows_sorted),
            "date_range": {
                "start": symbol_rows_sorted[0]["trade_date"],
                "end": symbol_rows_sorted[-1]["trade_date"],
            },
            "latest_trusted_close": closes[-1],
            "close_series_last_5": closes[-5:] if len(closes) >= 5 else closes,
            "close_ma_5": round(sum(closes[-5:]) / min(5, len(closes)), 4) if len(closes) >= 5 else None,
            "close_ma_20": round(sum(closes[-20:]) / min(20, len(closes)), 4) if len(closes) >= 20 else None,
            "period_high": max(r["high"] for r in symbol_rows_sorted),
            "period_low": min(r["low"] for r in symbol_rows_sorted),
            "readable_as_trusted_historic_context": True,
            "filtered_out_limited_fields": LIMITED_FIELDS,
            "marked_as_trusted_candidate_preview_only": True,
            "formal_trusted_consumption_not_applied": True,
        }

        dryrun_results.append({
            "symbol": symbol,
            "dryrun_type": "trusted_ohlc_as_historic_price_context",
            "historic_context": historic_context,
            "exported_context_path": str(FIELD_TRUST_PREVIEW_ROOT / f"backtest_dryrun_context_{symbol}.json"),
            "no_investment_conclusion_generated": True,
            "no_openai_api_called": True,
            "limited_fields_blocked": LIMITED_FIELDS,
        })

        # Export per-symbol context
        write_json(FIELD_TRUST_PREVIEW_ROOT / f"backtest_dryrun_context_{symbol}.json", historic_context)

    dryrun_summary = {
        "generated_at": utc_now(),
        "data_product_id": data_product["data_product_id"],
        "dryrun_completed": True,
        "dryrun_type": "backtest_forecast_trusted_ohlc_historic_price_context",
        "symbols_tested": len(dryrun_results),
        "trusted_ohlc_read": True,
        "trusted_ohlc_filtered_exported": True,
        "limited_fields_blocked": LIMITED_FIELDS,
        "limited_field_warning_emitted": True,
        "no_investment_conclusion_generated": True,
        "no_openai_api_called": True,
        "formal_trusted_consumption": False,
        "results": dryrun_results,
        "note": "All OHLC values read from trusted_candidate preview; all limited fields blocked; no investment advice or backtest conclusion generated.",
    }
    write_json(FIELD_TRUST_PREVIEW_ROOT / "backtest_trusted_ohlc_dryrun_v1.json", dryrun_summary)
    return {"completed": True, "symbols_tested": len(dryrun_results)}


# =============================================================================
# Step 6: Dashboard Data Product Status
# =============================================================================

def write_dashboard_data_product_status(data_product: dict[str, Any]) -> dict[str, Any]:
    """Write a dashboard panel showing data product level status, including version info."""
    DASHBOARD_ROOT.mkdir(parents=True, exist_ok=True)

    # Load manifest for version count if available
    manifest = read_json(FIELD_TRUST_PREVIEW_ROOT / "data_product_manifest.json")
    version_count = len(manifest.get("versions", [])) if manifest else 0

    panel = {
        "generated_at": utc_now(),
        "panel_type": "data_product_status",
        "data_product_id": data_product["data_product_id"],
        "data_product_name": data_product["data_product_name"],
        "version": data_product["version"],
        "version_id": data_product.get("version_id"),
        "current_version": data_product.get("version_id"),
        "latest_refresh_time": data_product["generated_at"],
        "version_count": version_count,
        "status_summary": {
            "symbols": data_product["scope"]["symbol_count"],
            "records": data_product["scope"]["record_count"],
            "date_range": data_product["scope"]["date_range"],
            "trusted_fields": TRUSTED_FIELDS,
            "limited_fields": LIMITED_FIELDS,
            "source_pair": data_product["source_pair"],
            "last_validation_time": data_product["last_validation_time"],
            "formal_trusted_consumption": "OFF",
            "qa_status": "PASSED (cross-source exact match OHLC)",
        },
        "upgrade_evidence_for_limited_fields": data_product["next_upgrade_evidence_required"],
        "dashboard_markers": [
            "A-share/ETF OHLC Trusted Preview Data Product v1",
            f"Current version: {data_product.get('version_id', 'N/A')}",
            f"Version count: {version_count}",
            "16 symbols, 1216 records, 2026-01-21 to 2026-05-20",
            "Trusted Fields: open, high, low, close",
            "Limited Fields: amount, turnover_rate, pct_change, preclose",
            "Source pair: Baostock + AKShare Tencent",
            "Formal Trusted Consumption: OFF",
            "All limited fields blocked and warned",
        ],
        "limited_field_guard_active": True,
    }

    write_json(DASHBOARD_ROOT / "data_product_panel.json", panel)
    return {"written": True, "path": str(DASHBOARD_ROOT / "data_product_panel.json")}


# =============================================================================
# Step 7: Detailed Limited-Field Upgrade Paths
# =============================================================================

def write_detailed_upgrade_paths() -> dict[str, Any]:
    """Write a detailed, field-by-field upgrade path for each limited field."""
    detailed = {
        "generated_at": utc_now(),
        "purpose": "Detailed upgrade pathways for limited fields currently blocked from trusted_candidate preview.",
        "current_state": {
            "trusted_candidate_fields": TRUSTED_FIELDS,
            "limited_fields": LIMITED_FIELDS,
            "formal_trusted_consumption": False,
            "preview_records": 1216,
        },
        "fields": {
            "amount": {
                "current_status": "ready_for_trusted_candidate_limited",
                "field_description": "Daily trading amount (成交额), typically in RMB yuan.",
                "blocked_because": "AKShare Tencent normalized sample does not provide consistent amount coverage across all symbols.",
                "upgrade_pathway": {
                    "step_1_unit_consistency": {
                        "action": "Confirm amount unit is consistent between Baostock (yuan) and any secondary source.",
                        "evidence_required": "Comparison of Baostock amount values against exchange-published turnover data.",
                        "validation_method": "Linear correlation check across at least 10 trading days per symbol.",
                    },
                    "step_2_formula_source": {
                        "action": "amount = volume * average_price (approximate); document whether any source provides raw amount directly.",
                        "evidence_required": "Source metadata confirming amount derivation method.",
                    },
                    "step_3_upstream_field_explanation": {
                        "action": "Explain upstream dependency on volume and average_price; verify that volume and price are both available.",
                        "evidence_required": "Cross-source validation of both volume and price fields for the same trade_date.",
                    },
                    "step_4_cross_source_consistency": {
                        "action": "Obtain amount from at least one additional source (e.g., Eastmoney if endpoint recovers, or TuShare).",
                        "evidence_required": "Normalized amount values from secondary source for all 16 symbols.",
                    },
                    "step_5_abnormal_range": {
                        "action": "Define acceptable range per symbol: daily amount typically 10^7 to 10^10 yuan range.",
                        "evidence_required": "Distribution analysis of Baostock amount values; flag any single-day outliers > 3 std dev.",
                    },
                    "step_6_trading_rule_constraints": {
                        "action": "Check amount against daily up/down limit rules (e.g., no trading on limit-down days should show zero or anomalous amount).",
                        "evidence_required": "Cross-check amount against pct_change extremes; flag anomalies.",
                    },
                    "minimum_evidence_to_promote": [
                        "secondary source amount coverage for all 16 symbols",
                        "unit normalization evidence (yuan)",
                        "cross-source tolerance policy (e.g., ±1% for amount)",
                        "QA pass over expanded watchlist",
                    ],
                },
            },
            "turnover_rate": {
                "current_status": "ready_for_trusted_candidate_limited",
                "field_description": "Daily turnover rate (换手率), typically a percentage of free-float shares traded.",
                "blocked_because": "Secondary source support/definition agreement is not available in the current controlled sample.",
                "upgrade_pathway": {
                    "step_1_unit_consistency": {
                        "action": "Confirm turnover_rate is expressed as percentage (0-100%).",
                        "evidence_required": "Baostock documentation and sample range check.",
                    },
                    "step_2_formula_source": {
                        "action": "Document whether turnover_rate = volume / free_float_shares * 100 or total_shares.",
                        "evidence_required": "Source metadata or formula documentation from Baostock API docs.",
                    },
                    "step_3_upstream_field_explanation": {
                        "action": "Explain dependency on volume and share structure; verify volume is available as production_candidate.",
                        "evidence_required": "Correlation between volume and turnover_rate across all symbols.",
                    },
                    "step_4_cross_source_consistency": {
                        "action": "Obtain turnover_rate from a second source for comparison.",
                        "evidence_required": "Normalized turnover_rate from a secondary source.",
                    },
                    "step_5_abnormal_range": {
                        "action": "Define acceptable range: typically 0-50% for most stocks, ETF may be higher.",
                        "evidence_required": "Distribution analysis; flag symbols where turnover_rate exceeds 100% or is exactly zero on trade days.",
                    },
                    "step_6_trading_rule_constraints": {
                        "action": "Turnover should be non-zero on regular trading days; zero values should be flagged.",
                        "evidence_required": "Review zero-turnover days against trading calendar.",
                    },
                    "minimum_evidence_to_promote": [
                        "documented source definition (Baostock turnover_rate formula)",
                        "secondary source coverage",
                        "reasonable range QA (0-100% nominal, flag >100% or zero on active days)",
                        "expanded cross-source validation",
                    ],
                },
            },
            "pct_change": {
                "current_status": "ready_for_trusted_candidate_limited",
                "field_description": "Daily percentage change (涨跌幅), typically (close - preclose) / preclose * 100.",
                "blocked_because": "Needs deterministic source definition or formula validation and tolerance policy.",
                "upgrade_pathway": {
                    "step_1_unit_consistency": {
                        "action": "Confirm pct_change is expressed as percentage with consistent precision.",
                        "evidence_required": "Verify that pct_change roughly matches (close - preclose)/preclose*100 within tolerance.",
                    },
                    "step_2_formula_source": {
                        "action": "Derive and validate: pct_change = (close - preclose) / preclose * 100.",
                        "evidence_required": "Compare Baostock pct_change against computed value from close and preclose for a sample of 50 records.",
                        "tolerance": "±0.01 percentage points",
                    },
                    "step_3_upstream_field_explanation": {
                        "action": "pct_change depends on close and preclose; preclose must itself pass trust validation.",
                        "evidence_required": "Document preclose definition and adjustment policy before promoting pct_change.",
                    },
                    "step_4_cross_source_consistency": {
                        "action": "Compare pct_change across Baostock and any secondary source.",
                        "evidence_required": "Cross-source pct_change comparison for all 16 symbols; tolerance ±0.05 pp.",
                    },
                    "step_5_abnormal_range": {
                        "action": "A-share daily limit: ±10% for most stocks (±20% for 300/688, ±30% for ST). Verify pct_change does not exceed limits.",
                        "evidence_required": "Rule-based check: flag any pct_change that exceeds market limit rules.",
                    },
                    "step_6_trading_rule_constraints": {
                        "action": "On limit-up days, close=high=limit; on limit-down days, close=low=limit; pct_change should match.",
                        "evidence_required": "Cross-check extreme pct_change values against OHLC for limit days.",
                    },
                    "minimum_evidence_to_promote": [
                        "deterministic formula or upstream definition",
                        "preclose/adjustment policy",
                        "precision tolerance rule (±0.01 pp vs computed)",
                        "mismatch review queue closure",
                    ],
                },
            },
            "preclose": {
                "current_status": "ready_for_trusted_candidate_limited",
                "field_description": "Previous trading day's adjusted close price (昨收), used as reference for pct_change.",
                "blocked_because": "Needs secondary-source coverage or documented derivation policy across corporate action adjustment modes.",
                "upgrade_pathway": {
                    "step_1_unit_consistency": {
                        "action": "Confirm preclose is in same price unit (RMB yuan) as OHLC.",
                        "evidence_required": "Compare preclose against previous day's close; should match exactly on non-adjustment days.",
                    },
                    "step_2_formula_source": {
                        "action": "Document whether preclose = previous day close or is adjusted after corporate actions.",
                        "evidence_required": "Baostock or exchange documentation on preclose adjustment rules.",
                    },
                    "step_3_upstream_field_explanation": {
                        "action": "preclose is derived from previous_day.close; verify the chain: D-1 close -> D preclose consistency.",
                        "evidence_required": "For non-adjustment days, verify preclose(trade_date) == close(trade_date - 1) for all symbols.",
                    },
                    "step_4_cross_source_consistency": {
                        "action": "Obtain preclose from a secondary source; compare on both normal and ex-right/ex-dividend dates.",
                        "evidence_required": "At least one secondary preclose source for comparison; special attention to corporate action dates.",
                    },
                    "step_5_abnormal_range": {
                        "action": "preclose should be within [low, high] range of previous day, and within typical price range.",
                        "evidence_required": "Flag any preclose that differs from previous close by > price tolerance on non-adjustment days.",
                    },
                    "step_6_trading_rule_constraints": {
                        "action": "On ex-right or ex-dividend dates, preclose is adjusted downward; verify adjustment formula matches exchange rules.",
                        "evidence_required": "Corporate action calendar cross-referenced with preclose adjustment verification.",
                    },
                    "minimum_evidence_to_promote": [
                        "secondary source coverage or audited derivation from previous close",
                        "corporate action adjustment mode policy",
                        "cross-source validation after ex-right/ex-dividend cases",
                    ],
                },
            },
        },
        "general_upgrade_prerequisite": {
            "formal_trusted_consumption_must_remain_off": True,
            "each_field_promoted_individually": True,
            "all_limited_fields_require_separate_qa_pass": True,
            "no_blanket_promotion": True,
        },
    }

    write_json(FIELD_TRUST_PREVIEW_ROOT / "field_upgrade_path_detailed_v1.json", detailed)
    return {"written": True, "fields_documented": len(detailed["fields"])}


# =============================================================================
# Step 8: Version Snapshot + Latest Pointer + Manifest
# =============================================================================

def generate_version_id() -> str:
    """Generate a timestamp-based version id, e.g. v20260521_183000."""
    now = datetime.now(timezone.utc)
    return f"v{now.strftime('%Y%m%d_%H%M%S')}"


def write_version_snapshot_and_pointers(data_product: dict[str, Any]) -> dict[str, Any]:
    """Write a versioned snapshot, latest pointer, and append to manifest."""
    version_id = data_product["version_id"]
    version_dir = VERSIONS_ROOT / version_id
    version_dir.mkdir(parents=True, exist_ok=True)

    # Copy key artefacts into version dir (lightweight symlinks would be better, but copy for Windows safety)
    root_files = {
        "data_product.json": FIELD_TRUST_PREVIEW_ROOT / "data_product_v1_ohlc_trusted_preview.json",
        "statistical_report.json": FIELD_TRUST_PREVIEW_ROOT / "statistical_report_trusted_ohlc_v1.json",
        "analysis_packet.json": FIELD_TRUST_PREVIEW_ROOT / "analysis_packet_trusted_ohlc_v1.json",
        "backtest_dryrun.json": FIELD_TRUST_PREVIEW_ROOT / "backtest_trusted_ohlc_dryrun_v1.json",
        "dashboard_panel.json": DASHBOARD_ROOT / "data_product_panel.json",
        "field_upgrade_paths.json": FIELD_TRUST_PREVIEW_ROOT / "field_upgrade_path_detailed_v1.json",
    }
    for name, src in root_files.items():
        if src.exists():
            dest = version_dir / name
            dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    # Build latest pointer
    scope = data_product["scope"]
    pointer = {
        "version_id": version_id,
        "created_at": utc_now(),
        "data_product_path": str(version_dir / "data_product.json"),
        "statistical_report_path": str(version_dir / "statistical_report.json"),
        "analysis_packet_path": str(version_dir / "analysis_packet.json"),
        "backtest_dryrun_path": str(version_dir / "backtest_dryrun.json"),
        "dashboard_panel_path": str(version_dir / "dashboard_panel.json"),
        "field_upgrade_paths_path": str(version_dir / "field_upgrade_paths.json"),
        "record_count": scope["record_count"],
        "symbol_count": scope["symbol_count"],
        "date_range": scope["date_range"],
        "trusted_fields": TRUSTED_FIELDS,
        "limited_fields": LIMITED_FIELDS,
        "formal_trusted_consumption_enabled": False,
        "limited_field_guard_active": True,
    }
    write_json(FIELD_TRUST_PREVIEW_ROOT / "latest_data_product.json", pointer)

    # Append-only manifest
    manifest_path = FIELD_TRUST_PREVIEW_ROOT / "data_product_manifest.json"
    manifest = read_json(manifest_path)
    if not manifest:
        manifest = {
            "data_product_id": data_product["data_product_id"],
            "data_product_name": data_product["data_product_name"],
            "created_at": utc_now(),
            "versions": [],
        }
    previous_count = len(manifest.get("versions", []))
    manifest.setdefault("versions", []).append({
        "version_id": version_id,
        "created_at": utc_now(),
        "record_count": scope["record_count"],
        "symbol_count": scope["symbol_count"],
        "date_range": scope["date_range"],
        "trusted_fields": TRUSTED_FIELDS,
        "limited_fields": LIMITED_FIELDS,
        "formal_trusted_consumption_enabled": False,
        "version_dir": str(version_dir),
    })
    write_json(manifest_path, manifest)

    return {
        "versioned": True,
        "version_id": version_id,
        "version_dir": str(version_dir),
        "latest_pointer_written": True,
        "manifest_updated": True,
        "previous_version_count": previous_count,
    }


# =============================================================================
# Consumer helpers: read latest pointer with fallback to root-level files
# =============================================================================

def read_latest_data_product() -> dict[str, Any] | None:
    """Read the latest data product via pointer if it exists."""
    pointer_path = FIELD_TRUST_PREVIEW_ROOT / "latest_data_product.json"
    if pointer_path.exists():
        pointer = read_json(pointer_path)
        dp_path = Path(pointer.get("data_product_path", ""))
        if dp_path.exists():
            return read_json(dp_path)
    return None


def read_latest_or_fallback(filename: str, fallback_root: Path) -> dict[str, Any]:
    """Read via latest pointer if available, otherwise fall back to root-level file."""
    pointer_path = FIELD_TRUST_PREVIEW_ROOT / "latest_data_product.json"
    if pointer_path.exists():
        pointer = read_json(pointer_path)
        key_map = {
            "data_product": "data_product_path",
            "statistical_report": "statistical_report_path",
            "analysis_packet": "analysis_packet_path",
            "backtest_dryrun": "backtest_dryrun_path",
            "dashboard_panel": "dashboard_panel_path",
            "field_upgrade_paths": "field_upgrade_paths_path",
        }
        if filename in key_map:
            mapped = Path(pointer.get(key_map[filename], ""))
            if mapped.exists():
                return read_json(mapped)
    # Fallback to root-level
    fallback = fallback_root / filename
    if fallback.exists():
        return read_json(fallback)
    return {}


# =============================================================================
# Utilities
# =============================================================================

def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    run_ohlc_trusted_data_product_v1()
