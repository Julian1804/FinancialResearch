"""Minimum release-pinned China Equity serving contract.

The contract serves accepted China-region Equity daily
market Series.  Exchange codes are effective aliases used for discovery; every
data read is performed against the durable listing and Series identities bound
to one immutable serving release.
"""

from __future__ import annotations

import json
import base64
import binascii
import hashlib
import sqlite3
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from backend.app.core.china_equity_identifiers import normalize_listing_code
from backend.app.core.data_freshness import with_result_freshness
from backend.app.core.china_equity_source_semantics import canonical_hkex_unadjusted_price_text
from backend.app.core.data_product_lifecycle import (
    LifecycleEvidenceError, equity_lifecycle, release_lifecycle_evidence,
)
from backend.app.core.china_equity_serving_store import (
    ServingStoreError,
    _is_serving_member,
    member_shards_for_range,
    query_series,
    resolve_serving_binding,
)
from backend.app.core.serving_release import (
    PinnedServingRelease,
    ServingReleaseError,
    pin_registered_serving_release,
    pin_serving_release,
)
from backend.app.core.storage_profile import resolve_unpublished_snapshot_path


COMPONENT_ID = "CN_A_SHARE"
CONTRACT_ID = "china_equity_minimum_daily_query_v1"
REALITY_OWNER = "metadata/a_share_update/authoritative_reality_owner_v1.ndjson"
IDENTITY_OWNER = "metadata/a_share_update/authoritative_identity_reconciliation_v1.json"
SUBJECTS = "metadata/subject_graph/subjects.parquet"
RELATIONSHIPS = "metadata/subject_graph/relationships.parquet"

METRIC_SERIES_FAMILY = {
    "equity.open": "daily_ohlc",
    "equity.high": "daily_ohlc",
    "equity.low": "daily_ohlc",
    "equity.close": "daily_ohlc",
    "market.volume": "market_volume",
    "market.trade_amount": "market_trade_amount",
    "market.turnover_rate": "market_turnover_rate",
}

_PRICE_METRICS = {"equity.open", "equity.high", "equity.low", "equity.close"}


def _query_value(
    value: Any, *, exchange: str, metric_id: str, adjustment_basis: str,
    economic_time: str,
) -> Any:
    """Project the accepted economic value, not a known provider codec tail."""
    if (
        exchange == "HKEX"
        and metric_id in _PRICE_METRICS
        and adjustment_basis == "unadjusted"
    ):
        return canonical_hkex_unadjusted_price_text(value, economic_time=economic_time)
    return value


class ChinaEquityQueryError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _in_interval(start: str | None, end: str | None, value: str) -> bool:
    return (start is None or start <= value) and (end is None or value <= end)


@dataclass(frozen=True)
class ChinaEquitySnapshot:
    release: PinnedServingRelease
    snapshot_root: Path
    manifest: dict[str, Any]
    contract: dict[str, Any]

    @classmethod
    def from_release(cls, release: PinnedServingRelease) -> "ChinaEquitySnapshot":
        if release.release_type != "composite_serving_release" or not release.snapshot_id:
            raise ChinaEquityQueryError("release_unavailable", "China Equity requires a composite serving release", 503)
        try:
            component = release.component(COMPONENT_ID)
            stored_contract = release.contract(CONTRACT_ID)
        except ServingReleaseError as exc:
            raise ChinaEquityQueryError("china_equity_component_unavailable", "serving release has no China Equity contract", 503) from exc
        if stored_contract.get("owner") != "embedded_release_contract":
            raise ChinaEquityQueryError("china_equity_contract_invalid", "China Equity serving contract has the wrong owner", 409)
        contract = dict(stored_contract.get("contract") or {})
        if component.get("database_generation_id") != release.database_generation_id:
            raise ChinaEquityQueryError("database_generation_mismatch", "China Equity component uses a different database generation", 409)
        root = resolve_unpublished_snapshot_path(release.snapshot_id)
        manifest_path = root / "metadata/corrected_candidate_manifest_v1.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("snapshot_id") != release.snapshot_id:
            raise ChinaEquityQueryError("snapshot_identity_mismatch", "served snapshot identity is inconsistent", 409)
        members = {row["relative_path"]: row for row in manifest.get("files", [])}
        required = {REALITY_OWNER, IDENTITY_OWNER, SUBJECTS, RELATIONSHIPS}
        if not required <= members.keys():
            raise ChinaEquityQueryError("china_equity_metadata_unavailable", "served snapshot lacks required China Equity metadata", 503)
        return cls(release=release, snapshot_root=root, manifest=manifest, contract=contract)


class _BindingCacheEntry:
    """Per-release-binding immutable metadata reused within one process.

    One entry exists per pinned serving binding (release identity + hash +
    snapshot).  A fresh binding resolves to a fresh entry, so a publication or
    rollback can never observe another release's cached identity or Series
    resolution.  Entries are process-local only; a restart simply rebuilds
    them from the same immutable snapshot.
    """

    def __init__(self, snapshot: "ChinaEquitySnapshot"):
        self.snapshot = snapshot
        self.identity: tuple[list[dict[str, Any]], dict[str, dict[str, Any]]] | None = None
        self.series_resolutions: "OrderedDict[tuple[str, str, str], dict[str, Any]]" = OrderedDict()
        self.serving_store: dict[str, Any] | None = None
        self.serving_store_resolved: bool = False


_MAX_BINDINGS = 4
_MAX_SERIES_RESOLUTIONS = 512
_BINDING_CACHE: "OrderedDict[tuple[str, str, str], _BindingCacheEntry]" = OrderedDict()
_BINDING_LOCK = threading.Lock()


def _binding_key(release: PinnedServingRelease) -> tuple[str, str, str]:
    return (str(release.release_id or ""), release.release_hash, str(release.snapshot_id or ""))


def _binding_for(release: PinnedServingRelease) -> _BindingCacheEntry:
    key = _binding_key(release)
    with _BINDING_LOCK:
        entry = _BINDING_CACHE.get(key)
        if entry is None:
            entry = _BindingCacheEntry(ChinaEquitySnapshot.from_release(release))
            _BINDING_CACHE[key] = entry
            while len(_BINDING_CACHE) > _MAX_BINDINGS:
                _BINDING_CACHE.popitem(last=False)
        else:
            _BINDING_CACHE.move_to_end(key)
        return entry


def _resolve_serving_store(snapshot: "ChinaEquitySnapshot") -> dict[str, Any] | None:
    """Resolve the activated serving generation for this binding, if it binds."""
    return resolve_serving_binding(
        release_id=snapshot.release.release_id,
        release_hash=snapshot.release.release_hash,
        snapshot_id=snapshot.release.snapshot_id,
        database_generation_id=snapshot.release.database_generation_id,
        manifest_sha256=str(snapshot.release.component(COMPONENT_ID).get("manifest_sha256") or ""),
        manifest=snapshot.manifest,
    )


def _load_identity_files(snapshot: "ChinaEquitySnapshot") -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    episodes = []
    with (snapshot.snapshot_root / REALITY_OWNER).open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                episodes.append(json.loads(line))
    identity = json.loads((snapshot.snapshot_root / IDENTITY_OWNER).read_text(encoding="utf-8"))
    objects = {str(row["episode_evidence_key"]): dict(row) for row in identity.get("objects", [])}
    if len(objects) != len(identity.get("objects", [])):
        raise ChinaEquityQueryError("identity_owner_invalid", "China Equity identity owner contains duplicate episodes", 409)
    return episodes, objects


class ChinaEquityQueryService:
    def __init__(self, snapshot: ChinaEquitySnapshot):
        self.snapshot = snapshot
        self._entry: _BindingCacheEntry | None = None

    @classmethod
    def active(cls) -> "ChinaEquityQueryService":
        return cls._from_entry(_binding_for(pin_serving_release()))

    @classmethod
    def for_release(cls, release: PinnedServingRelease) -> "ChinaEquityQueryService":
        return cls._from_entry(_binding_for(release))

    @classmethod
    def _from_entry(cls, entry: _BindingCacheEntry) -> "ChinaEquityQueryService":
        service = cls(entry.snapshot)
        service._entry = entry
        return service

    @classmethod
    def for_registered_release(cls, *, release_id: str, release_hash: str) -> "ChinaEquityQueryService":
        try:
            release = pin_registered_serving_release(release_id, release_hash)
        except ServingReleaseError as exc:
            raise ChinaEquityQueryError(
                "release_binding_unavailable",
                "the explicitly pinned China Equity serving release is unavailable or changed",
                409,
            ) from exc
        return cls.for_release(release)

    def snapshot_metadata(self) -> dict[str, Any]:
        return {
            "release_id": self.snapshot.release.release_id,
            "release_hash": self.snapshot.release.release_hash,
            "snapshot_id": self.snapshot.release.snapshot_id,
            "database_generation_id": self.snapshot.release.database_generation_id,
            "universe": "Equity",
            "region": "CN",
            "supported_market_jurisdictions": ["CN", "HK"],
            "jurisdiction": "CN",
            "jurisdiction_semantics": "legacy_China_region_scope_not_listing_jurisdiction",
            "operational_scope": "China_region_equity",
            "component_snapshot_id": self.snapshot.release.component(COMPONENT_ID)["snapshot_id"],
        }

    def _load_identity(self) -> None:
        """Load the immutable identity owners once per pinned binding."""
        entry = self._entry
        if entry is None:  # direct construction in tests/evidence helpers
            self._episodes, self._identity_by_episode = _load_identity_files(self.snapshot)
            return
        with _BINDING_LOCK:
            if entry.identity is None:
                entry.identity = _load_identity_files(self.snapshot)
        self._episodes, self._identity_by_episode = entry.identity

    def _serving_store(self) -> dict[str, Any] | None:
        """The release-bound serving store for this binding, resolved once per process."""
        entry = self._entry
        if entry is None:
            return None
        with _BINDING_LOCK:
            if not entry.serving_store_resolved:
                entry.serving_store = _resolve_serving_store(self.snapshot)
                entry.serving_store_resolved = True
        return entry.serving_store

    def search(
        self, query: str, *, limit: int = 20, market: str = "All",
        exchange: str | None = None, lifecycle: str = "All",
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """Discover accepted listing candidates; never choose an episode for the user.

        Only release-bound authoritative episode and identity owners are read.
        A name or code is a discovery signal, not a new identity decision.
        """
        term = " ".join(query.strip().casefold().split())
        if not term or len(term) > 100 or (len(term) < 2 and not term.isdigit()):
            raise ChinaEquityQueryError("invalid_search", "search requires a bounded name, code, or alias")
        if not 1 <= limit <= 100:
            raise ChinaEquityQueryError("invalid_limit", "search limit must be between 1 and 100")
        if market not in {"All", "Mainland", "Hong Kong"} or lifecycle not in {"All", "Current", "Historical", "Unconfirmed"}:
            raise ChinaEquityQueryError("invalid_discovery_filter", "unsupported market or lifecycle filter")
        if exchange is not None and exchange not in {"SSE", "SZSE", "BSE", "HKEX"}:
            raise ChinaEquityQueryError("invalid_discovery_filter", "unsupported exchange")
        filters = {"release_hash": self.snapshot.release.release_hash, "query": term,
                   "market": market, "exchange": exchange, "lifecycle": lifecycle}
        filter_hash = hashlib.sha256(json.dumps(filters, sort_keys=True).encode("utf-8")).hexdigest()
        offset = 0
        if cursor:
            try:
                decoded = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii") + b"=" * (-len(cursor) % 4)))
                if decoded["filter_hash"] != filter_hash or not isinstance(decoded["offset"], int) or decoded["offset"] < 0:
                    raise ValueError("cursor does not bind the requested search")
                offset = decoded["offset"]
            except (ValueError, KeyError, TypeError, UnicodeError, binascii.Error) as exc:
                raise ChinaEquityQueryError("invalid_discovery_cursor", "cursor is not valid for this fixed search") from exc
        self._load_identity()
        assert self._episodes is not None and self._identity_by_episode is not None
        evidence = self._lifecycle_evidence(required=lifecycle != "All")
        matches: list[tuple[int, dict[str, Any]]] = []
        for episode in self._episodes:
            identity = self._identity_by_episode.get(str(episode.get("episode_evidence_key") or ""))
            if identity is None:
                continue  # Unaccepted source evidence is not a product candidate.
            projected = (equity_lifecycle(episode, evidence=evidence) if evidence else {
                "lifecycle_class": None, "lifecycle_classification_status": "unavailable_for_this_release",
                "estimated_delisting_date": None,
            })
            if lifecycle != "All" and projected["lifecycle_class"] != lifecycle:
                continue
            venue = episode.get("exchange")
            if exchange and venue != exchange:
                continue
            if market == "Mainland" and venue not in {"SSE", "SZSE", "BSE"}:
                continue
            if market == "Hong Kong" and venue != "HKEX":
                continue
            values: list[tuple[str, str]] = []
            for alias in episode.get("code_aliases") or []:
                values.append((str(alias.get("code") or ""), "code_alias"))
            for key in ("historical_primary_code", "security_code_at_cutoff"):
                if episode.get(key):
                    values.append((str(episode[key]), "code"))
            for key in ("security_name_at_cutoff", "issuer_display_name", "issuer_legal_name"):
                if episode.get(key):
                    values.append((str(episode[key]), "name"))
            for alias in episode.get("name_aliases") or []:
                if alias.get("value"):
                    values.append((str(alias["value"]), "name_alias"))
            hits: list[tuple[int, str, str]] = []
            for value, kind in values:
                if term.isdigit() and kind in {"name", "name_alias"}:
                    continue  # Numeric input is a code query, not a name substring.
                normalized = " ".join(value.casefold().split())
                exact_numeric = term.isdigit() and normalized.isdigit() and int(term) == int(normalized)
                if normalized == term:
                    hits.append((0, value, kind))
                elif exact_numeric:
                    hits.append((1, value, kind))
                elif term.isdigit() and len(term) < 3:
                    continue  # One/two-digit code queries must be exact.
                elif normalized.startswith(term):
                    hits.append((2, value, kind))
                elif term in normalized:
                    hits.append((3, value, kind))
            if not hits:
                continue
            hits.sort(key=lambda hit: (hit[0], hit[2], hit[1]))
            code = str(episode.get("security_code_at_cutoff") or episode.get("historical_primary_code") or "")
            matches.append((hits[0][0], {
                "listing_id": identity["listing_id"],
                "instrument_id": identity["instrument_id"],
                "entity_id": identity["entity_id"],
                "object_type": "listing",
                "display_name": episode.get("security_name_at_cutoff") or episode.get("issuer_display_name"),
                "external_code": code,
                "exchange": episode.get("exchange"),
                "market_jurisdiction": episode.get("market_jurisdiction") or (
                    "CN" if episode.get("exchange") in {"SSE", "SZSE", "BSE"} else None
                ),
                "share_type": episode.get("share_type"),
                "board": episode.get("board"),
                "lifecycle_status": episode.get("lifecycle_status"),
                "lifecycle_class": projected["lifecycle_class"],
                "classification_status": projected["lifecycle_classification_status"],
                "lifecycle_classification_status": projected["lifecycle_classification_status"],
                "estimated_delisting_date": projected["estimated_delisting_date"],
                "listing_start_date": episode.get("listing_start_date"),
                "listing_start_boundary": episode.get("listing_start_boundary"),
                "listing_end_date": episode.get("listing_end_date"),
                "code_aliases": episode.get("code_aliases") or [],
                "episode_evidence_key": episode.get("episode_evidence_key"),
                "matched_value": hits[0][1],
                "match_kind": hits[0][2],
            }))
        matches.sort(key=lambda item: (item[0], item[1]["exchange"] or "", item[1]["external_code"], item[1]["episode_evidence_key"]))
        end_offset = offset + limit
        next_cursor = None
        if end_offset < len(matches):
            value = json.dumps({"filter_hash": filter_hash, "offset": end_offset}, sort_keys=True, separators=(",", ":"))
            next_cursor = base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")
        return {
            "snapshot": self.snapshot_metadata(),
            "query": query,
            "filters": {"market": market, "exchange": exchange, "lifecycle": lifecycle},
            "lifecycle_filter_status": "available_for_accepted_listings",
            "candidate_count": len(matches),
            "ambiguous": len(matches) > 1,
            "truncated": end_offset < len(matches),
            "next_cursor": next_cursor,
            "candidates": [item[1] for item in matches[offset:end_offset]],
            "selection_contract": "listing_id_from_accepted_identity_owner; user_selection_required",
        }

    def resolve_listing(self, *, exchange: str, code: str, alias_effective_date: str) -> dict[str, Any]:
        exchange = exchange.upper().strip()
        try:
            code = normalize_listing_code(exchange, code)
        except ValueError as exc:
            raise ChinaEquityQueryError(
                "invalid_alias", "exchange/code is outside the executable China-region Equity contract"
            ) from exc
        try:
            date.fromisoformat(alias_effective_date)
        except ValueError as exc:
            raise ChinaEquityQueryError(
                "invalid_alias_effective_date",
                "alias_effective_date must be an ISO calendar date used only for lifecycle-effective alias resolution",
            ) from exc
        self._load_identity()
        assert self._episodes is not None and self._identity_by_episode is not None
        matches = []
        for episode in self._episodes:
            if episode.get("exchange") != exchange:
                continue
            aliases = episode.get("code_aliases") or []
            if any(str(alias.get("code")) == code and _in_interval(alias.get("effective_from"), alias.get("effective_to"), alias_effective_date) for alias in aliases):
                matches.append(episode)
        if not matches:
            raise ChinaEquityQueryError("listing_not_found", "no accepted listing episode owns this alias on the requested date", 404)
        if len(matches) != 1:
            raise ChinaEquityQueryError("ambiguous_listing_episode", "more than one listing episode owns this alias/date", 409)
        episode = matches[0]
        identity = self._identity_by_episode.get(str(episode["episode_evidence_key"]))
        if identity is None:
            raise ChinaEquityQueryError("identity_crosswalk_missing", "accepted listing episode has no durable identity crosswalk", 409)
        return {
            "snapshot": self.snapshot_metadata(),
            "alias": {"exchange": exchange, "code": code, "alias_effective_date": alias_effective_date},
            "listing": {
                "listing_id": identity["listing_id"],
                "instrument_id": identity["instrument_id"],
                "entity_id": identity["entity_id"],
                "episode_evidence_key": episode["episode_evidence_key"],
                "effective_start": episode.get("listing_start_date"),
                "effective_end": episode.get("listing_end_date"),
                "lifecycle_status": episode.get("lifecycle_status"),
                "board": episode.get("board"),
                "share_type": episode.get("share_type"),
                "issuer_display_name": episode.get("issuer_display_name"),
            },
        }

    def listing_by_id(self, listing_id: str) -> dict[str, Any]:
        """Read one accepted listing episode by durable identity, never by code."""
        self._load_identity()
        assert self._episodes is not None and self._identity_by_episode is not None
        matches = []
        for episode in self._episodes:
            identity = self._identity_by_episode.get(str(episode.get("episode_evidence_key") or ""))
            if identity is not None and identity.get("listing_id") == listing_id:
                matches.append((episode, identity))
        if not matches:
            raise ChinaEquityQueryError("listing_not_found", "accepted listing ID was not found", 404)
        if len(matches) != 1:
            raise ChinaEquityQueryError("ambiguous_listing_identity", "listing ID maps to multiple accepted episodes", 409)
        episode, identity = matches[0]
        assert identity is not None
        evidence = self._lifecycle_evidence()
        return {
            "snapshot": self.snapshot_metadata(),
            "listing": self._listing_projection(episode, identity, evidence=evidence),
        }

    def accepted_listing_rows(self) -> list[dict[str, Any]]:
        """Release-bound accepted episodes for logical identity inspection."""
        self._load_identity()
        assert self._episodes is not None and self._identity_by_episode is not None
        evidence = self._lifecycle_evidence()
        return [
            self._listing_projection(episode, identity, evidence=evidence)
            for episode in self._episodes
            if (identity := self._identity_by_episode.get(str(episode.get("episode_evidence_key") or ""))) is not None
        ]

    def _lifecycle_evidence(self, *, required: bool = False):
        try:
            return release_lifecycle_evidence(self.snapshot.release)
        except LifecycleEvidenceError as exc:
            if required:
                raise ChinaEquityQueryError("lifecycle_evidence_unavailable", str(exc), 409) from exc
            return None

    @staticmethod
    def _listing_projection(episode: Mapping[str, Any], identity: Mapping[str, Any], *, evidence) -> dict[str, Any]:
        projected = (equity_lifecycle(episode, evidence=evidence) if evidence else {
            "lifecycle_class": None, "lifecycle_classification_status": "unavailable_for_this_release",
            "estimated_delisting_date": None,
        })
        return {
            "listing_id": identity["listing_id"], "instrument_id": identity["instrument_id"],
            "entity_id": identity["entity_id"],
            "display_name": episode.get("security_name_at_cutoff") or episode.get("issuer_display_name"),
            "exchange": episode.get("exchange"), "external_code": episode.get("security_code_at_cutoff"),
            "market_jurisdiction": episode.get("market_jurisdiction"),
            "listing_start_date": episode.get("listing_start_date"),
            "listing_start_boundary": episode.get("listing_start_boundary"),
            "listing_end_date": episode.get("listing_end_date"),
            "lifecycle_source_status": episode.get("lifecycle_status"),
            "lifecycle_class": projected["lifecycle_class"],
            "lifecycle_classification_status": projected["lifecycle_classification_status"],
            "estimated_delisting_date": projected["estimated_delisting_date"],
            "code_aliases": episode.get("code_aliases") or [],
            "name_aliases": episode.get("name_aliases") or [],
        }

    def _series_for_listing(self, listing_id: str, metric_id: str, adjustment_basis: str) -> dict[str, Any]:
        if metric_id not in METRIC_SERIES_FAMILY:
            raise ChinaEquityQueryError("unsupported_metric", "metric is outside the minimum China Equity daily contract")
        if adjustment_basis != "unadjusted":
            raise ChinaEquityQueryError("unsupported_adjustment_basis", "this release serves only explicit unadjusted China Equity Series")
        entry = self._entry
        if entry is not None:
            key = (listing_id, metric_id, adjustment_basis)
            with _BINDING_LOCK:
                resolved = entry.series_resolutions.get(key)
                if resolved is not None:
                    entry.series_resolutions.move_to_end(key)
                    return resolved
        resolved = self._resolve_series_uncached(listing_id, metric_id, adjustment_basis)
        if entry is not None:
            key = (listing_id, metric_id, adjustment_basis)
            with _BINDING_LOCK:
                entry.series_resolutions[key] = resolved
                while len(entry.series_resolutions) > _MAX_SERIES_RESOLUTIONS:
                    entry.series_resolutions.popitem(last=False)
        return resolved

    def _exchange_for_listing(self, listing_id: str) -> str:
        self._load_identity()
        assert self._episodes is not None and self._identity_by_episode is not None
        matches = [
            str(episode.get("exchange") or "")
            for episode in self._episodes
            if (
                identity := self._identity_by_episode.get(
                    str(episode.get("episode_evidence_key") or "")
                )
            ) is not None
            and identity.get("listing_id") == listing_id
        ]
        if len(matches) != 1 or not matches[0]:
            raise ChinaEquityQueryError(
                "ambiguous_listing_identity",
                "listing ID does not resolve to one accepted exchange owner",
                409,
            )
        return matches[0]

    def _resolve_series_uncached(self, listing_id: str, metric_id: str, adjustment_basis: str) -> dict[str, Any]:
        relationships = pq.read_table(
            self.snapshot.snapshot_root / RELATIONSHIPS,
            filters=[("to_id", "=", listing_id)],
        ).to_pylist()
        family = METRIC_SERIES_FAMILY[metric_id]
        series_ids = {
            str(row["from_id"])
            for row in relationships
            if row.get("from_type") == "series"
            and row.get("to_type") == "listing"
            and row.get("relationship_type") == "quoted_on"
            and json.loads(row.get("attributes_json") or "{}").get("series_family") == family
            and row.get("resolution_status") == "standard_id_ready"
        }
        if not series_ids:
            raise ChinaEquityQueryError("series_unavailable", "listing has no accepted Series for this metric", 404)
        subject_rows = pq.read_table(
            self.snapshot.snapshot_root / SUBJECTS,
            filters=[("subject_id", "in", sorted(series_ids))],
        ).to_pylist()
        accepted = []
        for row in subject_rows:
            attributes = json.loads(row.get("attributes_json") or "{}")
            if (attributes.get("series_dimensions") or {}).get("adjustment_basis") == adjustment_basis:
                accepted.append({"series_id": row["subject_id"], "series_family": family, "adjustment_basis": adjustment_basis})
        if len(accepted) != 1:
            raise ChinaEquityQueryError("ambiguous_series", "listing/metric/adjustment does not resolve to one accepted Series", 409)
        return accepted[0]

    def _daily_members(self, start: str, end: str) -> list[dict[str, Any]]:
        start_year, end_year = int(start[:4]), int(end[:4])
        result = []
        for member in self.snapshot.manifest.get("files", []):
            relative = str(member.get("relative_path") or "")
            if not relative.startswith("standard_facts/domain=equity/year="):
                continue
            try:
                year = int(relative.split("year=", 1)[1].split("/", 1)[0])
            except (ValueError, IndexError):
                continue
            if start_year <= year <= end_year and _is_serving_member(relative):
                result.append(dict(member))
        return sorted(result, key=lambda row: row["relative_path"])

    def _query_serving_store(
        self, store: dict[str, Any], members: list[dict[str, Any]], series: dict[str, Any],
        listing_id: str, metric_id: str, start: str, end: str, max_rows: int,
    ) -> dict[str, Any] | None:
        """Serve one bounded Series query from the B-tree store, or None to fall back.

        The source members the range touches are size-tripwired against the
        snapshot manifest first; on any failure the production full-column
        Parquet path runs unchanged and raises its own exact errors.
        """
        started = time.perf_counter()
        shards = member_shards_for_range(store["generation"], start, end)
        selected_paths = {entry["relative_path"] for entry in shards}
        touched_members = [member for member in members if member["relative_path"] in selected_paths]
        if len(touched_members) != len(selected_paths):
            return None
        for member in touched_members:
            path = self.snapshot.snapshot_root / member["relative_path"]
            if not path.is_file() or path.stat().st_size != int(member.get("byte_count") or -1):
                return None
        try:
            rows = query_series(
                shards=shards, shard_dir=store["shard_dir"],
                series_id=str(series["series_id"]), metric_id=metric_id,
                start=start, end=end,
            )
        except (ServingStoreError, sqlite3.DatabaseError):
            return None
        points: dict[str, dict[str, Any]] = {}
        for row in rows:
            points[str(row["logical_fact_key"])] = {
                "economic_time": str(row["economic_time"]),
                "value": row["normalized_value"],
                "unit": row["canonical_unit"],
                "currency": row["canonical_currency"],
                "scale": row["canonical_scale"],
                "time_role": row["primary_time_role"],
                "source_observation_id": row["source_observation_key"],
            }
        ordered = sorted(points.values(), key=lambda row: row["economic_time"])
        if len(ordered) > max_rows:
            raise ChinaEquityQueryError("result_too_large", "bounded China Equity query exceeds max_rows", 413)
        return with_result_freshness({
            "snapshot": self.snapshot_metadata(),
            "listing_id": listing_id,
            "series": series,
            "metric_id": metric_id,
            "requested_interval": {"start": start, "end": end},
            "status": "available" if ordered else "unavailable",
            "row_count": len(ordered),
            "points": ordered,
            "access": {
                "manifest_members_touched": len(touched_members),
                "rows_scanned": len(ordered),
                "rows_returned": len(ordered),
                "estimated_compressed_bytes_read": 0,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                "historical_full_scan": False,
                "serving_path": "serving_store_b_tree_seek",
                "serving_generation": str(store["generation"].get("generation_hash") or ""),
            },
        }, availability_field="status")

    def time_series(
        self, *, listing_id: str, metric_id: str, adjustment_basis: str,
        start: str, end: str, max_rows: int = 5_000,
    ) -> dict[str, Any]:
        try:
            start_date, end_date = date.fromisoformat(start), date.fromisoformat(end)
        except ValueError as exc:
            raise ChinaEquityQueryError("invalid_date_range", "start/end must be ISO calendar dates") from exc
        if start_date > end_date or (end_date - start_date).days > 366:
            raise ChinaEquityQueryError("invalid_date_range", "query interval must be ordered and no longer than 366 days")
        if max_rows < 1 or max_rows > 5_000:
            raise ChinaEquityQueryError("invalid_row_limit", "max_rows must be between 1 and 5000")
        series = self._series_for_listing(listing_id, metric_id, adjustment_basis)
        exchange = self._exchange_for_listing(listing_id)
        members = self._daily_members(start, end)
        if not members:
            return with_result_freshness({"snapshot": self.snapshot_metadata(), "listing_id": listing_id, "series": series, "metric_id": metric_id, "requested_interval": {"start": start, "end": end}, "row_count": 0, "points": [], "status": "unavailable"}, availability_field="status")
        store = self._serving_store()
        if store is not None:
            from_store = self._query_serving_store(
                store, members, series, listing_id, metric_id, start, end, max_rows,
            )
            if from_store is not None:
                for point in from_store["points"]:
                    point["value"] = _query_value(
                        point["value"], exchange=exchange, metric_id=metric_id,
                        adjustment_basis=adjustment_basis,
                        economic_time=point["economic_time"],
                    )
                return from_store
        columns = [
            "logical_fact_key", "metric_id", "series_id", "economic_time",
            "normalized_value", "canonical_unit", "canonical_currency", "canonical_scale",
            "source_observation_key", "primary_time_role",
        ]
        started = time.perf_counter()
        points: dict[str, dict[str, Any]] = {}
        rows_scanned = 0
        compressed_bytes = 0

        def read_member(member: dict[str, Any]) -> tuple[list[dict[str, Any]], int, int]:
            path = self.snapshot.snapshot_root / member["relative_path"]
            if not path.is_file() or path.stat().st_size != int(member.get("byte_count") or -1):
                raise ChinaEquityQueryError("manifest_member_unavailable", "manifest-bound China Equity member is unavailable", 503)
            parquet = pq.ParquetFile(path)
            table = parquet.read(columns=columns)
            names = parquet.schema_arrow.names
            selected = [names.index(name) for name in columns]
            compressed = sum(
                parquet.metadata.row_group(group).column(index).total_compressed_size
                for group in range(parquet.metadata.num_row_groups) for index in selected
            )
            mask = pc.and_(
                pc.and_(pc.equal(table["series_id"], series["series_id"]), pc.equal(table["metric_id"], metric_id)),
                pc.and_(pc.greater_equal(table["economic_time"], start), pc.less_equal(table["economic_time"], end)),
            )
            rows = []
            for row in table.filter(pc.fill_null(mask, False)).to_pylist():
                rows.append({
                    "_key": str(row["logical_fact_key"]),
                    "economic_time": str(row["economic_time"]),
                    "value": _query_value(
                        row["normalized_value"], exchange=exchange, metric_id=metric_id,
                        adjustment_basis=adjustment_basis,
                        economic_time=str(row["economic_time"]),
                    ),
                    "unit": row["canonical_unit"],
                    "currency": row["canonical_currency"],
                    "scale": row["canonical_scale"],
                    "time_role": row["primary_time_role"],
                    "source_observation_id": row["source_observation_key"],
                })
            return rows, table.num_rows, compressed

        # Bounded parallelism overlaps NAS reads and decode across the two
        # dominant year members.  The read predicate, column set, per-member
        # manifest size check, and merged result are identical to the
        # sequential path; only wall order changes.
        with ThreadPoolExecutor(max_workers=min(2, len(members))) as executor:
            results = list(executor.map(read_member, members))
        for rows, scanned, compressed in results:
            rows_scanned += scanned
            compressed_bytes += compressed
            for row in rows:
                key = str(row.pop("_key"))
                points[key] = row
        ordered = sorted(points.values(), key=lambda row: row["economic_time"])
        if len(ordered) > max_rows:
            raise ChinaEquityQueryError("result_too_large", "bounded China Equity query exceeds max_rows", 413)
        return with_result_freshness({
            "snapshot": self.snapshot_metadata(),
            "listing_id": listing_id,
            "series": series,
            "metric_id": metric_id,
            "requested_interval": {"start": start, "end": end},
            "status": "available" if ordered else "unavailable",
            "row_count": len(ordered),
            "points": ordered,
            "access": {
                "manifest_members_touched": len(members),
                "rows_scanned": rows_scanned,
                "rows_returned": len(ordered),
                "estimated_compressed_bytes_read": compressed_bytes,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                "historical_full_scan": False,
                "serving_path": "parquet_full_column_scan",
            },
        }, availability_field="status")
