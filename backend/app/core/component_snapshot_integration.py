"""Immutable Fund/Equity component integration, without historical fact reads.

Component payload remains authoritative. Shared semantic metadata is reconciled
against the inherited baseline; disagreement is not settled by last-writer-wins.
"""
from __future__ import annotations

import json
import os
import hashlib
import shutil
import sqlite3
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from backend.app.core.artifact_io import canonical_json, sha256_file, write_json_atomic
from backend.app.core.snapshot_manifest import clone_snapshot_from_manifest, reconcile_manifest_aggregate_counts
from backend.app.core.storage_profile import resolve_unpublished_snapshot_path, resolve_unpublished_control_path

MANIFEST = "metadata/corrected_candidate_manifest_v1.json"
FUND_CONTROL = "metadata/china_public_fund/fr_china_public_fund_control_v1.sqlite"
GRAPH = {"metadata/subject_graph/subjects.parquet": "subject_registry",
         "metadata/subject_graph/relationships.parquet": "subject_relationship_registry"}


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _semantic(row):
    return {k: json.loads(v) if k.endswith("_json") and v is not None else v
            for k, v in row.items() if k != "updated_at_utc"}


def _key(row):
    return (row["relationship_id"],) if "relationship_id" in row else (row["subject_type"], row["subject_id"])


def integrate_component_payload(*, equity_snapshot_id: str, fund_snapshot_id: str,
                                fund_baseline_id: str, successor_snapshot_id: str, resume: bool = False) -> dict[str, Any]:
    """Build an unpublished union; callers still own seal, QA, CAS and publish."""
    eq = resolve_unpublished_snapshot_path(equity_snapshot_id)
    fund = resolve_unpublished_snapshot_path(fund_snapshot_id)
    root = resolve_unpublished_snapshot_path(successor_snapshot_id)
    if root.exists() and not resume:
        raise FileExistsError(root)
    em, fm = _load(eq / MANIFEST), _load(fund / MANIFEST)
    if em.get("database_generation_id") != fm.get("database_generation_id"):
        raise ValueError("component integration mixes database generations")
    clone = clone_snapshot_from_manifest(equity_snapshot_id, successor_snapshot_id)
    members = {r["relative_path"]: dict(r) for r in em["files"]}
    linked, replaced = [], []
    for row in fm["files"]:
        rel = row["relative_path"]
        old = members.get(rel)
        if old and old["content_sha256"] == row["content_sha256"]:
            continue
        if old and not rel.startswith("metadata/china_public_fund/"):
            if rel.startswith("metadata/"):
                continue  # shared projections are reconciled explicitly below
            raise ValueError(f"immutable component payload collision: {rel}")
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target.unlink()  # detach only this new unpublished hardlink
            replaced.append(rel)
        else:
            linked.append(rel)
        os.link(fund / rel, target)
        members[rel] = dict(row)
    # The Fund branch has not changed shared coverage logically. Refuse an
    # unknown coverage merge instead of selecting a stale component projection.
    baseline = resolve_unpublished_snapshot_path(fund_baseline_id)
    coverage = "metadata/coverage/coverage_rows.parquet"
    if not pq.ParquetFile(fund / coverage).read().equals(pq.ParquetFile(baseline / coverage).read()):
        raise ValueError("Fund shared coverage changed; explicit coverage reconciliation is required")
    manifest = {**em, "snapshot_id": successor_snapshot_id, "predecessor_snapshot_id": equity_snapshot_id,
                "component_integration": {"equity_snapshot_id": equity_snapshot_id,
                                          "fund_snapshot_id": fund_snapshot_id,
                                          "fund_baseline_id": fund_baseline_id},
                "files": sorted(members.values(), key=lambda r: r["relative_path"])}
    manifest["file_count"] = len(manifest["files"])
    manifest["compressed_bytes"] = sum(r["byte_count"] for r in manifest["files"])
    write_json_atomic(root / MANIFEST, reconcile_manifest_aggregate_counts(manifest))
    return {"clone": clone, "fund_linked_members": linked, "fund_replaced_members": replaced,
            "historical_fact_rows_read": 0, "root": str(root)}


def merge_component_semantics(*, root: Path, control: Path, fund_snapshot_id: str,
                              fund_baseline_id: str) -> dict[str, Any]:
    """Merge Fund graph amendments and bounded control deltas into Eq control."""
    fund = resolve_unpublished_snapshot_path(fund_snapshot_id)
    baseline = resolve_unpublished_snapshot_path(fund_baseline_id)
    counts = {"graph_amendments": 0, "delta_subjects": 0, "delta_relationships": 0}
    with sqlite3.connect(control) as target:
        target.row_factory = sqlite3.Row
        for relative, table in GRAPH.items():
            before = {_key(r): r for r in pq.ParquetFile(baseline / relative).read().to_pylist()}
            for row in pq.ParquetFile(fund / relative).read().to_pylist():
                old = before.pop(_key(row), None)
                if old is not None and _semantic(old) == _semantic(row):
                    continue
                columns = ["relationship_id"] if "relationship_id" in row else ["subject_type", "subject_id"]
                current = target.execute(f"SELECT * FROM {table} WHERE " + " AND ".join(f"{k}=?" for k in columns), _key(row)).fetchone()
                if current and _semantic(dict(current)) != _semantic(row) and (old is None or _semantic(dict(current)) != _semantic(old)):
                    raise ValueError("competing accepted component semantic amendments")
                names = list(row)
                target.execute(f"INSERT OR REPLACE INTO {table} ({','.join(names)}) VALUES ({','.join('?' for _ in names)})", tuple(row.values()))
                counts["graph_amendments"] += 1
            if before:
                raise ValueError("Fund graph removed inherited subjects/relationships")
        # Follow only the accepted new control-delta chain, not financial data.
        chain = []
        sid = fund_snapshot_id
        while sid != fund_baseline_id:
            if sid in chain or len(chain) > 64:
                raise ValueError("invalid Fund control ancestry")
            chain.append(sid)
            path = resolve_unpublished_snapshot_path(sid) / FUND_CONTROL
            with sqlite3.connect("file:" + path.as_posix() + "?mode=ro", uri=True) as source:
                source.row_factory = sqlite3.Row
                info = source.execute("SELECT * FROM control_delta_metadata").fetchone()
                if not info or info["snapshot_id"] != sid:
                    raise ValueError("Fund delta ancestry is not explicit")
                if source.execute("SELECT count(*) FROM control_record_tombstone").fetchone()[0]:
                    raise ValueError("Fund semantic deletion requires explicit owner reconciliation")
                parent = resolve_unpublished_snapshot_path(str(info["predecessor_snapshot_id"]))
                if sha256_file(parent / MANIFEST) != info["predecessor_manifest_sha256"]:
                    raise ValueError("Fund semantic parent manifest is not bound")
                parent_control = next(r for r in _load(parent / MANIFEST)["files"] if r["relative_path"] == FUND_CONTROL)
                if parent_control["content_sha256"] != info["predecessor_control_sha256"]:
                    raise ValueError("Fund semantic parent control is not bound")
                sid = str(info["predecessor_snapshot_id"])
        for sid in reversed(chain):
            path = resolve_unpublished_snapshot_path(sid) / FUND_CONTROL
            with sqlite3.connect("file:" + path.as_posix() + "?mode=ro", uri=True) as source:
                source.row_factory = sqlite3.Row
                for table, label in [("subject_registry", "delta_subjects"), ("subject_relationship_registry", "delta_relationships")]:
                    for value in source.execute(f"SELECT * FROM {table}"):
                        row = dict(value)
                        if table == "subject_registry" and json.loads(row["attributes_json"]).get("universe") != "Fund":
                            raise ValueError("Fund semantic delta attempts to own another Universe")
                        if table == "subject_registry":
                            current = target.execute("SELECT attributes_json FROM subject_registry WHERE subject_type=? AND subject_id=?",
                                (row["subject_type"], row["subject_id"])).fetchone()
                            if current and json.loads(current[0]).get("universe") not in {None, "Fund"}:
                                raise ValueError("Fund semantic delta conflicts with another Universe owner")
                        names = list(row)
                        target.execute(f"INSERT OR REPLACE INTO {table} ({','.join(names)}) VALUES ({','.join('?' for _ in names)})", tuple(row.values()))
                        counts[label] += 1
        target.commit()
    return {**counts, "fund_control_ancestry": chain, "financial_fact_rows_read": 0}


def publication_union_if_needed(*, candidate_snapshot_id: str, equity_snapshot_id: str,
                                fund_snapshot_id: str) -> str:
    """Rebase diverged component branches before sealing a composite descriptor.

    Validated component heads are not rewritten. The composed physical snapshot
    is separately immutable, while each component retains its exact identity.
    """
    candidate = resolve_unpublished_snapshot_path(candidate_snapshot_id)
    have = {r["relative_path"]: r for r in _load(candidate / MANIFEST)["files"]}
    needs_union = False
    for sid in (equity_snapshot_id, fund_snapshot_id):
        for row in _load(resolve_unpublished_snapshot_path(sid) / MANIFEST)["files"]:
            rel = row["relative_path"]
            if rel not in have or (rel.startswith("metadata/china_public_fund/")
                                  and have[rel]["content_sha256"] != row["content_sha256"]
                                  and sid == fund_snapshot_id):
                needs_union = True
    if not needs_union:
        return candidate_snapshot_id
    from backend.app.core.subject_graph_projection import complete_subject_graph, verify_subject_graph_completion
    eqroot = resolve_unpublished_snapshot_path(equity_snapshot_id)
    state_rel = "metadata/a_share_update/validated_update_state_v1.json"
    state = _load(eqroot / state_rel)
    fund_state = _load(eqroot / "metadata/china_public_fund/validated_update_state_v1.json")
    baseline = str(fund_state["successor_snapshot_id"])
    digest = hashlib.sha256(canonical_json({"equity": equity_snapshot_id, "fund": fund_snapshot_id,
        "equity_manifest": sha256_file(eqroot / MANIFEST),
        "fund_manifest": sha256_file(resolve_unpublished_snapshot_path(fund_snapshot_id) / MANIFEST)}).encode()).hexdigest()[:24]
    sid = "frcomposite_" + digest
    root = resolve_unpublished_snapshot_path(sid)
    receipt = root / "metadata/subject_graph/completion_v1.json"
    if receipt.is_file() and _load(receipt).get("snapshot_id") == sid:
        verify_subject_graph_completion(root, deep=True)
        return sid
    integrate_component_payload(equity_snapshot_id=equity_snapshot_id, fund_snapshot_id=fund_snapshot_id,
                                fund_baseline_id=baseline, successor_snapshot_id=sid, resume=True)
    control = resolve_unpublished_control_path(sid)
    control.parent.mkdir(parents=True, exist_ok=True)
    # An unsealed interrupted union may be resumed from the same immutable
    # component inputs. Never reuse a partially copied semantic database.
    temporary = control.with_suffix(".partial")
    shutil.copy2(state["semantic_control_path"], temporary)
    os.replace(temporary, control)
    merge_component_semantics(root=root, control=control, fund_snapshot_id=fund_snapshot_id,
                              fund_baseline_id=baseline)
    write_json_atomic(root / state_rel, {**state, "semantic_control_path": str(control)})
    manifest = _load(root / MANIFEST)
    for row in manifest["files"]:
        if row["relative_path"] == state_rel:
            row.update(content_sha256=sha256_file(root / state_rel), byte_count=(root / state_rel).stat().st_size)
    write_json_atomic(root / MANIFEST, reconcile_manifest_aggregate_counts(manifest))
    complete_subject_graph(root, control)
    return sid
