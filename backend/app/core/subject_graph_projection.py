"""Complete and seal snapshot-local query metadata, never allocate identity.

The supplied SQLite registry is the successor's accepted semantic owner, not
the installation operation database. Projection copies its statuses verbatim.
Legacy releases without a completion receipt remain readable/rollbackable;
new Equity successors must complete before head acceptance and publication.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from backend.app.core.artifact_io import canonical_json, sha256_file, write_json_atomic

SUBJECTS = "metadata/subject_graph/subjects.parquet"
RELATIONSHIPS = "metadata/subject_graph/relationships.parquet"
COMPLETION = "metadata/subject_graph/completion_v1.json"
IDENTITY = "metadata/a_share_update/authoritative_identity_reconciliation_v1.json"
REALITY = "metadata/a_share_update/authoritative_reality_owner_v1.ndjson"
MANIFEST = "metadata/corrected_candidate_manifest_v1.json"
TABLES = {SUBJECTS: "subject_registry", RELATIONSHIPS: "subject_relationship_registry"}
ACCEPTED = frozenset({"standard_id_ready", "high_confidence_existing_identity_evidence",
                      "accepted_authoritative_identity", "accepted_authoritative_lifecycle", "accepted_lifecycle"})


class SubjectGraphCompletionError(ValueError):
    pass


def _key(row: dict[str, Any]) -> tuple[str, ...]:
    if "relationship_id" in row:
        return (row["relationship_id"],)
    return (row["subject_type"], row["subject_id"])


def _semantic(row: dict[str, Any]) -> dict[str, Any]:
    return {key: json.loads(value) if key.endswith("_json") and value is not None else value
            for key, value in row.items() if key != "updated_at_utc"}


def _index(rows: list[dict[str, Any]]) -> dict[tuple[str, ...], dict[str, Any]]:
    result = {_key(row): row for row in rows}
    if len(result) != len(rows):
        raise SubjectGraphCompletionError("duplicate subject graph semantic key")
    return result


def _digest(rows: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for row in sorted(rows, key=_key):
        digest.update((canonical_json(_semantic(row)) + "\n").encode("utf-8"))
    return digest.hexdigest()


def _registry(control: Path) -> dict[str, list[dict[str, Any]]]:
    with closing(sqlite3.connect(control.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN")  # one coherent semantic read, including WAL
        return {relative: [dict(row) for row in connection.execute(f"SELECT * FROM {table}")]
                for relative, table in TABLES.items()}


def _check_endpoints(subjects: list[dict[str, Any]], relationships: list[dict[str, Any]]) -> None:
    index = _index(subjects)
    _index(relationships)
    query_keys = {}
    for row in relationships:
        # Frozen pre-V1 high-confidence compatibility edges are preserved, not
        # newly promoted or re-adjudicated here (some non-serving Universes use
        # historical endpoint conventions). Current accepted writes are strict.
        if row["resolution_status"] not in ACCEPTED or row["resolution_status"] == "high_confidence_existing_identity_evidence":
            continue
        for prefix in ("from", "to"):
            endpoint = index.get((row[f"{prefix}_type"], row[f"{prefix}_id"]))
            if endpoint is None or endpoint["resolution_status"] not in ACCEPTED:
                raise SubjectGraphCompletionError("accepted relationship has missing or candidate endpoint")
        if row["relationship_type"] == "quoted_on" and row["resolution_status"] == "standard_id_ready":
            attributes = json.loads(row["attributes_json"])
            series = index[(row["from_type"], row["from_id"])]
            dimensions = json.loads(series["attributes_json"]).get("series_dimensions") or {}
            if not attributes.get("series_family") or not dimensions.get("adjustment_basis"):
                raise SubjectGraphCompletionError("query-visible Series lacks family or adjustment basis")
            key = (row["to_id"], attributes["series_family"], dimensions["adjustment_basis"])
            if key in query_keys and query_keys[key] != row["from_id"]:
                raise SubjectGraphCompletionError("ambiguous query-visible listing/family/adjustment Series")
            query_keys[key] = row["from_id"]
    financial_parents = {row["from_id"] for row in relationships
                         if row["relationship_type"] == "series_of" and row["to_type"] == "entity"
                         and row["resolution_status"] == "standard_id_ready"}
    for row in subjects:
        if (row["subject_type"] == "series" and row["resolution_status"] == "standard_id_ready"
                and json.loads(row["attributes_json"]).get("series_family") == "financial_reporting"
                and row["subject_id"] not in financial_parents):
            raise SubjectGraphCompletionError("accepted financial Series has no entity parent")


def _check_equity_owner(root: Path, subjects: list[dict[str, Any]], relationships: list[dict[str, Any]]) -> None:
    """Check accepted owner endpoints; no provider inference or ID allocation."""
    if not (root / IDENTITY).is_file():
        raise SubjectGraphCompletionError("successor has no accepted Equity identity owner")
    index = _index(subjects)
    edges = {(row["from_type"], row["from_id"], row["relationship_type"], row["to_type"], row["to_id"]): row
             for row in relationships}
    for obj in json.loads((root / IDENTITY).read_text(encoding="utf-8")).get("objects", []):
        for kind in ("entity", "instrument", "listing"):
            subject = index.get((kind, obj[f"{kind}_id"]))
            if subject is None or subject["resolution_status"] not in ACCEPTED:
                raise SubjectGraphCompletionError("accepted Equity owner endpoint is absent from query projection")
        for series in obj.get("series", []):
            sid = series["series_id"]
            subject = index.get(("series", sid))
            quoted = edges.get(("series", sid, "quoted_on", "listing", obj["listing_id"]))
            parent = edges.get(("series", sid, "series_of", "instrument", obj["instrument_id"]))
            if subject is None or quoted is None or parent is None:
                raise SubjectGraphCompletionError("accepted Equity Series is not query-resolvable")
            if (subject["resolution_status"] != "standard_id_ready"
                    or quoted["resolution_status"] != "standard_id_ready"
                    or parent["resolution_status"] != "standard_id_ready"
                    or json.loads(quoted["attributes_json"]).get("series_family") != series["series_family"]):
                raise SubjectGraphCompletionError("accepted Equity Series attributes/status disagree")


def _member(path: Path, root: Path, count: int) -> dict[str, Any]:
    relative = path.relative_to(root).as_posix()
    content_hash = sha256_file(path)
    return {"relative_path": relative, "layer_name": "metadata", "row_count": count,
            "byte_count": path.stat().st_size, "content_sha256": content_hash,
            "partition_id": hashlib.sha256(relative.encode()).hexdigest(), "completed": True}


def complete_subject_graph(root: Path, control: Path) -> dict[str, Any]:
    """Explicit unpublished-write boundary, before the final manifest identity.

    Full registry export is metadata-only, not a fact rebuild. Unknown graph-only
    keys fail closed rather than deleting content owned by another component.
    Atomic replacement detaches inherited hardlinks before changing bytes.
    """
    source = _registry(control)
    _check_endpoints(source[SUBJECTS], source[RELATIONSHIPS])
    _check_equity_owner(root, source[SUBJECTS], source[RELATIONSHIPS])
    manifest_path = root / MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = {row["relative_path"]: row for row in manifest["files"]}
    if (root / COMPLETION).is_file() and COMPLETION in entries:
        prior = json.loads((root / COMPLETION).read_text(encoding="utf-8"))
        if (all(prior.get("registries", {}).get(relative, {}).get("semantic_sha256") == _digest(rows)
                for relative, rows in source.items())
                and prior.get("owner_sha256") == {p: sha256_file(root / p) for p in (IDENTITY, REALITY)}
                and prior.get("snapshot_id") == manifest["snapshot_id"]):
            del source
            return verify_subject_graph_completion(root, control=control)
    result = {}
    for relative, rows in source.items():
        path = root / relative
        previous = pq.read_table(path).to_pylist()
        before, after = _index(previous), _index(rows)
        if before.keys() - after.keys():
            raise SubjectGraphCompletionError("control omits inherited graph keys; explicit owner treatment required")
        result[relative] = {"row_count": len(rows), "semantic_sha256": _digest(rows),
                            "added": len(after.keys() - before.keys()),
                            "changed": sum(_semantic(before[k]) != _semantic(after[k]) for k in before),
                            "unchanged": sum(_semantic(before[k]) == _semantic(after[k]) for k in before)}
        del previous, before, after
    for relative, rows in source.items():
        path = root / relative
        if _digest(pq.read_table(path).to_pylist()) != result[relative]["semantic_sha256"]:
            schema = pq.ParquetFile(path).schema_arrow
            temporary = path.with_name(f".{path.name}.{os.getpid()}.partial")
            pq.write_table(pa.Table.from_pylist(sorted(rows, key=_key), schema=schema), temporary, compression="zstd")
            os.replace(temporary, path)
        entries[relative] = _member(path, root, len(rows))
    receipt = {"schema_version": "fr_subject_graph_completion_v1", "snapshot_id": manifest["snapshot_id"],
               "database_generation_id": manifest.get("database_generation_id"),
               "semantic_owner": "snapshot_local_subject_and_relationship_registry",
               "registries": result,
               "owner_sha256": {relative: sha256_file(root / relative) for relative in (IDENTITY, REALITY)},
               "graph_sha256": {relative: sha256_file(root / relative) for relative in TABLES}}
    # Receipt is an immutable finalization proof, not a new financial authority.
    write_json_atomic(root / COMPLETION, receipt)
    entries[COMPLETION] = _member(root / COMPLETION, root, 1)
    manifest["files"] = sorted(entries.values(), key=lambda row: row["relative_path"])
    manifest["file_count"] = len(entries)
    manifest["compressed_bytes"] = sum(int(row["byte_count"]) for row in entries.values())
    write_json_atomic(manifest_path, manifest)
    # Do not retain the full exported registry while the independent readback
    # loads its own copy. The proof and all financial checks remain unchanged.
    del source, rows
    return verify_subject_graph_completion(root, control=control)


def verify_subject_graph_completion(root: Path, *, control: Path | None = None, deep: bool = True) -> dict[str, Any]:
    """Read-only proof at head acceptance (with control) / publication (sealed).

    Sealed reads need no mutable installation state. Source SQL is independently
    compared at head acceptance; publication consumes the manifest-bound proof.
    """
    manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    members = {row["relative_path"]: row for row in manifest["files"]}
    if COMPLETION not in members or not (root / COMPLETION).is_file():
        raise SubjectGraphCompletionError("successor subject graph semantic completion is missing")
    if sha256_file(root / COMPLETION) != members[COMPLETION]["content_sha256"]:
        raise SubjectGraphCompletionError("subject graph completion receipt hash mismatch")
    receipt = json.loads((root / COMPLETION).read_text(encoding="utf-8"))
    if (receipt.get("schema_version") != "fr_subject_graph_completion_v1"
            or receipt.get("snapshot_id") != manifest["snapshot_id"]
            or receipt.get("database_generation_id") != manifest.get("database_generation_id")):
        raise SubjectGraphCompletionError("subject graph completion binding mismatch")
    for relative in (IDENTITY, REALITY, *TABLES):
        expected = (receipt["graph_sha256"] if relative in TABLES else receipt["owner_sha256"]).get(relative)
        if (relative not in members or expected != members[relative]["content_sha256"]
                or not (root / relative).is_file()
                or (root / relative).stat().st_size != members[relative]["byte_count"]
                or (deep and sha256_file(root / relative) != expected)):
            raise SubjectGraphCompletionError("subject graph or accepted owner changed after completion")
    if not deep and control is None:
        return receipt  # request-time consumption of the lifecycle-bound proof
    projected = {relative: pq.read_table(root / relative).to_pylist() for relative in TABLES}
    for relative, rows in projected.items():
        actual = _digest(rows)
        expected = receipt["registries"][relative]
        if actual != expected["semantic_sha256"] or len(rows) != expected["row_count"]:
            raise SubjectGraphCompletionError("query graph semantic digest mismatch")
    _check_endpoints(projected[SUBJECTS], projected[RELATIONSHIPS])
    _check_equity_owner(root, projected[SUBJECTS], projected[RELATIONSHIPS])
    # Validate both authorities, sequentially: equality of the independently
    # recomputed semantic digests does not require both object graphs in RAM.
    del projected, rows
    if control is not None:
        source = _registry(control)
        for relative, rows in source.items():
            if _digest(rows) != receipt["registries"][relative]["semantic_sha256"]:
                raise SubjectGraphCompletionError("query graph differs from successor semantic control")
    return receipt
