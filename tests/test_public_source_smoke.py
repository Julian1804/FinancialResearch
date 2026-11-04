"""Bounded offline checks for the source-only public candidate."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from backend.app.core.china_public_fund_query import canonical_fund_query_time_role
from backend.app.core.first_install_bootstrap import load_source_contract
from backend.app.core.first_install_sources import (
    FirstInstallSourceAcquirer,
    HKEXIdentityReferenceGap,
)
from backend.app.core.governed_components import (
    load_governed_components,
    release_component_authority,
)
from backend.app.core.modeling_platform import (
    ModelingDatasetSpec,
    ModelingError,
    ModelingVariable,
    build_dataset,
)
from backend.app.main import app
from backend.app.modules.system_tasks.routers.first_install_router import run as run_first_install_route
from scripts.fr_public_source import application_source_files
from scripts.fr_public_validation import validation_environment


ROOT = Path(__file__).resolve().parents[1]


class PublicSourceSmokeTests(unittest.TestCase):
    def test_application_imports_without_internal_data(self) -> None:
        self.assertGreater(len(app.routes), 0)
        self.assertIn("/api/health", app.openapi()["paths"])

    def test_required_static_resource_closure(self) -> None:
        files = application_source_files(ROOT)
        self.assertIn("backend/app/main.py", files)
        self.assertIn("config/fr_governed_component_registry.json", files)
        self.assertTrue(all((ROOT / path).is_file() for path in files))

    def test_closure_detects_a_missing_static_resource(self) -> None:
        from scripts import fr_public_source
        missing = frozenset(set(fr_public_source.APPLICATION_RESOURCE_FILES) |
                            {"config/synthetic_missing_resource.json"})
        with patch.object(fr_public_source, "APPLICATION_RESOURCE_FILES", missing):
            with self.assertRaises(FileNotFoundError):
                fr_public_source.application_source_files(ROOT)

    def test_governed_components_preserve_serving_boundary(self) -> None:
        registry, digest = load_governed_components()
        self.assertEqual(len(digest), 64)
        self.assertTrue(registry["CN_PUBLIC_FUND"].serving_enabled)
        self.assertTrue(registry["CN_A_SHARE"].serving_enabled)
        self.assertFalse(any(row.serving_enabled for key, row in registry.items()
                             if key not in {"CN_PUBLIC_FUND", "CN_A_SHARE"}))
        with self.assertRaises(ValueError):
            release_component_authority({"FR_FOREIGN_EXCHANGE"}, registry=registry,
                                        registry_sha256=digest)

    def test_missing_component_registry_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(FileNotFoundError):
                load_governed_components(Path(temporary) / "missing.json")

    def test_public_package_excludes_internal_data_and_governance(self) -> None:
        for relative in (
            "AGENTS.md", "CLAUDE.md", "runtime",
            "config/fr_hkex_equity_population_reference_v1.json",
            "backend/app/core/fund_nav_legacy_time_role_proofs_v1.json",
        ):
            self.assertFalse((ROOT / relative).exists(), relative)

    def test_missing_hkex_reference_blocks_before_source_request(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            acquirer = FirstInstallSourceAcquirer(root / "source")
            with patch("backend.app.core.first_install_sources.HKEX_REFERENCE_PATH", root / "missing.json"), \
                 patch.object(acquirer, "_get", side_effect=AssertionError("source called")) as get:
                with self.assertRaisesRegex(HKEXIdentityReferenceGap, "identity_reference_gap"):
                    acquirer._hkex_equity_population()
                get.assert_not_called()

    def test_hkex_profile_preflight_blocks_all_source_requests(self) -> None:
        contract = load_source_contract()
        scope = SimpleNamespace(
            state="enabled", universe="CN_A_SHARE", full_available_history=False,
            population_mode="explicit_selection",
            population_spec={"selectors": [{"venue": "HKEX", "code": "00001"}]},
        )
        profile = SimpleNamespace(
            validate=lambda: None, scopes=(scope,),
            source_contract_id=contract["contract_id"],
            source_contract_version=contract["contract_version"],
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            acquirer = FirstInstallSourceAcquirer(root / "source")
            with patch("backend.app.core.first_install_sources.HKEX_REFERENCE_PATH", root / "missing.json"), \
                 patch.object(acquirer, "_get", side_effect=AssertionError("source called")) as get:
                with self.assertRaisesRegex(HKEXIdentityReferenceGap, "identity_reference_gap"):
                    acquirer.acquire(profile, run_id="synthetic", as_of_date="2000-01-01")
                get.assert_not_called()

    def test_auto_hkex_profile_preflight_blocks_before_source(self) -> None:
        contract = load_source_contract()
        scope = SimpleNamespace(
            state="enabled", universe="CN_A_SHARE", full_available_history=False,
            population_mode="current_population", population_spec={"venues": ["HKEX"]},
        )
        profile = SimpleNamespace(
            validate=lambda: None, scopes=(scope,),
            source_contract_id=contract["contract_id"],
            source_contract_version=contract["contract_version"],
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            acquirer = FirstInstallSourceAcquirer(root / "source")
            with patch("backend.app.core.first_install_sources.HKEX_REFERENCE_PATH", root / "missing.json"), \
                 patch.object(acquirer, "_get", side_effect=AssertionError("source called")) as get:
                with self.assertRaisesRegex(HKEXIdentityReferenceGap, "identity_reference_gap"):
                    acquirer.acquire(profile, run_id="synthetic", as_of_date="2000-01-01")
                get.assert_not_called()

    def test_empty_hkex_reference_is_not_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            reference = root / "reference.json"
            reference.write_text(json.dumps({
                "schema_version": "fr_hkex_equity_population_reference_v1", "rows": [],
            }), encoding="utf-8")
            acquirer = FirstInstallSourceAcquirer(root / "source")
            with patch("backend.app.core.first_install_sources.HKEX_REFERENCE_PATH", reference), \
                 patch.object(acquirer, "_get", side_effect=AssertionError("source called")) as get:
                with self.assertRaisesRegex(HKEXIdentityReferenceGap, "identity_reference_gap"):
                    acquirer._hkex_equity_population()
                get.assert_not_called()

    def test_malformed_hkex_rows_block_before_source(self) -> None:
        synthetic_row = {
            "code": "00001", "name": "Synthetic Equity", "currency": "HKD",
            "classification": "ordinary_equity_security",
            "economic_security_group_key": "hkex-security:synthetic",
            "fr_identity_treatment": "synthetic_offline_test_only",
            "counts_as_current_economic_security": True,
            "listing_start": "2000-01-01",
        }
        cases = {
            "missing_fields": [{}],
            "non_object": ["not a reference row"],
            "missing_identity_key": [{key: value for key, value in synthetic_row.items()
                                      if key != "economic_security_group_key"}],
            "no_usable_identity": [{**synthetic_row, "listing_start": None}],
            "no_accepted_row": [{**synthetic_row,
                                 "counts_as_current_economic_security": False}],
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            reference = root / "reference.json"
            acquirer = FirstInstallSourceAcquirer(root / "source")
            for name, rows in cases.items():
                with self.subTest(name=name):
                    reference.write_text(json.dumps({
                        "schema_version": "fr_hkex_equity_population_reference_v1",
                        "rows": rows,
                    }), encoding="utf-8")
                    with patch("backend.app.core.first_install_sources.HKEX_REFERENCE_PATH", reference), \
                         patch.object(acquirer, "_get", side_effect=AssertionError("source called")) as get:
                        with self.assertRaisesRegex(HKEXIdentityReferenceGap, "identity_reference_gap"):
                            acquirer._hkex_equity_population()
                        get.assert_not_called()

    def test_malformed_hkex_profile_blocks_all_source_requests(self) -> None:
        contract = load_source_contract()
        scope = SimpleNamespace(
            state="enabled", universe="CN_A_SHARE", full_available_history=False,
            population_mode="explicit_selection",
            population_spec={"selectors": [{"venue": "HKEX", "code": "00001"}]},
        )
        profile = SimpleNamespace(
            validate=lambda: None, scopes=(scope,),
            source_contract_id=contract["contract_id"],
            source_contract_version=contract["contract_version"],
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            reference = root / "reference.json"
            reference.write_text(json.dumps({
                "schema_version": "fr_hkex_equity_population_reference_v1",
                "rows": [{}],
            }), encoding="utf-8")
            acquirer = FirstInstallSourceAcquirer(root / "source")
            with patch("backend.app.core.first_install_sources.HKEX_REFERENCE_PATH", reference), \
                 patch.object(acquirer, "_get", side_effect=AssertionError("source called")) as get:
                with self.assertRaisesRegex(HKEXIdentityReferenceGap, "identity_reference_gap"):
                    acquirer.acquire(profile, run_id="synthetic", as_of_date="2000-01-01")
                get.assert_not_called()

    def test_structural_hkex_reference_allows_mixed_rows_without_real_source(self) -> None:
        accepted = {
            "code": "00001", "name": "Synthetic Equity", "currency": "HKD",
            "classification": "ordinary_equity_security",
            "economic_security_group_key": "hkex-security:synthetic",
            "fr_identity_treatment": "synthetic_offline_test_only",
            "counts_as_current_economic_security": True,
            "listing_start": "2000-01-01",
        }
        residual = {**accepted, "code": "00002",
                    "counts_as_current_economic_security": False,
                    "listing_start": None}
        attributed = {**accepted, "code": "00003", "listing_start": None,
                      "accepted_listing_id": "synthetic-listing",
                      "observation_attribution": "unique_current_episode_in_accepted_graph"}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            reference = root / "reference.json"
            reference.write_text(json.dumps({
                "schema_version": "fr_hkex_equity_population_reference_v1",
                "rows": [accepted, residual, attributed],
            }), encoding="utf-8")
            acquirer = FirstInstallSourceAcquirer(root / "source")
            with patch("backend.app.core.first_install_sources.HKEX_REFERENCE_PATH", reference), \
                 patch.object(acquirer, "_get", side_effect=RuntimeError("synthetic source stub")) as get:
                with self.assertRaisesRegex(RuntimeError, "synthetic source stub"):
                    acquirer._hkex_equity_population()
                get.assert_called_once()

    def test_first_install_api_reports_identity_gap(self) -> None:
        with patch("backend.app.modules.system_tasks.routers.first_install_router.run_first_install",
                   side_effect=HKEXIdentityReferenceGap("identity_reference_gap")):
            with self.assertRaises(HTTPException) as caught:
                run_first_install_route({})
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(caught.exception.detail["code"], "identity_reference_gap")

    def test_explicit_nav_date_is_preserved(self) -> None:
        role = canonical_fund_query_time_role(
            metric_id="fund.nav", subject_id="synthetic_share_class",
            economic_time="2000-01-01", source_observation_key="synthetic_observation",
            stored_time_role="nav_date", source_family="CSRC_EID", source_trace={},
        )
        self.assertEqual(role, "nav_date")

    def test_unproved_generic_nav_role_is_not_promoted(self) -> None:
        role = canonical_fund_query_time_role(
            metric_id="fund.nav", subject_id="synthetic_share_class",
            economic_time="2000-01-01", source_observation_key="synthetic_observation",
            stored_time_role="observation_date", source_family="CSRC_EID",
            source_trace={"mapping_basis": "accepted CSRC EID fundId plus scoped share-class code",
                          "provenance_refs": ["CSRC_EID_current_valuation"]},
        )
        self.assertEqual(role, "observation_date")

    def test_report_send_date_only_does_not_promote_nav_role(self) -> None:
        role = canonical_fund_query_time_role(
            metric_id="fund.nav", subject_id="synthetic_share_class",
            economic_time="2000-01-01", source_observation_key="synthetic_observation",
            stored_time_role="observation_date", source_family="CSRC_EID",
            source_trace={"mapping_basis": "accepted CSRC EID fundId plus scoped share-class code",
                          "provenance_refs": ["CSRC_EID_reportSendDate"]},
        )
        self.assertEqual(role, "observation_date")

    def test_modeling_rejects_unproved_fund_nav_time_role(self) -> None:
        spec = ModelingDatasetSpec(
            y=(ModelingVariable(name="NAV", series_key="synthetic_nav", role="Y"),),
            shape="univariate_time_series",
        )
        observations = {"synthetic_nav": [{
            "economic_time": "2000-01-01", "time_role": "observation_date",
            "value": 1.0, "unit": "CNY", "currency": "CNY", "scale": "unit",
        }]}
        metadata = {"release_id": "synthetic_release",
                    "accepted_time_roles": {"synthetic_nav": ["nav_date"]}}
        with self.assertRaises(ModelingError) as caught:
            build_dataset(spec, observations, input_metadata=metadata)
        self.assertEqual(caught.exception.code, "unsupported_modeling_time_role")

    def test_validation_overrides_inherited_storage_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "owned"
            environment = validation_environment(root)
            self.assertEqual(Path(environment["FR_LOCAL_STORAGE_ROOT"]), root / "local")
            self.assertEqual(Path(environment["FR_NAS_ROOT"]), root / "nas")
            self.assertEqual(Path(environment["FINANCIAL_RESEARCH_RUNTIME_ROOT"]), root / "runtime")
            self.assertEqual(environment["PYTHONNOUSERSITE"], "1")


if __name__ == "__main__":
    unittest.main()
