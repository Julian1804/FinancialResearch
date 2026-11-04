"""Accepted China-region Equity foundation and legacy A-share seed access."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from backend.app.core.artifact_io import canonical_json, sha256_file, stable_key, utc_now, write_json_atomic
from backend.app.core.china_equity_identifiers import normalize_listing_code
from backend.app.core.snapshot_manifest import (
    clone_snapshot_from_manifest,
    reconcile_manifest_aggregate_counts,
)

from backend.app.core.storage_profile import (
    resolve_active_snapshot_pointer,
    resolve_control_plane_path,
    resolve_identity_state_backup_root,
    resolve_identity_state_path,
)


FINANCIAL_METRIC_ALIASES = {
    "financial.net_financing_cash_flow": "financial.financing_cash_flow",
    "financial.net_investing_cash_flow": "financial.investing_cash_flow",
    "financial.net_operating_cash_flow": "financial.operating_cash_flow",
    "financial.total_equity": "financial.equity",
}


@dataclass(frozen=True)
class ChinaEquitySubjectBinding:
    exchange: str
    code: str
    entity_id: str
    instrument_id: str
    listing_id: str
    episode_evidence_key: str
    lifecycle_status: str
    listing_start_date: str | None
    listing_end_date: str | None
    code_aliases: tuple[tuple[str, str | None, str | None], ...] = ()


class AcceptedChinaEquityEpisodeIndex:
    """Resolve public exchange aliases only after accepted economic identity exists."""

    def __init__(self, rows: Iterable[ChinaEquitySubjectBinding]):
        self.rows = tuple(rows)
        self.by_exchange_code: dict[tuple[str, str], tuple[ChinaEquitySubjectBinding, ...]] = {}
        pending: dict[tuple[str, str], list[ChinaEquitySubjectBinding]] = {}
        for row in self.rows:
            aliases = row.code_aliases or ((row.code, row.listing_start_date, row.listing_end_date),)
            for code, _effective_from, _effective_to in aliases:
                key = (row.exchange.upper(), normalize_listing_code(row.exchange, code))
                pending.setdefault(key, []).append(row)
        self.by_exchange_code = {
            key: tuple(dict.fromkeys(bindings)) for key, bindings in pending.items()
        }

    @classmethod
    def load(cls, lifecycle_path: Path, identity_reconciliation_path: Path) -> "AcceptedChinaEquityEpisodeIndex":
        identities = json.loads(identity_reconciliation_path.read_text(encoding="utf-8"))
        by_episode = {row["episode_evidence_key"]: row for row in identities["objects"]}
        rows: list[ChinaEquitySubjectBinding] = []
        with lifecycle_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                lifecycle = json.loads(line)
                identity = by_episode[lifecycle["episode_evidence_key"]]
                rows.append(
                    ChinaEquitySubjectBinding(
                        exchange=str(lifecycle["exchange"]).upper(),
                        code=normalize_listing_code(lifecycle["exchange"], identity["code"]),
                        entity_id=identity["entity_id"],
                        instrument_id=identity["instrument_id"],
                        listing_id=identity["listing_id"],
                        episode_evidence_key=lifecycle["episode_evidence_key"],
                        lifecycle_status=lifecycle["lifecycle_status"],
                        listing_start_date=lifecycle.get("listing_start_date"),
                        listing_end_date=lifecycle.get("listing_end_date"),
                        code_aliases=tuple(
                            (
                                normalize_listing_code(lifecycle["exchange"], alias["code"]),
                                alias.get("effective_from"),
                                alias.get("effective_to"),
                            )
                            for alias in lifecycle.get("code_aliases", [])
                        ),
                    )
                )
        # The accepted 5,892-row owner is the seed, not a permanent universe
        # denominator.  Continuing successors must remain internally complete
        # while legitimately growing or ending episodes.
        if not rows or len(by_episode) != len(rows):
            raise ValueError("accepted China Equity lifecycle/identity owner is incomplete")
        return cls(rows)

    @staticmethod
    def _alias_is_effective(row: ChinaEquitySubjectBinding, code: str, effective_at: str) -> bool:
        aliases = row.code_aliases or ((row.code, row.listing_start_date, row.listing_end_date),)
        for alias_code, effective_from, effective_to in aliases:
            if normalize_listing_code(row.exchange, alias_code) != code:
                continue
            if effective_from and effective_at < effective_from:
                continue
            if effective_to and effective_at > effective_to:
                continue
            return True
        return False

    def resolve(self, exchange: str, code: str, effective_at: str | None = None) -> ChinaEquitySubjectBinding:
        key = (exchange.upper(), normalize_listing_code(exchange, code))
        try:
            candidates = self.by_exchange_code[key]
        except KeyError as exc:
            raise KeyError(f"China Equity code is not in the accepted episode owner: {key}") from exc
        if effective_at is not None:
            candidates = tuple(
                row for row in candidates if self._alias_is_effective(row, key[1], effective_at)
            )
        if len(candidates) != 1:
            scope = f" at {effective_at}" if effective_at else " without effective time"
            raise ValueError(
                f"ambiguous accepted China Equity code binding: {key}{scope}; "
                f"candidate_count={len(candidates)}"
            )
        return candidates[0]

    def as_rows(self) -> list[dict[str, Any]]:
        return [row.__dict__.copy() for row in self.rows]


def canonical_financial_metric(metric_id: str) -> str:
    return FINANCIAL_METRIC_ALIASES.get(metric_id, metric_id)


def financial_series_object_key(entity_id: str, metric_id: str, accounting_scope: str) -> str:
    return canonical_json(
        {
            "accounting_scope": accounting_scope,
            "entity_id": entity_id,
            "metric_id": canonical_financial_metric(metric_id),
            "object_type": "financial_metric_series",
            "universe": "a_share",
        }
    )


def financial_logical_fact_key(
    entity_id: str,
    metric_id: str,
    period_end: str,
    version_effective_scope: Mapping[str, Any] | None = None,
) -> str:
    """Return the source-independent identity of one financial fact version.

    An empty scope preserves the accepted historical key contract.  A later
    corrected filing supplies an explicit filing/revision scope so it remains
    distinct from the fact version that the correction supersedes.
    """
    payload: dict[str, Any] = {
        "economic_time": {"primary_role": "period_end", "primary_value": period_end},
        "fact_dimensions": {},
        "metric_id": canonical_financial_metric(metric_id),
        "subject": {"subject_id": entity_id, "subject_type": "entity"},
    }
    if version_effective_scope:
        payload["version_effective_scope"] = dict(version_effective_scope)
    return stable_key(
        "logical_fact",
        payload,
    )


def relationship_id(
    from_type: str,
    from_id: str,
    to_type: str,
    to_id: str,
    relationship_type: str,
    effective_start: str | None = None,
    effective_end: str | None = None,
) -> str:
    return stable_key(
        "subject_relationship",
        {
            "effective_end": effective_end,
            "effective_start": effective_start,
            "from_id": from_id,
            "from_type": from_type,
            "relationship_type": relationship_type,
            "to_id": to_id,
            "to_type": to_type,
        },
    )




def current_foundation_state() -> dict[str, Any]:
    identity_path = resolve_identity_state_path()
    pointer_path = resolve_active_snapshot_pointer()
    pointer = json.loads(pointer_path.read_text(encoding="utf-8")) if pointer_path.is_file() else None
    identity_metadata = None
    assignment_count = 0
    if identity_path.is_file():
        with closing(sqlite3.connect(identity_path)) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute("SELECT * FROM identity_state_metadata WHERE singleton_id=1").fetchone()
            identity_metadata = dict(row) if row else None
            assignment_count = connection.execute("SELECT COUNT(*) FROM identity_decision_assignment").fetchone()[0]
    update_head = None
    control_path = resolve_control_plane_path()
    if control_path.is_file():
        with closing(sqlite3.connect(control_path)) as connection:
            connection.row_factory = sqlite3.Row
            table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='validated_canonical_update_head'"
            ).fetchone()
            if table:
                row = connection.execute(
                    "SELECT * FROM validated_canonical_update_head WHERE universe='CN_A_SHARE'"
                ).fetchone()
                update_head = dict(row) if row else None
    return {
        "status": "ok",
        "identity_state_path": str(identity_path),
        "identity_state_exists": identity_path.is_file(),
        "identity_metadata": identity_metadata,
        "identity_assignment_count": assignment_count,
        "identity_backup_root": str(resolve_identity_state_backup_root()),
        "control_plane_path": str(control_path),
        "validated_a_share_update_head": update_head,
        "active_pointer_path": str(pointer_path),
        "active_pointer": pointer,
        "legacy_sqlite_required": False,
        "archived_updater_required": False,
    }


def derive_coverage_state(
    *,
    applicable: bool,
    observed_fact_count: int,
    source_route_available: bool,
    source_contract_limited: bool,
) -> str:
    """Derive coverage from reality/source conditions, never from a carried label."""
    if not applicable:
        return "not_applicable"
    if observed_fact_count > 0:
        return "available"
    if source_contract_limited or not source_route_available:
        return "provider_no_yield"
    return "genuinely_missing"


def ensure_clean_runtime_dependency(source_text: str) -> None:
    forbidden = (
        "old_monolithic_sqlite",
        "archive/historical_non_authoritative_scripts",
        "archive\\historical_non_authoritative_scripts",
        "fr_update_pipeline1_source_expand1_v1.py",
    )
    found = [token for token in forbidden if token in source_text]
    if found:
        raise ValueError(f"continuing China Equity update path contains legacy runtime dependencies: {found}")


# Historical Python callers retain the original class names; new code imports
# the region-scoped owners above.
AShareSubjectBinding = ChinaEquitySubjectBinding
AuthoritativeAShareIndex = AcceptedChinaEquityEpisodeIndex
