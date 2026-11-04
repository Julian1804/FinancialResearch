"""Hong Kong Equity current-security identity and lifecycle ownership.

The HKEX official directory is only a current market inventory.  This owner
therefore accepts rows only after they have been reconciled to FR's retained,
accepted HKEX economic-security/lifecycle reference.  Provider discoveries do
not enter this owner, and an unknown exact listing-start date is accepted only
when the retained lifecycle graph identifies one unique current episode.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from backend.app.core.china_equity_identifiers import normalize_listing_code


OWNER_SCHEMA = "fr_hong_kong_equity_current_ownership_v1"
OWNER_KEY = "hong_kong_equity_authoritative_owner_object_key"
SERIES_FAMILIES = (
    "daily_ohlc",
    "market_trade_amount",
    "market_turnover_rate",
    "market_volume",
)

_INSTRUMENT_TYPES = {
    "ordinary_equity_security": "ordinary_equity_security",
    "listed_investment_company_security": "listed_investment_company_equity_security",
    "trading_only_security_arrangement": "trading_only_equity_security_arrangement",
    "depositary_receipt_security": "equity_depositary_receipt_security",
    "preference_or_preferred_security": "preferred_equity_security",
}


def accepted_hkex_change(record: Any) -> dict[str, Any]:
    """Return accepted HKEX ownership metadata or raise for a non-owner row."""
    if str(record.exchange).upper() != "HKEX":
        raise ValueError("Hong Kong Equity owner accepts HKEX rows only")
    source = dict(record.source_record or {})
    reference = dict(source.get("accepted_reference") or {})
    if not reference:
        raise ValueError("HKEX row is not reconciled to the accepted current reference")
    if not bool(reference.get("counts_as_current_economic_security")):
        raise ValueError("HKEX reference row is not a current economic security")
    if reference.get("fr_identity_treatment") != "create_or_reuse_fr_economic_security_for_listing_lifecycle":
        raise ValueError("HKEX reference row does not authorize identity ownership")
    code = normalize_listing_code("HKEX", record.code)
    if normalize_listing_code("HKEX", reference.get("code")) != code:
        raise ValueError("HKEX directory code conflicts with the accepted reference")
    economic_key = str(reference.get("economic_security_group_key") or "").strip()
    classification = str(reference.get("classification") or "").strip()
    if not economic_key or classification not in _INSTRUMENT_TYPES:
        raise ValueError("HKEX accepted reference lacks an executable economic classification")
    listing_start = record.listing_date
    accepted_listing_id = str(reference.get("accepted_listing_id") or "").strip() or None
    if listing_start:
        episode_key = f"HKEX:{code}:{listing_start}:current"
        start_boundary = "exact"
    else:
        if not (
            reference.get("current_identity_resolution") == "accepted_current_economic_security"
            and reference.get("observation_attribution") == "unique_current_episode_in_accepted_graph"
            and (reference.get("listing_start_boundary") or {}).get("status") == "unknown"
            and accepted_listing_id
        ):
            raise ValueError("HKEX unknown-start row lacks one accepted unique current episode")
        episode_key = accepted_listing_id
        start_boundary = "unknown"
    evidence = {
        "config/fr_hkex_equity_population_reference_v1.json",
        "HKEX official List of Securities",
        *[str(value) for value in reference.get("accepted_identity_evidence_refs") or ()],
    }
    return {
        "episode_evidence_key": episode_key,
        "economic_security_group_key": economic_key,
        "entity_object_key": f"hkex_reference_owner:{economic_key}",
        "instrument_object_key": economic_key,
        "listing_start_boundary": start_boundary,
        "accepted_listing_id": accepted_listing_id,
        "share_type": "HKEX_EQUITY",
        "security_classification": str(reference.get("security_classification") or classification),
        "reference_classification": classification,
        "instrument_economic_object_type": _INSTRUMENT_TYPES[classification],
        "market_jurisdiction": "HK",
        "trading_currency": str(reference.get("currency") or source.get("trading_currency") or "") or None,
        "board": reference.get("sub_category"),
        "isin": reference.get("isin"),
        "provenance_refs": sorted(evidence),
    }


def accepted_hkex_change_or_none(record: Any) -> dict[str, Any] | None:
    try:
        return accepted_hkex_change(record)
    except ValueError:
        return None


def episode_key_for_change(change: Mapping[str, Any]) -> str:
    if str(change.get("exchange") or "").upper() == "HKEX":
        key = str(change.get("episode_evidence_key") or "").strip()
        if not key:
            raise ValueError("accepted HKEX change lacks its lifecycle episode key")
        return key
    exchange = str(change["exchange"]).upper()
    code = normalize_listing_code(exchange, change["code"])
    return f"{exchange}:{code}:{change['listing_date']}:current"


def allocate_accepted_hkex_changes(
    state: Any,
    changes: Iterable[Mapping[str, Any]],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Allocate/reuse all accepted HKEX objects in one durable batch.

    The caller supplies already-adjudicated changes.  This function performs no
    economic inference: it validates the accepted owner metadata, preserves
    opaque installation-local UUIDs, and returns explicit unresolved rows for
    anything outside that boundary.
    """
    accepted: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for raw in changes:
        change = dict(raw)
        if str(change.get("exchange") or "").upper() != "HKEX":
            continue
        required = {
            "episode_evidence_key", "economic_security_group_key",
            "entity_object_key", "instrument_object_key",
            "instrument_economic_object_type", "security_classification",
            "reference_classification", "listing_start_boundary",
            "market_jurisdiction", "provenance_refs",
        }
        if required - set(change) or change.get("market_jurisdiction") != "HK":
            unresolved.append({
                **change,
                "change_type": "accepted_hkex_owner_metadata_incomplete",
                "reason": "HKEX identity allocation requires the accepted market-owner contract",
            })
            continue
        accepted.append(change)

    existing = {
        row.get("decision_attributes", {}).get(OWNER_KEY): row
        for row in state.rows()
        if row.get("decision_attributes", {}).get(OWNER_KEY)
    }
    specifications: list[tuple[dict[str, Any], str, str, str, str]] = []
    seen_keys: set[str] = set()
    for change in accepted:
        episode = str(change["episode_evidence_key"])
        code = normalize_listing_code("HKEX", change["code"])
        specs = [
            ("entity", f"entity:{change['entity_object_key']}", "equity_issuer_or_reference_owner", f"Accepted owner for Hong Kong Equity security {code}"),
            ("instrument", f"instrument:{change['instrument_object_key']}", str(change["instrument_economic_object_type"]), f"Accepted Hong Kong Equity security {code}"),
            ("listing", f"listing:{episode}", "exchange_listing_episode", f"Accepted HKEX listing episode {episode}"),
            *[
                ("series", f"series:{episode}:{family}", "listing_period_equity_daily_series", f"Accepted {family} Series for {episode}")
                for family in SERIES_FAMILIES
            ],
        ]
        for subject_type, object_key, object_type, statement in specs:
            if object_key in seen_keys:
                raise ValueError(f"duplicate HKEX owner object in one allocation batch: {object_key}")
            seen_keys.add(object_key)
            specifications.append((change, subject_type, object_key, object_type, statement))
    missing = []
    for change, subject_type, object_key, object_type, statement in specifications:
        if object_key in existing:
            continue
        missing.append({
            "subject_type": subject_type,
            "accepted_identity_statement": statement,
            "economic_object_type": object_type,
            "decision_attributes": {
                OWNER_KEY: object_key,
                "authoritative_owner_schema": OWNER_SCHEMA,
                "universe": "Equity",
                "region": "CN",
                "market_jurisdiction": "HK",
                "venue": "HKEX",
                "share_type": "HKEX_EQUITY",
                "security_classification": change["security_classification"],
                "reference_classification": change["reference_classification"],
            },
            "provenance_refs": list(change["provenance_refs"]),
        })
    if missing:
        state.create_decisions_batch(missing)
        existing = {
            row.get("decision_attributes", {}).get(OWNER_KEY): row
            for row in state.rows()
            if row.get("decision_attributes", {}).get(OWNER_KEY)
        }

    resolutions: dict[str, dict[str, Any]] = {}
    created_keys = {item["decision_attributes"][OWNER_KEY] for item in missing}
    for change in accepted:
        episode = str(change["episode_evidence_key"])
        keys = {
            "entity": f"entity:{change['entity_object_key']}",
            "instrument": f"instrument:{change['instrument_object_key']}",
            "listing": f"listing:{episode}",
        }
        series_keys = {family: f"series:{episode}:{family}" for family in SERIES_FAMILIES}
        all_keys = [*keys.values(), *series_keys.values()]
        objects = {key: existing[key] for key in all_keys}
        resolution = {
            **change,
            "schema_version": "fr_hong_kong_equity_identity_resolution_v1",
            "code": normalize_listing_code("HKEX", change["code"]),
            "listing_start_date": change.get("listing_date"),
            "listing_end_date": None,
            "lifecycle_status": "current",
            "entity_id": objects[keys["entity"]]["subject_id"],
            "instrument_id": objects[keys["instrument"]]["subject_id"],
            "listing_id": objects[keys["listing"]]["subject_id"],
            "series": {family: objects[key]["subject_id"] for family, key in series_keys.items()},
            "created_assignment_count": sum(key in created_keys for key in all_keys),
            "reused_assignment_count": sum(key not in created_keys for key in all_keys),
        }
        resolutions[episode] = resolution
    return resolutions, unresolved
