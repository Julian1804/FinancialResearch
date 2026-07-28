from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping


LEGACY_STANDARD_FIELDS = frozenset(
    {"canonical" + "_data_id", "natural" + "_key", "investment" + "_id"}
)
SOURCE_FIELDS = (
    "source_provider",
    "source_interface",
    "source_symbol",
    "query_scope",
    "provider_update_id",
    "provider_release_id",
    "source_row_fingerprint",
    "source_field_locator",
    "source_field_name",
    "source_field_path",
    "source_native_observation_id",
    "source_native_report_id",
)
SUBJECT_ID_FIELDS = {
    "entity": "entity_id",
    "instrument": "instrument_id",
    "listing": "listing_id",
    "series": "series_id",
    "person": "person_id",
    "document": "document_id",
}
TIME_ROLE_FIELDS = {
    "observation_date": "observation_date",
    "observation_time": "observation_time",
    "period_start": "period_start",
    "period_end": "period_end",
    "publication_date": "publication_date",
    "publication_time": "publication_time",
    "effective_date": "effective_date",
    "effective_time": "effective_time",
    "revision_timestamp": "revision_timestamp",
    "version_timestamp": "version_timestamp",
    "ingestion_timestamp": "ingestion_timestamp",
    "process_timestamp": "process_timestamp",
}
VERSION_TIME_ROLES = (
    "revision_timestamp",
    "version_timestamp",
)
CONVERSION_EVIDENCE_FIELDS = (
    "source_currency",
    "target_currency",
    "fx_rate",
    "fx_time",
    "fx_series_id",
    "fx_source",
    "calendar_alignment",
    "time_zone_alignment",
    "formula",
    "rounding",
    "conversion_direction",
    "conversion_policy_version",
)
SOURCE_KEY_EXCLUDED_FIELDS = frozenset(
    {
        "metric_id",
        "subject_type",
        "subject_id",
        "entity_id",
        "instrument_id",
        "listing_id",
        "series_id",
        "logical_fact_key",
        "normalized_value",
        "canonical_unit",
        "canonical_currency",
        "currency_role",
        "normalization",
        "conversion_evidence",
        "target_conversion_currency",
        "data_role",
    }
)
PROHIBITED_LOGICAL_DIMENSIONS = frozenset(
    {
        "source_provider",
        "source_interface",
        "source_symbol",
        "query_scope",
        "provider_update_id",
        "source_row_fingerprint",
        "raw_unit",
        "raw_currency",
        "raw_scale",
        "dataset_name",
        "dataset_id",
        "run_id",
        "update_run_id",
        "derivation_method",
        "calculation_method",
    }
)


class UnifiedDataError(ValueError):
    pass


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stable_key(namespace: str, payload: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return f"{namespace}:{digest}"


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _number_for_json(value: Decimal | None) -> int | float | None:
    if value is None:
        return None
    if value == value.to_integral_value():
        return int(value)
    result = float(value)
    return result if math.isfinite(result) else None


def _nonempty(value: Any) -> bool:
    return value not in (None, "")


@dataclass(frozen=True)
class SubjectIdentity:
    subject_type: str
    subject_id: str
    entity_id: str | None = None
    instrument_id: str | None = None
    listing_id: str | None = None
    series_id: str | None = None

    def key_payload(self) -> dict[str, Any]:
        return {
            "subject_type": self.subject_type,
            "subject_id": self.subject_id,
        }


@dataclass(frozen=True)
class EconomicTime:
    primary_role: str
    primary_value: str
    roles: Mapping[str, str]

    def key_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "primary_role": self.primary_role,
            "primary_value": self.primary_value,
        }
        versions = {
            role: self.roles[role]
            for role in VERSION_TIME_ROLES
            if role in self.roles
        }
        if versions:
            payload["version_roles"] = versions
        return payload


@dataclass(frozen=True)
class MetricDefinition:
    metric_id: str
    chinese_name: str
    english_name: str
    financial_definition: str
    domain: str
    required_subject_type: str
    value_type: str
    canonical_unit: str
    currency_role: str
    currency_rule: str
    canonical_scale: Decimal
    date_time_contract: Mapping[str, Any]
    required_series_dimensions: tuple[str, ...]
    series_invariant_dimensions: tuple[str, ...]
    fact_varying_dimensions: tuple[str, ...]
    conditional_series_invariant_dimensions: tuple[str, ...]
    conditional_fact_varying_dimensions: tuple[str, ...]
    not_applicable_dimensions: tuple[str, ...]
    report_accounting_context: str
    adjustment_share_class_rules: str
    allowed_aliases: tuple[str, ...]
    prohibited_automatic_aliases: tuple[str, ...]
    source_field_mapping_evidence: tuple[Mapping[str, Any], ...]
    unit_conversion_rules: Mapping[str, Any]
    currency_conversion_rules: Mapping[str, Any]
    version_effective_date_rules: str
    conflict_tolerance_rules: Mapping[str, Any]
    direct_derived_preference: str
    applicability_coverage_rule: Mapping[str, Any]
    domain_authority_source_rule: Mapping[str, Any]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "MetricDefinition":
        required = {
            "metric_id",
            "chinese_name",
            "english_name",
            "financial_definition",
            "domain",
            "required_subject_type",
            "value_type",
            "canonical_unit",
            "currency_role",
            "currency_rule",
            "canonical_scale",
            "date_time_contract",
            "required_series_dimensions",
            "series_invariant_dimensions",
            "fact_varying_dimensions",
            "report_accounting_context",
            "adjustment_share_class_rules",
            "allowed_aliases",
            "prohibited_automatic_aliases",
            "source_field_mapping_evidence",
            "unit_conversion_rules",
            "currency_conversion_rules",
            "version_effective_date_rules",
            "conflict_tolerance_rules",
            "direct_derived_preference",
            "applicability_coverage_rule",
            "domain_authority_source_rule",
        }
        missing = sorted(required - raw.keys())
        if missing:
            raise UnifiedDataError(f"metric definition missing fields: {missing}")
        subject_type = str(raw["required_subject_type"])
        if subject_type not in SUBJECT_ID_FIELDS:
            raise UnifiedDataError(
                f"{raw['metric_id']} has unsupported required subject type: {subject_type}"
            )
        contract = raw["date_time_contract"]
        if not isinstance(contract, Mapping):
            raise UnifiedDataError(f"{raw['metric_id']} date_time_contract must be an object")
        primary_role = str(contract.get("primary_role") or "")
        if primary_role not in TIME_ROLE_FIELDS:
            raise UnifiedDataError(
                f"{raw['metric_id']} has unsupported primary time role: {primary_role}"
            )
        dimensions = tuple(str(item) for item in raw["required_series_dimensions"])
        series_invariant = tuple(str(item) for item in raw["series_invariant_dimensions"])
        fact_varying = tuple(str(item) for item in raw["fact_varying_dimensions"])
        conditional_series_invariant = tuple(
            str(item) for item in raw.get("conditional_series_invariant_dimensions", [])
        )
        conditional_fact_varying = tuple(
            str(item) for item in raw.get("conditional_fact_varying_dimensions", [])
        )
        not_applicable = tuple(
            str(item) for item in raw.get("not_applicable_dimensions", [])
        )
        if set(series_invariant).intersection(fact_varying):
            raise UnifiedDataError(
                f"{raw['metric_id']} dimension cannot be both invariant and fact-varying"
            )
        if set(series_invariant).union(fact_varying) != set(dimensions):
            raise UnifiedDataError(
                f"{raw['metric_id']} dimension classifications do not cover its contract"
            )
        classified_sets = (
            set(series_invariant),
            set(fact_varying),
            set(conditional_series_invariant),
            set(conditional_fact_varying),
            set(not_applicable),
        )
        for index, left in enumerate(classified_sets):
            for right in classified_sets[index + 1 :]:
                overlap = sorted(left.intersection(right))
                if overlap:
                    raise UnifiedDataError(
                        f"{raw['metric_id']} dimension classification overlap: {overlap}"
                    )
        logical_dimensions = set(dimensions).union(conditional_fact_varying)
        prohibited = sorted(PROHIBITED_LOGICAL_DIMENSIONS.intersection(logical_dimensions))
        if prohibited:
            raise UnifiedDataError(
                f"{raw['metric_id']} uses prohibited logical-fact dimensions: {prohibited}"
            )
        tolerance = raw["conflict_tolerance_rules"]
        if not isinstance(tolerance, Mapping):
            raise UnifiedDataError(f"{raw['metric_id']} tolerance rule must be an object")
        return cls(
            metric_id=str(raw["metric_id"]),
            chinese_name=str(raw["chinese_name"]),
            english_name=str(raw["english_name"]),
            financial_definition=str(raw["financial_definition"]),
            domain=str(raw["domain"]),
            required_subject_type=subject_type,
            value_type=str(raw["value_type"]),
            canonical_unit=str(raw["canonical_unit"]),
            currency_role=str(raw["currency_role"]),
            currency_rule=str(raw["currency_rule"]),
            canonical_scale=Decimal(str(raw["canonical_scale"])),
            date_time_contract=dict(contract),
            required_series_dimensions=dimensions,
            series_invariant_dimensions=series_invariant,
            fact_varying_dimensions=fact_varying,
            conditional_series_invariant_dimensions=conditional_series_invariant,
            conditional_fact_varying_dimensions=conditional_fact_varying,
            not_applicable_dimensions=not_applicable,
            report_accounting_context=str(raw["report_accounting_context"]),
            adjustment_share_class_rules=str(raw["adjustment_share_class_rules"]),
            allowed_aliases=tuple(str(item) for item in raw["allowed_aliases"]),
            prohibited_automatic_aliases=tuple(
                str(item) for item in raw["prohibited_automatic_aliases"]
            ),
            source_field_mapping_evidence=tuple(raw["source_field_mapping_evidence"]),
            unit_conversion_rules=dict(raw["unit_conversion_rules"]),
            currency_conversion_rules=dict(raw["currency_conversion_rules"]),
            version_effective_date_rules=str(raw["version_effective_date_rules"]),
            conflict_tolerance_rules=dict(tolerance),
            direct_derived_preference=str(raw["direct_derived_preference"]),
            applicability_coverage_rule=dict(raw["applicability_coverage_rule"]),
            domain_authority_source_rule=dict(raw["domain_authority_source_rule"]),
        )

    @property
    def primary_time_role(self) -> str:
        return str(self.date_time_contract["primary_role"])


class MetricRegistry:
    def __init__(self, definitions: Iterable[Mapping[str, Any]]) -> None:
        parsed = [MetricDefinition.from_dict(item) for item in definitions]
        self._definitions = {item.metric_id: item for item in parsed}
        if len(self._definitions) != len(parsed):
            raise UnifiedDataError("duplicate metric_id in metric registry")
        self._aliases: dict[str, str] = {}
        self._prohibited_aliases: set[str] = set()
        for definition in parsed:
            self._prohibited_aliases.update(definition.prohibited_automatic_aliases)
            for alias in definition.allowed_aliases:
                existing = self._aliases.get(alias)
                if existing and existing != definition.metric_id:
                    raise UnifiedDataError(f"ambiguous allowed metric alias: {alias}")
                self._aliases[alias] = definition.metric_id

    @classmethod
    def load(cls, path: Path) -> "MetricRegistry":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != "fr_unified_metric_registry_v1":
            raise UnifiedDataError("unsupported metric registry schema")
        return cls(payload["metrics"])

    def resolve(self, metric_id: str) -> MetricDefinition:
        if metric_id in self._definitions:
            return self._definitions[metric_id]
        if metric_id in self._prohibited_aliases:
            raise UnifiedDataError(f"prohibited automatic metric alias: {metric_id}")
        resolved = self._aliases.get(metric_id, metric_id)
        try:
            return self._definitions[resolved]
        except KeyError as exc:
            raise UnifiedDataError(f"unknown metric_id: {metric_id}") from exc

    def definitions(self) -> tuple[MetricDefinition, ...]:
        return tuple(self._definitions[key] for key in sorted(self._definitions))

    def __len__(self) -> int:
        return len(self._definitions)


def resolve_subject(
    record: Mapping[str, Any], definition: MetricDefinition
) -> SubjectIdentity | None:
    subject_type = record.get("subject_type")
    subject_id = record.get("subject_id")
    if not _nonempty(subject_type) or not _nonempty(subject_id):
        return None
    subject_type = str(subject_type)
    subject_id = str(subject_id)
    if subject_type != definition.required_subject_type:
        raise UnifiedDataError(
            f"{definition.metric_id} requires subject_type={definition.required_subject_type}"
        )
    id_field = SUBJECT_ID_FIELDS.get(subject_type)
    if id_field is None:
        raise UnifiedDataError(f"unsupported subject_type: {subject_type}")
    if str(record.get(id_field) or "") != subject_id:
        raise UnifiedDataError(f"{subject_type} subject_id must equal {id_field}")
    return SubjectIdentity(
        subject_type=subject_type,
        subject_id=subject_id,
        entity_id=str(record["entity_id"]) if _nonempty(record.get("entity_id")) else None,
        instrument_id=(
            str(record["instrument_id"]) if _nonempty(record.get("instrument_id")) else None
        ),
        listing_id=str(record["listing_id"]) if _nonempty(record.get("listing_id")) else None,
        series_id=str(record["series_id"]) if _nonempty(record.get("series_id")) else None,
    )


def resolve_economic_time(
    record: Mapping[str, Any], definition: MetricDefinition
) -> EconomicTime | None:
    primary_role = definition.primary_time_role
    primary_field = TIME_ROLE_FIELDS[primary_role]
    primary_value = record.get(primary_field)
    if not _nonempty(primary_value):
        return None
    roles = {
        role: str(record[field])
        for role, field in TIME_ROLE_FIELDS.items()
        if _nonempty(record.get(field))
    }
    return EconomicTime(primary_role, str(primary_value), roles)


def _required_dimensions(
    record: Mapping[str, Any], definition: MetricDefinition
) -> tuple[dict[str, Any], dict[str, str]] | None:
    inherited = (
        record.get("series_metadata")
        if isinstance(record.get("series_metadata"), Mapping)
        else {}
    )
    dimensions: dict[str, Any] = {}
    sources: dict[str, str] = {}
    for field in definition.required_series_dimensions:
        value = record.get(field)
        source = "fact"
        if not _nonempty(value):
            value = inherited.get(field)
            source = "series_metadata"
        if not _nonempty(value):
            return None
        dimensions[field] = value
        sources[field] = source
    for field in (
        *definition.conditional_series_invariant_dimensions,
        *definition.conditional_fact_varying_dimensions,
    ):
        value = record.get(field)
        source = "fact"
        if not _nonempty(value):
            value = inherited.get(field)
            source = "series_metadata"
        if _nonempty(value):
            dimensions[field] = value
            sources[field] = source
    return dimensions, sources


def _source_authority_rank(record: Mapping[str, Any], definition: MetricDefinition) -> int:
    trace = record.get("source_trace") if isinstance(record.get("source_trace"), Mapping) else {}
    source = " ".join(
        str(record.get(field, trace.get(field, ""))).lower()
        for field in ("source_provider", "source_interface")
    )
    authorities = definition.domain_authority_source_rule.get("authority_order", [])
    for rank, authority in enumerate(authorities):
        terms = authority if isinstance(authority, list) else [authority]
        if any(str(term).lower() in source for term in terms):
            return rank
    return len(authorities) + 1


def _direct_rank(record: Mapping[str, Any]) -> int:
    method = str(record.get("derivation_method", record.get("calculation_method", ""))).lower()
    return 1 if any(term in method for term in ("deriv", "formula", "calcul")) else 0


def _values_equal(
    left: Mapping[str, Any], right: Mapping[str, Any], definition: MetricDefinition
) -> bool:
    if left.get("canonical_unit") != right.get("canonical_unit"):
        return False
    if left.get("canonical_currency") != right.get("canonical_currency"):
        return False
    left_value = _decimal(left.get("normalized_value"))
    right_value = _decimal(right.get("normalized_value"))
    if left_value is None or right_value is None:
        return left.get("normalized_value") == right.get("normalized_value")
    absolute = Decimal(str(definition.conflict_tolerance_rules.get("absolute", "0")))
    relative = Decimal(str(definition.conflict_tolerance_rules.get("relative", "0")))
    difference = abs(left_value - right_value)
    scale = max(abs(left_value), abs(right_value), Decimal(1))
    return difference <= max(absolute, relative * scale)


def _matching_unit_rule(
    raw_unit: str, definition: MetricDefinition, record: Mapping[str, Any]
) -> Mapping[str, Any] | None:
    trace = record.get("source_trace") if isinstance(record.get("source_trace"), Mapping) else {}
    source_interface = str(record.get("source_interface") or trace.get("source_interface") or "")
    for rule in definition.unit_conversion_rules.get("conversion_rules", []):
        if not isinstance(rule, Mapping):
            continue
        source_units = {str(item) for item in rule.get("source_units", [])}
        source_interfaces = {str(item) for item in rule.get("source_interfaces", [])}
        if raw_unit in source_units and (
            not source_interfaces or source_interface in source_interfaces
        ):
            return rule
    return None


def _context_multiplier(
    record: Mapping[str, Any], factor_name: str
) -> tuple[Decimal, str] | None:
    for container_name in (
        "listing_metadata",
        "instrument_metadata",
        "market_contract",
        "source_contract",
    ):
        container = record.get(container_name)
        if isinstance(container, Mapping):
            value = _decimal(container.get(factor_name))
            if value is not None and value > 0:
                return value, f"{container_name}.{factor_name}"
    value = _decimal(record.get(factor_name))
    provenance = record.get(f"{factor_name}_source")
    if value is not None and value > 0 and _nonempty(provenance):
        return value, str(provenance)
    return None


def _single_scale_factor(
    raw_scale: Decimal,
    canonical_scale: Decimal,
    unit_multiplier: Decimal,
) -> tuple[Decimal, str] | None:
    if raw_scale == Decimal(1):
        return unit_multiplier / canonical_scale, "unit_label_multiplier"
    if raw_scale == unit_multiplier:
        return raw_scale / canonical_scale, "raw_scale_multiplier"
    return None


def _unit_conversion(
    numeric: Decimal,
    raw_unit: str,
    raw_scale: Decimal,
    record: Mapping[str, Any],
    definition: MetricDefinition,
) -> tuple[Decimal, dict[str, Any]] | None:
    rule = _matching_unit_rule(raw_unit, definition, record)
    family = str(rule.get("family")) if rule else "identity"
    accepted = {str(item) for item in definition.unit_conversion_rules.get("accepted_source_units", [])}
    configured_rules = definition.unit_conversion_rules.get("conversion_rules", [])
    if configured_rules and rule is None:
        return None
    if rule is None and accepted and raw_unit not in accepted:
        return None
    factor = raw_scale / definition.canonical_scale
    formula = "raw_value * raw_scale / canonical_scale"
    scale_application = "raw_scale_multiplier"
    context_evidence = None
    if family == "identity":
        pass
    elif family == "lots_to_shares":
        factor_field = str(rule.get("factor_field") or "lot_size")
        resolved = _context_multiplier(record, factor_field)
        if resolved is None:
            return None
        lot_size, context_evidence = resolved
        factor *= lot_size
        formula = "raw_value * raw_scale * lot_size / canonical_scale"
    elif family in {
        "thousands_to_base",
        "ten_thousands_to_base",
        "millions_to_base",
        "hundred_millions_to_base",
        "billions_to_base",
    }:
        magnitude = {
            "thousands_to_base": Decimal(1000),
            "ten_thousands_to_base": Decimal(10000),
            "millions_to_base": Decimal(1000000),
            "hundred_millions_to_base": Decimal(100000000),
            "billions_to_base": Decimal(1000000000),
        }[family]
        scale_result = _single_scale_factor(
            raw_scale, definition.canonical_scale, magnitude
        )
        if scale_result is None:
            return None
        factor, scale_application = scale_result
        formula = f"raw_value * {magnitude} / canonical_scale (exactly once)"
    elif family == "percent_to_decimal":
        scale_result = _single_scale_factor(
            raw_scale, definition.canonical_scale, Decimal("0.01")
        )
        if scale_result is None:
            return None
        factor, scale_application = scale_result
        formula = "raw_value * 0.01 / canonical_scale (exactly once)"
    elif family == "basis_points_to_decimal":
        scale_result = _single_scale_factor(
            raw_scale, definition.canonical_scale, Decimal("0.0001")
        )
        if scale_result is None:
            return None
        factor, scale_application = scale_result
        formula = "raw_value * 0.0001 / canonical_scale (exactly once)"
    elif family == "currency_subunit_to_base":
        subunits = _decimal(rule.get("subunits_per_base"))
        if not subunits:
            return None
        factor /= subunits
        formula = "raw_value * raw_scale / subunits_per_base / canonical_scale"
    elif family == "contract_multiplier":
        factor_field = str(rule.get("factor_field") or "contract_multiplier")
        resolved = _context_multiplier(record, factor_field)
        if resolved is None:
            return None
        multiplier, context_evidence = resolved
        factor *= multiplier
        formula = "raw_value * raw_scale * contract_multiplier / canonical_scale"
    else:
        return None
    return numeric * factor, {
        "rule_family": family,
        "raw_unit": raw_unit,
        "raw_scale": _number_for_json(raw_scale),
        "canonical_unit": definition.canonical_unit,
        "canonical_scale": _number_for_json(definition.canonical_scale),
        "conversion_rule": dict(rule) if rule is not None else {"family": "identity"},
        "formula": formula,
        "conversion_factor": str(factor),
        "scale_application": scale_application,
        "policy_version": definition.unit_conversion_rules.get(
            "policy_version", "fr_unit_normalization_v4"
        ),
        "conversion_evidence_reference": (
            rule.get("evidence_source")
            if rule and rule.get("evidence_source")
            else f"metrics_registry:{definition.metric_id}:{family}"
        ),
        "context_evidence_reference": context_evidence,
    }


def _round_converted(value: Decimal, rounding: Any) -> Decimal | None:
    text = str(rounding).lower()
    digits = "".join(character for character in text if character.isdigit())
    if not digits:
        return None
    places = int(digits)
    quantum = Decimal(1).scaleb(-places)
    mode = ROUND_HALF_EVEN if "half_even" in text else ROUND_HALF_UP
    return value.quantize(quantum, rounding=mode)


def _normalize_representation(
    record: dict[str, Any], definition: MetricDefinition
) -> bool:
    raw_value = record.pop("value", record.get("raw_value"))
    raw_unit = record.pop("unit", record.get("raw_unit"))
    raw_currency = record.pop("currency", record.get("raw_currency"))
    raw_scale = record.pop("scale", record.get("raw_scale", 1))
    record.update(
        {
            "raw_value": raw_value,
            "raw_unit": raw_unit,
            "raw_currency": raw_currency,
            "raw_scale": raw_scale,
        }
    )
    if raw_value is None or not _nonempty(raw_unit):
        return False
    numeric = _decimal(raw_value)
    source_scale = _decimal(raw_scale)
    interface = str(
        record.get("source_interface")
        or (
            record.get("source_trace", {}).get("source_interface")
            if isinstance(record.get("source_trace"), Mapping)
            else ""
        )
    )
    scale_overrides = definition.unit_conversion_rules.get(
        "source_interface_scale_overrides", {}
    )
    override = scale_overrides.get(interface) if isinstance(scale_overrides, Mapping) else None
    if isinstance(override, Mapping):
        permitted_units = {str(item) for item in override.get("source_units", [])}
        if not permitted_units or str(raw_unit) in permitted_units:
            source_scale = _decimal(override.get("effective_raw_scale"))
    if definition.value_type == "number" and (numeric is None or source_scale is None):
        return False
    unit_result = (
        _unit_conversion(numeric, str(raw_unit), source_scale, record, definition)
        if numeric is not None and source_scale is not None
        else None
    )
    if definition.value_type == "number" and unit_result is None:
        return False
    normalized, normalization = unit_result if unit_result else (None, {})
    if isinstance(override, Mapping) and source_scale is not None:
        normalization["source_scale_contract_override"] = {
            "source_interface": interface,
            "source_raw_scale": raw_scale,
            "effective_raw_scale": str(source_scale),
            "evidence_source": override.get("evidence_source"),
        }
    currency_rule = definition.currency_rule
    if currency_rule == "not_applicable":
        canonical_currency = "not_applicable"
    elif currency_rule in {"preserve_source_currency", "reporting_currency"}:
        if not _nonempty(raw_currency):
            return False
        canonical_currency = str(raw_currency)
    elif currency_rule == "explicit_currency_pair_basis":
        if not all(_nonempty(record.get(field)) for field in ("base_currency", "quote_currency")):
            return False
        canonical_currency = "not_applicable"
    else:
        canonical_currency = currency_rule

    target = record.get("target_conversion_currency")
    if _nonempty(target) and str(target) != str(canonical_currency):
        evidence = record.get("conversion_evidence")
        if not isinstance(evidence, Mapping):
            return False
        if any(not _nonempty(evidence.get(field)) for field in CONVERSION_EVIDENCE_FIELDS):
            return False
        fx_rate = _decimal(evidence.get("fx_rate"))
        if normalized is None or fx_rate is None or fx_rate == 0:
            return False
        direction = str(evidence.get("conversion_direction")).lower()
        pre_fx_value = normalized
        if direction == "multiply":
            normalized *= fx_rate
        elif direction == "divide":
            normalized /= fx_rate
        else:
            return False
        rounded = _round_converted(normalized, evidence.get("rounding"))
        if rounded is None:
            return False
        normalized = rounded
        canonical_currency = str(target)
        normalization["currency_conversion"] = {
            field: evidence.get(field) for field in CONVERSION_EVIDENCE_FIELDS
        }
        normalization["currency_conversion"].update(
            {
                "numeric_value_before_fx": _number_for_json(pre_fx_value),
                "numeric_value_after_fx": _number_for_json(normalized),
                "target_currency": canonical_currency,
            }
        )
    record["normalized_value"] = (
        _number_for_json(normalized) if normalized is not None else raw_value
    )
    record["canonical_unit"] = definition.canonical_unit
    record["canonical_currency"] = canonical_currency
    record["currency_role"] = definition.currency_role
    normalization["registry_metric_id"] = definition.metric_id
    normalization["policy"] = definition.unit_conversion_rules.get("policy")
    record["normalization"] = normalization
    return True


def build_source_observation_key(
    record: Mapping[str, Any],
) -> str:
    trace = record.get("source_trace") if isinstance(record.get("source_trace"), Mapping) else {}
    payload: dict[str, Any] = {}
    for field in SOURCE_FIELDS:
        value = record.get(field, trace.get(field))
        if _nonempty(value):
            payload[field] = value
    if not payload:
        payload["source_native_record"] = {
            key: value
            for key, value in record.items()
            if key not in SOURCE_KEY_EXCLUDED_FIELDS
        }
    return stable_key("source_observation", payload)


def build_logical_fact_key(
    record: Mapping[str, Any], definition: MetricDefinition
) -> str:
    subject = resolve_subject(record, definition)
    economic_time = resolve_economic_time(record, definition)
    dimension_result = _required_dimensions(record, definition)
    if subject is None:
        raise UnifiedDataError(f"{definition.metric_id} has no explicit financial subject")
    if economic_time is None:
        raise UnifiedDataError(
            f"{definition.metric_id} requires {definition.primary_time_role}"
        )
    if dimension_result is None:
        raise UnifiedDataError(f"{definition.metric_id} is missing required series dimensions")
    dimensions, _ = dimension_result
    payload = {
        "subject": subject.key_payload(),
        "metric_id": definition.metric_id,
        "economic_time": economic_time.key_payload(),
        "fact_dimensions": {
            field: dimensions[field]
            for field in (
                *definition.fact_varying_dimensions,
                *definition.conditional_fact_varying_dimensions,
            )
            if field in dimensions
        },
    }
    return stable_key("logical_fact", payload)


def prepare_source_record(
    raw_record: Mapping[str, Any],
    registry: MetricRegistry,
    *,
    permit_source_detail_without_metric: bool = True,
) -> dict[str, Any]:
    record = dict(raw_record)
    legacy = sorted(LEGACY_STANDARD_FIELDS.intersection(record))
    if legacy:
        raise UnifiedDataError(f"legacy fields are forbidden in the unified write path: {legacy}")
    source_observation_key = build_source_observation_key(record)
    metric_id = record.get("metric_id")
    if not _nonempty(metric_id):
        if not permit_source_detail_without_metric:
            raise UnifiedDataError("standard fact has no metric_id")
        record["data_role"] = "source_detail"
        record["source_observation_key"] = source_observation_key
        return record

    definition = registry.resolve(str(metric_id))
    record["metric_id"] = definition.metric_id
    subject = resolve_subject(record, definition)
    economic_time = resolve_economic_time(record, definition)
    dimensions = _required_dimensions(record, definition)
    if subject is None or economic_time is None or dimensions is None:
        record["data_role"] = "source_detail"
        record["source_observation_key"] = source_observation_key
        return record
    _, dimension_sources = dimensions
    record["dimension_resolution"] = dimension_sources

    record["data_role"] = "source_observation"
    if not _normalize_representation(record, definition):
        record["data_role"] = "source_detail"
        record["source_observation_key"] = source_observation_key
        return record
    record["source_observation_key"] = source_observation_key
    record["logical_fact_key"] = build_logical_fact_key(record, definition)
    return record


def validate_new_write(record: Mapping[str, Any], registry: MetricRegistry) -> None:
    legacy = sorted(LEGACY_STANDARD_FIELDS.intersection(record))
    if legacy:
        raise UnifiedDataError(f"legacy standard fields are forbidden: {legacy}")
    metric_id = record.get("metric_id")
    if not _nonempty(metric_id):
        return
    definition = registry.resolve(str(metric_id))
    if record.get("data_role") == "source_detail":
        if not record.get("source_observation_key"):
            raise UnifiedDataError("source detail missing source_observation_key")
        return
    resolve_subject(record, definition)
    resolve_economic_time(record, definition)
    for field in ("source_observation_key", "logical_fact_key"):
        if not record.get(field):
            raise UnifiedDataError(f"standard fact missing {field}")
    for field in (
        "raw_value",
        "raw_unit",
        "raw_currency",
        "raw_scale",
        "normalized_value",
        "canonical_unit",
        "canonical_currency",
        "currency_role",
    ):
        if field not in record:
            raise UnifiedDataError(f"standard fact missing {field}")


class UnifiedDataEntryCore:
    """Authoritative finance-first entry point for active project writers."""

    def __init__(
        self,
        registry: MetricRegistry,
        *,
        subject_aliases: Mapping[tuple[str, str], Any] | None = None,
    ) -> None:
        self.registry = registry
        self.subject_aliases = dict(subject_aliases or {})

    def _resolve_subject_alias(
        self,
        subject_type: str,
        subject_id: str,
        economic_time: EconomicTime | None,
    ) -> str | None:
        candidate = self.subject_aliases.get((subject_type, subject_id))
        if isinstance(candidate, str):
            return candidate
        if not isinstance(candidate, (list, tuple)) or economic_time is None:
            return None
        matches: list[str] = []
        point = economic_time.primary_value
        for interval in candidate:
            if not isinstance(interval, Mapping):
                continue
            start = str(interval.get("effective_start") or "")
            end = str(interval.get("effective_end") or "9999-12-31")
            canonical_id = interval.get("subject_id")
            if canonical_id and start <= point <= end:
                matches.append(str(canonical_id))
        if len(matches) > 1:
            raise UnifiedDataError("subject alias has overlapping effective intervals")
        return matches[0] if matches else None

    def prepare_record(self, record: Mapping[str, Any]) -> dict[str, Any]:
        prepared = prepare_source_record(record, self.registry)
        definition = (
            self.registry.resolve(str(prepared["metric_id"]))
            if _nonempty(prepared.get("metric_id"))
            else None
        )
        if definition is not None and prepared.get("subject_type") and prepared.get("subject_id"):
            alias_key = (str(prepared["subject_type"]), str(prepared["subject_id"]))
            economic_time = resolve_economic_time(prepared, definition)
            resolved = self._resolve_subject_alias(*alias_key, economic_time)
            if resolved:
                id_field = SUBJECT_ID_FIELDS[str(prepared["subject_type"])]
                prepared["subject_id"] = resolved
                prepared[id_field] = resolved
                if prepared.get("logical_fact_key"):
                    prepared["logical_fact_key"] = build_logical_fact_key(prepared, definition)
        validate_new_write(prepared, self.registry)
        return prepared

    def prepare_batch(
        self, records: Iterable[Mapping[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        accepted: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        for index, record in enumerate(records):
            try:
                accepted.append(self.prepare_record(record))
            except Exception as exc:
                rejected.append(
                    {
                        "row_index": index,
                        "error": str(exc),
                        "local_stop_scope": next(
                            (
                                scope
                                for scope in ("series_id", "listing_id", "instrument_id", "entity_id")
                                if _nonempty(record.get(scope))
                            ),
                            "row",
                        ),
                    }
                )
        return accepted, rejected

    def reconcile(
        self, observations: Iterable[Mapping[str, Any]]
    ) -> tuple[
        list[dict[str, Any]],
        dict[str, list[dict[str, Any]]],
        list[dict[str, Any]],
    ]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for observation in observations:
            logical_key = str(observation.get("logical_fact_key") or "")
            if logical_key:
                grouped.setdefault(logical_key, []).append(dict(observation))
        selected: list[dict[str, Any]] = []
        lineage: dict[str, list[dict[str, Any]]] = {}
        conflicts: list[dict[str, Any]] = []
        for logical_key, rows in grouped.items():
            definition = self.registry.resolve(str(rows[0]["metric_id"]))
            lineage[logical_key] = rows
            candidates = [
                row
                for row in rows
                if not row.get("provider_converted_display")
                or row.get("provider_methodology_is_research_series")
            ]
            if not candidates:
                conflicts.append(
                    {
                        "logical_fact_key": logical_key,
                        "metric_id": definition.metric_id,
                        "classification": "provider_converted_source_detail_only",
                        "source_observation_count": len(rows),
                    }
                )
                continue
            if not all(
                _values_equal(candidates[0], row, definition)
                for row in candidates[1:]
            ):
                conflicts.append(
                    {
                        "logical_fact_key": logical_key,
                        "metric_id": definition.metric_id,
                        "classification": "same_series_version_unequal_values",
                        "source_observation_count": len(candidates),
                    }
                )
                continue
            candidates.sort(
                key=lambda row: (
                    _direct_rank(row),
                    _source_authority_rank(row, definition),
                    str(row.get("source_observation_key") or ""),
                )
            )
            fact = dict(candidates[0])
            fact["data_role"] = "standard_fact"
            fact["same_value_support_count"] = len(candidates)
            fact["provider_converted_source_detail_count"] = len(rows) - len(candidates)
            selected.append(fact)
        return selected, lineage, conflicts

    def coverage_projection(
        self,
        universe: str,
        expected: Mapping[str, Any],
        observed: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        subject_type = str(expected.get("subject_type") or "")
        subject_id = str(expected.get("subject_id") or "")
        metric_id = str(expected.get("metric_id") or "")
        applicable = bool(expected.get("applicable", True))
        state = "genuinely_missing"
        fact_count = 0
        min_time = None
        max_time = None
        if not applicable:
            state = "not_applicable"
        elif not subject_type or not subject_id:
            state = "subject_unresolved"
        elif observed:
            fact_count = int(observed.get("fact_count", 1 if observed.get("logical_fact_key") else 0))
            state = str(observed.get("coverage_state") or ("available" if fact_count else "source_detail_only"))
            min_time = observed.get("min_time")
            max_time = observed.get("max_time")
        return {
            "universe": universe,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "metric_id": metric_id,
            "coverage_state": state,
            "fact_count": fact_count,
            "min_time": min_time,
            "max_time": max_time,
            "expected_next_observation": expected.get("expected_next_observation"),
            "read_model_state": "read_model_stale",
        }

    @staticmethod
    def load_checkpoint(path: Path) -> dict[str, Any]:
        if not path.is_file():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise UnifiedDataError("checkpoint must be a JSON object")
        return payload

    @staticmethod
    def save_checkpoint(path: Path, payload: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(
                    json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
                )
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        except Exception:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise

    @contextmanager
    def transaction(self, connection: Any):
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield connection
        except Exception:
            connection.rollback()
            raise
        else:
            connection.commit()


def write_ndjson_atomic(
    path: Path, records: Iterable[Mapping[str, Any]]
) -> tuple[int, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    count = 0
    digest = hashlib.sha256()
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            for record in records:
                line = canonical_json(record) + "\n"
                handle.write(line)
                digest.update(line.encode("utf-8"))
                count += 1
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise
    return count, digest.hexdigest()
