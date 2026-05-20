from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.run_market_data_foundation_v1 import run_market_data_foundation_v1  # noqa: E402


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_outputs() -> None:
    if not (PROJECT_ROOT / "runtime" / "market_data_foundation_catalog" / "foundation_summary.json").exists():
        run_market_data_foundation_v1()


def test_taxonomy_v2_outputs() -> None:
    ensure_outputs()
    config_root = PROJECT_ROOT / "config"
    macro = load_json(config_root / "macro_taxonomy.json")
    asset = load_json(config_root / "asset_class_taxonomy.json")
    rates = load_json(config_root / "rates_bond_taxonomy.json")
    fx = load_json(config_root / "fx_currency_taxonomy.json")
    commodity = load_json(config_root / "commodity_taxonomy.json")
    domains = load_json(config_root / "market_data_domain_taxonomy.json")

    assert macro["items"]
    assert asset["items"]
    assert rates["items"]
    assert fx["items"]
    assert commodity["futures_framework"]["schema_ready"] is True
    assert {"COMEX", "NYMEX", "LME", "SHFE", "INE", "DCE", "CZCE"}.issubset(
        set(commodity["futures_framework"]["supported_future_exchanges"])
    )
    assert "economic meaning" in domains["classification_correction_policy"]
    assert {"macro_fundamental", "macro_policy", "rates_market", "fx_market", "commodity", "futures"}.issubset(
        {item["domain"] for item in domains["domains"]}
    )


def test_foundation_catalog_outputs() -> None:
    ensure_outputs()
    root = PROJECT_ROOT / "runtime" / "market_data_foundation_catalog"
    summary = load_json(root / "foundation_summary.json")
    catalog = load_json(root / "foundation_catalog.json")
    gaps = load_json(root / "source_gap_matrix.json")
    plan = load_json(root / "next_ingestion_plan.json")

    assert summary["item_count"] >= 40
    assert summary["schema_ready_count"] == summary["item_count"]
    assert summary["domain_counts"]["macro"] > 0
    assert summary["domain_counts"]["rates_bonds"] > 0
    assert summary["domain_counts"]["fx"] > 0
    assert summary["domain_counts"]["commodity"] > 0
    assert summary["domain_counts"]["futures"] > 0
    assert catalog["candidate_only"] is True
    assert catalog["formal_trusted_consumption"] is False
    assert all(item["schema_ready"] is True for item in catalog["items"])
    assert gaps["items"]
    assert plan["items"]


def test_schema_and_trust_docs_exist() -> None:
    docs = [
        "MACRO_DATA_MODEL_V1.md",
        "ASSET_CLASS_DATA_MODEL_V1.md",
        "RATES_BOND_DATA_MODEL_V1.md",
        "FX_CURRENCY_DATA_MODEL_V1.md",
        "COMMODITY_DATA_MODEL_V1.md",
        "MARKET_DATA_FOUNDATION_SCHEMA.md",
        "MARKET_DATA_FOUNDATION_CATALOG_V1.md",
        "ECONOMIC_CLASSIFICATION_AND_TRUST_PRINCIPLES.md",
    ]
    for doc in docs:
        path = PROJECT_ROOT / "docs" / doc
        assert path.exists(), doc
        text = path.read_text(encoding="utf-8")
        assert len(text) > 200
        assert "#" in text


if __name__ == "__main__":
    run_market_data_foundation_v1()
    test_taxonomy_v2_outputs()
    test_foundation_catalog_outputs()
    test_schema_and_trust_docs_exist()
    print("market data foundation v1 tests passed")
