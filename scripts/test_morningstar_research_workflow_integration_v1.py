from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = PROJECT_ROOT / "runtime" / "morningstar_research_workflow_v1"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def ensure_outputs() -> None:
    if not (OUTPUT_ROOT / "manifest" / "integration_manifest.json").exists():
        from scripts.run_morningstar_research_workflow_integration_v1 import run_integration
        run_integration()


def test_workspace_index_exists_and_has_evidence_boundary() -> None:
    ensure_outputs()
    ws = load_json(OUTPUT_ROOT / "workspace" / "morningstar_workspace_index.json")
    assert ws["workspace_id"] == "morningstar_candidate_workspace_v1"
    assert ws["formal_trusted_consumption_enabled"] is False
    assert ws["us_equity_standalone_excluded"] is True

    boundary = ws["evidence_boundary"]
    assert boundary["consumable_fields"]["returns"]["status"] == "production_candidate_preview"
    assert boundary["consumable_fields"]["holdings_exposure"]["status"] == "production_candidate_preview"
    assert boundary["consumable_fields"]["lookthrough_holdings"]["status"] == "production_candidate_preview"
    assert boundary["proxy_fields"]["holdings_derived_aum"]["status"] == "candidate_proxy"
    assert boundary["identifier_mapping_fields"]["underlying_entity_shell"]["status"] == "identifier_mapping_candidate"
    assert boundary["blocked_fields"]["tna_enf"]["status"] == "blocked_unit_scale_unknown"
    blocked_dps = boundary["blocked_fields"]["tna_enf"]["data_points_blocked"]
    assert "TNA0M" in blocked_dps and "ENF0M" in blocked_dps


def test_statistical_report_has_returns_and_holdings_stats() -> None:
    ensure_outputs()
    report = load_json(OUTPUT_ROOT / "statistical_report" / "morningstar_statistical_report_v1.json")
    assert report["formal_trusted_consumption"] is False
    assert report["us_equity_standalone_excluded"] is True
    assert report["tna_enf_blocked"] is True

    # Returns stats should exist (SPY has 5 observations)
    assert report["returns_stats"]
    for sid, stats in report["returns_stats"].items():
        assert stats["observations"] > 0
        assert isinstance(stats["mean_pct"], (int, float))

    # Holdings stats should exist for all 5 seeds
    assert len(report["holdings_stats"]) == 5
    for seed, hstats in report["holdings_stats"].items():
        assert hstats["row_count"] is not None
        assert hstats["sum_marketValue_usd"] is not None

    # AUM proxy aggregate
    assert report["aum_proxy_aggregate"]["seed_count"] == 5
    assert report["aum_proxy_aggregate"]["total_sum_marketValue_usd"] > 0


def test_analysis_packet_integration_has_seed_summaries_and_blocked_fields() -> None:
    ensure_outputs()
    packet = load_json(OUTPUT_ROOT / "analysis_packet" / "morningstar_analysis_packet_integration_v1.json")
    assert packet["formal_trusted_consumption"] is False
    seeds = packet["seed_summaries"]
    assert len(seeds) == 5
    for seed, summary in seeds.items():
        assert summary["returns_candidate_preview"]["status"] == "production_candidate_preview"
        assert summary["holdings_exposure_candidate_preview"]["status"] == "production_candidate_preview"
        assert summary["holdings_derived_aum_candidate_proxy"]["status"] == "candidate_proxy"
        assert summary["blocked_fields"]["tna_enf"]["status"] == "blocked_unit_scale_unknown"
        assert summary["us_equity_standalone_exclusion"]["excluded"] is True

    boundary = packet["evidence_boundary"]
    assert "returns" in boundary["candidate_preview_fields"]
    assert "holdings_derived_aum" in boundary["candidate_proxy_fields"]
    assert "tna_enf" in boundary["blocked_fields"]
    assert "us_equity_price_time_series" in boundary["excluded_standalone_series"]


def test_manifest_records_zero_api_calls_and_boundaries() -> None:
    ensure_outputs()
    manifest = load_json(OUTPUT_ROOT / "manifest" / "integration_manifest.json")
    assert manifest["api_calls_made"] == 0
    assert manifest["no_openai_api_called"] is True
    assert manifest["parse_lab_affected"] is False
    assert manifest["formal_trusted_consumption_enabled"] is False
    assert manifest["us_equity_standalone_excluded"] is True
    assert manifest["tna_enf_blocked"] is True


if __name__ == "__main__":
    test_workspace_index_exists_and_has_evidence_boundary()
    test_statistical_report_has_returns_and_holdings_stats()
    test_analysis_packet_integration_has_seed_summaries_and_blocked_fields()
    test_manifest_records_zero_api_calls_and_boundaries()
    print("morningstar research workflow integration v1 tests passed")
