from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

PHASE8_ROOT = PROJECT_ROOT / "runtime" / "morningstar_candidate_data_product_v1"
OUTPUT_ROOT = PROJECT_ROOT / "runtime" / "morningstar_research_workflow_v1"

ENVELOPE_PATH = PHASE8_ROOT / "manifest" / "morningstar_data_product_envelope.json"
REGISTRY_PATH = PROJECT_ROOT / "config" / "data_product_registry.json"
LATEST_POINTER_PATH = PHASE8_ROOT / "manifest" / "latest_data_product.json"

RETURNS_PATH = PHASE8_ROOT / "normalized" / "morningstar_returns_candidate_preview.json"
HOLDINGS_PATH = PHASE8_ROOT / "normalized" / "morningstar_holdings_exposure_candidate_preview.json"
LOOKTHROUGH_PATH = PHASE8_ROOT / "normalized" / "morningstar_lookthrough_holdings_candidate_preview.json"
AUM_PROXY_PATH = PHASE8_ROOT / "normalized" / "morningstar_holdings_derived_aum_candidate_proxy.json"
ENTITY_SHELL_PATH = PHASE8_ROOT / "entity_master" / "morningstar_underlying_entity_shell.json"
US_EQUITY_SHELL_PATH = PHASE8_ROOT / "entity_master" / "morningstar_us_equity_entity_shell.json"
BOND_SHELL_PATH = PHASE8_ROOT / "entity_master" / "morningstar_bond_entity_shell.json"
COMMODITY_SHELL_PATH = PHASE8_ROOT / "entity_master" / "morningstar_commodity_entity_shell.json"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_integration() -> dict[str, Any]:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    envelope = read_json(ENVELOPE_PATH)
    registry = read_json(REGISTRY_PATH)
    latest_pointer = read_json(LATEST_POINTER_PATH)

    returns_data = read_json(RETURNS_PATH) if RETURNS_PATH.exists() else {}
    holdings_data = read_json(HOLDINGS_PATH) if HOLDINGS_PATH.exists() else {}
    lookthrough_data = read_json(LOOKTHROUGH_PATH) if LOOKTHROUGH_PATH.exists() else {}
    aum_proxy_data = read_json(AUM_PROXY_PATH) if AUM_PROXY_PATH.exists() else {}

    entity_counts = {
        "total": _count_json_array(ENTITY_SHELL_PATH),
        "us_equity": _count_json_array(US_EQUITY_SHELL_PATH),
        "bond": _count_json_array(BOND_SHELL_PATH),
        "commodity": _count_json_array(COMMODITY_SHELL_PATH),
    }

    workspace_result = build_workspace_index(envelope, returns_data, holdings_data, lookthrough_data, aum_proxy_data, entity_counts)
    stat_report_result = build_statistical_report(envelope, returns_data, holdings_data, lookthrough_data, aum_proxy_data, entity_counts)
    packet_result = build_analysis_packet_integration(envelope, returns_data, holdings_data, lookthrough_data, aum_proxy_data, entity_counts)

    manifest = {
        "generated_at": utc_now(),
        "integration_id": "morningstar_research_workflow_v1",
        "data_product_id": envelope["data_product_id"],
        "version_id": envelope["version_id"],
        "source_envelope": str(ENVELOPE_PATH),
        "source_registry": str(REGISTRY_PATH),
        "source_latest_pointer": str(LATEST_POINTER_PATH),
        "workspace_index_path": str(workspace_result["path"]),
        "statistical_report_path": str(stat_report_result["path"]),
        "analysis_packet_integration_path": str(packet_result["path"]),
        "api_calls_made": 0,
        "no_openai_api_called": True,
        "parse_lab_affected": False,
        "formal_trusted_consumption_enabled": False,
        "us_equity_standalone_excluded": True,
        "tna_enf_blocked": True,
        "outputs": {
            "workspace_index": str(workspace_result["path"]),
            "statistical_report": str(stat_report_result["path"]),
            "analysis_packet_integration": str(packet_result["path"]),
        },
    }
    write_json(OUTPUT_ROOT / "manifest" / "integration_manifest.json", manifest)

    summary = {
        "generated_at": utc_now(),
        "integration_completed": True,
        "data_product_id": envelope["data_product_id"],
        "version_id": envelope["version_id"],
        "workspace_index": workspace_result["summary"],
        "statistical_report": stat_report_result["summary"],
        "analysis_packet_integration": packet_result["summary"],
        "manifest_path": str(OUTPUT_ROOT / "manifest" / "integration_manifest.json"),
        "api_calls_made": 0,
        "no_openai_api_called": True,
        "parse_lab_affected": False,
        "formal_trusted_consumption_enabled": False,
        "us_equity_standalone_excluded": True,
        "tna_enf_blocked": True,
    }
    write_json(OUTPUT_ROOT / "manifest" / "integration_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def build_workspace_index(
    envelope: dict[str, Any],
    returns_data: dict[str, Any],
    holdings_data: dict[str, Any],
    lookthrough_data: dict[str, Any],
    aum_proxy_data: dict[str, Any],
    entity_counts: dict[str, int],
) -> dict[str, Any]:
    seed_universe = envelope.get("scope", {}).get("seed_universe", {})

    # Returns latest sample
    latest_returns = {}
    for row in returns_data.get("latest_sample", []):
        sid = row.get("Id")
        if sid:
            latest_returns.setdefault(sid, []).append({
                "date": row.get("Date"),
                "monthly_return_pct": row.get("Monthly Return"),
            })

    # Holdings summary per seed
    holdings_summary = {}
    for seed, info in (holdings_data.get("holdings", {}).get("samples", {}) or {}).items():
        holdings_summary[seed] = {
            "portfolio_date": info.get("portfolio_date"),
            "row_count": info.get("row_count"),
            "status": "production_candidate_preview",
        }

    # Look-through summary
    lookthrough_summary = {
        "sample": lookthrough_data.get("sample"),
        "row_count": lookthrough_data.get("row_count"),
        "portfolio_date": lookthrough_data.get("portfolio_date"),
        "status": "production_candidate_preview",
    }

    # AUM proxy summary
    aum_summary = {}
    for seed, info in (aum_proxy_data.get("samples", {}) or {}).items():
        aum_summary[seed] = {
            "sum_marketValue_usd": info.get("sum_marketValue_usd"),
            "row_count": info.get("row_count"),
            "portfolio_date": info.get("portfolio_date"),
            "status": "candidate_proxy",
            "limitations": aum_proxy_data.get("limitations", []),
        }

    workspace = {
        "generated_at": utc_now(),
        "workspace_id": "morningstar_candidate_workspace_v1",
        "data_product_id": envelope["data_product_id"],
        "version_id": envelope["version_id"],
        "formal_trusted_consumption_enabled": False,
        "us_equity_standalone_excluded": True,
        "evidence_boundary": {
            "consumable_fields": {
                "returns": {"status": "production_candidate_preview", "note": "Monthly return percent; validated via get_data_point_settings."},
                "holdings_exposure": {"status": "production_candidate_preview", "note": "Weight (%) and marketValue (USD) from get_holdings."},
                "lookthrough_holdings": {"status": "production_candidate_preview", "note": "Weight (%) from get_lookthrough_holdings."},
            },
            "proxy_fields": {
                "holdings_derived_aum": {"status": "candidate_proxy", "note": "sum(marketValue) proxy only; not official AUM."},
            },
            "identifier_mapping_fields": {
                "underlying_entity_shell": {"status": "identifier_mapping_candidate", "note": "Identifier-only shells; no price time series."},
            },
            "blocked_fields": {
                "tna_enf": {
                    "status": "blocked_unit_scale_unknown",
                    "reason": "Currency confirmed USD; unit/scale not disclosed. VTI outlier prevents universal unit hypothesis.",
                    "data_points_blocked": ["TNA0M", "ENF0M", "TNA0R", "ENF0R", "TNA1M", "ENF1M"],
                },
            },
        },
        "seed_universe": seed_universe,
        "latest_returns_sample": latest_returns,
        "holdings_summary": holdings_summary,
        "lookthrough_summary": lookthrough_summary,
        "aum_proxy_summary": aum_summary,
        "entity_shell_counts": entity_counts,
        "license_warnings": [
            "All Morningstar data in this workspace is candidate_preview or candidate_proxy.",
            "TNA/ENF are BLOCKED. Do not use for capital flow conclusions.",
            "US equities appear only as holdings underlying entities / entity shells, not as standalone price time series.",
        ],
    }
    path = OUTPUT_ROOT / "workspace" / "morningstar_workspace_index.json"
    write_json(path, workspace)
    return {
        "path": str(path),
        "summary": {
            "seeds": list(seed_universe.keys()),
            "consumable_field_count": 3,
            "proxy_field_count": 1,
            "blocked_field_count": 1,
            "entity_shell_count": entity_counts["total"],
        },
    }


def build_statistical_report(
    envelope: dict[str, Any],
    returns_data: dict[str, Any],
    holdings_data: dict[str, Any],
    lookthrough_data: dict[str, Any],
    aum_proxy_data: dict[str, Any],
    entity_counts: dict[str, int],
) -> dict[str, Any]:
    # Returns stats per investmentId
    returns_stats = {}
    rows_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in returns_data.get("latest_sample", []):
        rows_by_id[row.get("Id", "")].append(row)
    for sid, rows in rows_by_id.items():
        vals = [r["Monthly Return"] for r in rows if isinstance(r.get("Monthly Return"), (int, float))]
        if vals:
            returns_stats[sid] = {
                "observations": len(vals),
                "min_pct": round(min(vals), 4),
                "max_pct": round(max(vals), 4),
                "mean_pct": round(sum(vals) / len(vals), 4),
                "latest_pct": round(vals[0], 4) if vals else None,  # latest_sample first row is latest
            }

    # Holdings stats per seed
    holdings_stats = {}
    for seed, info in (aum_proxy_data.get("samples", {}) or {}).items():
        top = info.get("top_holdings_sample", [])[:3]
        holdings_stats[seed] = {
            "row_count": info.get("row_count"),
            "sum_marketValue_usd": info.get("sum_marketValue_usd"),
            "sum_weight_percent": info.get("sum_weight_percent"),
            "portfolio_date": info.get("portfolio_date"),
            "top_3_holdings": [
                {
                    "name": h.get("name"),
                    "ticker": h.get("ticker") if not _is_nan(h.get("ticker")) else None,
                    "weight_pct": h.get("weight"),
                    "marketValue_usd": h.get("marketValue"),
                    "detailHoldingType": h.get("detailHoldingType"),
                }
                for h in top
            ],
        }

    # Look-through stats
    lookthrough_stats = {
        "row_count": lookthrough_data.get("row_count"),
        "portfolio_date": lookthrough_data.get("portfolio_date"),
        "sample": lookthrough_data.get("sample"),
    }

    # AUM proxy aggregate
    aum_aggregate = {
        "seed_count": len(aum_proxy_data.get("samples", {})),
        "total_sum_marketValue_usd": sum(
            info.get("sum_marketValue_usd", 0) or 0
            for info in (aum_proxy_data.get("samples", {}) or {}).values()
        ),
        "method": aum_proxy_data.get("method"),
        "currency_inferred": aum_proxy_data.get("currency_inferred"),
        "limitations": aum_proxy_data.get("limitations", []),
    }

    report = {
        "generated_at": utc_now(),
        "statistical_report_id": "morningstar_statistical_report_v1",
        "data_product_id": envelope["data_product_id"],
        "version_id": envelope["version_id"],
        "formal_trusted_consumption": False,
        "us_equity_standalone_excluded": True,
        "tna_enf_blocked": True,
        "field_level_status": envelope.get("field_level_status", {}),
        "returns_stats": returns_stats,
        "holdings_stats": holdings_stats,
        "lookthrough_stats": lookthrough_stats,
        "aum_proxy_aggregate": aum_aggregate,
        "entity_shell_counts": entity_counts,
        "evidence_boundary_note": (
            "Returns/holdings/look-through are production_candidate_preview. "
            "Holdings-derived AUM is candidate_proxy. TNA/ENF is blocked_unit_scale_unknown. "
            "US equities are excluded as standalone time series."
        ),
    }
    path = OUTPUT_ROOT / "statistical_report" / "morningstar_statistical_report_v1.json"
    write_json(path, report)
    return {
        "path": str(path),
        "summary": {
            "returns_symbols": list(returns_stats.keys()),
            "holdings_seeds": list(holdings_stats.keys()),
            "aum_proxy_seed_count": aum_aggregate["seed_count"],
            "entity_shell_count": entity_counts["total"],
        },
    }


def build_analysis_packet_integration(
    envelope: dict[str, Any],
    returns_data: dict[str, Any],
    holdings_data: dict[str, Any],
    lookthrough_data: dict[str, Any],
    aum_proxy_data: dict[str, Any],
    entity_counts: dict[str, int],
) -> dict[str, Any]:
    seed_universe = envelope.get("scope", {}).get("seed_universe", {})

    # Pre-compute returns by investmentId
    returns_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in returns_data.get("latest_sample", []):
        returns_by_id[row.get("Id", "")].append(row)

    seed_summaries = {}
    for seed, secid in seed_universe.items():
        # Returns
        ret_rows = returns_by_id.get(secid, [])
        ret_latest = ret_rows[0] if ret_rows else None
        ret_history = [
            {"date": r.get("Date"), "monthly_return_pct": r.get("Monthly Return")}
            for r in ret_rows
        ]

        # Holdings
        h_info = (aum_proxy_data.get("samples", {}) or {}).get(seed, {})
        top_holdings = h_info.get("top_holdings_sample", [])[:3]

        # AUM proxy
        aum_value = h_info.get("sum_marketValue_usd")

        seed_summaries[seed] = {
            "secid": secid,
            "returns_candidate_preview": {
                "status": "production_candidate_preview",
                "latest_monthly_return_pct": ret_latest.get("Monthly Return") if ret_latest else None,
                "history": ret_history,
                "unit": "percent (%)",
                "currency": "BASE",
                "note": "Validated via get_data_point_settings; still candidate_preview.",
            },
            "holdings_exposure_candidate_preview": {
                "status": "production_candidate_preview",
                "portfolio_date": h_info.get("portfolio_date"),
                "holdings_row_count": h_info.get("row_count"),
                "top_holdings": [
                    {
                        "name": h.get("name"),
                        "ticker": h.get("ticker") if not _is_nan(h.get("ticker")) else None,
                        "weight_pct": h.get("weight"),
                        "marketValue_usd": h.get("marketValue"),
                        "detailHoldingType": h.get("detailHoldingType"),
                    }
                    for h in top_holdings
                ],
                "unit_weight": "percent (%)",
                "unit_marketValue": "absolute local currency (USD)",
                "note": "Holdings exposure available; weight sums near 100%.",
            },
            "lookthrough_holdings_candidate_preview": {
                "status": "production_candidate_preview",
                "row_count": lookthrough_data.get("row_count") if seed == "SPY" else None,
                "portfolio_date": lookthrough_data.get("portfolio_date") if seed == "SPY" else None,
                "note": "Look-through available for SPY only in current sample." if seed != "SPY" else "Look-through holdings provide secId + weight.",
            },
            "holdings_derived_aum_candidate_proxy": {
                "status": "candidate_proxy",
                "value_usd": aum_value,
                "method": "sum(marketValue) from get_holdings",
                "coverage_date": h_info.get("portfolio_date"),
                "limitations": aum_proxy_data.get("limitations", []),
                "note": "Proxy only; not official Morningstar AUM/TNA.",
            },
            "blocked_fields": {
                "tna_enf": {
                    "status": "blocked_unit_scale_unknown",
                    "reason": "Currency confirmed USD; unit/scale not disclosed.",
                    "data_points_blocked": ["TNA0M", "ENF0M", "TNA0R", "ENF0R", "TNA1M", "ENF1M"],
                    "note": "TNA/ENF must NOT be used for capital flow conclusions.",
                },
            },
            "us_equity_standalone_exclusion": {
                "excluded": True,
                "note": "US equities appear only as holdings underlying entities / entity shells, not as standalone price time series.",
            },
        }

    packet = {
        "generated_at": utc_now(),
        "packet_integration_id": "morningstar_analysis_packet_integration_v1",
        "data_product_id": envelope["data_product_id"],
        "version_id": envelope["version_id"],
        "formal_trusted_consumption": False,
        "as_of_date": utc_now()[:10],
        "seed_summaries": seed_summaries,
        "evidence_boundary": {
            "candidate_preview_fields": ["returns", "holdings_exposure", "lookthrough_holdings"],
            "candidate_proxy_fields": ["holdings_derived_aum"],
            "identifier_mapping_fields": ["underlying_entity_shell"],
            "blocked_fields": ["tna_enf"],
            "excluded_standalone_series": ["us_equity_price_time_series"],
        },
        "license_warnings": [
            "All Morningstar data in this packet is candidate_preview or candidate_proxy.",
            "Do not treat returns/holdings as trusted final facts.",
            "Do not use holdings-derived AUM as official AUM.",
            "TNA/ENF is BLOCKED from any capital flow conclusion.",
        ],
    }
    path = OUTPUT_ROOT / "analysis_packet" / "morningstar_analysis_packet_integration_v1.json"
    write_json(path, packet)
    return {
        "path": str(path),
        "summary": {
            "seed_count": len(seed_summaries),
            "candidate_preview_fields": 3,
            "candidate_proxy_fields": 1,
            "blocked_field_groups": 1,
        },
    }


def _count_json_array(path: Path) -> int:
    if not path.exists():
        return 0
    data = read_json(path)
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        if "total_entities" in data:
            return int(data["total_entities"])
        if "entities" in data and isinstance(data["entities"], list):
            return len(data["entities"])
        return len(data)
    return 0


def _is_nan(value: Any) -> bool:
    if value is None:
        return True
    try:
        return math.isnan(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False


def main() -> int:
    summary = run_integration()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
