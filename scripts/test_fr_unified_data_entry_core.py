from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from fr_unified_data_entry_core import (  # noqa: E402
    CONVERSION_EVIDENCE_FIELDS,
    MetricDefinition,
    MetricRegistry,
    TIME_ROLE_FIELDS,
    UnifiedDataEntryCore,
    UnifiedDataError,
    _unit_conversion,
    build_source_observation_key,
)


ROOT = SCRIPT_DIR.parent
REGISTRY_PATH = ROOT / "config" / "metrics_registry.json"


class UnifiedDataEntryCoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = MetricRegistry.load(REGISTRY_PATH)
        cls.core = UnifiedDataEntryCore(cls.registry)

    @staticmethod
    def _dimension_value(field: str) -> str:
        values = {
            "accounting_standard": "PRC_GAAP",
            "adjustment_basis": "unadjusted",
            "base_currency": "USD",
            "base_year": "2020",
            "constituent_effective_scope": "close_of_session",
            "contract_code": "AU2412",
            "contract_multiplier": "1000",
            "contract_type": "deliverable",
            "conversion_policy": "native",
            "delivery_month": "2024-12",
            "effective_scope": "national",
            "exchange": "XSHG",
            "fixing_basis": "spot_mid",
            "frequency": "daily",
            "fund_share_class": "A",
            "fund_vehicle_id": "FUND:510300",
            "geography": "CN",
            "index_variant": "price_return",
            "instrument_id": "INS:BOND:1",
            "market_location": "onshore",
            "market_session": "official_close",
            "maturity": "10Y",
            "nav_or_transaction_basis": "unit_nav",
            "no_trade_policy": "explicit_no_trade",
            "price_basis": "close",
            "publisher_methodology": "publisher_method_v1",
            "quote_basis": "native_market_quote",
            "quote_currency": "CNY",
            "rate_convention": "actual_365",
            "rate_side": "mid",
            "rating_scope": "issue",
            "release_version": "initial",
            "report_type": "annual",
            "return_variant": "price_return",
            "seasonal_adjustment": "not_adjusted",
            "session": "day",
            "share_class": "A",
            "statement_period_basis": "year_to_date",
            "statement_type": "consolidated",
            "tenor": "10Y",
            "trading_session": "official_close",
            "version": "original",
            "yield_basis": "yield_to_maturity",
        }
        return values.get(field, f"{field}:value")

    def observation(
        self,
        metric_id: str = "market.close_price",
        *,
        subject_id: str | None = None,
        provider: str = "official exchange",
        value: Any = 10,
        scale: float = 1,
        derivation_method: str = "direct",
        **overrides: Any,
    ) -> dict[str, Any]:
        definition = self.registry.resolve(metric_id)
        subject_type = definition.required_subject_type
        subject_id = subject_id or f"{subject_type.upper()}:{metric_id}:1"
        record: dict[str, Any] = {
            "metric_id": metric_id,
            "subject_type": subject_type,
            "subject_id": subject_id,
            f"{subject_type}_id": subject_id,
            TIME_ROLE_FIELDS[definition.primary_time_role]: "2026-07-17",
            "value": value,
            "unit": definition.canonical_unit,
            "currency": (
                "CNY"
                if definition.currency_rule in {"preserve_source_currency", "reporting_currency"}
                else None
            ),
            "scale": scale,
            "source_provider": provider,
            "source_interface": f"{definition.domain}_validated_interface",
            "source_row_fingerprint": (
                f"{provider}:{metric_id}:{subject_id}:{value}:{scale}:{derivation_method}"
            ),
            "derivation_method": derivation_method,
        }
        for field in definition.required_series_dimensions:
            record[field] = self._dimension_value(field)
        record.update(overrides)
        return record

    def prepared(self, metric_id: str = "market.close_price", **kwargs: Any) -> dict[str, Any]:
        result = self.core.prepare_record(self.observation(metric_id, **kwargs))
        self.assertEqual(result["data_role"], "source_observation")
        return result

    def test_all_metric_contracts_are_executable(self) -> None:
        self.assertEqual(len(self.registry), 119)
        domains: set[str] = set()
        for definition in self.registry.definitions():
            domains.add(definition.domain)
            result = self.prepared(definition.metric_id)
            self.assertEqual(result["subject_type"], definition.required_subject_type)
            self.assertEqual(result["canonical_unit"], definition.canonical_unit)
            self.assertIn("domain", definition.domain_authority_source_rule)
            self.assertEqual(
                set(definition.required_series_dimensions),
                set(definition.series_invariant_dimensions).union(
                    definition.fact_varying_dimensions
                ),
            )
            classified = (
                set(definition.required_series_dimensions)
                | set(definition.conditional_series_invariant_dimensions)
                | set(definition.conditional_fact_varying_dimensions)
                | set(definition.not_applicable_dimensions)
            )
            self.assertEqual(
                len(classified),
                len(definition.required_series_dimensions)
                + len(definition.conditional_series_invariant_dimensions)
                + len(definition.conditional_fact_varying_dimensions)
                + len(definition.not_applicable_dimensions),
            )
            self.assertFalse(definition.canonical_unit.startswith("source_defined"))
            self.assertNotEqual(definition.canonical_unit, "units")
        self.assertEqual(
            domains,
            {
                "bonds",
                "commodities",
                "derivatives",
                "equities",
                "financial_statements",
                "funds_etfs",
                "fx_rates",
                "indices",
                "macro",
                "market_data",
                "rates",
            },
        )

    def test_legacy_ambiguous_fields_and_aliases_are_rejected(self) -> None:
        for forbidden in (
            "canonical" + "_data_id",
            "natural" + "_key",
            "investment" + "_id",
        ):
            with self.assertRaises(UnifiedDataError):
                self.core.prepare_record({forbidden: "legacy"})
        with self.assertRaises(UnifiedDataError):
            self.registry.resolve("close")
        with self.assertRaises(UnifiedDataError):
            self.registry.resolve("financial.operating_income")

    def test_one_issuer_a_h_adr_and_listing_series_remain_distinct(self) -> None:
        rows = []
        for share_class, venue, currency in (
            ("A", "XSHG", "CNY"),
            ("H", "XHKG", "HKD"),
            ("ADR", "XNYS", "USD"),
        ):
            rows.append(
                self.prepared(
                    subject_id=f"SERIES:ISSUER1:{share_class}:native_close",
                    entity_id="ENTITY:ISSUER1",
                    instrument_id=f"INSTRUMENT:ISSUER1:{share_class}",
                    listing_id=f"LISTING:ISSUER1:{venue}",
                    series_id=f"SERIES:ISSUER1:{share_class}:native_close",
                    share_class=share_class,
                    exchange=venue,
                    currency=currency,
                )
            )
        self.assertEqual(len({row["logical_fact_key"] for row in rows}), 3)
        self.assertEqual({row["entity_id"] for row in rows}, {"ENTITY:ISSUER1"})

    def test_parent_relationship_corrections_do_not_change_fact_identity(self) -> None:
        base = self.observation(
            subject_id="SERIES:ISSUER1:A:native_close",
            series_id="SERIES:ISSUER1:A:native_close",
            entity_id="ENTITY:OLD",
            instrument_id="INSTRUMENT:OLD",
            listing_id="LISTING:OLD",
            source_row_fingerprint="native-row-1",
        )
        corrected = {
            **base,
            "entity_id": "ENTITY:CORRECTED",
            "instrument_id": "INSTRUMENT:CORRECTED",
            "listing_id": "LISTING:CORRECTED",
        }
        self.assertEqual(
            self.core.prepare_record(base)["logical_fact_key"],
            self.core.prepare_record(corrected)["logical_fact_key"],
        )

    def test_source_identity_is_independent_of_canonical_mapping(self) -> None:
        base = self.observation(source_row_fingerprint="native-row-2")
        remapped = {
            **base,
            "metric_id": "equity.close",
            "subject_type": "series",
            "subject_id": "SERIES:REMAPPED",
            "series_id": "SERIES:REMAPPED",
            "logical_fact_key": "logical_fact:later-mapping",
            "canonical_currency": "USD",
        }
        self.assertEqual(
            build_source_observation_key(base),
            build_source_observation_key(remapped),
        )

    def test_multiple_bonds_fund_share_classes_and_venues_remain_distinct(self) -> None:
        bonds = [
            self.prepared(
                "bond.yield",
                subject_id=f"SERIES:BOND:{issue}:YTM",
                entity_id="ENTITY:ISSUER1",
                instrument_id=f"INSTRUMENT:BOND:{issue}",
                series_id=f"SERIES:BOND:{issue}:YTM",
            )
            for issue in ("2029", "2034")
        ]
        funds = [
            self.prepared(
                "fund.nav",
                subject_id=f"SERIES:FUND1:{share_class}:NAV",
                entity_id="ENTITY:MANAGER1",
                instrument_id=f"INSTRUMENT:FUND1:{share_class}",
                series_id=f"SERIES:FUND1:{share_class}:NAV",
                fund_share_class=share_class,
            )
            for share_class in ("A", "C")
        ]
        self.assertEqual(len({row["logical_fact_key"] for row in bonds}), 2)
        self.assertEqual(len({row["logical_fact_key"] for row in funds}), 2)

    def test_alias_codes_use_nonoverlapping_effective_intervals(self) -> None:
        core = UnifiedDataEntryCore(
            self.registry,
            subject_aliases={
                ("series", "SERIES:ALIAS"): [
                    {
                        "effective_start": "2000-01-01",
                        "effective_end": "2025-12-31",
                        "subject_id": "SERIES:OLD",
                    },
                    {
                        "effective_start": "2026-01-01",
                        "effective_end": "9999-12-31",
                        "subject_id": "SERIES:NEW",
                    },
                ]
            },
        )
        old_record = self.observation(
            subject_id="SERIES:ALIAS",
            observation_date="2025-12-31",
        )
        new_record = self.observation(
            subject_id="SERIES:ALIAS",
            observation_date="2026-01-02",
        )
        self.assertEqual(core.prepare_record(old_record)["series_id"], "SERIES:OLD")
        self.assertEqual(core.prepare_record(new_record)["series_id"], "SERIES:NEW")

    def test_ambiguous_subject_or_missing_dimensions_stays_source_detail(self) -> None:
        ambiguous = self.observation()
        ambiguous.pop("subject_type")
        ambiguous.pop("subject_id")
        ambiguous.pop("series_id")
        result = self.core.prepare_record(ambiguous)
        self.assertEqual(result["data_role"], "source_detail")
        self.assertNotIn("logical_fact_key", result)
        incomplete = self.observation("equity.close")
        incomplete.pop("adjustment_basis")
        result = self.core.prepare_record(incomplete)
        self.assertEqual(result["data_role"], "source_detail")

    def test_native_and_converted_quotes_have_explicit_series_and_evidence(self) -> None:
        native = self.prepared(
            subject_id="SERIES:HK:0005:native_close",
            series_id="SERIES:HK:0005:native_close",
            instrument_id="INSTRUMENT:HK:0005",
            listing_id="LISTING:XHKG:0005",
            currency="HKD",
            quote_basis="native_market_quote",
            conversion_policy="native",
        )
        evidence = {
            "source_currency": "HKD",
            "target_currency": "CNY",
            "fx_rate": "0.92",
            "fx_time": "2026-07-17T16:00:00+08:00",
            "fx_series_id": "SERIES:FX:HKD_CNY:close",
            "fx_source": "official fixing authority",
            "calendar_alignment": "same_hk_session",
            "time_zone_alignment": "Asia/Hong_Kong_to_Asia/Shanghai",
            "formula": "HKD_value * HKD_CNY",
            "rounding": "half_even_6dp",
            "conversion_direction": "multiply",
            "conversion_policy_version": "canonical_display_v1",
        }
        converted = []
        for provider in ("provider one", "provider two"):
            converted.append(
                self.prepared(
                    subject_id="SERIES:HK:0005:cny_display",
                    series_id="SERIES:HK:0005:cny_display",
                    instrument_id="INSTRUMENT:HK:0005",
                    listing_id="LISTING:XHKG:0005",
                    provider=provider,
                    currency="HKD",
                    quote_basis="canonical_converted_display",
                    conversion_policy="canonical_display_v1",
                    target_conversion_currency="CNY",
                    conversion_evidence=evidence,
                )
            )
        self.assertEqual(native["canonical_currency"], "HKD")
        self.assertEqual(converted[0]["canonical_currency"], "CNY")
        self.assertEqual(converted[0]["normalized_value"], 9.2)
        self.assertEqual(converted[0]["logical_fact_key"], converted[1]["logical_fact_key"])
        self.assertNotEqual(
            converted[0]["source_observation_key"], converted[1]["source_observation_key"]
        )
        self.assertNotEqual(native["logical_fact_key"], converted[0]["logical_fact_key"])
        incomplete = self.observation(
            subject_id="SERIES:HK:0005:cny_display",
            series_id="SERIES:HK:0005:cny_display",
            currency="HKD",
            quote_basis="canonical_converted_display",
            conversion_policy="canonical_display_v1",
            target_conversion_currency="CNY",
            conversion_evidence={field: "x" for field in CONVERSION_EVIDENCE_FIELDS[:-1]},
        )
        self.assertEqual(self.core.prepare_record(incomplete)["data_role"], "source_detail")

        canonical = converted[0]
        provider_displays = [
            self.prepared(
                subject_id="SERIES:HK:0005:cny_display",
                series_id="SERIES:HK:0005:cny_display",
                instrument_id="INSTRUMENT:HK:0005",
                listing_id="LISTING:XHKG:0005",
                provider=f"display provider {index}",
                value=value,
                currency="CNY",
                quote_basis="canonical_converted_display",
                conversion_policy="canonical_display_v1",
                provider_converted_display=True,
            )
            for index, value in enumerate((9.19, 9.21), 1)
        ]
        selected, lineage, conflicts = self.core.reconcile([canonical, *provider_displays])
        self.assertEqual(conflicts, [])
        self.assertEqual(selected[0]["normalized_value"], 9.2)
        self.assertEqual(selected[0]["provider_converted_source_detail_count"], 2)
        self.assertEqual(len(lineage[canonical["logical_fact_key"]]), 3)

    def test_adjustment_no_trade_and_unit_rules(self) -> None:
        unadjusted = self.prepared(
            subject_id="SERIES:PRICE:UNADJUSTED",
            series_id="SERIES:PRICE:UNADJUSTED",
            adjustment_basis="unadjusted",
        )
        adjusted = self.prepared(
            subject_id="SERIES:PRICE:ADJUSTED",
            series_id="SERIES:PRICE:ADJUSTED",
            adjustment_basis="split_dividend_adjusted",
        )
        self.assertNotEqual(unadjusted["logical_fact_key"], adjusted["logical_fact_key"])
        no_trade = self.core.prepare_record(self.observation(value=None))
        self.assertEqual(no_trade["data_role"], "source_detail")
        wrong_unit = self.core.prepare_record(self.observation(unit="shares"))
        self.assertEqual(wrong_unit["data_role"], "source_detail")

    def test_series_invariant_dimensions_are_inherited(self) -> None:
        definition = self.registry.resolve("market.close_price")
        record = self.observation()
        metadata = {}
        for field in definition.series_invariant_dimensions:
            metadata[field] = record.pop(field)
        record["series_metadata"] = metadata
        prepared = self.core.prepare_record(record)
        self.assertEqual(prepared["data_role"], "source_observation")
        for field in definition.series_invariant_dimensions:
            self.assertEqual(prepared["dimension_resolution"][field], "series_metadata")

    def test_all_required_unit_conversion_rule_families(self) -> None:
        base = self.registry.resolve("financial.revenue")
        cases = [
            ("identity", {}, Decimal("2")),
            (
                "lots_to_shares",
                {"listing_metadata": {"lot_size": 100}},
                Decimal("200"),
            ),
            ("thousands_to_base", {}, Decimal("2000")),
            ("ten_thousands_to_base", {}, Decimal("20000")),
            ("millions_to_base", {}, Decimal("2000000")),
            ("hundred_millions_to_base", {}, Decimal("200000000")),
            ("billions_to_base", {}, Decimal("2000000000")),
            ("percent_to_decimal", {}, Decimal("0.02")),
            ("basis_points_to_decimal", {}, Decimal("0.0002")),
            ("currency_subunit_to_base", {}, Decimal("0.02")),
            (
                "contract_multiplier",
                {"source_contract": {"contract_multiplier": 10}},
                Decimal("20"),
            ),
        ]
        for family, record, expected in cases:
            rule = {"family": family, "source_units": ["source_unit"]}
            if family == "currency_subunit_to_base":
                rule["subunits_per_base"] = 100
            definition = replace(
                base,
                canonical_unit="target_unit",
                unit_conversion_rules={
                    "accepted_source_units": ["source_unit"],
                    "conversion_rules": [rule],
                    "policy_version": "test_v1",
                },
            )
            result = _unit_conversion(
                Decimal("2"), "source_unit", Decimal("1"), record, definition
            )
            self.assertIsNotNone(result, family)
            self.assertEqual(result[0], expected, family)
            self.assertIn("conversion_evidence_reference", result[1])

    def test_observed_unit_aliases_preserve_numeric_values(self) -> None:
        cases = (
            ("market.close_price", "CNY", "CNY", 10),
            ("equity.close", "CNY/share", "CNY", 10),
            ("fund.nav", "CNY_per_unit", "CNY", 10),
        )
        for metric_id, unit, currency, expected in cases:
            result = self.prepared(
                metric_id,
                value=expected,
                unit=unit,
                currency=currency,
            )
            self.assertEqual(result["normalized_value"], expected, unit)
            self.assertEqual(result["raw_unit"], unit)
            self.assertIn(
                "conversion_evidence_reference", result["normalization"], unit
            )

    def test_v4_financial_unit_semantics_are_not_percentage_ambiguous(self) -> None:
        ratio = self.prepared(
            "financial.roe",
            value="0.25",
            unit="ratio",
            currency=None,
            scale=1,
        )
        percentage_points = self.prepared(
            "financial.roe",
            value="25",
            unit="percent",
            currency=None,
            scale=1,
        )
        self.assertEqual(ratio["canonical_unit"], "decimal_ratio")
        self.assertEqual(ratio["normalized_value"], 0.25)
        self.assertEqual(percentage_points["normalized_value"], 0.25)

    def test_v4_instrument_units_are_distinct(self) -> None:
        self.assertEqual(self.registry.resolve("equity.close").canonical_unit, "currency_per_share")
        self.assertEqual(self.registry.resolve("fund.nav").canonical_unit, "currency_per_fund_unit")
        self.assertEqual(self.registry.resolve("fund.fund_units").canonical_unit, "fund_units")
        self.assertEqual(self.registry.resolve("futures.volume").canonical_unit, "contracts")
        self.assertEqual(self.registry.resolve("index.close").canonical_unit, "index_points")

    def test_scale_is_applied_exactly_once(self) -> None:
        base = self.registry.resolve("financial.revenue")
        definition = replace(
            base,
            canonical_unit="currency",
            unit_conversion_rules={
                "accepted_source_units": ["thousand CNY"],
                "conversion_rules": [
                    {
                        "family": "thousands_to_base",
                        "source_units": ["thousand CNY"],
                    }
                ],
                "policy_version": "test_v3",
            },
        )
        from_label = _unit_conversion(
            Decimal("2"), "thousand CNY", Decimal("1"), {}, definition
        )
        from_raw_scale = _unit_conversion(
            Decimal("2"), "thousand CNY", Decimal("1000"), {}, definition
        )
        conflicting_scale = _unit_conversion(
            Decimal("2"), "thousand CNY", Decimal("1000000"), {}, definition
        )
        self.assertEqual(from_label[0], Decimal("2000"))
        self.assertEqual(from_raw_scale[0], Decimal("2000"))
        self.assertIsNone(conflicting_scale)

    def test_context_conversion_requires_provenance(self) -> None:
        base = self.registry.resolve("market.volume")
        definition = replace(
            base,
            unit_conversion_rules={
                "accepted_source_units": ["lot"],
                "conversion_rules": [
                    {"family": "lots_to_shares", "source_units": ["lot"]}
                ],
                "policy_version": "test_v3",
            },
        )
        accepted = _unit_conversion(
            Decimal("2"),
            "lot",
            Decimal("1"),
            {"market_contract": {"lot_size": 100}},
            definition,
        )
        self.assertEqual(accepted[0], Decimal("200"))
        self.assertEqual(
            accepted[1]["context_evidence_reference"], "market_contract.lot_size"
        )
        self.assertIsNone(
            _unit_conversion(Decimal("2"), "lot", Decimal("1"), {}, definition)
        )
        self.assertIsNone(
            _unit_conversion(
                Decimal("2"), "lot", Decimal("1"), {"lot_size": 100}, definition
            )
        )

    def test_fx_divide_direction_and_rounding(self) -> None:
        evidence = {
            "source_currency": "HKD",
            "target_currency": "CNY",
            "fx_rate": "3",
            "fx_time": "2026-07-17T16:00:00+08:00",
            "fx_series_id": "SERIES:FX:CNY_HKD:close",
            "fx_source": "official fixing authority",
            "calendar_alignment": "same_hk_session",
            "time_zone_alignment": "Asia/Hong_Kong_to_Asia/Shanghai",
            "formula": "HKD_value / CNY_HKD",
            "rounding": "half_even_2dp",
            "conversion_direction": "divide",
            "conversion_policy_version": "canonical_display_v1",
        }
        converted = self.prepared(
            value=10,
            currency="HKD",
            target_conversion_currency="CNY",
            conversion_evidence=evidence,
        )
        self.assertEqual(converted["normalized_value"], 3.33)
        self.assertEqual(converted["canonical_currency"], "CNY")
        fx = converted["normalization"]["currency_conversion"]
        self.assertEqual(fx["conversion_direction"], "divide")
        self.assertEqual(fx["numeric_value_after_fx"], 3.33)

    def test_statement_time_context_version_and_reporting_currency(self) -> None:
        base = {
            "subject_id": "ENTITY:ISSUER1",
            "entity_id": "ENTITY:ISSUER1",
            "period_start": "2026-01-01",
            "period_end": "2026-03-31",
            "publication_date": "2026-04-30",
            "statement_type": "consolidated",
            "statement_period_basis": "single_quarter",
            "report_type": "quarterly",
            "accounting_standard": "IFRS",
            "reporting_currency_basis": "issuer_reporting_currency",
            "currency": "HKD",
        }
        first = self.prepared("financial.revenue", **base)
        later_publication = self.prepared(
            "financial.revenue", **{**base, "publication_date": "2026-05-02"}
        )
        restated = self.prepared(
            "financial.revenue",
            **{**base, "revision_timestamp": "2026-06-01T00:00:00Z", "version": "restated"},
        )
        parent = self.prepared(
            "financial.revenue", **{**base, "statement_type": "parent"}
        )
        ytd = self.prepared(
            "financial.revenue", **{**base, "statement_period_basis": "year_to_date"}
        )
        self.assertEqual(first["logical_fact_key"], later_publication["logical_fact_key"])
        self.assertNotEqual(first["logical_fact_key"], restated["logical_fact_key"])
        self.assertNotEqual(first["logical_fact_key"], parent["logical_fact_key"])
        self.assertNotEqual(first["logical_fact_key"], ytd["logical_fact_key"])
        self.assertEqual(first["canonical_currency"], "HKD")

    def test_bond_rate_and_price_conventions_are_not_automatic_aliases(self) -> None:
        ytm = self.prepared(
            "bond.yield",
            subject_id="SERIES:BOND:1:YTM",
            series_id="SERIES:BOND:1:YTM",
            yield_basis="yield_to_maturity",
            tenor="10Y",
        )
        current = self.prepared(
            "bond.yield",
            subject_id="SERIES:BOND:1:CURRENT_YIELD",
            series_id="SERIES:BOND:1:CURRENT_YIELD",
            yield_basis="current_yield",
            tenor="10Y",
        )
        self.assertNotEqual(ytm["logical_fact_key"], current["logical_fact_key"])
        for unresolved_metric in ("bond.coupon", "bond.clean_price", "bond.dirty_price"):
            with self.assertRaises(UnifiedDataError):
                self.registry.resolve(unresolved_metric)

    def test_fx_direction_location_fixing_and_rate_side_are_distinct(self) -> None:
        usd_cny = self.prepared(
            "usd_cny",
            subject_id="SERIES:FX:USD_CNY:spot_mid",
            series_id="SERIES:FX:USD_CNY:spot_mid",
            base_currency="USD",
            quote_currency="CNY",
            fixing_basis="spot",
            market_location="onshore",
            rate_side="mid",
        )
        cny_usd = self.prepared(
            "usd_cny",
            subject_id="SERIES:FX:CNY_USD:spot_mid",
            series_id="SERIES:FX:CNY_USD:spot_mid",
            base_currency="CNY",
            quote_currency="USD",
            fixing_basis="spot",
            market_location="onshore",
            rate_side="mid",
        )
        cnh = self.prepared(
            "fx.usd_cnh",
            subject_id="SERIES:FX:USD_CNH:spot_mid",
            series_id="SERIES:FX:USD_CNH:spot_mid",
            base_currency="USD",
            quote_currency="CNH",
            fixing_basis="spot",
            market_location="offshore",
            rate_side="mid",
        )
        bid = self.prepared(
            "usd_cny",
            subject_id="SERIES:FX:USD_CNY:spot_bid",
            series_id="SERIES:FX:USD_CNY:spot_bid",
            rate_side="bid",
        )
        self.assertEqual(len({row["logical_fact_key"] for row in (usd_cny, cny_usd, cnh, bid)}), 4)

    def test_macro_index_fund_and_derivative_conventions(self) -> None:
        macro_initial = self.prepared(
            "macro.gdp",
            subject_id="SERIES:MACRO:CN:GDP:Q",
            series_id="SERIES:MACRO:CN:GDP:Q",
            period_end="2026-03-31",
            publication_date="2026-04-20",
            release_version="initial",
            seasonal_adjustment="not_adjusted",
            frequency="quarterly",
            base_year="2020",
        )
        macro_revision = self.prepared(
            "macro.gdp",
            subject_id="SERIES:MACRO:CN:GDP:Q",
            series_id="SERIES:MACRO:CN:GDP:Q",
            period_end="2026-03-31",
            publication_date="2026-05-20",
            release_version="revised",
            revision_timestamp="2026-05-20T00:00:00Z",
            seasonal_adjustment="not_adjusted",
            frequency="quarterly",
            base_year="2020",
        )
        index_price = self.prepared(
            "index.close",
            subject_id="SERIES:INDEX:CSI300:PRICE",
            series_id="SERIES:INDEX:CSI300:PRICE",
            index_variant="price_return",
            return_variant="price_return",
        )
        index_total = self.prepared(
            "index.close",
            subject_id="SERIES:INDEX:CSI300:TOTAL",
            series_id="SERIES:INDEX:CSI300:TOTAL",
            index_variant="total_return",
            return_variant="total_return",
        )
        continuous = self.prepared(
            "futures.settlement_price",
            subject_id="SERIES:FUTURE:AU:CONTINUOUS",
            series_id="SERIES:FUTURE:AU:CONTINUOUS",
            contract_type="continuous",
        )
        deliverable = self.prepared(
            "futures.settlement_price",
            subject_id="SERIES:FUTURE:AU:2412",
            series_id="SERIES:FUTURE:AU:2412",
            contract_type="deliverable",
        )
        self.assertNotEqual(macro_initial["logical_fact_key"], macro_revision["logical_fact_key"])
        self.assertNotEqual(index_price["logical_fact_key"], index_total["logical_fact_key"])
        self.assertNotEqual(continuous["logical_fact_key"], deliverable["logical_fact_key"])

    def test_replay_equal_and_unequal_conflict_handling(self) -> None:
        first = self.prepared(provider="official exchange")
        replay = self.prepared(provider="official exchange")
        same = self.prepared(provider="secondary market source")
        unequal = self.prepared(provider="secondary market source", value=11)
        self.assertEqual(first["source_observation_key"], replay["source_observation_key"])
        selected, lineage, conflicts = self.core.reconcile([first, same])
        self.assertEqual(len(selected), 1)
        self.assertEqual(len(lineage[first["logical_fact_key"]]), 2)
        self.assertEqual(conflicts, [])
        selected, lineage, conflicts = self.core.reconcile([first, unequal])
        self.assertEqual(selected, [])
        self.assertEqual(len(lineage[first["logical_fact_key"]]), 2)
        self.assertEqual(conflicts[0]["classification"], "same_series_version_unequal_values")
        direct = self.prepared(provider="secondary market source", derivation_method="direct")
        derived = self.prepared(provider="official exchange", derivation_method="formula")
        selected, _, conflicts = self.core.reconcile([derived, direct])
        self.assertEqual(conflicts, [])
        self.assertEqual(selected[0]["derivation_method"], "direct")

    def test_expected_denominator_coverage_states(self) -> None:
        expected = {
            "subject_type": "series",
            "subject_id": "SERIES:EXPECTED",
            "metric_id": "market.close_price",
            "expected_next_observation": "2026-07-20",
        }
        missing = self.core.coverage_projection("a_share_listings", expected)
        available = self.core.coverage_projection(
            "a_share_listings", expected, {"logical_fact_key": "key", "fact_count": 1}
        )
        not_applicable = self.core.coverage_projection(
            "a_share_listings", {**expected, "applicable": False}
        )
        self.assertEqual(missing["coverage_state"], "genuinely_missing")
        self.assertEqual(available["coverage_state"], "available")
        self.assertEqual(not_applicable["coverage_state"], "not_applicable")

    def test_local_stop_checkpoint_resume_and_transaction_rollback(self) -> None:
        accepted, rejected = self.core.prepare_batch(
            [self.observation(), {"metric_id": "unknown.metric", "series_id": "SERIES:X"}]
        )
        self.assertEqual(len(accepted), 1)
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0]["local_stop_scope"], "series_id")
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "checkpoint.json"
            self.core.save_checkpoint(checkpoint, {"completed": 7})
            self.assertEqual(self.core.load_checkpoint(checkpoint), {"completed": 7})
        connection = sqlite3.connect(":memory:")
        connection.execute("CREATE TABLE facts(value INTEGER)")
        with self.core.transaction(connection):
            connection.execute("INSERT INTO facts VALUES(1)")
        with self.assertRaises(RuntimeError):
            with self.core.transaction(connection):
                connection.execute("INSERT INTO facts VALUES(2)")
                raise RuntimeError("rollback")
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM facts").fetchone()[0], 1)
        connection.close()


if __name__ == "__main__":
    unittest.main()
