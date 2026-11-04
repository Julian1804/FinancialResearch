"""Release-bound lifecycle evidence for accepted Fund and Equity identities.

This is a read projection of immutable owners, not another identity registry or
an as-of inference from null dates, provider observations, or current websites.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
from typing import Any, Mapping

from backend.app.core.artifact_io import sha256_file
from backend.app.core.serving_release import PinnedServingRelease
from backend.app.core.storage_profile import resolve_unpublished_snapshot_path


FUND_HISTORY = "metadata/china_public_fund/accepted_historical_temporal_ownership_v1.ndjson"
EQUITY_STATE = "metadata/a_share_update/validated_update_state_v1.json"
MANIFEST = "metadata/corrected_candidate_manifest_v1.json"


class LifecycleEvidenceError(RuntimeError):
    """Required accepted lifecycle evidence cannot be bound to this release."""


@dataclass(frozen=True)
class ReleaseLifecycleEvidence:
    historical_fund_subjects: frozenset[str]
    historical_share_classes: frozenset[str]
    historical_fund_listings: frozenset[str]
    unproved_fund_listing_ends: frozenset[str]
    unconfirmed_equity_episodes: frozenset[str]
    unconfirmed_equity_codes: frozenset[tuple[str, str]]


def _member(root: Path, members: Mapping[str, Mapping[str, Any]], relative: str) -> Path:
    recorded = members.get(relative)
    path = root / relative
    if recorded is None or not path.is_file():
        raise LifecycleEvidenceError(f"release lifecycle member unavailable: {relative}")
    if path.stat().st_size != recorded.get("byte_count") or sha256_file(path) != recorded.get("content_sha256"):
        raise LifecycleEvidenceError(f"release lifecycle member changed: {relative}")
    return path


@lru_cache(maxsize=8)
def _load(snapshot_id: str, release_hash: str) -> ReleaseLifecycleEvidence:
    root = resolve_unpublished_snapshot_path(snapshot_id)
    manifest_path = root / MANIFEST
    if not manifest_path.is_file():
        raise LifecycleEvidenceError("release lifecycle manifest is unavailable")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("snapshot_id") != snapshot_id:
        raise LifecycleEvidenceError("release lifecycle manifest identifies another snapshot")
    if len({str(row.get("relative_path")) for row in manifest.get("files", [])}) != len(manifest.get("files", [])):
        raise LifecycleEvidenceError("release lifecycle manifest has duplicate member paths")
    members = {str(row["relative_path"]): row for row in manifest.get("files", [])}
    history = [json.loads(line) for line in _member(root, members, FUND_HISTORY).read_text(encoding="utf-8").splitlines() if line]
    state = json.loads(_member(root, members, EQUITY_STATE).read_text(encoding="utf-8"))
    product_assignments = [row for row in history
                           if row.get("record_type") == "identity_assignment"
                           and row.get("subject_type") == "fund"]
    if len({str(row.get("subject_id")) for row in product_assignments}) != len(product_assignments):
        raise LifecycleEvidenceError("duplicate historical Fund Product assignment")
    assignments = {
        kind: frozenset(str(row["subject_id"]) for row in history
                        if row.get("record_type") == "identity_assignment"
                        and row.get("subject_type") == kind)
        for kind in ("fund", "fund_share_class", "listing")
    }
    unproved_codes = {
        str(row["historical_code"])
        for row in history
        if row.get("record_type") == "historical_trading_episode"
        and row.get("historical_listing_end") is None
    }
    unproved_listings = frozenset(
        str(row["subject_id"]) for row in history
        if row.get("record_type") == "identity_assignment"
        and row.get("subject_type") == "listing"
        and any(str(row.get("object_key") or "").startswith(f"listing:{code}:") for code in unproved_codes)
    )
    unresolved = list(state.get("unresolved_authoritative_changes") or [])
    known_roles = {
        "hkex_current_candidate_requires_accepted_identity_lifecycle",
        "missing_from_current_requires_termination_evidence",
        "existing_subject_reality_event_unresolved",
    }
    unknown_roles = {str(row.get("change_type")) for row in unresolved} - known_roles
    if unknown_roles:
        raise LifecycleEvidenceError(f"unmapped unresolved Equity lifecycle roles: {sorted(unknown_roles)}")
    accepted_impact = [row for row in unresolved
                       if row.get("change_type") != "hkex_current_candidate_requires_accepted_identity_lifecycle"]
    return ReleaseLifecycleEvidence(
        historical_fund_subjects=assignments["fund"],
        historical_share_classes=assignments["fund_share_class"],
        historical_fund_listings=assignments["listing"],
        unproved_fund_listing_ends=unproved_listings,
        unconfirmed_equity_episodes=frozenset(str(row["episode_evidence_key"]) for row in accepted_impact
                                              if row.get("episode_evidence_key")),
        unconfirmed_equity_codes=frozenset((str(row["exchange"]), str(row["code"]))
                                            for row in accepted_impact if not row.get("episode_evidence_key")),
    )


def release_lifecycle_evidence(release: PinnedServingRelease) -> ReleaseLifecycleEvidence:
    snapshot_id = getattr(release, "snapshot_id", None)
    release_hash = getattr(release, "release_hash", None)
    if not snapshot_id or not release_hash:
        raise LifecycleEvidenceError("lifecycle projection requires one pinned composite release")
    return _load(snapshot_id, release_hash)


def fund_lifecycle(
    subject: Mapping[str, Any], *, kind: str, evidence: ReleaseLifecycleEvidence,
) -> dict[str, Any]:
    """Classify one accepted object at its own grain; never inherit child ends."""
    subject_id = str(subject["subject_id"])
    attrs = json.loads(subject.get("attributes_json") or "{}")
    end = subject.get("effective_end")
    if end == "9999-12-31":  # open-end sentinel, not a real termination day
        end = None
    historical = (
        evidence.historical_share_classes if kind == "fund_share_class" else
        evidence.historical_fund_listings if kind == "listing" else frozenset()
    )
    if subject_id in historical:
        lifecycle, status = "Historical", "accepted_historical_identity_and_lifecycle_owner"
    elif kind == "fund":
        current = bool(attrs.get("display_name")) and (
            str(attrs.get("population_basis") or "").startswith("csrc_product_index_")
            or attrs.get("population_basis") == "authoritative_post_index_discovery"
            or bool(attrs.get("csrc_eid_fund_id") and attrs.get("fund_type") and attrs.get("operation_type"))
        )
        if subject_id in evidence.historical_fund_subjects:
            # This assignment proves a distinct historical Product identity,
            # not its termination. Reconcile it at Product grain: accepted
            # current Product evidence may prove continuity, but a historical
            # Share Class/code interval never proves this Product ended.
            lifecycle, status = (
                ("Current", "historical_product_identity_with_accepted_current_product_evidence") if current else
                ("Unconfirmed", "historical_product_identity_without_product_level_current_or_termination_proof")
            )
            if not current:
                end = None  # no accepted Product-level exact cessation proof
        else:
            lifecycle, status = (("Current", "accepted_official_product_population") if current else
                                 ("Unconfirmed", "accepted_identity_without_current_product_lifecycle_proof"))
    elif kind == "fund_share_class":
        current = bool(attrs.get("display_name")) and (
            bool(attrs.get("offering_status") and attrs.get("parent_csrc_eid_fund_id"))
            or bool(attrs.get("csrc_eid_fund_id"))
        )
        lifecycle, status = (("Current", "accepted_official_share_class_population") if current else
                             ("Unconfirmed", "accepted_identity_without_current_share_class_lifecycle_proof"))
    elif kind == "listing":
        # Both exact-start and unknown-start current exchange rows are accepted.
        current = bool(attrs.get("display_name") or attrs.get("listing_start_date"))
        lifecycle, status = (("Current", "accepted_current_exchange_listing_population") if current else
                             ("Unconfirmed", "accepted_identity_without_current_listing_lifecycle_proof"))
    else:
        raise ValueError(f"unsupported Fund lifecycle grain: {kind}")
    if kind == "listing" and subject_id in evidence.unproved_fund_listing_ends:
        end = None  # prior value was a source last-observation date, not proved end
        status += ";exact_end_unproved"
    estimated = attrs.get("estimated_delisting_date") if kind == "listing" and lifecycle == "Current" else None
    if lifecycle == "Current" and end is not None:
        lifecycle, status, estimated = "Unconfirmed", "accepted_current_evidence_conflicts_with_recorded_end", None
    return {
        "lifecycle_class": lifecycle,
        "lifecycle_classification_status": status,
        "effective_end": end,
        "estimated_delisting_date": estimated,
    }


def equity_lifecycle(
    episode: Mapping[str, Any], *, evidence: ReleaseLifecycleEvidence,
) -> dict[str, Any]:
    """Classify accepted listings from owner state plus bounded unresolved events."""
    status = episode.get("lifecycle_status") or episode.get("lifecycle_source_status")
    code = episode.get("security_code_at_cutoff") or episode.get("external_code")
    unresolved = (
        str(episode.get("episode_evidence_key") or "") in evidence.unconfirmed_equity_episodes
        or (str(episode.get("exchange") or ""), str(code or "")) in evidence.unconfirmed_equity_codes
    )
    if status == "ended":
        lifecycle, reason = "Historical", "accepted_authoritative_listing_termination"
    elif unresolved:
        lifecycle, reason = "Unconfirmed", "accepted_listing_with_unresolved_authoritative_change"
    elif status in {"current", "current_at_cutoff"}:
        lifecycle, reason = "Current", "accepted_authoritative_current_listing_owner"
    else:
        lifecycle, reason = "Unconfirmed", "accepted_listing_without_proved_current_or_historical_state"
    estimated = None
    if lifecycle == "Current" and episode.get("listing_end_date") is not None:
        lifecycle, reason = "Unconfirmed", "accepted_current_evidence_conflicts_with_recorded_end"
    if lifecycle == "Current":
        # An official scheduled listing end is not an actual end. The evidence
        # must already be part of this immutable release's accepted owner.
        planned = {
            str(event.get("effective_date"))
            for event in episode.get("market_status_events") or []
            if event.get("event_type") == "listing_termination"
            and event.get("date_role") == "scheduled_future_listing_end"
            and event.get("source_document_sha256")
            and event.get("effective_date")
        }
        if len(planned) == 1:
            estimated = next(iter(planned))
        elif len(planned) > 1:
            lifecycle, reason = "Unconfirmed", "conflicting_official_planned_listing_ends"
    return {
        "lifecycle_class": lifecycle,
        "lifecycle_classification_status": reason,
        "estimated_delisting_date": estimated,
    }
