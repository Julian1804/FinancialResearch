"""Current supported financial check scopes for one configured Update action.

The descriptors are application capability routing, not new Universes or
publication components.  The lifecycle consumes them without knowing the
number or geography of future market scopes.
"""

from __future__ import annotations

import hashlib
from typing import Any, Mapping

from backend.app.core.artifact_io import canonical_json


SUPPORTED_SCOPE_ROUTES: tuple[dict[str, Any], ...] = (
    {
        "scope_id": "fund.china.public",
        "component_id": "CN_PUBLIC_FUND",
        "universe": "Fund", "region": "China", "market": "public_fund",
        "market_key": None,
        "supported_families": ("fund_nav", "listed_market_daily"),
        "required_source_roles": ("official_listed_population", "accepted_fund_fact_routes"),
        "optional_source_roles": (),
    },
    {
        "scope_id": "equity.china.mainland",
        "component_id": "CN_A_SHARE",
        "universe": "Equity", "region": "China", "market": "Mainland China",
        "market_key": "mainland_china",
        "supported_families": ("unadjusted_daily_market",),
        "required_source_roles": ("official_current_population", "official_disclosure_index", "unadjusted_daily_for_selected_objects"),
        "optional_source_roles": (),
    },
    {
        "scope_id": "equity.china.hong_kong",
        "component_id": "CN_A_SHARE",
        "universe": "Equity", "region": "China", "market": "Hong Kong",
        "market_key": "hong_kong",
        "supported_families": ("unadjusted_daily_market",),
        "required_source_roles": ("official_current_population", "complete_candidate_inventory", "unadjusted_daily_for_supported_objects"),
        "optional_source_roles": ("secondary_candidate_crosscheck",),
    },
)


def freeze_required_update_scopes(configuration: Mapping[str, Any]) -> dict[str, Any]:
    """Freeze selected, supported scopes before any provider or writer work.

    A configured component with a family the current ordinary Update cannot
    check fails closed instead of silently removing that obligation.
    """
    if configuration.get("authority") != "current_effective_data_configuration" or configuration.get("status") != "configured":
        raise ValueError("current effective data configuration is unavailable or has no enabled scope")
    configured = {str(row["component_id"]): row for row in configuration.get("scopes", [])
                  if row.get("state") == "enabled"}
    if not configured:
        raise ValueError("no enabled data scope is configured")
    supported_components = {str(row["component_id"]) for row in SUPPORTED_SCOPE_ROUTES}
    unknown_components = sorted(set(configured) - supported_components)
    if unknown_components:
        raise ValueError(f"ordinary Update has no capability for configured components: {unknown_components}")
    supported_families: dict[str, set[str]] = {}
    for route in SUPPORTED_SCOPE_ROUTES:
        supported_families.setdefault(str(route["component_id"]), set()).update(route["supported_families"])
    for component_id, row in configured.items():
        unsupported = set(row.get("data_families") or []) - supported_families[component_id]
        if unsupported:
            raise ValueError(f"ordinary Update cannot check configured {component_id} families: {sorted(unsupported)}")
    required = []
    for route in SUPPORTED_SCOPE_ROUTES:
        component = configured.get(str(route["component_id"]))
        if component is None:
            continue
        families = sorted(set(component.get("data_families") or []) & set(route["supported_families"]))
        if families:
            required.append({**route, "selected_data_families": families})
    if not required:
        raise ValueError("configured data families have no supported ordinary Update scope")
    payload = {
        "schema_version": "fr_required_update_scopes_v1",
        "configuration_authority": configuration["authority"],
        "current_profile_id": configuration.get("current_profile_id"),
        "profile_sha256": configuration.get("profile_sha256"),
        "configuration_updated_at_utc": configuration.get("updated_at_utc"),
        "required_scopes": required,
    }
    payload["denominator_sha256"] = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return payload
