from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


RUNTIME_ROOT = PROJECT_ROOT / "runtime" / "field_level_trusted_preview"
CONFIG_PATH = PROJECT_ROOT / "config" / "field_level_trust_contract.json"
DOC_CONTRACT = PROJECT_ROOT / "docs" / "FIELD_LEVEL_TRUST_CONTRACT.md"
DOC_SELECTOR = PROJECT_ROOT / "docs" / "TRUSTED_CANDIDATE_PREVIEW_SELECTOR.md"
DOC_A_SHARE = PROJECT_ROOT / "docs" / "A_SHARE_ETF_FIELD_LEVEL_TRUST_PREVIEW.md"
RECALIBRATION_PATH = (
    PROJECT_ROOT
    / "runtime"
    / "automated_ingestion_system"
    / "trust_threshold_recalibration"
    / "a_share_etf_trust_recalibration_result.json"
)


TRUSTED_OHLC_FIELDS = ["open", "high", "low", "close"]
LIMITED_FIELDS = ["amount", "turnover_rate", "pct_change", "preclose"]
PRODUCTION_CANDIDATE_FIELDS = ["volume"]


def run_field_level_trusted_preview() -> dict[str, Any]:
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    recalibration = read_json(RECALIBRATION_PATH)
    normalized_paths = recalibration.get("evidence", {}).get("normalized_paths", {})
    baostock_path = Path(normalized_paths.get("baostock", ""))
    akshare_path = Path(normalized_paths.get("akshare_tencent", ""))
    baostock_records = read_jsonl(baostock_path)
    akshare_records = read_jsonl(akshare_path)
    akshare_by_key = {(row.get("symbol"), row.get("trade_date")): row for row in akshare_records}

    preview_rows: list[dict[str, Any]] = []
    excluded_rows: list[dict[str, Any]] = []
    trusted_field_counts = {field: 0 for field in TRUSTED_OHLC_FIELDS}
    symbols: set[str] = set()
    dates: list[str] = []
    for primary in baostock_records:
        key = (primary.get("symbol"), primary.get("trade_date"))
        secondary = akshare_by_key.get(key)
        if not secondary:
            excluded_rows.append(
                {
                    "symbol": primary.get("symbol"),
                    "trade_date": primary.get("trade_date"),
                    "reason": "missing_secondary_record",
                }
            )
            continue
        field_status = {}
        trusted_values = {}
        all_trusted_fields_match = True
        for field in TRUSTED_OHLC_FIELDS:
            primary_value = primary.get(field)
            secondary_value = secondary.get(field)
            exact_match = values_equal(primary_value, secondary_value)
            field_status[field] = {
                "trust_status": "trusted_candidate",
                "selection_status": "included",
                "baostock_value": primary_value,
                "akshare_tencent_value": secondary_value,
                "exact_match": exact_match,
            }
            if exact_match:
                trusted_field_counts[field] += 1
                trusted_values[field] = primary_value
            else:
                all_trusted_fields_match = False
        if not all_trusted_fields_match:
            excluded_rows.append(
                {
                    "symbol": primary.get("symbol"),
                    "trade_date": primary.get("trade_date"),
                    "reason": "trusted_field_mismatch",
                    "field_status": field_status,
                }
            )
            continue
        symbol = str(primary.get("symbol"))
        trade_date = str(primary.get("trade_date"))
        symbols.add(symbol)
        dates.append(trade_date)
        preview_rows.append(
            {
                "dataset_id": "a_share_etf_daily_field_trusted_preview_v1",
                "entity_id": f"a_share_or_etf:{symbol}",
                "symbol": symbol,
                "trade_date": trade_date,
                **trusted_values,
                "field_trust": field_status,
                "excluded_limited_fields": LIMITED_FIELDS,
                "production_candidate_fields": PRODUCTION_CANDIDATE_FIELDS,
                "source_pair": ["baostock_daily", "akshare_tencent_daily"],
                "primary_value_source": "baostock_daily",
                "secondary_validation_source": "akshare_tencent_daily",
                "trust_status": "trusted_candidate_preview",
                "staging_status": "field_level_trusted_candidate_preview",
                "preview_only": True,
                "formal_trusted_consumption": False,
                "limitation_note": "Only OHLC fields are selected as trusted_candidate preview; amount, turnover_rate, pct_change, and preclose remain limited/review fields.",
            }
        )

    min_date = min(dates) if dates else None
    max_date = max(dates) if dates else None
    symbol_list = sorted(symbols)
    contract = build_contract(recalibration, symbol_list, min_date, max_date, preview_rows, excluded_rows)
    limited_review = build_limited_field_review()
    packet_input = build_packet_input(contract, preview_rows)
    statistical_input = build_statistical_input(contract, preview_rows)
    field_upgrade_path = build_field_upgrade_path()
    dashboard_summary = build_dashboard_summary(contract, limited_review, field_upgrade_path)

    write_json(CONFIG_PATH, contract)
    write_json(RUNTIME_ROOT / "field_level_trust_contract.json", contract)
    write_json(RUNTIME_ROOT / "trusted_candidate_preview_selector_results.json", {
        "generated_at": utc_now(),
        "selector_id": "a_share_etf_ohlc_trusted_candidate_preview_selector_v1",
        "input_records": {
            "baostock": len(baostock_records),
            "akshare_tencent": len(akshare_records),
        },
        "included_records": len(preview_rows),
        "excluded_records": len(excluded_rows),
        "trusted_field_counts": trusted_field_counts,
        "preview_jsonl_path": str(RUNTIME_ROOT / "a_share_etf_ohlc_trusted_candidate_preview.jsonl"),
        "formal_trusted_consumption": False,
        "excluded_preview": excluded_rows[:20],
    })
    write_jsonl(RUNTIME_ROOT / "a_share_etf_ohlc_trusted_candidate_preview.jsonl", preview_rows)
    write_json(RUNTIME_ROOT / "a_share_etf_limited_field_review.json", limited_review)
    write_json(RUNTIME_ROOT / "analysis_packet_trusted_preview_input.json", packet_input)
    write_json(RUNTIME_ROOT / "statistical_report_trusted_preview_input.json", statistical_input)
    write_json(RUNTIME_ROOT / "field_upgrade_path.json", field_upgrade_path)
    write_json(RUNTIME_ROOT / "dashboard_field_trust_summary.json", dashboard_summary)
    summary = {
        "generated_at": utc_now(),
        "field_level_trust_contract_completed": True,
        "trusted_candidate_preview_selector_completed": True,
        "a_share_etf_ohlc_trusted_candidate_preview": len(preview_rows) > 0,
        "preview_records": len(preview_rows),
        "trusted_candidate_fields": TRUSTED_OHLC_FIELDS,
        "limited_fields": LIMITED_FIELDS,
        "production_candidate_fields": PRODUCTION_CANDIDATE_FIELDS,
        "formal_trusted_consumption": False,
        "output_root": str(RUNTIME_ROOT),
    }
    write_json(RUNTIME_ROOT / "field_level_trusted_preview_summary.json", summary)
    write_docs(contract, len(preview_rows), limited_review, field_upgrade_path)
    return summary


def build_contract(
    recalibration: dict[str, Any],
    symbols: list[str],
    min_date: str | None,
    max_date: str | None,
    preview_rows: list[dict[str, Any]],
    excluded_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "contract_id": "field_level_trust_contract_v1",
        "generated_at": utc_now(),
        "scope": {
            "dataset_id": "a_share_etf_daily_baostock_akshare_tencent_v4",
            "data_category": "market_daily",
            "entity_type": "a_share_or_etf",
            "symbols": symbols,
            "time_window": {
                "start_trade_date": min_date,
                "end_trade_date": max_date,
                "time_window_trust_status": "trusted_candidate_preview",
            },
            "source_pair": ["baostock_daily", "akshare_tencent_daily"],
        },
        "source_level_trust": {
            "baostock_daily": {
                "source_role": "primary_value_source",
                "trust_status": "production_candidate",
                "provenance_note": "Operational source with cross-source validation partner.",
            },
            "akshare_tencent_daily": {
                "source_role": "secondary_validation_source",
                "trust_status": "institutional_proxy_high_confidence_candidate",
                "provenance_note": "AKShare wrapper around Tencent-backed daily market interface; interface-level trust only.",
            },
        },
        "field_level_trust": {
            field: {
                "trust_status": "trusted_candidate",
                "consumption_preview_allowed": True,
                "selection_rule": "Baostock primary value allowed only when AKShare Tencent exact-matches the same symbol/date field.",
                "evidence": "1216 common records and 4864 total OHLC exact matches in trust threshold recalibration.",
            }
            for field in TRUSTED_OHLC_FIELDS
        }
        | {
            "volume": {
                "trust_status": "production_candidate",
                "consumption_preview_allowed": False,
                "reason": "Volume is useful operational evidence, but current trusted preview is scoped to OHLC only.",
            }
        }
        | {
            field: {
                "trust_status": "ready_for_trusted_candidate_limited",
                "consumption_preview_allowed": False,
                "reason": "Field lacks consistent secondary-source coverage or definition agreement in current normalized sample.",
            }
            for field in LIMITED_FIELDS
        },
        "dataset_level_trust": {
            "status": "ready_for_trusted_candidate",
            "reason": "The full daily table has strong source-level evidence, but only OHLC is consumable as trusted_candidate preview.",
        },
        "entity_level_trust": {
            "status": "trusted_candidate_preview_for_controlled_watchlist",
            "entity_mapping_required": True,
            "unmapped_entity_behavior": "exclude_from_trusted_candidate_preview",
        },
        "preview_layer_policy": {
            "formal_trusted_consumption": False,
            "preview_only": True,
            "do_not_promote_whole_table": True,
            "limited_fields_must_emit_warning": True,
        },
        "selector_evidence": {
            "input_common_records": recalibration.get("summary", {}).get("input_common_records"),
            "selector_included_records": len(preview_rows),
            "selector_excluded_records": len(excluded_rows),
            "ohlc_exact_match_count": recalibration.get("summary", {}).get("ohlc_exact_match_count"),
            "expected_ohlc_match_count": recalibration.get("summary", {}).get("expected_ohlc_match_count"),
        },
    }


def build_limited_field_review() -> dict[str, Any]:
    return {
        "generated_at": utc_now(),
        "limited_fields": {
            "amount": {
                "current_status": "ready_for_trusted_candidate_limited",
                "warning": "Excluded from trusted_candidate preview.",
                "reason": "AKShare Tencent normalized sample does not provide consistent amount coverage.",
            },
            "turnover_rate": {
                "current_status": "ready_for_trusted_candidate_limited",
                "warning": "Excluded from trusted_candidate preview.",
                "reason": "Secondary source support/definition agreement is not available in the current controlled sample.",
            },
            "pct_change": {
                "current_status": "ready_for_trusted_candidate_limited",
                "warning": "Excluded from trusted_candidate preview.",
                "reason": "Needs deterministic source definition or formula validation and tolerance policy.",
            },
            "preclose": {
                "current_status": "ready_for_trusted_candidate_limited",
                "warning": "Excluded from trusted_candidate preview.",
                "reason": "Needs secondary-source coverage or documented derivation policy across corporate action adjustment modes.",
            },
        },
        "formal_trusted_consumption": False,
    }


def build_packet_input(contract: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows_by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        rows_by_symbol.setdefault(str(row.get("symbol")), []).append(row)
    latest_by_symbol = {
        symbol: sorted(symbol_rows, key=lambda row: row["trade_date"])[-1]
        for symbol, symbol_rows in rows_by_symbol.items()
        if symbol_rows
    }
    return {
        "generated_at": utc_now(),
        "can_consume_trusted_candidate_fields": True,
        "formal_trusted_consumption": False,
        "trusted_candidate_fields": TRUSTED_OHLC_FIELDS,
        "limited_fields": LIMITED_FIELDS,
        "dataset_id": contract["scope"]["dataset_id"],
        "time_window": contract["scope"]["time_window"],
        "latest_trusted_ohlc_by_symbol": latest_by_symbol,
        "packet_limitation_note": "Analysis packets may cite OHLC as trusted_candidate preview evidence; limited fields must remain warnings/candidate context.",
    }


def build_statistical_input(contract: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "generated_at": utc_now(),
        "field_level_trusted_candidate_preview_available": True,
        "formal_trusted_consumption": False,
        "dataset_id": contract["scope"]["dataset_id"],
        "trusted_candidate_fields": TRUSTED_OHLC_FIELDS,
        "limited_fields": LIMITED_FIELDS,
        "preview_record_count": len(rows),
        "symbol_count": len(contract["scope"]["symbols"]),
        "time_window": contract["scope"]["time_window"],
        "statistical_report_usage": "Allowed to summarize OHLC as trusted_candidate preview; amount, turnover_rate, pct_change, and preclose must be warning-only.",
    }


def build_field_upgrade_path() -> dict[str, Any]:
    return {
        "generated_at": utc_now(),
        "fields": {
            "amount": {
                "current_status": "ready_for_trusted_candidate_limited",
                "required_evidence_to_upgrade": [
                    "secondary source amount coverage",
                    "unit normalization evidence",
                    "cross-source tolerance policy",
                    "QA pass over expanded watchlist",
                ],
            },
            "turnover_rate": {
                "current_status": "ready_for_trusted_candidate_limited",
                "required_evidence_to_upgrade": [
                    "documented source definition",
                    "secondary source coverage",
                    "reasonable range QA",
                    "expanded cross-source validation",
                ],
            },
            "pct_change": {
                "current_status": "ready_for_trusted_candidate_limited",
                "required_evidence_to_upgrade": [
                    "deterministic formula or upstream definition",
                    "preclose/adjustment policy",
                    "precision tolerance rule",
                    "mismatch review queue closure",
                ],
            },
            "preclose": {
                "current_status": "ready_for_trusted_candidate_limited",
                "required_evidence_to_upgrade": [
                    "secondary source coverage or audited derivation from previous close",
                    "corporate action adjustment mode policy",
                    "cross-source validation after ex-right/ex-dividend cases",
                ],
            },
        },
    }


def build_dashboard_summary(contract: dict[str, Any], limited_review: dict[str, Any], field_upgrade_path: dict[str, Any]) -> dict[str, Any]:
    return {
        "generated_at": utc_now(),
        "panel_title": "Field-Level Trusted Candidate Preview",
        "selector_name": "Trusted Candidate Preview Selector",
        "ohlc_trusted_candidate_fields": TRUSTED_OHLC_FIELDS,
        "limited_fields": list(limited_review["limited_fields"].keys()),
        "preview_record_count": contract["selector_evidence"]["selector_included_records"],
        "symbol_count": len(contract["scope"]["symbols"]),
        "time_window": contract["scope"]["time_window"],
        "formal_trusted_consumption": False,
        "upgrade_path_fields": list(field_upgrade_path["fields"].keys()),
        "dashboard_markers": [
            "Field-Level Trusted Candidate Preview",
            "Trusted Candidate Preview Selector",
            "OHLC Trusted Candidate Fields",
            "Limited Field Review",
            "Formal Trusted Consumption Off",
        ],
    }


def write_docs(contract: dict[str, Any], preview_count: int, limited_review: dict[str, Any], field_upgrade_path: dict[str, Any]) -> None:
    DOC_CONTRACT.write_text(
        f"""# Field-Level Trust Contract

Generated: {contract['generated_at']}

This contract keeps trust scoped to dataset, field, source, entity, and time window. It does not open formal trusted consumption.

- Dataset: `{contract['scope']['dataset_id']}`
- Trusted candidate preview fields: `{', '.join(TRUSTED_OHLC_FIELDS)}`
- Limited fields: `{', '.join(LIMITED_FIELDS)}`
- Preview records: `{preview_count}`
- Formal trusted consumption: `false`

The full daily table is not trusted as a whole. Only OHLC fields that exact-match across Baostock and AKShare Tencent are consumable in preview.
""",
        encoding="utf-8",
    )
    DOC_SELECTOR.write_text(
        f"""# Trusted Candidate Preview Selector

The selector reads the controlled Baostock and AKShare Tencent normalized samples and emits only field-level trusted candidate OHLC rows.

Selection rule:

1. Match on `symbol + trade_date`.
2. Require exact match for `open`, `high`, `low`, and `close`.
3. Export only OHLC plus provenance and field trust metadata.
4. Exclude `amount`, `turnover_rate`, `pct_change`, and `preclose` from trusted candidate preview.
5. Keep formal trusted consumption off.

Output path: `runtime/field_level_trusted_preview/a_share_etf_ohlc_trusted_candidate_preview.jsonl`.
""",
        encoding="utf-8",
    )
    DOC_A_SHARE.write_text(
        f"""# A-Share / ETF Field-Level Trust Preview

OHLC is the first trusted candidate preview data product for the controlled A-share / ETF watchlist.

Limited field upgrade path:

```json
{json.dumps(field_upgrade_path, ensure_ascii=False, indent=2)}
```

Limited field review:

```json
{json.dumps(limited_review, ensure_ascii=False, indent=2)}
```
""",
        encoding="utf-8",
    )


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def values_equal(left: Any, right: Any) -> bool:
    try:
        return abs(float(left) - float(right)) <= 0.000001
    except (TypeError, ValueError):
        return left == right


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


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""), encoding="utf-8")


if __name__ == "__main__":
    result = run_field_level_trusted_preview()
    print(json.dumps(result, ensure_ascii=False, indent=2))
