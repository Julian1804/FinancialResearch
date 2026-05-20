from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

CONFIG_PATH = PROJECT_ROOT / "config" / "commodity_taxonomy.json"
MACRO_ASSET_ROOT = PROJECT_ROOT / "runtime" / "macro_asset_historical_ingestion"
SAMPLE_ROOT = PROJECT_ROOT / "runtime" / "commodity_exchange_sample_ingestion"

DOC_MODEL = PROJECT_ROOT / "docs" / "COMMODITY_DATA_MODEL_V1.md"
DOC_SOURCE_AUDIT = PROJECT_ROOT / "docs" / "COMMODITY_SOURCE_FEASIBILITY_AUDIT.md"
DOC_SAMPLE = PROJECT_ROOT / "docs" / "COMMODITY_EXCHANGE_SAMPLE_INGESTION_REPORT.md"
DOC_DASHBOARD = PROJECT_ROOT / "docs" / "COMMODITY_DASHBOARD_V1_REPORT.md"


def run_commodity_dashboard_v1() -> dict[str, Any]:
    taxonomy = build_taxonomy()
    CONFIG_PATH.write_text(json.dumps(taxonomy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = read_json(MACRO_ASSET_ROOT / "dashboard_macro_asset_summary.json")
    upgraded = [upgrade_series(item) for item in summary.get("asset_series", [])]
    schema_summary = build_schema_summary(upgraded)
    source_audit = build_source_feasibility_audit()
    sample_result = build_sample_ingestion_result(summary)
    dashboard_data = build_dashboard_data(upgraded, schema_summary, source_audit, sample_result)

    write_json(MACRO_ASSET_ROOT / "commodity_schema_upgrade_summary.json", schema_summary | {"items": upgraded})
    write_json(MACRO_ASSET_ROOT / "commodity_source_feasibility_audit.json", source_audit)
    write_json(SAMPLE_ROOT / "commodity_exchange_sample_ingestion_results.json", sample_result)
    write_json(SAMPLE_ROOT / "commodity_dashboard_v1_data.json", dashboard_data)

    DOC_MODEL.write_text(render_model_doc(schema_summary), encoding="utf-8")
    DOC_SOURCE_AUDIT.write_text(render_source_audit_doc(source_audit), encoding="utf-8")
    DOC_SAMPLE.write_text(render_sample_doc(sample_result), encoding="utf-8")
    DOC_DASHBOARD.write_text(render_dashboard_doc(dashboard_data), encoding="utf-8")

    return {
        "generated_at": utc_now(),
        "commodity_data_model_completed": True,
        "spot_futures_exchange_distinction_completed": True,
        "commodity_series_count": len(upgraded),
        "source_feasibility_audit_completed": True,
        "exchange_sample_ingestion_status": sample_result["status"],
        "dashboard_data_path": str(SAMPLE_ROOT / "commodity_dashboard_v1_data.json"),
        "candidate_only": True,
        "formal_trusted_consumption": False,
        "no_openai_api_called": True,
    }


def build_taxonomy() -> dict[str, Any]:
    return {
        "version": "commodity_data_model_v1",
        "generated_at": utc_now(),
        "price_types": ["spot", "futures", "index", "benchmark", "settlement", "average_price", "spot_or_benchmark_unclear", "unknown"],
        "exchanges": ["COMEX", "LME", "SHFE", "NYMEX", "ICE", "CBOT", "DCE", "CZCE", "INE", "World Bank", "FRED", "other", "unknown"],
        "commodity_categories": ["energy", "precious_metals", "base_metals", "ferrous_metals", "agriculture", "chemicals", "livestock", "softs", "freight", "other"],
        "instrument_fields": [
            "instrument_name",
            "underlying_commodity",
            "contract_code",
            "contract_month",
            "currency",
            "unit",
            "frequency",
            "source_id",
            "provider_name",
            "publish_date",
            "observation_date",
            "data_period_start",
            "data_period_end",
            "vintage_date",
            "revision_status",
            "quality_status",
            "trust_status",
            "candidate_only",
        ],
        "world_bank_policy": "World Bank Pink Sheet is benchmark/average-price evidence, not exchange futures.",
    }


def upgrade_series(item: dict[str, Any]) -> dict[str, Any]:
    series_id = item.get("series_id", "")
    category = normalize_category(item.get("category"), series_id)
    price_type = "benchmark" if item.get("source_id") == "world_bank_pink_sheet" else "spot_or_benchmark_unclear"
    exchange = "World Bank" if item.get("source_id") == "world_bank_pink_sheet" else "FRED" if item.get("source_id") == "fred_public_api" else "unknown"
    return {
        "dataset_id": item.get("dataset_id"),
        "source_id": item.get("source_id"),
        "provider_name": item.get("provider_name"),
        "price_type": price_type,
        "exchange": exchange,
        "commodity_category": category,
        "instrument_name": item.get("metric_name") or item.get("series_id"),
        "underlying_commodity": infer_underlying(item.get("series_id", ""), item.get("metric_name", "")),
        "contract_code": None,
        "contract_month": None,
        "currency": item.get("currency"),
        "unit": item.get("unit"),
        "frequency": item.get("frequency"),
        "publish_date": None,
        "publish_date_source": item.get("publish_date_source"),
        "observation_date": item.get("latest_observation_date"),
        "data_period_start": item.get("latest_observation_date"),
        "data_period_end": item.get("latest_observation_date"),
        "latest_value": item.get("latest_value"),
        "vintage_date": None,
        "revision_status": item.get("revision_status"),
        "quality_status": item.get("quality_status"),
        "trust_status": item.get("trust_status"),
        "candidate_only": True,
        "source_coverage_warning": "benchmark_or_average_price_not_exchange_futures" if exchange == "World Bank" else "source_specific_definition_required",
    }


def normalize_category(category: str | None, series_id: str) -> str:
    if category == "metals":
        return "ferrous_metals" if "IRON" in series_id else "base_metals"
    if category in {"energy", "precious_metals", "agriculture"}:
        return category
    return "other"


def infer_underlying(series_id: str, name: str) -> str:
    label = name or series_id
    if "WTI" in series_id or "oil" in label.lower():
        return "crude_oil"
    if "BRENT" in series_id:
        return "crude_oil"
    if "GOLD" in series_id:
        return "gold"
    if "SILVER" in series_id:
        return "silver"
    if "COPPER" in series_id:
        return "copper"
    if "ALUMIN" in series_id:
        return "aluminum"
    if "IRON" in series_id:
        return "iron_ore"
    if "WHEAT" in series_id:
        return "wheat"
    if "SOY" in series_id:
        return "soybeans"
    if "COAL" in series_id:
        return "coal"
    return series_id.lower()


def build_schema_summary(upgraded: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "generated_at": utc_now(),
        "commodity_schema_upgrade_completed": True,
        "series_count": len(upgraded),
        "price_type_counts": dict(Counter(item["price_type"] for item in upgraded)),
        "exchange_counts": dict(Counter(item["exchange"] for item in upgraded)),
        "commodity_category_counts": dict(Counter(item["commodity_category"] for item in upgraded)),
        "exchange_covered_series_count": sum(1 for item in upgraded if item["exchange"] not in {"World Bank", "FRED", "unknown"}),
        "world_bank_benchmark_series_count": sum(1 for item in upgraded if item["exchange"] == "World Bank"),
        "futures_series_count": sum(1 for item in upgraded if item["price_type"] == "futures"),
        "spot_series_count": sum(1 for item in upgraded if item["price_type"] == "spot"),
        "candidate_only": True,
        "formal_trusted_consumption": False,
    }


def build_source_feasibility_audit() -> dict[str, Any]:
    items = [
        source_item("world_bank_pink_sheet", "World Bank Pink Sheet", True, True, False, "connected", "benchmark/monthly commodity prices; not exchange futures", "trusted_by_real_external_candidate_if_quality_passed"),
        source_item("fred_commodity_series", "FRED commodity series", True, True, False, "connected_partial", "WTI and other public series available; provider-specific definitions required", "trusted_by_real_external_candidate_if_quality_passed"),
        source_item("cme_comex_nymex", "CME/COMEX/NYMEX", True, "limited", "often", "future_connector", "Official historical settlements typically require CME DataMine/licensing or limited product pages; do not scrape aggressively.", "candidate_or_authorized_source_required"),
        source_item("lme", "LME", True, "limited", "likely", "future_connector", "Historical data generally requires licensing/subscription; current phase does not use it.", "authorized_source_required"),
        source_item("shfe", "SHFE", True, "possible", False, "small_sample_candidate", "Official site may publish daily/monthly market data; requires endpoint-specific smoke before use.", "candidate_until_stable"),
        source_item("ine", "INE", True, "possible", False, "small_sample_candidate", "Official energy exchange data may be available; endpoint stability must be verified.", "candidate_until_stable"),
        source_item("dce", "DCE", True, "possible", False, "small_sample_candidate", "Official historical quotes may be available; endpoint/format needs separate connector.", "candidate_until_stable"),
        source_item("czce", "CZCE", True, "possible", False, "small_sample_candidate", "Official data may be available; needs low-frequency endpoint verification.", "candidate_until_stable"),
        source_item("nasdaq_data_link", "Nasdaq Data Link", False, "dataset_dependent", "sometimes", "optional_candidate", "Useful datasets may be free or paid; dataset-level license required.", "candidate_only"),
        source_item("stooq_yahoo_investing", "Stooq/Yahoo/Investing", False, "free_or_scraped", False, "optional_candidate", "Non-official or terms-sensitive; never trusted by default.", "candidate_only"),
    ]
    return {
        "generated_at": utc_now(),
        "items": items,
        "official_exchange_ingestion_decision": "defer_exchange_connectors_until_endpoint_specific_smoke",
        "no_exchange_data_fabricated": True,
    }


def source_item(source_id: str, name: str, official: bool, free: Any, needs_auth: Any, status: str, note: str, trust: str) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "source_name": name,
        "official_source": official,
        "free_level": free,
        "requires_account_or_license": needs_auth,
        "current_status": status,
        "note": note,
        "trust_eligibility": trust,
    }


def build_sample_ingestion_result(summary: dict[str, Any]) -> dict[str, Any]:
    fred_wti = next((item for item in summary.get("macro_series", []) if item.get("series_id") == "DCOILWTICO"), None)
    if fred_wti:
        return {
            "generated_at": utc_now(),
            "status": "connected_non_exchange_official_sample",
            "sample_source": "FRED DCOILWTICO",
            "sample_type": "official spot/benchmark commodity series, not exchange futures",
            "record_count": fred_wti.get("record_count"),
            "latest_observation_date": fred_wti.get("latest_observation_date"),
            "latest_value": fred_wti.get("latest_value"),
            "exchange_sample_connected": False,
            "exchange_sample_deferred_reason": "No free official exchange endpoint was confirmed stable without separate endpoint-specific smoke; World Bank/FRED remain connected non-exchange samples.",
            "candidate_only": True,
        }
    return {
        "generated_at": utc_now(),
        "status": "deferred",
        "exchange_sample_connected": False,
        "exchange_sample_deferred_reason": "No existing official commodity series available in runtime.",
        "candidate_only": True,
    }


def build_dashboard_data(upgraded: list[dict[str, Any]], schema_summary: dict[str, Any], source_audit: dict[str, Any], sample_result: dict[str, Any]) -> dict[str, Any]:
    by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_exchange: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in upgraded:
        by_category[item["commodity_category"]].append(item)
        by_exchange[item["exchange"]].append(item)
    return {
        "generated_at": utc_now(),
        "overview_cards": {
            "commodity_series_count": len(upgraded),
            "spot_series_count": schema_summary["spot_series_count"],
            "futures_series_count": schema_summary["futures_series_count"],
            "exchange_covered_series_count": schema_summary["exchange_covered_series_count"],
            "world_bank_benchmark_series_count": schema_summary["world_bank_benchmark_series_count"],
            "quality_passed_count": sum(1 for item in upgraded if item["quality_status"] == "quality_passed"),
            "quality_warning_count": sum(1 for item in upgraded if item["quality_status"] != "quality_passed"),
            "missing_publish_date_count": sum(1 for item in upgraded if item["publish_date_source"] in {None, "unavailable"}),
            "source_coverage_warning": "World Bank/FRED coverage is benchmark/spot-like; exchange futures coverage is deferred.",
        },
        "category_view": summarize_groups(by_category),
        "exchange_view": summarize_groups(by_exchange),
        "chart_builder": {
            "available_series": [
                {
                    "dataset_id": item["dataset_id"],
                    "instrument_name": item["instrument_name"],
                    "commodity_category": item["commodity_category"],
                    "exchange": item["exchange"],
                    "price_type": item["price_type"],
                    "latest_value": item["latest_value"],
                    "latest_observation_date": item["observation_date"],
                }
                for item in upgraded
            ],
            "chart_types": ["line", "bar", "pie"],
            "grouping_options": ["by_category", "by_exchange", "by_price_type"],
            "normalize_options": ["raw_value", "indexed_to_100", "pct_change"],
            "implementation_status": "line_and_bar_client_side; pie/share control available as partial",
        },
        "source_audit_summary": source_audit,
        "sample_ingestion": sample_result,
        "candidate_only": True,
    }


def summarize_groups(groups: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    rows = []
    for key, items in sorted(groups.items()):
        representative = sorted(items, key=lambda item: str(item.get("observation_date") or ""), reverse=True)[0]
        rows.append(
            {
                "group": key,
                "series_count": len(items),
                "representative_instrument": representative["instrument_name"],
                "latest_value": representative["latest_value"],
                "latest_observation_date": representative["observation_date"],
                "quality_counts": dict(Counter(item["quality_status"] for item in items)),
                "source_coverage": sorted(set(item["exchange"] for item in items)),
            }
        )
    return rows


def render_model_doc(summary: dict[str, Any]) -> str:
    return f"""# Commodity Data Model v1

Generated: {utc_now()}

Commodity schema now distinguishes `price_type`, `exchange`, `commodity_category`, and instrument identity.

Current upgraded series: {summary['series_count']}

Price type counts:

```json
{json.dumps(summary['price_type_counts'], ensure_ascii=False, indent=2)}
```

Exchange counts:

```json
{json.dumps(summary['exchange_counts'], ensure_ascii=False, indent=2)}
```

World Bank Pink Sheet series are marked benchmark/average-price style evidence, not exchange futures.
"""


def render_source_audit_doc(audit: dict[str, Any]) -> str:
    lines = ["# Commodity Source Feasibility Audit", "", f"Generated: {utc_now()}", "", "| Source | Status | Note |", "| --- | --- | --- |"]
    for item in audit["items"]:
        lines.append(f"| {item['source_name']} | {item['current_status']} | {item['note']} |")
    lines.append("")
    lines.append("No exchange prices are fabricated. Exchange connectors remain deferred unless a free official endpoint is verified.")
    return "\n".join(lines) + "\n"


def render_sample_doc(sample: dict[str, Any]) -> str:
    return f"""# Commodity Exchange Sample Ingestion Report

Generated: {utc_now()}

Status: `{sample['status']}`.

Exchange sample connected: {sample.get('exchange_sample_connected')}.

Reason: {sample.get('exchange_sample_deferred_reason')}

Connected non-exchange sample: {sample.get('sample_source', 'none')}.
"""


def render_dashboard_doc(data: dict[str, Any]) -> str:
    return f"""# Commodity Dashboard v1 Report

Generated: {utc_now()}

Commodity Dashboard v1 contains:

- Overview cards
- Category View
- Exchange View
- Custom Chart Builder controls for line, bar and pie/share
- Secondary data table

Series count: {data['overview_cards']['commodity_series_count']}

Candidate-only: true
"""


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    print(json.dumps(run_commodity_dashboard_v1(), ensure_ascii=False, indent=2))
