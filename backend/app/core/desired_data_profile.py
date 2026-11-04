"""Durable user intent and scoped bootstrap coverage for first installation.

This module owns product intent and coverage bookkeeping only.  It does not
decide financial identity, acquire source data, or promote facts.  Universe
owners supply the population and identity conclusions recorded here.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from backend.app.core.artifact_io import canonical_json
from backend.app.core.storage_profile import resolve_control_plane_path


PROFILE_SCHEMA = "fr_desired_data_profile_v1"
COVERAGE_SCHEMA = "fr_bootstrap_coverage_contract_v1"
CURRENT_CONFIGURATION_SCHEMA = "fr_current_effective_data_configuration_v1"
CURRENT_CONFIGURATION_ID = "installation"
# These values are persisted source/component scope IDs, not FR Universes.
SUPPORTED_COMPONENT_IDS = frozenset({"CN_PUBLIC_FUND", "CN_A_SHARE"})
SUPPORTED_UNIVERSES = SUPPORTED_COMPONENT_IDS  # v1 profile compatibility
COMPONENT_FINANCIAL_SCOPES = {
    "CN_PUBLIC_FUND": {"universe": "Fund", "region": "China", "classification": "public_fund"},
    "CN_A_SHARE": {"universe": "Equity", "region": "China", "classification": "china_equity"},
}
POPULATION_MODES = frozenset({"explicit_selection", "current_population", "historical_interval_population"})
PROFILE_STATES = frozenset({"enabled", "paused"})
GAP_TYPES = frozenset({
    "source_unsupported", "source_unavailable", "acquisition_retryable",
    "identity_blocked", "semantic_conflict", "validation_failed",
})


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class DesiredUniverseScope:
    """V1 persisted scope; ``universe`` stores a component compatibility ID."""
    universe: str
    state: str
    population_mode: str
    population_spec: Mapping[str, Any]
    data_families: tuple[str, ...]
    history_start: str | None
    history_end: str | None
    full_available_history: bool

    def validate(self) -> None:
        if self.universe not in SUPPORTED_COMPONENT_IDS:
            raise ValueError(f"unsupported bootstrap component scope: {self.universe}")
        if self.state not in PROFILE_STATES:
            raise ValueError(f"unsupported Desired Data Profile state: {self.state}")
        if self.population_mode not in POPULATION_MODES:
            raise ValueError(f"unsupported population mode: {self.population_mode}")
        if not self.data_families:
            raise ValueError("a Desired Data Profile scope requires at least one data family")
        if len(set(self.data_families)) != len(self.data_families):
            raise ValueError("Desired Data Profile data families must be unique")
        if self.full_available_history and (self.history_start or self.history_end):
            raise ValueError("full available history cannot also name a bounded interval")
        if not self.full_available_history:
            if not self.history_start or not self.history_end:
                raise ValueError("bounded history requires both start and end")
            start, end = date.fromisoformat(self.history_start), date.fromisoformat(self.history_end)
            if start > end:
                raise ValueError("Desired Data Profile history interval is reversed")
        if self.population_mode == "explicit_selection" and not self.population_spec.get("selectors"):
            raise ValueError("explicit population requires selectors")


@dataclass(frozen=True)
class DesiredDataProfile:
    profile_id: str
    source_contract_id: str
    source_contract_version: str
    scopes: tuple[DesiredUniverseScope, ...]

    def validate(self) -> None:
        if not self.profile_id or any(token in self.profile_id for token in ("/", "\\", "..")):
            raise ValueError("profile_id must be one path-safe segment")
        if not self.source_contract_id or not self.source_contract_version:
            raise ValueError("source/evidence contract identity is required")
        if not self.scopes:
            raise ValueError("Desired Data Profile has no Universe scopes")
        for scope in self.scopes:
            scope.validate()
        universes = [scope.universe for scope in self.scopes]
        if len(set(universes)) != len(universes):
            raise ValueError("Desired Data Profile contains duplicate Universe scopes")

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema_version": PROFILE_SCHEMA,
            "profile_id": self.profile_id,
            "source_contract_id": self.source_contract_id,
            "source_contract_version": self.source_contract_version,
            "scopes": [asdict(scope) for scope in self.scopes],
        }


def desired_data_profile_from_payload(value: Mapping[str, Any]) -> DesiredDataProfile:
    payload = dict(value)
    schema = payload.pop("schema_version", PROFILE_SCHEMA)
    payload.pop("profile_sha256", None)
    if schema != PROFILE_SCHEMA:
        raise ValueError("unsupported Desired Data Profile schema")
    scopes = tuple(DesiredUniverseScope(
        universe=str(row["universe"]), state=str(row["state"]),
        population_mode=str(row["population_mode"]),
        population_spec=dict(row["population_spec"]),
        data_families=tuple(str(item) for item in row["data_families"]),
        history_start=row.get("history_start"), history_end=row.get("history_end"),
        full_available_history=bool(row["full_available_history"]),
    ) for row in payload.pop("scopes"))
    profile = DesiredDataProfile(scopes=scopes, **payload)
    profile.validate()
    return profile


class DesiredDataProfileRepository:
    """Explicit write owner; reads never create a database or schema."""

    def __init__(self, path: Path | None = None):
        self.path = path or resolve_control_plane_path()

    def _initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS desired_data_profile(
                  profile_id TEXT PRIMARY KEY,
                  schema_version TEXT NOT NULL,
                  profile_sha256 TEXT NOT NULL,
                  profile_json TEXT NOT NULL,
                  updated_at_utc TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS bootstrap_coverage_contract(
                  snapshot_id TEXT PRIMARY KEY,
                  profile_id TEXT NOT NULL,
                  schema_version TEXT NOT NULL,
                  coverage_sha256 TEXT NOT NULL,
                  coverage_json TEXT NOT NULL,
                  recorded_at_utc TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS current_effective_data_configuration(
                  configuration_id TEXT PRIMARY KEY,
                  profile_id TEXT NOT NULL,
                  profile_sha256 TEXT NOT NULL,
                  configuration_json TEXT NOT NULL,
                  updated_at_utc TEXT NOT NULL
                );
                """
            )

    @staticmethod
    def _validated_profile_payload(row: tuple[Any, ...]) -> dict[str, Any]:
        payload = json.loads(str(row[1]))
        if hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest() != str(row[0]):
            raise ValueError("Desired Data Profile digest mismatch")
        desired_data_profile_from_payload(payload)
        return payload

    @staticmethod
    def _current_projection(payload: Mapping[str, Any], *, profile_sha256: str, updated_at_utc: str) -> dict[str, Any]:
        profile = desired_data_profile_from_payload(payload)
        scopes = [
            {
                "universe": scope.universe,
                "state": scope.state,
                "enabled": scope.state == "enabled",
                "population_mode": scope.population_mode,
                "data_families": list(scope.data_families),
            }
            for scope in profile.scopes
        ]
        enabled = sorted(scope["universe"] for scope in scopes if scope["enabled"])
        for scope in scopes:
            scope["component_id"] = scope["universe"]
            scope["financial_scope"] = dict(COMPONENT_FINANCIAL_SCOPES[scope["component_id"]])
        return {
            "schema_version": CURRENT_CONFIGURATION_SCHEMA,
            "authority": "current_effective_data_configuration",
            "status": "configured" if enabled else "no_universe_enabled",
            "scope_status": "configured" if enabled else "no_data_scope_enabled",
            "supported_universes": sorted(SUPPORTED_UNIVERSES),
            "supported_component_ids": sorted(SUPPORTED_COMPONENT_IDS),
            "current_profile_id": profile.profile_id,
            "profile_sha256": profile_sha256,
            "updated_at_utc": updated_at_utc,
            "enabled_universes": enabled,
            "enabled_component_ids": enabled,
            "scopes": scopes,
        }

    def put(self, profile: DesiredDataProfile, *, make_current: bool = False) -> dict[str, Any]:
        payload = profile.payload()
        encoded = canonical_json(payload)
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        self._initialize()
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT profile_sha256 FROM desired_data_profile WHERE profile_id=?",
                (profile.profile_id,),
            ).fetchone()
            if row and str(row[0]) != digest:
                connection.execute(
                    "UPDATE desired_data_profile SET profile_sha256=?,profile_json=?,updated_at_utc=? WHERE profile_id=?",
                    (digest, encoded, _utc_now(), profile.profile_id),
                )
            elif row is None:
                connection.execute(
                    "INSERT INTO desired_data_profile VALUES (?,?,?,?,?)",
                    (profile.profile_id, PROFILE_SCHEMA, digest, encoded, _utc_now()),
                )
            if make_current:
                self._set_current_in_transaction(
                    connection,
                    profile_id=profile.profile_id,
                    profile_sha256=digest,
                    profile_json=encoded,
                )
            connection.commit()
        return {**json.loads(encoded), "profile_sha256": digest}

    @staticmethod
    def _set_current_in_transaction(
        connection: sqlite3.Connection,
        *,
        profile_id: str,
        profile_sha256: str,
        profile_json: str,
    ) -> None:
        updated_at = _utc_now()
        connection.execute(
            "UPDATE current_effective_data_configuration SET profile_id=?,profile_sha256=?,configuration_json=?,updated_at_utc=? WHERE configuration_id=?",
            (profile_id, profile_sha256, profile_json, updated_at, CURRENT_CONFIGURATION_ID),
        )
        if connection.execute(
            "SELECT 1 FROM current_effective_data_configuration WHERE configuration_id=?",
            (CURRENT_CONFIGURATION_ID,),
        ).fetchone() is None:
            connection.execute(
                "INSERT INTO current_effective_data_configuration VALUES (?,?,?,?,?)",
                (CURRENT_CONFIGURATION_ID, profile_id, profile_sha256, profile_json, updated_at),
            )

    def set_current_profile(self, profile_id: str) -> dict[str, Any]:
        """Select one saved profile as the installation's current configuration."""
        self._initialize()
        with closing(sqlite3.connect(self.path)) as connection:
            row = connection.execute(
                "SELECT profile_sha256,profile_json FROM desired_data_profile WHERE profile_id=?",
                (profile_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Desired Data Profile does not exist: {profile_id}")
            payload = self._validated_profile_payload(row)
            self._set_current_in_transaction(
                connection,
                profile_id=profile_id,
                profile_sha256=str(row[0]),
                profile_json=canonical_json(payload),
            )
            connection.commit()
            current = connection.execute(
                "SELECT updated_at_utc FROM current_effective_data_configuration WHERE configuration_id=?",
                (CURRENT_CONFIGURATION_ID,),
            ).fetchone()
        return self._current_projection(payload, profile_sha256=str(row[0]), updated_at_utc=str(current[0]))

    def get(self, profile_id: str) -> dict[str, Any] | None:
        if not self.path.is_file():
            return None
        with closing(sqlite3.connect(f"file:{self.path.resolve().as_posix()}?mode=ro", uri=True)) as connection:
            try:
                row = connection.execute(
                    "SELECT profile_sha256,profile_json FROM desired_data_profile WHERE profile_id=?",
                    (profile_id,),
                ).fetchone()
            except sqlite3.OperationalError as exc:
                if "no such table" in str(exc).lower():
                    return None
                raise
        if not row:
            return None
        payload = json.loads(str(row[1]))
        if hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest() != row[0]:
            raise ValueError("Desired Data Profile digest mismatch")
        return {**payload, "profile_sha256": str(row[0])}

    def current_configuration(self) -> dict[str, Any]:
        """Return the installation-level current configuration projection.

        A missing projection is intentionally not inferred from retained
        profile rows.  Legacy rows therefore fail closed until an explicit
        profile is selected as current.
        """
        if not self.path.is_file():
            return {
                "schema_version": CURRENT_CONFIGURATION_SCHEMA,
                "authority": "current_effective_data_configuration",
                "status": "unconfigured",
                "scope_status": "unconfigured",
                "supported_universes": sorted(SUPPORTED_UNIVERSES),
                "supported_component_ids": sorted(SUPPORTED_COMPONENT_IDS),
                "current_profile_id": None,
                "profile_sha256": None,
                "updated_at_utc": None,
                "enabled_universes": [],
                "enabled_component_ids": [],
                "scopes": [],
            }
        with closing(sqlite3.connect(f"file:{self.path.resolve().as_posix()}?mode=ro", uri=True)) as connection:
            try:
                row = connection.execute(
                    "SELECT profile_id,profile_sha256,configuration_json,updated_at_utc FROM current_effective_data_configuration WHERE configuration_id=?",
                    (CURRENT_CONFIGURATION_ID,),
                ).fetchone()
            except sqlite3.OperationalError as exc:
                if "no such table" in str(exc).lower():
                    row = None
                else:
                    raise
            if row is None:
                try:
                    saved_count = int(connection.execute("SELECT COUNT(*) FROM desired_data_profile").fetchone()[0])
                except sqlite3.OperationalError as exc:
                    if "no such table" in str(exc).lower():
                        saved_count = 0
                    else:
                        raise
                return {
                    "schema_version": CURRENT_CONFIGURATION_SCHEMA,
                    "authority": "current_effective_data_configuration",
                    "status": "authority_unset" if saved_count else "unconfigured",
                    "scope_status": "authority_unset" if saved_count else "unconfigured",
                    "supported_universes": sorted(SUPPORTED_UNIVERSES),
                    "supported_component_ids": sorted(SUPPORTED_COMPONENT_IDS),
                    "current_profile_id": None,
                    "profile_sha256": None,
                    "updated_at_utc": None,
                    "enabled_universes": [],
                    "enabled_component_ids": [],
                    "scopes": [],
                }
        payload = json.loads(str(row[2]))
        if hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest() != str(row[1]):
            raise ValueError("current data configuration digest mismatch")
        profile = desired_data_profile_from_payload(payload)
        if profile.profile_id != str(row[0]):
            raise ValueError("current data configuration profile mismatch")
        return self._current_projection(payload, profile_sha256=str(row[1]), updated_at_utc=str(row[3]))

    def configured_universes(self) -> set[str]:
        """Compatibility name: returns enabled persisted component IDs."""
        return self.configured_component_ids()

    def configured_component_ids(self) -> set[str]:
        """Return only enabled component IDs in the explicit current projection."""
        return set(self.current_configuration()["enabled_component_ids"])

    def is_component_configured(self, component_id: str) -> bool:
        return str(component_id) in self.configured_component_ids()

    def is_universe_configured(self, universe: str) -> bool:
        """Compatibility name; ``universe`` is a persisted component ID."""
        return self.is_component_configured(universe)

    def record_coverage(self, snapshot_id: str, profile_id: str, coverage: Mapping[str, Any]) -> dict[str, Any]:
        if not snapshot_id:
            raise ValueError("coverage requires a snapshot_id")
        gaps = list(coverage.get("gaps") or [])
        unknown = sorted({str(row.get("gap_type")) for row in gaps} - GAP_TYPES)
        if unknown:
            raise ValueError(f"unsupported coverage gap types: {unknown}")
        promoted_blocked = [
            row for row in gaps
            if row.get("gap_type") in {"identity_blocked", "semantic_conflict", "validation_failed"}
            and row.get("promoted_fact_count")
        ]
        if promoted_blocked:
            raise ValueError("unsafe bootstrap gaps cannot contain promoted facts")
        value = {
            "schema_version": COVERAGE_SCHEMA,
            "snapshot_id": snapshot_id,
            "profile_id": profile_id,
            **dict(coverage),
        }
        encoded = canonical_json(value)
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        self._initialize()
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT coverage_sha256 FROM bootstrap_coverage_contract WHERE snapshot_id=?",
                (snapshot_id,),
            ).fetchone()
            if existing and str(existing[0]) != digest:
                connection.rollback()
                raise ValueError("immutable snapshot coverage was changed")
            connection.execute(
                "INSERT OR IGNORE INTO bootstrap_coverage_contract VALUES (?,?,?,?,?,?)",
                (snapshot_id, profile_id, COVERAGE_SCHEMA, digest, encoded, _utc_now()),
            )
            connection.commit()
        return {**value, "coverage_sha256": digest}
