from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.modules.financial_report.services import data_connector_phase2_service as phase2  # noqa: E402


OUTPUT_ROOT = PROJECT_ROOT / "runtime" / "analysis_packet_builder_v2"
PHASE6_ROOT = PROJECT_ROOT / "runtime" / "frdata_connectors_phase6"
FIELD_TRUST_PREVIEW_ROOT = PROJECT_ROOT / "runtime" / "field_level_trusted_preview"
DOC_REPORT = PROJECT_ROOT / "docs" / "ANALYSIS_PACKET_BUILDER_V2_REPORT.md"
DOC_PROMPT = PROJECT_ROOT / "docs" / "GPT_WEB_PROMPT_TEMPLATE_V2.md"
DOC_CONTRACT = PROJECT_ROOT / "docs" / "ANALYSIS_PACKET_DATA_CONTRACT.md"
DOC_INGESTION_SCHEMA = PROJECT_ROOT / "docs" / "GPT_REPORT_INGESTION_SCHEMA.md"
TARGETS = ["600519", "000001"]


def run_builder_v2() -> dict[str, Any]:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    context = phase2.load_context()
    source_context = load_source_context()
    packets = []
    for target in TARGETS:
        packet_set = build_packet_set(
            target_symbol=target,
            market="A_SHARE",
            as_of_date=date.today().isoformat(),
            analysis_scope="daily_update",
            lookback_days=30,
            include_macro=True,
            include_commodity=True,
            include_financial_report_metadata=True,
            include_previous_reports=True,
            include_candidate_notes=True,
            source_context=source_context,
        )
        target_root = OUTPUT_ROOT / target
        target_root.mkdir(parents=True, exist_ok=True)
        write_json(target_root / "analysis_packet.json", packet_set["analysis_packet"])
        (target_root / "analysis_packet.md").write_text(render_packet_md(packet_set["analysis_packet"]), encoding="utf-8")
        (target_root / "copy_to_gpt_prompt.md").write_text(render_prompt(packet_set["analysis_packet"]), encoding="utf-8")
        write_json(target_root / "packet_manifest.json", packet_set["packet_manifest"])
        packets.append(packet_set["packet_manifest"])

    summary = {
        "generated_at": utc_now(),
        "builder_version": "analysis_packet_builder_v2_real_data_integration",
        "packet_count": len(packets),
        "targets": TARGETS,
        "packets": packets,
        "data_sources": {
            "frdata_connectors_metadata_index": str(PHASE6_ROOT / "frdata_connectors_metadata.sqlite"),
            "staging_v2": str(PHASE6_ROOT / "consumption_grade_staging_v2.json"),
            "connector_run_results": str(PHASE6_ROOT / "connector_run_results.json"),
        },
        "no_openai_api_called": True,
        "parse_lab_affected": False,
        "trusted_consumption_affected": False,
        "formal_investment_advice_generated": False,
    }
    write_json(OUTPUT_ROOT / "builder_run_summary.json", summary)
    DOC_REPORT.write_text(render_builder_report(summary), encoding="utf-8")
    DOC_PROMPT.write_text(render_prompt_template_doc(), encoding="utf-8")
    DOC_CONTRACT.write_text(render_data_contract_doc(), encoding="utf-8")
    DOC_INGESTION_SCHEMA.write_text(render_ingestion_schema_doc(), encoding="utf-8")
    sample_report = build_sample_final_report_json(summary["packets"][0])
    parsed = parse_final_report_json(sample_report)
    write_json(OUTPUT_ROOT / "sample_ingested_report_validation.json", parsed)
    return summary


def load_source_context() -> dict[str, Any]:
    connector_runs = read_json(PHASE6_ROOT / "connector_run_results.json")
    staging = read_json(PHASE6_ROOT / "consumption_grade_staging_v2.json")
    mismatch = read_json(PHASE6_ROOT / "a_share_daily_mismatch_review.json")
    metadata = read_json(PHASE6_ROOT / "metadata_index_summary.json")
    field_trust_preview = read_json(FIELD_TRUST_PREVIEW_ROOT / "analysis_packet_trusted_preview_input.json")
    return {
        "connector_runs": connector_runs,
        "staging": staging,
        "mismatch": mismatch,
        "metadata": metadata,
        "field_trust_preview": field_trust_preview,
        "run_by_source": {item["source_id"]: item for item in connector_runs.get("items", [])},
        "staging_by_source": build_staging_by_source(staging),
    }


def build_packet_set(
    target_symbol: str,
    market: str,
    as_of_date: str,
    analysis_scope: str,
    lookback_days: int,
    include_macro: bool,
    include_commodity: bool,
    include_financial_report_metadata: bool,
    include_previous_reports: bool,
    include_candidate_notes: bool,
    source_context: dict[str, Any],
) -> dict[str, Any]:
    data_snapshot_id = "snapshot_" + hash_short(f"{target_symbol}|{as_of_date}|{analysis_scope}")
    packet_id = "packet_" + hash_short(f"{data_snapshot_id}|analysis_packet_v2")
    market_summary = build_market_daily_summary(target_symbol, source_context, lookback_days)
    macro_summary = build_macro_summary(source_context) if include_macro else insufficient("macro_summary", "disabled_by_packet_request")
    commodity_summary = build_commodity_summary(source_context) if include_commodity else insufficient("commodity_summary", "disabled_by_packet_request")
    report_metadata = build_financial_report_metadata(target_symbol, source_context) if include_financial_report_metadata else insufficient("financial_report_metadata", "disabled_by_packet_request")
    previous_reports = build_previous_reports_placeholder(target_symbol) if include_previous_reports else []
    packet = {
        "packet_id": packet_id,
        "data_snapshot_id": data_snapshot_id,
        "target_symbol": target_symbol,
        "market": market,
        "as_of_date": as_of_date,
        "analysis_scope": analysis_scope,
        "lookback_days": lookback_days,
        "requested_includes": {
            "macro": include_macro,
            "commodity": include_commodity,
            "financial_report_metadata": include_financial_report_metadata,
            "previous_reports": include_previous_reports,
            "candidate_notes": include_candidate_notes,
        },
        "data_layer_legend": data_layer_legend(),
        "source_layers": build_source_layers(source_context),
        "field_level_trusted_candidate_preview": source_context.get("field_trust_preview", {
            "can_consume_trusted_candidate_fields": False,
            "formal_trusted_consumption": False,
        }),
        "market_daily_summary": market_summary,
        "macro_summary": macro_summary,
        "commodity_summary": commodity_summary,
        "financial_report_metadata": report_metadata,
        "previous_reports_and_forecasts": previous_reports,
        "candidate_notes": build_candidate_notes(source_context) if include_candidate_notes else [],
        "insufficient_evidence": collect_insufficient_evidence([market_summary, macro_summary, commodity_summary, report_metadata, {"items": previous_reports}]),
        "guardrails": {
            "no_openai_api_called": True,
            "candidate_data_not_trusted_facts": True,
            "formal_trusted_consumption_unchanged": True,
            "no_investment_advice_generated": True,
            "as_of_date_boundary": as_of_date,
        },
    }
    manifest = {
        "packet_id": packet_id,
        "data_snapshot_id": data_snapshot_id,
        "target_symbol": target_symbol,
        "market": market,
        "as_of_date": as_of_date,
        "analysis_scope": analysis_scope,
        "created_at": utc_now(),
        "paths": {
            "analysis_packet_json": str(OUTPUT_ROOT / target_symbol / "analysis_packet.json"),
            "analysis_packet_md": str(OUTPUT_ROOT / target_symbol / "analysis_packet.md"),
            "copy_to_gpt_prompt": str(OUTPUT_ROOT / target_symbol / "copy_to_gpt_prompt.md"),
            "packet_manifest": str(OUTPUT_ROOT / target_symbol / "packet_manifest.json"),
        },
        "source_counts": {
            "source_layers": len(packet["source_layers"]),
            "insufficient_evidence": len(packet["insufficient_evidence"]),
        },
        "no_openai_api_called": True,
        "formal_trusted_consumption": False,
    }
    return {"analysis_packet": packet, "packet_manifest": manifest}


def build_market_daily_summary(target_symbol: str, source_context: dict[str, Any], lookback_days: int) -> dict[str, Any]:
    run_by_source = source_context["run_by_source"]
    baostock_run = run_by_source.get("baostock_daily", {})
    akshare_run = run_by_source.get("akshare_tencent_daily", {})
    baostock_records = filter_symbol_records(read_jsonl(baostock_run.get("normalized_output_path", "")), target_symbol)
    akshare_records = filter_symbol_records(read_jsonl(akshare_run.get("normalized_output_path", "")), target_symbol)
    primary_records = baostock_records[-lookback_days:]
    if len(primary_records) < 2:
        return insufficient("market_daily_summary", f"not enough Baostock records for {target_symbol}")
    latest = primary_records[-1]
    previous = primary_records[-2]
    closes = [record["close"] for record in primary_records if is_number(record.get("close"))]
    volumes = [record["volume"] for record in primary_records if is_number(record.get("volume"))]
    summary = {
        "status": "available_candidate_staging",
        "target_symbol": target_symbol,
        "latest_trade_date": latest.get("trade_date"),
        "latest_close": latest.get("close"),
        "previous_close": previous.get("close"),
        "daily_pct_change": calc_pct_change(previous.get("close"), latest.get("close")),
        "price_change_5d": price_change_for_window(closes, 5),
        "price_change_20d": price_change_for_window(closes, 20),
        "price_change_60d": insufficient("price_change_60d", f"only {len(closes)} close observations available"),
        "volume_average_5d": average_last(volumes, 5),
        "volume_average_20d": average_last(volumes, 20),
        "high_low_range": {
            "window_days": len(primary_records),
            "high": max(record["high"] for record in primary_records if is_number(record.get("high"))),
            "low": min(record["low"] for record in primary_records if is_number(record.get("low"))),
        },
        "abnormal_volume_signal": abnormal_volume_signal(volumes),
        "price_trend_note": price_trend_note(closes),
        "source_consistency_note": build_source_consistency_note(target_symbol, source_context),
        "field_level_trusted_candidate_preview": build_symbol_field_trust_preview(target_symbol, source_context),
        "baostock_vs_akshare_tencent": {
            "baostock_record_count": len(baostock_records),
            "akshare_tencent_record_count": len(akshare_records),
            "cross_source_note": "OHLC cross-source values are exact-match in Phase 6. One pct_change mismatch exists for 300750 only.",
        },
        "data_items": [
            source_layer_item("baostock_daily", baostock_run, "market_daily_candidate_staging", "Primary operational source; candidate-only."),
            source_layer_item("akshare_tencent_daily", akshare_run, "market_daily_secondary_candidate_staging", "Secondary candidate source; amount/turnover/trade_status/ST unsupported."),
            {
                "source_id": "baostock_daily+akshare_tencent_daily",
                "source_name": "Baostock / AKShare Tencent cross-source validation",
                "source_type": "cross_source_validation",
                "quality_status": "quality_passed",
                "trust_status": "cross_validated_candidate",
                "staging_status": "cross_validated_candidate",
                "retrieved_at": source_context["connector_runs"].get("generated_at"),
                "raw_reference": "",
                "normalized_reference": str(PHASE6_ROOT / "a_share_daily_mismatch_review.json"),
                "limitation_note": "Cross-validated candidate only; not a trusted final fact.",
            },
        ],
        "candidate_only": True,
        "formal_trusted_consumption": False,
    }
    return summary


def build_symbol_field_trust_preview(target_symbol: str, source_context: dict[str, Any]) -> dict[str, Any]:
    preview = source_context.get("field_trust_preview") or {}
    latest_by_symbol = preview.get("latest_trusted_ohlc_by_symbol", {})
    latest = latest_by_symbol.get(target_symbol)
    if not latest:
        return {
            "status": "insufficient_evidence",
            "reason": f"no field-level trusted candidate OHLC preview row for {target_symbol}",
            "formal_trusted_consumption": False,
        }
    return {
        "status": "available_trusted_candidate_preview",
        "trusted_candidate_fields": preview.get("trusted_candidate_fields", []),
        "limited_fields": preview.get("limited_fields", []),
        "latest_trade_date": latest.get("trade_date"),
        "latest_ohlc": {field: latest.get(field) for field in preview.get("trusted_candidate_fields", [])},
        "source_pair": latest.get("source_pair", []),
        "limitation_note": preview.get("packet_limitation_note"),
        "formal_trusted_consumption": False,
    }


def build_macro_summary(source_context: dict[str, Any]) -> dict[str, Any]:
    run_by_source = source_context["run_by_source"]
    items = []
    for source_id in ["bls_public_api", "treasury_fiscaldata", "fred_public_csv"]:
        run = run_by_source.get(source_id)
        if not run:
            items.append(insufficient(source_id, "source not present in Phase 6 run log"))
            continue
        records = read_jsonl(run.get("normalized_output_path", ""))
        latest = latest_record(records)
        if run.get("status") != "success" or not latest:
            items.append(source_layer_item(source_id, run, run.get("staging_status", "blocked"), "No usable latest observation in Phase 6; keep as insufficient_evidence."))
            continue
        items.append(
            {
                **source_layer_item(source_id, run, run.get("staging_status", "consumption_grade_candidate"), "Official/authoritative candidate after quality gate; not formal trusted consumption."),
                "frequency": infer_frequency(source_id),
                "latest_period": latest.get("date") or latest.get("period"),
                "latest_metric": latest.get("metric_name") or latest.get("series_id") or latest.get("metric"),
                "latest_value": latest.get("value"),
                "unit": latest.get("unit"),
            }
        )
    return {"status": "available_with_gaps", "items": items}


def build_commodity_summary(source_context: dict[str, Any]) -> dict[str, Any]:
    run = source_context["run_by_source"].get("world_bank_pink_sheet")
    if not run:
        return insufficient("commodity_summary", "World Bank Pink Sheet source missing")
    records = read_jsonl(run.get("normalized_output_path", ""))
    latest_by_metric = {}
    for record in records:
        metric = record.get("metric_name") or record.get("commodity") or record.get("series_id")
        if not metric:
            continue
        if metric not in latest_by_metric or str(record.get("date", "")) > str(latest_by_metric[metric].get("date", "")):
            latest_by_metric[metric] = record
    items = []
    for metric, record in sorted(latest_by_metric.items())[:6]:
        items.append(
            {
                **source_layer_item("world_bank_pink_sheet", run, run.get("staging_status", "consumption_grade_candidate"), "World Bank commodity sample; candidate for real external trust resolution."),
                "frequency": "monthly",
                "latest_period": record.get("date") or record.get("period"),
                "metric_name": metric,
                "latest_value": record.get("value"),
                "unit": record.get("unit"),
            }
        )
    return {"status": "available_candidate", "items": items or [insufficient("commodity_summary", "no commodity observations parsed")]}


def build_financial_report_metadata(target_symbol: str, source_context: dict[str, Any]) -> dict[str, Any]:
    run = source_context["run_by_source"].get("cninfo_disclosure")
    if not run:
        return insufficient("financial_report_metadata", "CNINFO discovery source missing")
    records = [record for record in read_jsonl(run.get("normalized_output_path", "")) if str(record.get("symbol")) == target_symbol]
    if not records:
        return insufficient("financial_report_metadata", f"no CNINFO discovery metadata for {target_symbol} in current small sample")
    items = []
    for record in records:
        items.append(
            {
                **source_layer_item("cninfo_disclosure", run, run.get("staging_status", "consumption_grade_candidate"), "Discovery/PDF smoke metadata only; report content not reparsed in this phase."),
                "report_type": infer_report_type(record.get("report_title", "")),
                "report_period": infer_report_period(record.get("report_title", "")),
                "announcement_date": normalize_cninfo_date(record.get("date")),
                "source_url": record.get("download_url"),
                "pdf_path": record.get("pdf_path"),
                "checksum": record.get("checksum"),
                "parse_status": "not_reparsed_in_analysis_packet_builder_v2",
            }
        )
    return {"status": "available_metadata_only", "items": items}


def build_previous_reports_placeholder(target_symbol: str) -> list[dict[str, Any]]:
    reports_root = PROJECT_ROOT / "runtime" / "analysis_reports"
    if not reports_root.exists():
        return [insufficient("previous_reports", f"no ingested report history directory for {target_symbol}")]
    matches = list(reports_root.glob(f"*{target_symbol}*"))
    if not matches:
        return [insufficient("previous_reports", f"no prior ingested report found for {target_symbol}")]
    return [{"status": "available", "path": str(path)} for path in matches]


def build_source_layers(source_context: dict[str, Any]) -> list[dict[str, Any]]:
    layers = []
    for item in source_context["staging"].get("items", []):
        run = source_context["run_by_source"].get(item.get("source_id"), {})
        layers.append(
            {
                "source_id": item.get("source_id"),
                "source_name": source_name(item.get("source_id")),
                "source_type": item.get("data_category"),
                "quality_status": item.get("quality_check_status"),
                "trust_status": item.get("trust_status"),
                "staging_status": item.get("staging_status"),
                "retrieved_at": run.get("retrieved_at") or source_context["staging"].get("generated_at"),
                "raw_reference": item.get("raw_output_path") or run.get("raw_output_path", ""),
                "normalized_reference": item.get("normalized_output_path") or run.get("normalized_output_path", ""),
                "limitation_note": limitation_note(item.get("staging_status"), item.get("source_id")),
            }
        )
    return layers


def data_layer_legend() -> dict[str, str]:
    return {
        "trusted_by_real_external_candidate": "Official or authoritative source candidate after quality gate; still must pass FR trust resolution before formal consumption.",
        "market_daily_candidate_staging": "Primary A-share daily candidate source, not trusted.",
        "market_daily_secondary_candidate_staging": "Secondary A-share daily candidate source, not trusted.",
        "cross_validated_candidate": "Multiple candidate sources agree within rule/tolerance; still not a trusted final fact.",
        "needs_review_candidate": "Requires human or rule review before any downstream use.",
        "blocked": "Not eligible for packet consumption except as a caveat.",
        "not_used_in_current_pipeline": "Deferred source excluded from current pipeline.",
        "insufficient_evidence": "Data missing or too thin; analysis must state insufficient evidence.",
    }


def build_candidate_notes(source_context: dict[str, Any]) -> list[str]:
    return [
        "Baostock and AKShare Tencent market data remain candidate/staging only.",
        "Cross-source OHLC consistency improves confidence but does not create formal trusted facts.",
        "Official macro/commodity sources are trusted_by_real_external_candidate after quality pass, not formal trusted consumption.",
        f"Mismatch review: {source_context['mismatch']['summary'].get('mismatch_count', 0)} item(s), primary cause: {source_context['mismatch']['summary'].get('primary_cause')}.",
    ]


def collect_insufficient_evidence(sections: list[Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if value.get("status") == "insufficient_evidence":
                found.append(value)
            for nested in value.values():
                walk(nested)
        elif isinstance(value, list):
            for nested in value:
                walk(nested)

    for section in sections:
        walk(section)
    return found


def parse_final_report_json(raw_report_text: str) -> dict[str, Any]:
    match = re.search(r"FINAL_REPORT_JSON\s*```json\s*(\{.*?\})\s*```", raw_report_text, flags=re.DOTALL)
    if not match:
        return {"schema_valid": False, "error": "FINAL_REPORT_JSON fenced json block not found"}
    payload = json.loads(match.group(1))
    required = {
        "packet_id",
        "data_snapshot_id",
        "target_symbol",
        "as_of_date",
        "analysis_scope",
        "key_assumptions",
        "investment_view",
        "forecast_items",
        "risk_items",
        "watchlist_signals",
        "confidence",
        "next_review_date",
        "insufficient_evidence_items",
        "candidate_data_usage_note",
    }
    missing = sorted(required - set(payload))
    return {
        "schema_valid": not missing,
        "missing_fields": missing,
        "parsed_report": payload,
        "raw_report_text_preserved": True,
        "created_at": utc_now(),
    }


def build_sample_final_report_json(manifest: dict[str, Any]) -> str:
    payload = {
        "packet_id": manifest["packet_id"],
        "data_snapshot_id": manifest["data_snapshot_id"],
        "target_symbol": manifest["target_symbol"],
        "as_of_date": manifest["as_of_date"],
        "analysis_scope": manifest["analysis_scope"],
        "key_assumptions": [],
        "investment_view": "insufficient_evidence",
        "forecast_items": [
            {
                "forecast_item": "sample_placeholder",
                "target_metric": "close",
                "forecast_horizon": "not_forecasted",
                "expected_direction": "insufficient_evidence",
                "expected_range": None,
                "confidence": "low",
                "thesis": "Schema validation sample only.",
                "risk_trigger": "candidate data cannot be used as trusted fact",
                "review_date": manifest["as_of_date"],
                "actual_value_later": None,
                "backtest_result": None,
                "revision_note": "",
            }
        ],
        "risk_items": [],
        "watchlist_signals": [],
        "confidence": "low",
        "next_review_date": (date.fromisoformat(manifest["as_of_date"]) + timedelta(days=7)).isoformat(),
        "insufficient_evidence_items": ["sample validation report only"],
        "candidate_data_usage_note": "Candidate data was not treated as trusted facts.",
    }
    return "# Sample Report\n\nFINAL_REPORT_JSON\n```json\n" + json.dumps(payload, ensure_ascii=False, indent=2) + "\n```\n"


def render_prompt(packet: dict[str, Any]) -> str:
    compact_packet = json.dumps(packet, ensure_ascii=False, indent=2)
    return f"""# GPT Web Analysis Prompt v2

You are helping analyze a FinancialResearch data packet. Use only the information inside the packet below.

Rules:
- Treat `{packet['as_of_date']}` as the information boundary. Do not use future information.
- Candidate/staging data is not trusted final fact.
- Mark `needs_review_candidate` and `insufficient_evidence` explicitly.
- Do not invent missing financial report facts, valuation facts, or future outcomes.
- If evidence is insufficient, write `insufficient_evidence`.
- This is a research draft, not formal investment advice.

Output:
1. Markdown analysis report.
2. A `FINAL_REPORT_JSON` fenced block with valid JSON.

The JSON must include:
- packet_id
- data_snapshot_id
- target_symbol
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

Packet:
```json
{compact_packet}
```
"""


def render_packet_md(packet: dict[str, Any]) -> str:
    return f"""# Analysis Packet v2

Packet ID: `{packet['packet_id']}`

Target: `{packet['target_symbol']}`

As-of date: `{packet['as_of_date']}`

Scope: `{packet['analysis_scope']}`

## Market Daily Summary

```json
{json.dumps(packet['market_daily_summary'], ensure_ascii=False, indent=2)}
```

## Macro Summary

```json
{json.dumps(packet['macro_summary'], ensure_ascii=False, indent=2)}
```

## Commodity Summary

```json
{json.dumps(packet['commodity_summary'], ensure_ascii=False, indent=2)}
```

## Financial Report Metadata

```json
{json.dumps(packet['financial_report_metadata'], ensure_ascii=False, indent=2)}
```

## Insufficient Evidence

```json
{json.dumps(packet['insufficient_evidence'], ensure_ascii=False, indent=2)}
```
"""


def render_builder_report(summary: dict[str, Any]) -> str:
    return f"""# Analysis Packet Builder v2 Report

Generated: {summary['generated_at']}

## Result

- Packet count: {summary['packet_count']}
- Targets: {', '.join(summary['targets'])}
- OpenAI API called: false
- Formal trusted consumption affected: false

## Data Sources

- FRDataConnectors metadata index: `{summary['data_sources']['frdata_connectors_metadata_index']}`
- Staging v2: `{summary['data_sources']['staging_v2']}`
- Connector run results: `{summary['data_sources']['connector_run_results']}`

## Outputs

```json
{json.dumps(summary['packets'], ensure_ascii=False, indent=2)}
```
"""


def render_prompt_template_doc() -> str:
    return """# GPT Web Prompt Template v2

The generated prompt is stored per target as `copy_to_gpt_prompt.md`.

Key requirements enforced by the template:

- Use only packet information.
- Treat `as_of_date` as the information boundary.
- Candidate/staging data cannot be treated as trusted final fact.
- `needs_review_candidate` and `insufficient_evidence` must be visible.
- Output a Markdown report plus a valid `FINAL_REPORT_JSON` block.
- Do not call any API from FR; the user copies the prompt into ChatGPT Web manually.
"""


def render_data_contract_doc() -> str:
    return """# Analysis Packet Data Contract

## Required Packet Fields

- `packet_id`
- `data_snapshot_id`
- `target_symbol`
- `market`
- `as_of_date`
- `analysis_scope`
- `data_layer_legend`
- `source_layers`
- `market_daily_summary`
- `macro_summary`
- `commodity_summary`
- `financial_report_metadata`
- `previous_reports_and_forecasts`
- `candidate_notes`
- `insufficient_evidence`
- `guardrails`

## Source Layer Fields

Every source layer item must preserve:

- `source_id`
- `source_name`
- `source_type`
- `quality_status`
- `trust_status`
- `staging_status`
- `retrieved_at`
- `raw_reference`
- `normalized_reference`
- `limitation_note`

## Trust Boundary

`trusted_by_real_external_candidate`, `market_daily_candidate_staging`, and `cross_validated_candidate` are not formal trusted facts. Formal trusted consumption remains unchanged in this phase.
"""


def render_ingestion_schema_doc() -> str:
    return """# GPT Report Ingestion Schema

## Raw Input

The user pastes the complete GPT Web report into FR. FR preserves:

- `raw_report_text`
- `packet_id`
- `data_snapshot_id`
- `created_at`
- `report_version`

## FINAL_REPORT_JSON

The pasted report must include a fenced JSON block after `FINAL_REPORT_JSON` with:

- `packet_id`
- `data_snapshot_id`
- `target_symbol`
- `as_of_date`
- `analysis_scope`
- `key_assumptions`
- `investment_view`
- `forecast_items`
- `risk_items`
- `watchlist_signals`
- `confidence`
- `next_review_date`
- `insufficient_evidence_items`
- `candidate_data_usage_note`

## Forecast / Backtest Fields

Each forecast item stores:

- `forecast_item`
- `target_metric`
- `forecast_horizon`
- `expected_direction`
- `expected_range`
- `confidence`
- `thesis`
- `risk_trigger`
- `review_date`
- `actual_value_later`
- `backtest_result`
- `revision_note`

## Candidate Data Rule

Reports must not treat candidate/staging data as trusted final facts. Any use of candidate data must be explained in `candidate_data_usage_note`.
"""


def source_layer_item(source_id: str, run: dict[str, Any], staging_status: str, note: str) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "source_name": source_name(source_id),
        "source_type": run.get("data_category", ""),
        "quality_status": run.get("quality_check_status", ""),
        "trust_status": run.get("trust_status", ""),
        "staging_status": staging_status,
        "retrieved_at": run.get("retrieved_at", ""),
        "raw_reference": run.get("raw_output_path", ""),
        "normalized_reference": run.get("normalized_output_path", ""),
        "limitation_note": note,
    }


def build_staging_by_source(staging: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for item in staging.get("items", []):
        result.setdefault(item.get("source_id", ""), []).append(item)
    return result


def read_json(path: Path | str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_jsonl(path_text: str) -> list[dict[str, Any]]:
    if not path_text:
        return []
    path = Path(path_text)
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def filter_symbol_records(records: list[dict[str, Any]], symbol: str) -> list[dict[str, Any]]:
    return sorted([record for record in records if str(record.get("symbol")) == symbol], key=lambda item: item.get("trade_date", ""))


def latest_record(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not records:
        return None
    return sorted(records, key=lambda item: str(item.get("date") or item.get("period") or item.get("trade_date") or ""))[-1]


def calc_pct_change(previous: Any, latest: Any) -> float | dict[str, Any]:
    if not is_number(previous) or not is_number(latest) or float(previous) == 0:
        return insufficient("daily_pct_change", "previous/latest close unavailable")
    return round((float(latest) - float(previous)) / float(previous) * 100, 4)


def price_change_for_window(closes: list[float], window: int) -> float | dict[str, Any]:
    if len(closes) <= window:
        return insufficient(f"price_change_{window}d", f"only {len(closes)} observations available")
    start = float(closes[-window - 1])
    end = float(closes[-1])
    if start == 0:
        return insufficient(f"price_change_{window}d", "starting close is zero")
    return round((end - start) / start * 100, 4)


def average_last(values: list[float], window: int) -> float | dict[str, Any]:
    if len(values) < window:
        return insufficient(f"volume_average_{window}d", f"only {len(values)} observations available")
    return round(sum(float(value) for value in values[-window:]) / window, 4)


def abnormal_volume_signal(volumes: list[float]) -> dict[str, Any]:
    avg20 = average_last(volumes, 20)
    if isinstance(avg20, dict) or not volumes:
        return insufficient("abnormal_volume_signal", "insufficient volume observations")
    latest = float(volumes[-1])
    ratio = latest / float(avg20) if avg20 else None
    return {
        "latest_volume": latest,
        "volume_average_20d": avg20,
        "latest_to_20d_avg_ratio": round(ratio, 4) if ratio is not None else None,
        "signal": "high_volume" if ratio and ratio >= 1.5 else "normal_or_unflagged",
    }


def price_trend_note(closes: list[float]) -> str:
    change5 = price_change_for_window(closes, 5)
    change20 = price_change_for_window(closes, 20)
    if isinstance(change5, dict) or isinstance(change20, dict):
        return "insufficient_evidence for robust trend; short window only."
    if change5 > 0 and change20 > 0:
        return "5d and 20d price changes are both positive in candidate market data."
    if change5 < 0 and change20 < 0:
        return "5d and 20d price changes are both negative in candidate market data."
    return "5d and 20d price changes are mixed in candidate market data."


def build_source_consistency_note(target_symbol: str, source_context: dict[str, Any]) -> str:
    comparisons = [item for item in source_context["mismatch"].get("items", []) if item.get("symbol") == target_symbol]
    if comparisons:
        fields = ", ".join(sorted({item["field_name"] for item in comparisons}))
        return f"{target_symbol} has {len(comparisons)} cross-source mismatch item(s), affecting {fields}; OHLC remains exact-match."
    return f"{target_symbol} has no mismatch item in Phase 6 mismatch review; OHLC cross-source agreement is available."


def insufficient(section: str, reason: str) -> dict[str, Any]:
    return {"status": "insufficient_evidence", "section": section, "reason": reason}


def is_number(value: Any) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def infer_frequency(source_id: str) -> str:
    return {"bls_public_api": "monthly", "treasury_fiscaldata": "daily", "fred_public_csv": "daily_or_monthly"}.get(source_id, "unknown")


def infer_report_type(title: str) -> str:
    if "annual" in title.lower() or "年" in title:
        return "annual_report_candidate"
    return "unknown_report_type"


def infer_report_period(title: str) -> str:
    match = re.search(r"20\d{2}", title)
    return match.group(0) if match else "insufficient_evidence"


def normalize_cninfo_date(value: Any) -> str | None:
    if isinstance(value, int):
        try:
            return datetime.fromtimestamp(value / 1000, tz=timezone.utc).date().isoformat()
        except Exception:
            return None
    return str(value) if value else None


def source_name(source_id: str | None) -> str:
    names = {
        "baostock_daily": "Baostock daily A-share prices",
        "akshare_tencent_daily": "AKShare Tencent alternative daily A-share prices",
        "baostock_daily+akshare_tencent_daily": "Baostock / AKShare Tencent cross-source validation",
        "cninfo_disclosure": "CNINFO disclosure discovery",
        "bls_public_api": "BLS public API",
        "treasury_fiscaldata": "U.S. Treasury FiscalData",
        "sec_edgar_companyfacts": "SEC EDGAR company facts",
        "world_bank_pink_sheet": "World Bank Pink Sheet",
        "fred_public_csv": "FRED public CSV/API",
        "eastmoney_push2his_direct": "Eastmoney push2his direct",
    }
    return names.get(source_id or "", source_id or "")


def limitation_note(staging_status: str | None, source_id: str | None) -> str:
    if staging_status == "consumption_grade_candidate":
        return "Eligible candidate after source/quality checks, but not formal trusted consumption."
    if staging_status == "market_daily_candidate_staging":
        return "Candidate A-share daily source; not trusted."
    if staging_status == "market_daily_secondary_candidate_staging":
        return "Secondary candidate source; use only for comparison/staging."
    if staging_status == "cross_validated_candidate":
        return "Cross-source agreement candidate, not a final fact."
    if staging_status == "needs_review_candidate":
        return "Needs review before any downstream use."
    if staging_status == "blocked":
        return "Blocked by quality/source status."
    if staging_status == "not_used_in_current_pipeline":
        return "Deferred source not used in this packet."
    return f"Candidate layer item from {source_id}."


def hash_short(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> int:
    summary = run_builder_v2()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
