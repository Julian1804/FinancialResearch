from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[5]
OUTPUT_DIR = PROJECT_ROOT / "runtime" / "financial_report" / "data_foundation_phase1"


@dataclass
class AnalysisPacketInput:
    company: str
    ticker: str
    as_of_date: str
    analysis_scope: str
    selected_financial_reports: list[dict[str, Any]] = field(default_factory=list)
    trusted_facts: list[dict[str, Any]] = field(default_factory=list)
    candidate_facts_summary: dict[str, Any] = field(default_factory=dict)
    price_data_placeholder: dict[str, Any] = field(default_factory=dict)
    macro_data_placeholder: dict[str, Any] = field(default_factory=dict)
    asset_class_data_placeholder: dict[str, Any] = field(default_factory=dict)
    sentiment_management_commentary_placeholder: dict[str, Any] = field(default_factory=dict)
    previous_reports_forecasts: list[dict[str, Any]] = field(default_factory=list)


def build_analysis_packet(
    packet_input: AnalysisPacketInput,
    output_dir: Path | str = OUTPUT_DIR,
) -> dict[str, Any]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_at = _utc_now()
    snapshot = _build_data_snapshot(packet_input, generated_at)
    packet_id = _stable_id(
        "analysis_packet",
        packet_input.company,
        packet_input.ticker,
        packet_input.as_of_date,
        generated_at[:19],
    )
    packet_json = {
        "packet_id": packet_id,
        "data_snapshot_id": snapshot["data_snapshot_id"],
        "company": packet_input.company,
        "ticker": packet_input.ticker,
        "as_of_date": packet_input.as_of_date,
        "analysis_scope": packet_input.analysis_scope,
        "generated_at": generated_at,
        "trusted_facts": packet_input.trusted_facts,
        "candidate_facts_summary": packet_input.candidate_facts_summary,
        "selected_financial_reports": packet_input.selected_financial_reports,
        "price_data_placeholder": packet_input.price_data_placeholder,
        "macro_data_placeholder": packet_input.macro_data_placeholder,
        "asset_class_data_placeholder": packet_input.asset_class_data_placeholder,
        "sentiment_management_commentary_placeholder": packet_input.sentiment_management_commentary_placeholder,
        "previous_reports_forecasts": packet_input.previous_reports_forecasts,
        "insufficient_trusted_evidence": _find_packet_gaps(packet_input),
        "candidate_only_policy": "candidate facts are context only and cannot be used as final facts",
        "no_openai_api_called": True,
    }
    markdown_packet = _render_markdown_packet(packet_json)
    prompt = _render_gpt_web_prompt(packet_json, markdown_packet)
    outputs = {
        "packet": packet_json,
        "data_snapshot": snapshot,
        "markdown_packet": markdown_packet,
        "gpt_web_prompt": prompt,
        "output_paths": {
            "packet_json": str(output_dir / f"{packet_id}.analysis_packet.json"),
            "packet_markdown": str(output_dir / f"{packet_id}.analysis_packet.md"),
            "gpt_web_prompt": str(output_dir / f"{packet_id}.gpt_web_prompt.md"),
            "data_snapshot": str(output_dir / f"{snapshot['data_snapshot_id']}.data_snapshot.json"),
        },
    }
    _write_json(Path(outputs["output_paths"]["packet_json"]), packet_json)
    _write_json(Path(outputs["output_paths"]["data_snapshot"]), snapshot)
    Path(outputs["output_paths"]["packet_markdown"]).write_text(markdown_packet, encoding="utf-8")
    Path(outputs["output_paths"]["gpt_web_prompt"]).write_text(prompt, encoding="utf-8")
    return outputs


def ingest_gpt_web_report(
    raw_report_text: str,
    packet_id: str,
    data_snapshot_id: str,
    output_dir: Path | str = OUTPUT_DIR / "ingested_reports",
) -> dict[str, Any]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    parsed = _extract_final_report_json(raw_report_text)
    validation = _validate_report_payload(parsed)
    report_id = _stable_id("gpt_web_report", packet_id, data_snapshot_id, _utc_now()[:19])
    report_version = 1
    record = {
        "report_id": report_id,
        "packet_id": packet_id,
        "data_snapshot_id": data_snapshot_id,
        "report_version": report_version,
        "created_at": _utc_now(),
        "raw_report_text": raw_report_text,
        "final_report_json": parsed,
        "schema_valid": validation["valid"],
        "schema_errors": validation["errors"],
        "forecasts": parsed.get("forecasts", []),
        "assumptions": parsed.get("assumptions", []),
        "risks": parsed.get("risks", []),
        "watchlist_signals": parsed.get("watchlist_signals", []),
        "backtest_ready_forecast_items": [
            _forecast_backtest_record(report_id, index, item)
            for index, item in enumerate(parsed.get("forecasts", []), start=1)
        ],
        "no_openai_api_called": True,
    }
    _write_json(output_dir / f"{report_id}.ingested_report.json", record)
    return record


def build_sample_analysis_packet_and_ingestion(
    output_dir: Path | str = OUTPUT_DIR / "sample",
) -> dict[str, Any]:
    output_dir = Path(output_dir)
    trusted_facts = [
        {
            "fact_id": "sample_sec_companyfacts_revenue_2024",
            "canonical_field": "revenue",
            "value": 391035000000,
            "unit": "USD",
            "currency": "USD",
            "period": "FY2024",
            "source_id": "sec_edgar_companyfacts",
            "source_url": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
            "retrieved_at": "2026-05-18T00:00:00Z",
            "trust_status": "trusted_by_real_external",
            "quality_status": "passed",
            "provenance": {
                "official_source": True,
                "quality_checks": ["numeric_format_ok", "date_format_ok", "unit_currency_check"],
                "sample_data_only": True,
            },
        }
    ]
    packet = build_analysis_packet(
        AnalysisPacketInput(
            company="Apple Inc.",
            ticker="AAPL",
            as_of_date="2025-01-31",
            analysis_scope="Phase 1 sample: trusted facts packet without background API analysis",
            selected_financial_reports=[
                {
                    "source_pdf": "AAPL FY2024 Form 10-K",
                    "source_type": "official_filing",
                    "source_url": "https://www.sec.gov/Archives/edgar/data/320193/",
                    "candidate_only": False,
                }
            ],
            trusted_facts=trusted_facts,
            candidate_facts_summary={
                "candidate_count": 0,
                "policy": "candidate facts are excluded from final conclusions",
            },
            price_data_placeholder={"status": "not_connected_phase1"},
            macro_data_placeholder={"status": "not_connected_phase1"},
            asset_class_data_placeholder={"status": "not_connected_phase1"},
            sentiment_management_commentary_placeholder={"status": "not_connected_phase1"},
        ),
        output_dir=output_dir,
    )
    sample_report_text = _sample_gpt_report(packet["packet"]["packet_id"], packet["packet"]["data_snapshot_id"])
    ingestion = ingest_gpt_web_report(
        sample_report_text,
        packet_id=packet["packet"]["packet_id"],
        data_snapshot_id=packet["packet"]["data_snapshot_id"],
        output_dir=output_dir / "ingested_reports",
    )
    summary = {
        "completed": True,
        "packet_id": packet["packet"]["packet_id"],
        "data_snapshot_id": packet["packet"]["data_snapshot_id"],
        "report_id": ingestion["report_id"],
        "schema_valid": ingestion["schema_valid"],
        "trusted_fact_count": len(trusted_facts),
        "forecast_count": len(ingestion["forecasts"]),
        "output_dir": str(output_dir),
        "no_openai_api_called": True,
    }
    _write_json(output_dir / "sample_analysis_packet_summary.json", summary)
    return {"packet": packet, "ingestion": ingestion, "summary": summary}


def _build_data_snapshot(packet_input: AnalysisPacketInput, generated_at: str) -> dict[str, Any]:
    payload = {
        "company": packet_input.company,
        "ticker": packet_input.ticker,
        "as_of_date": packet_input.as_of_date,
        "trusted_fact_count": len(packet_input.trusted_facts),
        "candidate_fact_summary": packet_input.candidate_facts_summary,
        "selected_financial_reports": packet_input.selected_financial_reports,
    }
    return {
        "data_snapshot_id": _stable_id("data_snapshot", json.dumps(payload, sort_keys=True, ensure_ascii=False)),
        "generated_at": generated_at,
        "as_of_date": packet_input.as_of_date,
        "raw_data_preservation": True,
        "source_classification_required": True,
        "normalization_required": True,
        "quality_gate_required": True,
        "trust_resolution_required": True,
        "consumption_grade_only": True,
        "snapshot_payload_hash": _hash_json(payload),
    }


def _find_packet_gaps(packet_input: AnalysisPacketInput) -> list[str]:
    gaps = []
    if not packet_input.trusted_facts:
        gaps.append("insufficient_trusted_evidence:no_trusted_facts")
    if packet_input.price_data_placeholder.get("status") != "available":
        gaps.append("insufficient_trusted_evidence:price_data")
    if packet_input.macro_data_placeholder.get("status") != "available":
        gaps.append("insufficient_trusted_evidence:macro_data")
    if packet_input.asset_class_data_placeholder.get("status") != "available":
        gaps.append("insufficient_trusted_evidence:asset_class_data")
    return gaps


def _render_markdown_packet(packet: dict[str, Any]) -> str:
    lines = [
        f"# Analysis Packet: {packet['company']} ({packet['ticker']})",
        "",
        f"- packet_id: `{packet['packet_id']}`",
        f"- data_snapshot_id: `{packet['data_snapshot_id']}`",
        f"- as_of_date: `{packet['as_of_date']}`",
        f"- analysis_scope: {packet['analysis_scope']}",
        "",
        "## Trusted Facts",
    ]
    if packet["trusted_facts"]:
        for fact in packet["trusted_facts"]:
            lines.append(
                f"- {fact.get('canonical_field') or fact.get('field_name')}: {fact.get('value')} {fact.get('unit')} "
                f"({fact.get('period')}, {fact.get('trust_status')}, source={fact.get('source_id')})"
            )
    else:
        lines.append("- insufficient_trusted_evidence:no_trusted_facts")
    lines.extend([
        "",
        "## Candidate Facts Summary",
        "",
        json.dumps(packet["candidate_facts_summary"], ensure_ascii=False, indent=2),
        "",
        "## Evidence Gaps",
    ])
    lines.extend(f"- {gap}" for gap in packet["insufficient_trusted_evidence"])
    return "\n".join(lines) + "\n"


def _render_gpt_web_prompt(packet: dict[str, Any], markdown_packet: str) -> str:
    return f"""You are helping with a human-in-the-loop financial analysis workflow.

Use only information available on or before as_of_date={packet['as_of_date']}.
Do not use future information. Do not browse unless the human explicitly provides more sources.
Trusted facts may be used as facts. Candidate facts are context only and cannot be treated as final facts.
If evidence is missing or ambiguous, write insufficient_evidence.

Return:
1. A concise markdown report.
2. A FINAL_REPORT_JSON fenced block with keys:
   report_title, as_of_date, summary, assumptions, forecasts, risks,
   watchlist_signals, confidence, next_review_date, insufficient_evidence.

Forecast items must include:
forecast_item, target_metric, forecast_horizon, expected_direction,
expected_range, confidence, thesis, risk_trigger, review_date.

Analysis packet:

{markdown_packet}
"""


def _extract_final_report_json(raw_report_text: str) -> dict[str, Any]:
    patterns = [
        r"FINAL_REPORT_JSON\s*```json\s*(\{.*?\})\s*```",
        r"```json\s*(\{.*?\})\s*```",
    ]
    for pattern in patterns:
        match = re.search(pattern, raw_report_text, flags=re.DOTALL)
        if match:
            return json.loads(match.group(1))
    raise ValueError("FINAL_REPORT_JSON block not found")


def _validate_report_payload(payload: dict[str, Any]) -> dict[str, Any]:
    required = {
        "report_title",
        "as_of_date",
        "summary",
        "assumptions",
        "forecasts",
        "risks",
        "watchlist_signals",
        "confidence",
        "next_review_date",
        "insufficient_evidence",
    }
    errors = [f"missing:{field}" for field in sorted(required) if field not in payload]
    for index, forecast in enumerate(payload.get("forecasts", []), start=1):
        for field_name in [
            "forecast_item",
            "target_metric",
            "forecast_horizon",
            "expected_direction",
            "expected_range",
            "confidence",
            "thesis",
            "risk_trigger",
            "review_date",
        ]:
            if field_name not in forecast:
                errors.append(f"forecast_{index}_missing:{field_name}")
    return {"valid": not errors, "errors": errors}


def _forecast_backtest_record(report_id: str, index: int, forecast: dict[str, Any]) -> dict[str, Any]:
    return {
        "forecast_item_id": f"{report_id}_forecast_{index:03d}",
        "target_metric": forecast.get("target_metric", ""),
        "forecast_horizon": forecast.get("forecast_horizon", ""),
        "expected_direction": forecast.get("expected_direction", ""),
        "expected_range": forecast.get("expected_range", {}),
        "confidence": forecast.get("confidence", ""),
        "thesis": forecast.get("thesis", ""),
        "risk_trigger": forecast.get("risk_trigger", ""),
        "review_date": forecast.get("review_date", ""),
        "actual_value_later": None,
        "backtest_result": "pending",
        "revision_note": "",
    }


def _sample_gpt_report(packet_id: str, data_snapshot_id: str) -> str:
    payload = {
        "report_title": "Sample human-in-the-loop analysis report",
        "as_of_date": "2025-01-31",
        "packet_id": packet_id,
        "data_snapshot_id": data_snapshot_id,
        "summary": "Revenue evidence is available, but a full investment report is not supported by Phase 1 data.",
        "assumptions": ["Use only trusted facts in the packet.", "Treat missing price and macro data as evidence gaps."],
        "forecasts": [
            {
                "forecast_item": "sample_revenue_direction",
                "target_metric": "revenue",
                "forecast_horizon": "next_fiscal_year",
                "expected_direction": "not_forecastable",
                "expected_range": {"low": None, "high": None, "unit": "USD"},
                "confidence": "low",
                "thesis": "insufficient_evidence: no trend, price, macro, or margin packet data",
                "risk_trigger": "new audited filing or trusted market data changes packet evidence",
                "review_date": "2025-04-30",
            }
        ],
        "risks": ["insufficient_trusted_evidence:price_data", "insufficient_trusted_evidence:multi_period_trend"],
        "watchlist_signals": ["next 10-Q revenue and margin trend"],
        "confidence": "low",
        "next_review_date": "2025-04-30",
        "insufficient_evidence": ["price_data", "macro_data", "multi_period_trend"],
    }
    return "# Sample Report\n\nThis is a sample pasted-back report.\n\nFINAL_REPORT_JSON\n```json\n" + json.dumps(payload, ensure_ascii=False, indent=2) + "\n```\n"


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def _hash_json(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
