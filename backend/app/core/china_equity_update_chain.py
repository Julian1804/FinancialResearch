from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from backend.app.core.snapshot_manifest import reconcile_manifest_aggregate_counts
from backend.app.core.artifact_io import canonical_json, sha256_file, write_json_atomic
from backend.app.core.china_equity_bounded_plan import iter_plan_coverage, iter_plan_rows
from backend.app.core.china_equity_update_workflow import UserUpdateConfig, run_user_triggered_update
from backend.app.core.china_equity_identifiers import normalize_listing_code
from backend.app.core.hong_kong_equity_ownership import episode_key_for_change
from backend.app.core.storage_profile import (
    resolve_unpublished_snapshot_path,
)
from backend.app.core.validated_update_repository import (
    StaleUpdateHead,
    ValidatedUpdateHead,
    ValidatedUpdateRepository,
    validate_head_files,
)


UNIVERSE = "CN_A_SHARE"


class ValidatedChinaEquityUpdateRepository(ValidatedUpdateRepository):
    """Facade supplying the persisted China Equity component ID explicitly."""

    def current(self, universe: str = UNIVERSE) -> ValidatedUpdateHead | None:
        return super().current(universe)

    def history(self, universe: str = UNIVERSE) -> list[dict[str, Any]]:
        return super().history(universe)


def read_ndjson(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_ndjson_atomic(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text("".join(canonical_json(dict(row)) + "\n" for row in rows), encoding="utf-8")
    partial.replace(path)


def bootstrap_validated_a_share_head(
    repository: ValidatedChinaEquityUpdateRepository,
    *,
    seed_snapshot_id: str,
    accepted_owner_path: Path,
    authoritative_cutoff: str,
) -> ValidatedUpdateHead:
    current = repository.current()
    if current is not None:
        return current
    root = repository.path.parent / "update_state/a_share" / f"seed_{seed_snapshot_id}"
    root.mkdir(parents=True, exist_ok=True)
    reality = root / "authoritative_reality_owner_v1.ndjson"
    if not reality.is_file():
        shutil.copy2(accepted_owner_path, reality)
    state_path = root / "validated_update_state_v1.json"
    seed_state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {
            "schema_version": "fr_a_share_validated_update_state_v1",
            "universe": UNIVERSE,
            "database_generation_id": repository.database_generation_id(),
            "predecessor_snapshot_id": None,
            "successor_snapshot_id": seed_snapshot_id,
            "authoritative_cutoff": authoritative_cutoff,
            "reality_episode_count": len(read_ndjson(reality)),
            "unresolved_authoritative_changes": [],
            "family_state": {"daily": {}, "financial": {}, "documents": {}},
            "pending_point_gaps": [],
            "repaired_point_gaps": [],
            "source_receipts": [],
            "reality_receipts": [{"path": str(accepted_owner_path), "sha256": sha256_file(accepted_owner_path)}],
            "transaction_id": f"seed:{seed_snapshot_id}",
            "run_id": f"seed:{seed_snapshot_id}",
        }
    seed_state["identity_owner_path"] = str(accepted_owner_path.parent / "evidence/authoritative_identity_reconciliation_v1.json")
    seed_state["identity_owner_sha256"] = sha256_file(Path(seed_state["identity_owner_path"]))
    write_json_atomic(state_path, seed_state)
    manifest = resolve_unpublished_snapshot_path(seed_snapshot_id) / "metadata/corrected_candidate_manifest_v1.json"
    head = ValidatedUpdateHead(
        universe=UNIVERSE,
        database_generation_id=repository.database_generation_id(),
        snapshot_id=seed_snapshot_id,
        snapshot_manifest_sha256=sha256_file(manifest),
        reality_owner_path=str(reality),
        reality_owner_sha256=sha256_file(reality),
        state_path=str(state_path),
        state_sha256=sha256_file(state_path),
        authoritative_cutoff=authoritative_cutoff,
        predecessor_snapshot_id=None,
        transaction_id=f"seed:{seed_snapshot_id}",
        run_id=f"seed:{seed_snapshot_id}",
    )
    return repository.bootstrap(head)


def build_successor_reality(
    predecessor_rows: list[dict[str, Any]],
    accepted_owner_rows: list[dict[str, Any]],
    diff: Mapping[str, Any],
    *,
    authoritative_cutoff: str,
    identity_resolutions: Iterable[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    by_episode = {str(row["episode_evidence_key"]): dict(row) for row in predecessor_rows}
    accepted_by_episode = {str(row["episode_evidence_key"]): row for row in accepted_owner_rows}
    resolutions = {str(row["episode_evidence_key"]): row for row in identity_resolutions}
    for change in diff.get("deterministic_changes", []):
        episode = episode_key_for_change(change)
        if episode in accepted_by_episode:
            by_episode[episode] = dict(accepted_by_episode[episode])
        elif episode in resolutions:
            resolution = resolutions[episode]
            exchange = str(change["exchange"]).upper()
            code = normalize_listing_code(exchange, change["code"])
            by_episode[episode] = {
                "schema_version": "fr_authoritative_a_share_lifecycle_owner_v1",
                "episode_evidence_key": episode,
                "exchange": exchange,
                "security_code_at_cutoff": code,
                "security_name_at_cutoff": change["security_name"],
                "listing_start_date": change["listing_date"],
                "listing_end_date": None,
                "last_trading_date": None,
                "lifecycle_status": "current",
                "share_type": resolution.get("share_type", "A_share"),
                "security_classification": resolution.get("security_classification"),
                "reference_classification": resolution.get("reference_classification"),
                "market_jurisdiction": resolution.get("market_jurisdiction", "CN"),
                "trading_currency": resolution.get("trading_currency"),
                "board": resolution.get("board"),
                "listing_start_boundary": resolution.get("listing_start_boundary", "exact"),
                "code_aliases": [{
                    "code": code,
                    "effective_from": change["listing_date"],
                    "effective_to": None,
                    "role": "exchange_code",
                }],
                "name_aliases": [{
                    "alias_kind": "security_short_name",
                    "date_role": "authoritative_record_observation",
                    "effective_from": authoritative_cutoff,
                    "effective_to": authoritative_cutoff,
                    "source_id": change.get("source_id"),
                    "value": change["security_name"],
                }],
                "economic_entity_decision_key": resolution["entity_object_key"],
                "economic_instrument_decision_key": resolution["instrument_object_key"],
                "issuer_external_key": (
                    str(resolution["entity_object_key"]).removeprefix("cninfo_org:")
                    if exchange != "HKEX" else None
                ),
                "continuity_classification": (
                    "accepted_current_hkex_economic_security_and_unique_listing_episode"
                    if exchange == "HKEX" else
                    "existing_b_share_security_owner_onboarding_not_new_listing"
                    if change.get("change_type") == "existing_security_requires_owner_onboarding" else
                    "new_listing_episode_and_new_ordinary_share_instrument"
                ),
                "termination_reason": None,
                "authoritative_evidence_refs": list(resolution.get("provenance_refs") or []),
            }
        else:
            raise ValueError(f"deterministic reality change lacks accepted or newly resolved identity: {episode}")
    for change in diff.get("existing_subject_changes", []):
        episode = str(change["episode_evidence_key"])
        row = dict(by_episode[episode])
        aliases = list(row.get("name_aliases") or [])
        alias = {
            "alias_kind": "security_short_name",
            "date_role": "authoritative_record_observation",
            "effective_from": str(change.get("effective_at") or authoritative_cutoff)[:10],
            "effective_to": str(change.get("effective_at") or authoritative_cutoff)[:10],
            "source_id": change.get("source_id"),
            "value": change["security_name"],
        }
        if alias not in aliases:
            aliases.append(alias)
        row["name_aliases"] = aliases
        row["security_name_at_cutoff"] = change["security_name"]
        by_episode[episode] = row
    for event in diff.get("existing_subject_reality_events", []):
        episode = str(event["episode_evidence_key"])
        row = dict(by_episode[episode])
        history = list(row.get("market_status_events") or [])
        material = {
            key: event[key]
            for key in (
                "event_type", "effective_date", "date_role", "observed_at",
                "announcement_id", "source_url", "source_document_sha256",
                "evidence_excerpt",
            )
            if event.get(key) is not None
        }
        identity = (
            material.get("event_type"), material.get("effective_date"),
            material.get("announcement_id"),
        )
        if identity not in {
            (old.get("event_type"), old.get("effective_date"), old.get("announcement_id"))
            for old in history
        }:
            history.append(material)
        row["market_status_events"] = sorted(
            history,
            key=lambda item: (str(item.get("effective_date") or ""), str(item.get("event_type") or "")),
        )
        if event.get("event_type") == "listing_termination" and event.get("date_role") == "actual_listing_end":
            row["listing_end_date"] = event["effective_date"]
            row["lifecycle_status"] = "ended"
            aliases = []
            for alias in row.get("code_aliases") or []:
                alias = dict(alias)
                if str(alias.get("code") or "").zfill(6) == str(event.get("code") or "").zfill(6):
                    old_end = alias.get("effective_to")
                    if old_end is None or str(old_end) > str(event["effective_date"]):
                        alias["effective_to"] = event["effective_date"]
                aliases.append(alias)
            row["code_aliases"] = aliases
            if event.get("termination_reason"):
                row["termination_reason"] = event["termination_reason"]
        elif event.get("event_type") == "last_trading_date" and event.get("date_role") == "actual_last_trading_date":
            row["last_trading_date"] = event["effective_date"]
        elif event.get("date_role") == "actual_market_status_effective":
            row["market_status_at_cutoff"] = (
                "trading" if event["event_type"] == "trading_resumption" else "suspended"
            )
            row["market_status_effective_date"] = event["effective_date"]
        by_episode[episode] = row
    return [by_episode[key] for key in sorted(by_episode)]


def build_successor_identity_owner(
    predecessor_path: Path,
    resolutions: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    owner = json.loads(predecessor_path.read_text(encoding="utf-8"))
    objects = {str(row["episode_evidence_key"]): dict(row) for row in owner["objects"]}
    previous_ids = {kind: {row[f"{kind}_id"] for row in objects.values()} for kind in ("entity", "instrument", "listing")}
    previous_ids["series"] = {series["series_id"] for row in objects.values() for series in row.get("series", [])}
    resolutions = list(resolutions)
    added = 0
    for resolution in resolutions:
        episode = str(resolution["episode_evidence_key"])
        if episode in objects:
            continue
        objects[episode] = {
            "code": normalize_listing_code(resolution["exchange"], resolution["code"]),
            "entity_id": resolution["entity_id"],
            "episode_evidence_key": episode,
            "exchange": str(resolution["exchange"]).upper(),
            "existing_episode_reused": False,
            "instrument_id": resolution["instrument_id"],
            "lifecycle_status": resolution["lifecycle_status"],
            "listing_id": resolution["listing_id"],
            "old_entity_id": None,
            "old_instrument_id": None,
            "old_listing_id": None,
            "series": [
                {"series_family": family, "series_id": series_id}
                for family, series_id in sorted(resolution["series"].items())
            ],
        }
        added += 1
    owner["objects"] = [objects[key] for key in sorted(objects)]
    owner["listing_count"] = len(owner["objects"])
    if added:
        counts = {}
        for kind in ("entity", "instrument", "listing"):
            ids = {row[f"{kind}_id"] for row in objects.values()}
            counts[kind] = len(ids - previous_ids[kind])
            if kind != "listing":
                owner[f"{kind}_component_count"] = len(ids)
        counts["series"] = len({s["series_id"] for row in objects.values() for s in row.get("series", [])} - previous_ids["series"])
        for kind, count in counts.items():
            owner[f"{kind}_new_count"] = int(owner.get(f"{kind}_new_count", 0)) + count
        owner["decisions_after"] = int(owner.get("decisions_after", 0)) + sum(counts.values())
        owner["decisions_created_this_run"] = sum(int(r.get("created_assignment_count", 0)) for r in resolutions)
    else:
        owner["decisions_created_this_run"] = 0
    owner["result"] = "PASS"
    return owner


def _manifest_entry(path: Path, root: Path, created_at: str) -> dict[str, Any]:
    relative = path.relative_to(root).as_posix()
    payload = path.read_bytes()
    return {
        "partition_id": hashlib.sha256(canonical_json({"layer_name": "metadata", "relative_path": relative}).encode()).hexdigest(),
        "layer_name": "metadata",
        "relative_path": relative,
        "row_count": payload.count(b"\n") if path.suffix == ".ndjson" else 1,
        "byte_count": len(payload),
        "schema_sha256": hashlib.sha256(path.suffix.encode()).hexdigest(),
        "content_sha256": hashlib.sha256(payload).hexdigest(),
        "completed": True,
        "created_at_utc": created_at,
    }


def attach_successor_state(
    successor_snapshot_id: str,
    reality_source: Path,
    identity_source: Path,
    state: Mapping[str, Any],
    *,
    created_at: str,
    semantic_control_path: Path,
) -> tuple[Path, Path, Path, str]:
    root = resolve_unpublished_snapshot_path(successor_snapshot_id)
    target_root = root / "metadata/a_share_update"
    target_root.mkdir(parents=True, exist_ok=True)
    reality_target = target_root / "authoritative_reality_owner_v1.ndjson"
    # Snapshot inheritance uses hard links.  Detach successor metadata before
    # writing so a continuing update can never mutate its predecessor inode.
    reality_target.unlink(missing_ok=True)
    shutil.copy2(reality_source, reality_target)
    identity_target = target_root / "authoritative_identity_reconciliation_v1.json"
    identity_target.unlink(missing_ok=True)
    shutil.copy2(identity_source, identity_target)
    # Lifecycle amendments belong to both accepted owner projections; they do
    # not allocate/rekey a financial subject or mutate the sealed predecessor.
    lifecycle = {r["episode_evidence_key"]: r for r in read_ndjson(reality_target)}
    identity_value = json.loads(identity_target.read_text(encoding="utf-8"))
    amended = False
    for row in identity_value.get("objects", []):
        status = lifecycle[row["episode_evidence_key"]]["lifecycle_status"]
        if row.get("lifecycle_status") != status:
            row["lifecycle_status"] = status
            amended = True
    if amended:
        write_json_atomic(identity_target, identity_value)
    state_target = target_root / "validated_update_state_v1.json"
    state_target.unlink(missing_ok=True)
    write_json_atomic(state_target, {**state, "semantic_control_path": str(semantic_control_path),
        "identity_owner_path": str(identity_target), "identity_owner_sha256": sha256_file(identity_target)})
    manifest_path = root / "metadata/corrected_candidate_manifest_v1.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = {row["relative_path"]: row for row in manifest["files"]}
    for path in (reality_target, identity_target, state_target):
        row = _manifest_entry(path, root, created_at)
        entries[row["relative_path"]] = row
    manifest["files"] = sorted(entries.values(), key=lambda row: row["relative_path"])
    manifest["file_count"] = len(manifest["files"])
    manifest["compressed_bytes"] = sum(int(row["byte_count"]) for row in manifest["files"])
    manifest = reconcile_manifest_aggregate_counts(manifest)
    write_json_atomic(manifest_path, manifest)
    # All accepted owners are now final. Complete their query projection before
    # exposing a final manifest hash to validated-head CAS or publication.
    from backend.app.core.subject_graph_projection import complete_subject_graph
    from backend.app.core.china_equity_materialization import complete_accepted_daily_series_dimensions
    complete_accepted_daily_series_dimensions(semantic_control_path, identity_target)
    complete_subject_graph(root, semantic_control_path)
    return reality_target, identity_target, state_target, sha256_file(manifest_path)


def _point_gaps(
    previous_state: Mapping[str, Any],
    proof: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    pending = {
        (row["subject_code"], row["metric_id"], row["economic_date"]): dict(row)
        for row in previous_state.get("pending_point_gaps", [])
    }
    repaired: list[dict[str, Any]] = []
    plan_path = Path(proof["internal_plan_path"])
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if pending:
        for batch in iter_plan_rows(plan_path, plan, "daily_observations"):
            for row in batch:
                key = (str(row["code"]).zfill(6), row["metric_id"], row["economic_time"])
                if key in pending:
                    repaired.append({**pending.pop(key), "repaired_by_run_id": proof["run_id"]})
            if not pending:
                break
    for evidence in iter_plan_coverage(plan_path, plan):
        if evidence.get("subject_role") != "instrument" or evidence.get("route_attempt_status") == "success":
            continue
        start = evidence.get("requested_from")
        end = evidence.get("requested_to")
        if start and end and start == end:
            key = (str(evidence["code"]).zfill(6), evidence["metric_id"], start)
            pending[key] = {
                "subject_code": key[0], "metric_id": key[1], "economic_date": key[2],
                "state": "expected_point_still_missing",
                "route_outcome": evidence["route_attempt_status"],
                "evidence_path": proof["source_evidence_path"],
                "first_seen_run_id": proof["run_id"],
            }
    return list(sorted(pending.values(), key=lambda row: (row["subject_code"], row["metric_id"], row["economic_date"]))), repaired


def run_continuous_user_update(
    *,
    repository: ValidatedChinaEquityUpdateRepository,
    base_config: UserUpdateConfig,
    accepted_owner_path: Path,
    identity_state: Any,
    materialize: Callable[[Path, Path], dict[str, Any]],
    run_id: str,
) -> dict[str, Any]:
    head = repository.current()
    if head is None:
        raise RuntimeError("validated A-share update head is not initialized")
    if head.database_generation_id != repository.database_generation_id():
        raise ValueError("validated update head generation is not current")
    run_root = base_config.output_root / "runs" / run_id
    if run_root.exists():
        raise FileExistsError(f"immutable update run already exists: {run_id}")
    run_root.mkdir(parents=True)
    prior_state = json.loads(Path(head.state_path).read_text(encoding="utf-8"))
    prior_market_cutoffs = dict(prior_state.get("market_authoritative_cutoffs") or {
        "mainland_china": head.authoritative_cutoff,
        "hong_kong": head.authoritative_cutoff,
    })
    if set(prior_market_cutoffs) != {"mainland_china", "hong_kong"}:
        raise ValueError("Equity market cutoff owner is incomplete")
    baseline_date = (prior_market_cutoffs[base_config.market_scope]
                     if base_config.market_scope is not None else head.authoritative_cutoff)
    config = replace(
        base_config,
        output_root=run_root,
        lifecycle_path=Path(head.reality_owner_path),
        identity_reconciliation_path=Path(prior_state["identity_owner_path"]),
        predecessor_snapshot_id=head.snapshot_id,
        baseline_reality_date=baseline_date,
        previous_update_state=prior_state,
    )
    try:
        proof = run_user_triggered_update(config, identity_state=identity_state, materialize=materialize)
        proof["run_id"] = run_id
        proof["internal_plan_path"] = str(run_root / "internal_update_plan_v1.json")
        proof["source_evidence_path"] = str(run_root / "source_route_execution_v1.json")
        if proof["canonical_transaction"].get("no_op"):
            result = {
                "schema_version": "fr_a_share_continuous_update_chain_run_v1",
                "run_id": run_id, "predecessor_snapshot_id": head.snapshot_id,
                "successor_snapshot_id": None, "head_advanced": False,
                "no_op": True, "result": "PASS",
                "source_route_warnings": proof["authoritative_refresh"].get("source_route_warnings", []),
            }
            write_json_atomic(run_root / "chain_run_result_v1.json", result)
            return result

        plan = json.loads(Path(proof["internal_plan_path"]).read_text(encoding="utf-8"))
        predecessor_rows = read_ndjson(Path(head.reality_owner_path))
        accepted_rows = read_ndjson(accepted_owner_path)
        reality_rows = build_successor_reality(
            predecessor_rows,
            accepted_rows,
            {
                **proof["reality_diff"],
                "existing_subject_reality_events": plan.get("existing_subject_reality_events", []),
            },
            authoritative_cutoff=config.as_of_date,
            identity_resolutions=plan.get("identity_resolutions", []),
        )
        reality_by_episode = {row["episode_evidence_key"]: row for row in reality_rows}
        for change in proof["reality_diff"].get("deterministic_changes", []):
            episode = episode_key_for_change(change)
            if episode not in reality_by_episode:
                raise ValueError(f"validated successor omitted deterministic reality change: {episode}")
        for change in proof["reality_diff"].get("existing_subject_changes", []):
            row = reality_by_episode.get(change["episode_evidence_key"])
            if not row or row.get("security_name_at_cutoff") != change["security_name"]:
                raise ValueError("validated successor omitted existing-subject authoritative change")
        for event in plan.get("existing_subject_reality_events", []):
            row = reality_by_episode.get(event["episode_evidence_key"])
            identities = {
                (item.get("event_type"), item.get("effective_date"), item.get("announcement_id"))
                for item in (row or {}).get("market_status_events", [])
            }
            expected = (event["event_type"], event["effective_date"], event["announcement_id"])
            if expected not in identities:
                raise ValueError("validated successor omitted existing-subject market-status event")
        reality_stage = run_root / "successor_reality_owner_v1.ndjson"
        write_ndjson_atomic(reality_stage, reality_rows)
        identity_stage = run_root / "successor_identity_reconciliation_v1.json"
        write_json_atomic(identity_stage, build_successor_identity_owner(
            config.identity_reconciliation_path, plan.get("identity_resolutions", [])
        ))
        previous_state = json.loads(Path(head.state_path).read_text(encoding="utf-8"))
        pending, repaired = _point_gaps(previous_state, proof)
        identity_target = resolve_unpublished_snapshot_path(proof["successor_snapshot_id"]) / "metadata/a_share_update/authoritative_identity_reconciliation_v1.json"
        source_progress = dict(plan.get("source_event_progress") or {})

        def family_state(name: str) -> dict[str, Any]:
            prior = dict(previous_state.get("family_state", {}).get(name) or {})
            result = {**prior, **dict(source_progress.get(name) or {})}
            result["scope_count"] = proof["source_execution"]["family_scope_counts"].get(name, 0)
            if result["scope_count"]:
                result["latest_attempt_cutoff"] = config.as_of_date
            return result

        market_cutoffs = dict(prior_market_cutoffs)
        if config.market_scope is None:
            market_cutoffs = {key: config.as_of_date for key in market_cutoffs}
        else:
            market_cutoffs[config.market_scope] = config.as_of_date
        conservative_cutoff = min(market_cutoffs.values())
        state = {
            "schema_version": "fr_a_share_validated_update_state_v1",
            "universe": UNIVERSE,
            "database_generation_id": head.database_generation_id,
            "predecessor_snapshot_id": head.snapshot_id,
            "successor_snapshot_id": proof["successor_snapshot_id"],
            # The compatibility head field is a conservative shared lower
            # bound.  Each market's actual authority is recorded separately;
            # a failed market never inherits the successful market's date.
            "authoritative_cutoff": conservative_cutoff,
            "market_authoritative_cutoffs": market_cutoffs,
            "reality_episode_count": len(reality_rows),
            "unresolved_authoritative_changes": proof["source_execution"]["unresolved_changes"],
            "family_state": {
                "daily": family_state("daily"),
                "financial": family_state("financial"),
                "documents": family_state("documents"),
                "reality": family_state("reality"),
            },
            "pending_point_gaps": pending,
            "repaired_point_gaps": list(previous_state.get("repaired_point_gaps", [])) + repaired,
            "source_receipts": [{"path": proof["source_evidence_path"], "sha256": sha256_file(Path(proof["source_evidence_path"]))}],
            "reality_receipts": [{"path": str(run_root / "authoritative_refresh_v1.json"), "sha256": sha256_file(run_root / "authoritative_refresh_v1.json")}],
            "transaction_id": proof["successor_snapshot_id"],
            "run_id": run_id,
            "plan_sha256": sha256_file(Path(proof["internal_plan_path"])),
            "point_coverage_evidence_count": int((plan.get("coverage_evidence") or {}).get("count", 0)),
            "pending_source_event_count": sum(
                len(row.get("pending_events", [])) for row in source_progress.values()
            ),
            "identity_owner_path": str(identity_target),
            "identity_owner_sha256": sha256_file(identity_stage),
        }
        reality_target, identity_target, state_target, manifest_hash = attach_successor_state(
            proof["successor_snapshot_id"], reality_stage, identity_stage, state,
            created_at=plan["created_at_utc"],
            semantic_control_path=Path(plan["successor_control_path"]),
        )
        candidate = ValidatedUpdateHead(
            universe=UNIVERSE,
            database_generation_id=head.database_generation_id,
            snapshot_id=proof["successor_snapshot_id"],
            snapshot_manifest_sha256=manifest_hash,
            reality_owner_path=str(reality_target),
            reality_owner_sha256=sha256_file(reality_target),
            state_path=str(state_target),
            state_sha256=sha256_file(state_target),
            authoritative_cutoff=conservative_cutoff,
            predecessor_snapshot_id=head.snapshot_id,
            transaction_id=proof["successor_snapshot_id"],
            run_id=run_id,
        )
        repository.compare_and_swap(head.snapshot_id, candidate)
        result = {
            "schema_version": "fr_a_share_continuous_update_chain_run_v1",
            "run_id": run_id, "predecessor_snapshot_id": head.snapshot_id,
            "successor_snapshot_id": candidate.snapshot_id,
            "head_advanced": True, "no_op": False,
            "reality_change_count": plan.get("reality_change_count", 0),
            "family_scope_counts": proof["source_execution"]["family_scope_counts"],
            "pending_point_gap_count": len(pending),
            "repaired_point_gap_count": len(repaired),
            "pending_source_event_count": state["pending_source_event_count"],
            "source_route_warnings": proof["authoritative_refresh"].get("source_route_warnings", []),
            "manifest_sha256": manifest_hash,
            "result": "PASS",
        }
        write_json_atomic(run_root / "chain_run_result_v1.json", result)
        return result
    except Exception as exc:
        failure = {
            "schema_version": "fr_a_share_continuous_update_chain_failure_v1",
            "run_id": run_id,
            "predecessor_snapshot_id": head.snapshot_id,
            "head_after_failure": repository.current().snapshot_id if repository.current() else None,
            "error_type": type(exc).__name__, "error": str(exc), "result": "FAIL",
        }
        write_json_atomic(run_root / "chain_run_failure_v1.json", failure)
        raise


# Python compatibility for historical callers; the persisted component ID and
# snapshot metadata above are deliberately unchanged.
ValidatedAShareUpdateRepository = ValidatedChinaEquityUpdateRepository
