"""Bounded canonical query support for the China Public Fund vertical."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import sqlite3
import time
import threading
from copy import copy
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

import pyarrow.parquet as pq
import pyarrow.compute as pc

from backend.app.core.artifact_io import canonical_json, sha256_file
from backend.app.core.data_freshness import with_result_freshness
from backend.app.core.validated_update_repository import ValidatedUpdateRepository
from backend.app.core.incremental_control import (
    IncrementalControlError, IncrementalControlSearchLimit, IncrementalControlView,
    verify_manifest_control_member,
)
from backend.app.core.china_public_fund_query_index import normalize_search_term
from backend.app.core.serving_release import (
    PinnedServingRelease,
    ServingReleaseError,
    pin_registered_serving_release,
    pin_serving_release,
)
from backend.app.core.serving_control_receipt import resolve_serving_control_receipt
from backend.app.core.storage_profile import (
    resolve_active_snapshot_pointer,
    resolve_control_plane_path,
    resolve_unpublished_snapshot_path,
)


FUND_UNIVERSE = "CN_PUBLIC_FUND"
FUND_DOMAIN = "funds_etfs"  # Physical compatibility name only.
SEARCHABLE_TYPES = ("fund", "fund_share_class", "instrument", "listing", "entity")
SUPPORTED_METRICS: dict[str, str] = {
    "fund.nav": "fund_share_class",
    "fund.accumulated_nav": "fund_share_class",
    "market.close_price": "listing",
    "market.volume": "listing",
    "market.trade_amount": "listing",
}
FUND_QUERY_CONTRACT = "metadata/china_public_fund/query_contract_v1.json"
FUND_STATE_OWNER = "metadata/china_public_fund/validated_update_state_v1.json"
ACCESS_MODES = ("active", "release", "validated_review")
CONTROL_RELATIVE = "metadata/china_public_fund/fr_china_public_fund_control_v1.sqlite"
_FUND_NAV_METRICS = frozenset({"fund.nav", "fund.accumulated_nav"})
_CSRC_EID_NAV_MAPPING_BASIS = "accepted CSRC EID fundId plus scoped share-class code"
# Public installations do not inherit the development installation's
# observation-specific NAV proofs. Generic stored roles therefore fail closed.
_LEGACY_NAV_ROLE_PROOFS: dict[str, dict[str, str]] = {}


def canonical_fund_query_time_role(
    *,
    metric_id: str,
    subject_id: str,
    economic_time: str,
    source_observation_key: str,
    stored_time_role: str | None,
    source_family: str | None,
    source_trace: Mapping[str, Any] | None,
) -> str | None:
    """Project a stored Fund time role into the release-bound query contract.

    Earlier CSRC EID NAV facts stored a generic role and did not retain which
    native date field supplied it. Only exact source observations independently
    matched to a retained ``valuationDate`` may be projected. A row produced
    from ``reportSendDate`` alone remains on its stored role and fails closed
    for Modeling. Immutable source observations and standard facts stay intact.
    """
    role = str(stored_time_role) if stored_time_role is not None else None
    if role != "observation_date":
        return role
    trace = dict(source_trace or {})
    provenance = {str(item) for item in (trace.get("provenance_refs") or [])}
    proof = _LEGACY_NAV_ROLE_PROOFS.get(source_observation_key)
    if (
        metric_id in _FUND_NAV_METRICS
        and str(source_family or "") == "CSRC_EID"
        and str(trace.get("mapping_basis") or "") == _CSRC_EID_NAV_MAPPING_BASIS
        and "CSRC_EID_current_valuation" in provenance
        and proof == {"subject_id": subject_id, "metric_id": metric_id, "economic_time": economic_time}
    ):
        return "nav_date"
    return role
_RELEASE_CONTROL_VIEWS: dict[tuple[str, str, str], IncrementalControlView] = {}
_RELEASE_CONTROL_VIEW_LOCK = threading.Lock()


class FundQueryError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class FundSnapshot:
    snapshot_id: str
    manifest_sha256: str
    authoritative_cutoff: str
    database_generation_id: str
    snapshot_root: Path
    control_path: Path
    manifest_path: Path
    state: str = "validated_unpublished"
    release_id: str | None = None
    release_hash: str | None = None
    verification_receipt: Mapping[str, Any] | None = None

    def control_view(self) -> IncrementalControlView:
        receipts: dict[str, Mapping[str, Any]] = {}
        if self.verification_receipt is not None:
            receipts[self.snapshot_id] = self.verification_receipt
        if self.state == "release_pinned_serving":
            # The publication lifecycle already certifies several immutable
            # ancestors. Discover those receipts from the control predecessor
            # chain; IncrementalControlView still verifies each manifest,
            # parent hash, control member size, and receipt binding itself.
            current = self.snapshot_id
            visited: set[str] = set()
            while current not in visited:
                visited.add(current)
                try:
                    control = (self.control_path if current == self.snapshot_id
                               else resolve_unpublished_snapshot_path(current) / CONTROL_RELATIVE)
                    with closing(sqlite3.connect(f"file:{control.as_posix()}?mode=ro", uri=True)) as connection:
                        exists = connection.execute(
                            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='control_delta_metadata'"
                        ).fetchone()
                        if not exists:
                            break
                        parent_row = connection.execute(
                            "SELECT predecessor_snapshot_id FROM control_delta_metadata WHERE singleton_id=1"
                        ).fetchone()
                        if parent_row is None:
                            break  # The verified view below rejects malformed delta metadata.
                        parent = str(parent_row[0])
                    if parent in visited:
                        break  # The verified view below reports a predecessor cycle.
                    parent_manifest = (resolve_unpublished_snapshot_path(parent)
                                       / "metadata/corrected_candidate_manifest_v1.json")
                    receipt = resolve_serving_control_receipt(
                        snapshot_id=parent, manifest_sha256=sha256_file(parent_manifest),
                        control_relative_path=CONTROL_RELATIVE,
                    )
                    if receipt is not None:
                        receipts[parent] = receipt
                    current = parent
                except (OSError, ValueError, sqlite3.DatabaseError):
                    break  # Only a receipt optimization; verified traversal still decides validity.
        return IncrementalControlView(
            self.snapshot_id,
            control_path=lambda value: (
                self.control_path
                if value == self.snapshot_id
                else resolve_unpublished_snapshot_path(value) / CONTROL_RELATIVE
            ),
            manifest_path=lambda value: self.manifest_path
            if value == self.snapshot_id else resolve_unpublished_snapshot_path(value)
            / "metadata/corrected_candidate_manifest_v1.json",
            control_relative_path=CONTROL_RELATIVE,
            verification_receipts=receipts,
        )

    @classmethod
    def _load(
        cls, *, snapshot_id: str, manifest_sha256: str, state: str,
        release_id: str | None = None, release_hash: str | None = None,
        manifest_trusted_control: bool = False,
        verification_receipt: Mapping[str, Any] | None = None,
    ) -> "FundSnapshot":
        root = resolve_unpublished_snapshot_path(snapshot_id)
        manifest = root / "metadata/corrected_candidate_manifest_v1.json"
        control = root / CONTROL_RELATIVE
        contract = root / FUND_QUERY_CONTRACT
        if not manifest.is_file() or not control.is_file() or not contract.is_file():
            raise FundQueryError(
                "fund_snapshot_not_queryable",
                "the selected immutable snapshot does not contain the China Public Fund query contract",
                503,
            )
        digest = sha256_file(manifest)
        if digest != manifest_sha256:
            raise FundQueryError(
                "fund_snapshot_hash_mismatch",
                "selected Fund snapshot manifest hash does not match its binding",
                409,
            )
        manifest_value = json.loads(manifest.read_text(encoding="utf-8"))
        try:
            if manifest_trusted_control:
                members = [row for row in manifest_value.get("files", []) if row.get("relative_path") == CONTROL_RELATIVE]
                if len(members) != 1 or not control.is_file() or control.stat().st_size != int(members[0].get("byte_count") or -1):
                    raise ValueError("release-bound control member is unavailable or has the wrong size")
            else:
                verify_manifest_control_member(
                    manifest, control, CONTROL_RELATIVE,
                    receipt=verification_receipt,
                )
        except Exception as exc:
            raise FundQueryError(
                "fund_snapshot_control_hash_mismatch",
                "selected Fund snapshot control is not certified by its manifest",
                409,
            ) from exc
        contract_value = json.loads(contract.read_text(encoding="utf-8"))
        state_owner = root / FUND_STATE_OWNER
        state_value = json.loads(state_owner.read_text(encoding="utf-8")) if state_owner.is_file() else {}
        identity_owner = root / "metadata/china_public_fund/authoritative_identity_owner_v1.json"
        identity_value = json.loads(identity_owner.read_text(encoding="utf-8")) if identity_owner.is_file() else {}
        if manifest_value.get("snapshot_id") != snapshot_id or contract_value.get("snapshot_id") != snapshot_id:
            raise FundQueryError(
                "fund_snapshot_identity_mismatch",
                "selected Fund snapshot owners do not agree on snapshot identity",
                409,
            )
        return cls(
            snapshot_id=snapshot_id,
            manifest_sha256=digest,
            authoritative_cutoff=str(manifest_value.get("reality_cutoff_date") or ""),
            database_generation_id=str(
                contract_value.get("database_generation_id")
                or state_value.get("database_generation_id")
                or identity_value.get("database_generation_id") or ""
            ),
            snapshot_root=root,
            control_path=control,
            manifest_path=manifest,
            state=state,
            release_id=release_id,
            release_hash=release_hash,
            verification_receipt=verification_receipt,
        )

    @classmethod
    def current_validated(cls) -> "FundSnapshot":
        head = ValidatedUpdateRepository(resolve_control_plane_path()).current(FUND_UNIVERSE)
        if head is None:
            raise FundQueryError("fund_snapshot_unavailable", "validated China Public Fund head is unavailable", 503)
        # The catalog path may consume the publication receipt for the
        # validated head snapshot; without one it falls back to the full
        # content verification unchanged.
        receipt = resolve_serving_control_receipt(
            snapshot_id=head.snapshot_id,
            manifest_sha256=head.snapshot_manifest_sha256,
            control_relative_path=CONTROL_RELATIVE,
        )
        return cls._load(
            snapshot_id=head.snapshot_id,
            manifest_sha256=head.snapshot_manifest_sha256,
            state="validated_unpublished_review",
            verification_receipt=receipt,
        )

    @classmethod
    def resolve_binding(
        cls, *, access_mode: str, snapshot_id: str | None,
        manifest_sha256: str | None, release: PinnedServingRelease | None = None,
    ) -> "FundSnapshot":
        if access_mode not in ACCESS_MODES:
            raise FundQueryError("invalid_access_mode", "unsupported Fund snapshot access mode")
        if access_mode in {"active", "release"}:
            if access_mode == "release" and release is None:
                raise FundQueryError(
                    "explicit_release_binding_required",
                    "release-pinned Fund access requires an immutable release ID and hash",
                )
            pointer_path = None
            pointer_value: dict[str, Any] = {}
            if release is None:
                pointer_path = resolve_active_snapshot_pointer()
                pointer_value = json.loads(pointer_path.read_text(encoding="utf-8"))
            if release is None and not pointer_value.get("release_type"):
                legacy_id = str(pointer_value.get("snapshot_id") or "")
                legacy_hash = str(pointer_value.get("snapshot_manifest_sha256") or "")
                return cls._load(
                    snapshot_id=legacy_id,
                    manifest_sha256=legacy_hash,
                    state="active_serving",
                    verification_receipt=resolve_serving_control_receipt(
                        snapshot_id=legacy_id,
                        manifest_sha256=legacy_hash,
                        control_relative_path=CONTROL_RELATIVE,
                    ),
                )
            try:
                pinned = release or pin_serving_release(pointer_path)
            except (OSError, ValueError, ServingReleaseError) as exc:
                raise FundQueryError("active_release_unavailable", "active serving release is unavailable", 503) from exc
            active_id = str(pinned.snapshot_id or "")
            component_hash = None
            component_snapshot_id = active_id
            if pinned.component_bindings:
                try:
                    component = pinned.component(FUND_UNIVERSE)
                    serving_contract = pinned.contract("china_public_fund_minimum_query_v1")
                except ServingReleaseError as exc:
                    raise FundQueryError("fund_component_unavailable", "active release does not bind China Public Fund", 503) from exc
                component_snapshot_id = str(component.get("snapshot_id") or "")
                if not component_snapshot_id:
                    raise FundQueryError("fund_component_unavailable", "Fund component has no immutable snapshot binding", 503)
                contract = dict(serving_contract.get("contract") or {})
                if (
                    serving_contract.get("owner") != "embedded_release_contract"
                    or contract.get("release_binding") != "request_pinned_immutable_serving_release"
                ):
                    raise FundQueryError("fund_release_contract_invalid", "Fund serving contract is not release-pinned", 409)
                component_hash = str(component.get("manifest_sha256") or "")
            active_hash = component_hash or str(pointer_value.get("snapshot_manifest_sha256") or "")
            if snapshot_id and snapshot_id not in {active_id, component_snapshot_id}:
                raise FundQueryError("snapshot_binding_conflict", "request snapshot differs from active serving release", 409)
            if manifest_sha256 and manifest_sha256 != active_hash:
                raise FundQueryError("snapshot_binding_conflict", "request manifest differs from active serving release", 409)
            receipt = resolve_serving_control_receipt(
                snapshot_id=component_snapshot_id,
                manifest_sha256=active_hash,
                control_relative_path=CONTROL_RELATIVE,
                release=pinned,
            )
            if not pinned.component_bindings:
                return cls._load(
                    snapshot_id=component_snapshot_id, manifest_sha256=active_hash, state="active_serving",
                    verification_receipt=receipt,
                )
            return cls._load(
                snapshot_id=component_snapshot_id, manifest_sha256=active_hash, state="release_pinned_serving",
                release_id=pinned.release_id, release_hash=pinned.release_hash,
                manifest_trusted_control=True,
                verification_receipt=receipt,
            )
        if not snapshot_id or not manifest_sha256:
            raise FundQueryError(
                "explicit_review_binding_required",
                "validated review access requires an explicit snapshot ID and manifest hash",
                400,
            )
        validated_history = ValidatedUpdateRepository(
            resolve_control_plane_path()
        ).history(FUND_UNIVERSE)
        validated_match = next((
            row for row in validated_history
            if row.get("successor_snapshot_id") == snapshot_id
            and row.get("snapshot_manifest_sha256") == manifest_sha256
        ), None)
        if validated_match is None:
            raise FundQueryError(
                "fund_review_snapshot_not_validated",
                "selected Fund review snapshot and manifest are not in validated history",
                404,
            )
        root = resolve_unpublished_snapshot_path(snapshot_id)
        state_path = root / FUND_STATE_OWNER
        if not state_path.is_file():
            raise FundQueryError("fund_review_state_unavailable", "selected review snapshot has no validated state owner", 404)
        state_value = json.loads(state_path.read_text(encoding="utf-8"))
        if state_value.get("snapshot_id") != snapshot_id:
            raise FundQueryError("fund_review_state_mismatch", "selected review state has a different snapshot ID", 409)
        return cls._load(
            snapshot_id=snapshot_id, manifest_sha256=manifest_sha256,
            state="validated_unpublished_review",
        )


def fund_release_catalog() -> dict[str, Any]:
    active_pointer = resolve_active_snapshot_pointer()
    active = json.loads(active_pointer.read_text(encoding="utf-8")) if active_pointer.is_file() else {}
    active_id = str(active.get("snapshot_id") or "")
    active_hash = active.get("snapshot_manifest_sha256")
    release_id = None
    release_hash = None
    if active.get("release_type") == "composite_serving_release":
        # The pointer names the composite; Fund sessions bind the component.
        # Resolve through the verified descriptor so the catalog cannot hand a
        # composite manifest hash to a component snapshot (or vice versa).
        try:
            pinned = pin_serving_release(active_pointer)
            component = pinned.component(FUND_UNIVERSE)
            active_id = str(component.get("snapshot_id") or "")
            active_hash = component.get("manifest_sha256")
            release_id = pinned.release_id
            release_hash = pinned.release_hash
        except (OSError, ValueError, ServingReleaseError):
            active_id = ""
            active_hash = None
    active_root = resolve_unpublished_snapshot_path(active_id) if active_id else None
    active_queryable = bool(
        active_root
        and (active_root / FUND_QUERY_CONTRACT).is_file()
        and (active_root / CONTROL_RELATIVE).is_file()
    )
    head = ValidatedUpdateRepository(resolve_control_plane_path()).current(FUND_UNIVERSE)
    validated = None
    if head is not None:
        snapshot = FundSnapshot.current_validated()
        validated = {
            "snapshot_id": head.snapshot_id,
            "manifest_sha256": head.snapshot_manifest_sha256,
            "authoritative_cutoff": snapshot.authoritative_cutoff,
            "validated_head_cutoff": head.authoritative_cutoff,
            "database_generation_id": snapshot.database_generation_id,
            "state": "validated_unpublished_review",
            "query_available": True,
            "explicit_selection_required": True,
        }
    return {
        "universe": "Fund",
        "jurisdiction": "CN",
        "active_serving": {
            "snapshot_id": active_id or None,
            "manifest_sha256": active_hash,
            "release_id": release_id,
            "release_hash": release_hash,
            "state": "active_serving",
            "query_available": active_queryable,
            "reason": None if active_queryable else "active serving release does not contain the China Public Fund query contract",
        },
        "validated_review": validated,
        "default_access_mode": "active",
        "validated_review_is_never_implicit": True,
    }


def _filter_query_table(
    table: Any,
    *,
    subject_id: str,
    series_id: str,
    metric_id: str,
    start: str | None,
    end: str | None,
) -> Any:
    """Filter one already locator-bounded Arrow table before Python conversion."""
    mask = pc.and_(
        pc.and_(
            pc.equal(table["subject_id"], subject_id),
            pc.equal(table["series_id"], series_id),
        ),
        pc.equal(table["metric_id"], metric_id),
    )
    if start is not None:
        mask = pc.and_(mask, pc.greater_equal(table["economic_time"], start))
    if end is not None:
        mask = pc.and_(mask, pc.less_equal(table["economic_time"], end))
    return table.filter(pc.fill_null(mask, False))


def require_fund_query_schema(connection: sqlite3.Connection) -> None:
    present = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('fund_search_index','fund_nonpromoted_interval_index')"
        )
    }
    if present != {"fund_search_index", "fund_nonpromoted_interval_index"}:
        raise FundQueryError("fund_query_index_unavailable", "validated Fund snapshot has no query index", 503)


def _interval_overlaps(
    left_start: str | None, left_end: str | None,
    right_start: str | None, right_end: str | None,
) -> bool:
    return (left_end is None or right_start is None or left_end >= right_start) and (
        right_end is None or left_start is None or right_end >= left_start
    )


class ChinaPublicFundQueryService:
    """Semantic Fund repository plus bounded Parquet reader for one snapshot."""

    def __init__(self, snapshot: FundSnapshot):
        self.snapshot = snapshot
        self.__control_view: IncrementalControlView | None = None

    def _control_view(self) -> IncrementalControlView:
        if self.__control_view is None:
            if self.snapshot.state != "release_pinned_serving" or not self.snapshot.release_hash:
                self.__control_view = self.snapshot.control_view()
            else:
                # The release binding verifies the target manifest/member on
                # each service construction.  Immutable ancestor control
                # layers are verified once per process; request-local clones
                # keep mutable resolution diagnostics independent.
                key = (self.snapshot.snapshot_id, self.snapshot.manifest_sha256,
                       self.snapshot.release_hash)
                with _RELEASE_CONTROL_VIEW_LOCK:
                    template = _RELEASE_CONTROL_VIEWS.get(key)
                    if template is None:
                        template = self.snapshot.control_view()
                        if len(_RELEASE_CONTROL_VIEWS) >= 4:
                            _RELEASE_CONTROL_VIEWS.pop(next(iter(_RELEASE_CONTROL_VIEWS)))
                        _RELEASE_CONTROL_VIEWS[key] = template
                self.__control_view = copy(template)
                self.__control_view.last_resolution_stats = {}
        return self.__control_view

    @classmethod
    def current(cls) -> "ChinaPublicFundQueryService":
        """Internal evidence helper; product routes must use an explicit binding."""
        return cls(FundSnapshot.current_validated())

    @classmethod
    def for_binding(
        cls, *, access_mode: str, snapshot_id: str | None,
        manifest_sha256: str | None, release: PinnedServingRelease | None = None,
    ) -> "ChinaPublicFundQueryService":
        return cls(FundSnapshot.resolve_binding(
            access_mode=access_mode,
            snapshot_id=snapshot_id,
            manifest_sha256=manifest_sha256,
            release=release,
        ))

    @classmethod
    def for_registered_release(cls, *, release_id: str, release_hash: str) -> "ChinaPublicFundQueryService":
        try:
            release = pin_registered_serving_release(release_id, release_hash)
        except ServingReleaseError as exc:
            raise FundQueryError(
                "release_binding_unavailable",
                "the explicitly pinned Fund serving release is unavailable or changed",
                409,
            ) from exc
        return cls.for_binding(
            access_mode="release", snapshot_id=release.snapshot_id,
            manifest_sha256=release.component(FUND_UNIVERSE)["manifest_sha256"],
            release=release,
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(f"file:{self.snapshot.control_path.as_posix()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        return connection

    def snapshot_metadata(self) -> dict[str, Any]:
        binding_id = hashlib.sha256(canonical_json({
            "snapshot_id": self.snapshot.snapshot_id,
            "manifest_sha256": self.snapshot.manifest_sha256,
            "state": self.snapshot.state,
        }).encode("utf-8")).hexdigest()
        return {
            "snapshot_id": self.snapshot.snapshot_id,
            "manifest_sha256": self.snapshot.manifest_sha256,
            "authoritative_cutoff": self.snapshot.authoritative_cutoff,
            "database_generation_id": self.snapshot.database_generation_id,
            "state": self.snapshot.state,
            "release_id": self.snapshot.release_id,
            "release_hash": self.snapshot.release_hash,
            "binding_id": f"fund_snapshot_binding:{binding_id}",
        }

    def search(
        self, query: str, *, alias_effective_date: str | None = None,
        subject_types: Sequence[str] | None = None, limit: int = 20,
        complete: bool = False, market: str = "All", cursor: str | None = None,
    ) -> dict[str, Any]:
        term = normalize_search_term(query)
        if not term:
            raise FundQueryError("empty_search", "search query is empty")
        if limit < 1 or limit > 100:
            raise FundQueryError("invalid_limit", "search limit must be between 1 and 100")
        types = tuple(subject_types or SEARCHABLE_TYPES)
        if not types or any(value not in SEARCHABLE_TYPES for value in types):
            raise FundQueryError("invalid_subject_type", "search contains an unsupported Fund object type")
        if market not in {"All", "Mainland", "Hong Kong"}:
            raise FundQueryError("invalid_market_filter", "unsupported Fund market filter")
        if market == "Hong Kong":
            raise FundQueryError("unsupported_market_scope", "this Fund release does not bind Hong Kong Fund identity", 409)
        if cursor and not complete:
            raise FundQueryError("invalid_search_cursor", "continuation requires complete release-bound discovery")
        high = term + chr(0x10FFFF)
        try:
            rows = (self._control_view().search_complete(term, high, types)
                    if complete else self._control_view().search(term, high, types, limit=limit))
        except IncrementalControlSearchLimit as exc:
            raise FundQueryError("search_too_broad", "narrow the Fund discovery query; no partial results were returned", 413) from exc
        except IncrementalControlError as exc:
            raise FundQueryError("fund_control_binding_invalid", "release-bound Fund control cannot be read safely", 409) from exc
        if complete:
            rows = [row for row in rows if (json.loads(row.get("scope_json") or "{}").get("jurisdiction") == "CN")]
        if alias_effective_date:
            try:
                date.fromisoformat(alias_effective_date)
            except ValueError as exc:
                raise FundQueryError(
                    "invalid_alias_effective_date",
                    "alias_effective_date must be an ISO calendar date used only for lifecycle-effective alias resolution",
                ) from exc
            rows = [
                row for row in rows
                if (row.get("effective_start") is None or row["effective_start"] <= alias_effective_date)
                and (row.get("effective_end") is None or row["effective_end"] >= alias_effective_date)
            ]
        rows.sort(key=lambda row: (
            0 if row["normalized_term"] == term else 1,
            0 if row["match_kind"] == "canonical_name" else 1,
            row["normalized_term"], row["subject_type"], row["subject_id"],
        ))
        candidates: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            key = (str(row["subject_type"]), str(row["subject_id"]))
            item = candidates.setdefault(key, {
                "subject_type": key[0], "subject_id": key[1],
                "canonical_name": row["canonical_name"], "matched_values": [],
                "effective_start": row["effective_start"], "effective_end": row["effective_end"],
            })
            item["matched_values"].append({
                "value": row["display_value"], "match_kind": row["match_kind"],
                "alias_type": row["alias_type"], "effective_start": row["effective_start"],
                "effective_end": row["effective_end"],
            })
        all_candidates = list(candidates.values())
        offset = 0
        if complete:
            filter_material = {"snapshot_id": self.snapshot.snapshot_id,
                               "manifest_sha256": self.snapshot.manifest_sha256,
                               "release_hash": self.snapshot.release_hash,
                               "query": term, "types": types, "alias_effective_date": alias_effective_date,
                               "market": market}
            filter_hash = hashlib.sha256(canonical_json(filter_material).encode()).hexdigest()
            if cursor:
                try:
                    decoded = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii") + b"=" * (-len(cursor) % 4)))
                    if (decoded["filter_hash"] != filter_hash or type(decoded["offset"]) is not int
                            or not 0 <= decoded["offset"] < len(all_candidates)):
                        raise ValueError("cursor is not bound to this fixed search")
                    offset = decoded["offset"]
                except (ValueError, KeyError, TypeError, UnicodeError, binascii.Error) as exc:
                    raise FundQueryError("invalid_search_cursor", "cursor is not valid for this fixed search") from exc
            next_cursor = None
            if offset + limit < len(all_candidates):
                token = canonical_json({"filter_hash": filter_hash, "offset": offset + limit})
                next_cursor = base64.urlsafe_b64encode(token.encode()).decode("ascii").rstrip("=")
        else:
            next_cursor = None
        result = all_candidates[offset:offset + limit]
        return {
            "snapshot": self.snapshot_metadata(), "universe": "Fund", "query": query,
            "alias_effective_date": alias_effective_date,
            "candidate_count": len(all_candidates) if complete else len(result),
            "ambiguous": len(all_candidates) > 1 if complete else len(result) > 1,
            "discovery_completeness": "complete_for_fixed_query" if complete else "legacy_bounded_candidates",
            "market_scope": "Mainland China Public Fund; Hong Kong Fund not bound",
            "next_cursor": next_cursor,
            "candidates": result,
        }

    def subject(self, subject_type: str, subject_id: str) -> dict[str, Any]:
        if subject_type not in SEARCHABLE_TYPES and subject_type != "series":
            raise FundQueryError("invalid_subject_type", "unsupported Fund object type")
        view = self._control_view()
        row = view.subject(subject_type, subject_id)
        if row is None or row.get("domain") != FUND_DOMAIN:
            raise FundQueryError("subject_not_found", "canonical Fund subject was not found", 404)
        aliases = view.aliases(subject_type, subject_id)
        relationships = view.relationships(subject_type, subject_id)
        aliases.sort(key=lambda value: (value["alias_type"], value["alias_value"], value.get("effective_start") or ""))
        relationships.sort(key=lambda value: (value["relationship_type"], value.get("effective_start") or "", value["relationship_id"]))
        with closing(self._connect()) as connection:
            related_keys = {
                (str(rel["to_type"]), str(rel["to_id"]))
                if rel["from_type"] == subject_type and rel["from_id"] == subject_id
                else (str(rel["from_type"]), str(rel["from_id"]))
                for rel in relationships
            }
            related_names: dict[tuple[str, str], str | None] = {}
            for related_type, related_id in related_keys:
                related = view.subject(related_type, related_id)
                related_names[(related_type, related_id)] = (
                    json.loads(related["attributes_json"]).get("display_name") if related else None
                )
        payload = dict(row)
        payload.pop("domain", None)
        payload["universe"] = "Fund"
        payload["attributes"] = json.loads(payload.pop("attributes_json"))
        payload["code_aliases"] = json.loads(payload.pop("code_aliases_json"))
        alias_payload = []
        for alias in aliases:
            item = dict(alias)
            item["scope"] = json.loads(item.pop("scope_json"))
            item["provenance_refs"] = json.loads(item.pop("provenance_json"))
            alias_payload.append(item)
        relationship_payload = []
        for rel in relationships:
            item = dict(rel)
            item["attributes"] = json.loads(item.pop("attributes_json"))
            if item["from_type"] == subject_type and item["from_id"] == subject_id:
                related_key = (item["to_type"], item["to_id"]); direction = "outgoing"
            else:
                related_key = (item["from_type"], item["from_id"]); direction = "incoming"
            item["direction"] = direction
            item["related_canonical_name"] = related_names.get(related_key)
            relationship_payload.append(item)
        return {
            "snapshot": self.snapshot_metadata(), "subject": payload,
            "aliases": alias_payload, "relationships": relationship_payload,
            "lifecycle_note": "subject and relationship effective intervals are financial lifecycle evidence; observation and alias intervals are not promoted to lifecycle unless explicitly accepted",
        }

    def _series(self, connection: sqlite3.Connection, subject_type: str, subject_id: str, metric_id: str) -> list[dict[str, Any]]:
        view = self._control_view()
        rows = []
        for relationship in view.relationships(subject_type, subject_id):
            if relationship["relationship_type"] != "series_of" or relationship["from_type"] != "series" or relationship["to_type"] != subject_type or relationship["to_id"] != subject_id:
                continue
            subject = view.subject("series", relationship["from_id"])
            if subject and json.loads(subject["attributes_json"]).get("metric_id") == metric_id:
                rows.append({
                    "subject_id": subject["subject_id"],
                    "attributes_json": subject["attributes_json"],
                    "effective_start": relationship["effective_start"],
                    "effective_end": relationship["effective_end"],
                    "relationship_attributes_json": relationship["attributes_json"],
                })
        rows.sort(key=lambda value: value["subject_id"])
        return [{
            "series_id": row["subject_id"],
            "attributes": json.loads(row["attributes_json"]),
            "effective_start": row["effective_start"], "effective_end": row["effective_end"],
            "relationship_attributes": json.loads(row["relationship_attributes_json"]),
        } for row in rows]

    def _nonpromoted_matches(
        self, connection: sqlite3.Connection, subject_type: str, subject_id: str,
        metric_id: str, start: str | None, end: str | None,
    ) -> list[dict[str, Any]]:
        rows = self._control_view().nonpromoted(subject_type, subject_id, metric_id, start, end)
        rows.sort(key=lambda value: (value.get("time_start") or "", value["record_id"]))
        result = []
        for row in rows:
            item = dict(row); item["evidence_refs"] = json.loads(item.pop("evidence_json")); result.append(item)
        return result

    def time_series(
        self, *, subject_type: str, subject_id: str, metric_id: str,
        start: str | None = None, end: str | None = None,
        max_rows: int = 20_000, include_locator_evidence: bool = False,
    ) -> dict[str, Any]:
        if metric_id not in SUPPORTED_METRICS:
            raise FundQueryError("unsupported_metric", "metric is not in the minimal canonical Fund API")
        if start and end and start > end:
            raise FundQueryError("invalid_date_range", "start must not be later than end")
        if max_rows < 1 or max_rows > 50_000:
            raise FundQueryError("invalid_row_limit", "max_rows must be between 1 and 50000")
        subject_detail = self.subject(subject_type, subject_id)["subject"]
        expected_type = SUPPORTED_METRICS[metric_id]
        with closing(self._connect()) as connection:
            require_fund_query_schema(connection)
            nonpromoted = self._nonpromoted_matches(
                connection, subject_type, subject_id, metric_id, start, end
            )
            if subject_type != expected_type:
                return self._empty_result(
                    subject_detail, metric_id, start, end, "lifecycle_not_applicable",
                    f"{metric_id} belongs to {expected_type}, not {subject_type}", nonpromoted,
                )
            series = self._series(connection, subject_type, subject_id, metric_id)
            if len(series) > 1:
                raise FundQueryError("ambiguous_series", "multiple canonical Series match; dimensions are required", 409)
            if not series:
                return self._empty_result(
                    subject_detail, metric_id, start, end,
                    "known_nonpromoted_history" if nonpromoted else "source_gap",
                    "no canonical Series is available for this accepted object and metric", nonpromoted,
                )
            locator_started = time.perf_counter()
            locators = self._control_view().locators(
                layer_name="standard_facts",
                subject_type=subject_type,
                subject_id=subject_id,
                metric_id=metric_id,
                time_start=start,
                time_end=end,
                scope_contains={"universe": "Fund", "jurisdiction": "CN"},
                limit=2048,
            )
            locator_ms = (time.perf_counter() - locator_started) * 1000
            full_series_locators = self._control_view().locators(
                layer_name="standard_facts", subject_type=subject_type,
                subject_id=subject_id, metric_id=metric_id,
                time_start=None, time_end=None,
                scope_contains={"universe": "Fund", "jurisdiction": "CN"},
                limit=2048,
            )
            starts = [row["time_start"] for row in full_series_locators if row.get("time_start")]
            ends = [row["time_end"] for row in full_series_locators if row.get("time_end")]
            coverage = (
                min(starts) if starts else None,
                max(ends) if ends else None,
                len({row["relative_path"] for row in full_series_locators}),
            )
        if not locators:
            state = "known_nonpromoted_history" if nonpromoted else self._outside_lifecycle_state(subject_detail, start, end)
            if state is None:
                state = "source_gap"
            result = self._empty_result(
                subject_detail, metric_id, start, end, state,
                "no manifest-backed canonical locator overlaps the requested interval", nonpromoted,
            )
            result["series"] = series[0]
            result["coverage"] = {
                "available_start": coverage[0], "available_end": coverage[1],
                "latest_observation": coverage[1], "files_in_full_series": coverage[2],
                "availability_is_not_lifecycle": True,
            }
            result["access"] = {
                "locator_lookup_ms": round(locator_ms, 3), "files_touched": 0,
                "row_groups_touched": 0, "estimated_compressed_bytes_read": 0,
                "rows_scanned": 0, "rows_returned": 0,
                "predecessor_gzip_reads": 0, "manifest_membership_verified": True,
            }
            return with_result_freshness(result, availability_field="data_state")

        started = time.perf_counter()
        points: dict[str, dict[str, Any]] = {}
        file_paths: set[str] = set()
        row_groups: set[tuple[str, int]] = set()
        locator_evidence: list[dict[str, Any]] = []
        estimated_bytes = 0
        rows_scanned = 0
        columns = [
            "logical_fact_key", "metric_id", "subject_type", "subject_id", "series_id",
            "economic_time", "primary_time_role", "normalized_value", "canonical_unit",
            "canonical_currency", "canonical_scale", "source_observation_key",
            "source_family", "source_trace_json", "normalization_evidence_json",
        ]
        planned: dict[str, set[int]] = {}
        locator_by_path: dict[str, list[dict[str, Any]]] = {}
        for locator in locators:
            relative = str(locator["relative_path"])
            start_group = int(locator["row_group_start"] or 0)
            if locator["row_group_end"] is None:
                path = self.snapshot.snapshot_root / relative
                end_group = pq.ParquetFile(path).metadata.num_row_groups - 1
            else:
                end_group = int(locator["row_group_end"])
            planned.setdefault(relative, set()).update(range(start_group, end_group + 1))
            locator_by_path.setdefault(relative, []).append(locator)

        def read_file(item: tuple[str, set[int]]) -> tuple[str, int, int, list[dict[str, Any]]]:
            relative, groups = item
            path = self.snapshot.snapshot_root / relative
            if not path.is_file():
                raise FundQueryError("locator_payload_missing", "manifest-backed Fund payload is unavailable", 503)
            parquet = pq.ParquetFile(path)
            selected_indices = [parquet.schema_arrow.names.index(name) for name in columns]
            compressed = 0; scanned = 0; selected_rows: list[dict[str, Any]] = []
            for group in sorted(groups):
                metadata = parquet.metadata.row_group(group)
                compressed += sum(metadata.column(index).total_compressed_size for index in selected_indices)
                table = parquet.read_row_group(group, columns=columns)
                scanned += table.num_rows
                # Incremental Fund members may contain tens of thousands of
                # subjects in one row group.  Keep the manifest/locator-bounded
                # physical read unchanged, but discard unrelated rows in Arrow
                # before materializing Python dictionaries.  This avoids making
                # Python conversion cost proportional to every subject in each
                # touched row group while preserving the exact query predicate.
                selected_rows.extend(_filter_query_table(
                    table,
                    subject_id=subject_id,
                    series_id=series[0]["series_id"],
                    metric_id=metric_id,
                    start=start,
                    end=end,
                ).to_pylist())
            return relative, compressed, scanned, selected_rows

        ordered_plan = sorted(planned.items())
        with ThreadPoolExecutor(max_workers=min(8, len(ordered_plan))) as executor:
            file_results = list(executor.map(read_file, ordered_plan))
        for relative, compressed, scanned, raw_rows in file_results:
            file_paths.add(relative); estimated_bytes += compressed; rows_scanned += scanned
            row_groups.update((relative, group) for group in planned[relative])
            for row in raw_rows:
                economic_time = str(row["economic_time"])
                if row["subject_id"] != subject_id or row["series_id"] != series[0]["series_id"] or row["metric_id"] != metric_id:
                    continue
                if start and economic_time < start:
                    continue
                if end and economic_time > end:
                    continue
                trace = json.loads(row["source_trace_json"])
                time_role = canonical_fund_query_time_role(
                    metric_id=metric_id,
                    subject_id=subject_id,
                    economic_time=economic_time,
                    source_observation_key=row["source_observation_key"],
                    stored_time_role=row["primary_time_role"],
                    source_family=row["source_family"],
                    source_trace=trace,
                )
                points[str(row["logical_fact_key"])] = {
                    "economic_time": economic_time,
                    "value": row["normalized_value"],
                    "unit": row["canonical_unit"],
                    "currency": row["canonical_currency"],
                    "scale": row["canonical_scale"],
                    "time_role": time_role,
                    "source": {
                        "source_observation_id": row["source_observation_key"],
                        "source_family": row["source_family"],
                        "mapping_basis": trace.get("mapping_basis"),
                        "provenance_refs": trace.get("provenance_refs", []),
                    },
                }
        if include_locator_evidence:
            for relative in sorted(locator_by_path):
                for locator in locator_by_path[relative]:
                    locator_evidence.append({
                        "relative_path": relative, "content_sha256": locator["content_sha256"],
                        "row_group_start": locator["row_group_start"], "row_group_end": locator["row_group_end"],
                        "time_start": locator["time_start"], "time_end": locator["time_end"],
                    })
        result_points = sorted(points.values(), key=lambda row: row["economic_time"])
        if len(result_points) > max_rows:
            raise FundQueryError("result_too_large", "bounded Fund query exceeds max_rows", 413)
        wall_ms = (time.perf_counter() - started) * 1000
        data_state = "available" if result_points else (
            "known_nonpromoted_history" if nonpromoted else "true_empty"
        )
        result = {
            "snapshot": self.snapshot_metadata(),
            "subject": {
                "subject_type": subject_type, "subject_id": subject_id,
                "canonical_name": subject_detail["attributes"].get("display_name"),
                "universe": "Fund", "jurisdiction": subject_detail.get("jurisdiction"),
                "effective_start": subject_detail.get("effective_start"),
                "effective_end": subject_detail.get("effective_end"),
            },
            "series": series[0], "metric_id": metric_id,
            "requested_interval": {"start": start, "end": end},
            "data_state": data_state,
            "data_state_detail": "canonical observations returned" if result_points else "canonical Series exists but the requested interval contains no observation",
            "coverage": {
                "available_start": coverage[0], "available_end": coverage[1],
                "latest_observation": coverage[1], "files_in_full_series": coverage[2],
                "availability_is_not_lifecycle": True,
            },
            "excluded_nonpromoted": nonpromoted,
            "row_count": len(result_points), "points": result_points,
            "access": {
                "locator_lookup_ms": round(locator_ms, 3), "read_wall_ms": round(wall_ms, 3),
                "files_touched": len(file_paths), "row_groups_touched": len(row_groups),
                "estimated_compressed_bytes_read": estimated_bytes,
                "rows_scanned": rows_scanned, "rows_returned": len(result_points),
                "row_read_amplification": round(rows_scanned / max(1, len(result_points)), 3),
                "predecessor_gzip_reads": 0, "manifest_membership_verified": True,
            },
        }
        if include_locator_evidence:
            result["locator_evidence"] = locator_evidence
        return with_result_freshness(result, availability_field="data_state")

    def _outside_lifecycle_state(self, subject: Mapping[str, Any], start: str | None, end: str | None) -> str | None:
        if not _interval_overlaps(subject.get("effective_start"), subject.get("effective_end"), start, end):
            return "lifecycle_not_applicable"
        return None

    def _empty_result(
        self, subject: Mapping[str, Any], metric_id: str, start: str | None,
        end: str | None, state: str, detail: str,
        nonpromoted: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        return with_result_freshness({
            "snapshot": self.snapshot_metadata(),
            "subject": {
                "subject_type": subject["subject_type"], "subject_id": subject["subject_id"],
                "canonical_name": subject["attributes"].get("display_name"),
                "universe": "Fund", "jurisdiction": subject.get("jurisdiction"),
                "effective_start": subject.get("effective_start"),
                "effective_end": subject.get("effective_end"),
            },
            "series": None, "metric_id": metric_id,
            "requested_interval": {"start": start, "end": end},
            "data_state": state, "data_state_detail": detail,
            "coverage": None, "excluded_nonpromoted": list(nonpromoted),
            "row_count": 0, "points": [],
            "access": {"files_touched": 0, "row_groups_touched": 0, "estimated_compressed_bytes_read": 0, "rows_scanned": 0, "rows_returned": 0, "predecessor_gzip_reads": 0},
        }, availability_field="data_state")

    def batch_time_series(self, requests: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        if not requests or len(requests) > 8:
            raise FundQueryError("invalid_batch_size", "batch must contain between 1 and 8 requests")
        results = [self.time_series(**dict(request)) for request in requests]
        return {
            "snapshot": self.snapshot_metadata(), "result_count": len(results), "results": results,
            "access": {
                "files_touched_sum": sum(item["access"]["files_touched"] for item in results),
                "row_groups_touched_sum": sum(item["access"]["row_groups_touched"] for item in results),
                "estimated_compressed_bytes_read_sum": sum(item["access"]["estimated_compressed_bytes_read"] for item in results),
            },
        }

    def nonpromoted_summary(self, *, external_code: str | None = None) -> dict[str, Any]:
        manifest = json.loads(self.snapshot.manifest_path.read_text(encoding="utf-8"))
        if "china_public_fund_unresolved_history_rows" in manifest:
            exclusion_count = int(manifest["china_public_fund_unresolved_history_rows"])
        elif (
            manifest.get("schema_version") == "fr_corrected_candidate_manifest_v1"
            and manifest.get("source_contract_id") == "fr_public_fund_equity_bootstrap_sources"
        ):
            # Older source-driven snapshots and their successors did not write
            # this historical-corpus field; they have no such corpus.
            exclusion_count = 0
        else:
            raise FundQueryError(
                "fund_nonpromoted_summary_unavailable",
                "Fund snapshot is missing its historical exclusion count",
                503,
            )
        rows = self._control_view().effective_rows(
            "fund_nonpromoted_interval_index", "record_id",
            where_sql=" WHERE external_code=?" if external_code else "",
            params=(external_code,) if external_code else (), snapshot_scoped=True,
            tombstone_kind="fund_nonpromoted",
        )
        rows.sort(key=lambda value: (value.get("external_code") or "", value.get("metric_id") or "", value.get("time_start") or ""))
        rows = rows[:500]
        details = []
        for row in rows:
            item = dict(row); item["evidence_refs"] = json.loads(item.pop("evidence_json")); details.append(item)
        return {
            "snapshot": self.snapshot_metadata(),
            "canonical_query_exclusion_count": exclusion_count,
            "meaning": "retained source/fact evidence without accepted canonical ownership; excluded from canonical time-series results",
            "filter_external_code": external_code, "indexed_interval_count": len(details),
            "indexed_intervals": details,
        }
