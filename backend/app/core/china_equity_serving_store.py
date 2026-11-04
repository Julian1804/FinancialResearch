"""Release-bound China Equity serving store (immutable indexed shards).

Measured access-path selection established the B-tree (SQLite) indexed
serving layer over the authoritative Parquet standard facts.  This module
owns the derived-artifact lifecycle that makes that layer safe to serve:

- every derived artifact is one immutable, content-addressed shard: one
  SQLite file per source standard-facts member, named by the source member's
  content hash and never mutated after it is built;
- building a shard computes its own cryptographic content identity
  (SHA-256) plus row count and the SQLite header change counter, all
  recorded in the generation manifest;
- a generation manifest binds the shard set to the exact release identity,
  the China Equity component manifest identity, and per-source-member
  content signatures; its own hash is its name and is also self-checked;
- activation is one atomic pointer replacement to the verified generation
  (``build -> validate -> hash -> bind -> atomic activation``); a failed or
  interrupted build leaves the previous generation active and untouched;
- serving resolves the current generation, verifies the binding and the
  shard tripwires (file presence, size, SQLite change counter), seeks the
  in-range shards, and falls back to the production Parquet path on any
  unbound or tripped state.  Full content re-verification belongs to the
  explicit ``verify`` lifecycle command and to rebuilds of changed members;
- maintenance is driven by the real update change unit: unchanged source
  members reuse their immutable shards, changed/new members build only
  their own shards.  Ordinary trading-day updates touch only the small
  continuing-update members of the current year (the year members are
  hard-linked immutables across successors), so ordinary maintenance cost
  is proportional to changed data, not history.

Build pragmas such as ``journal_mode=OFF`` are applied only while writing a
not-yet-activated shard file.  Active shards are opened read-only and are
never mutated in place.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence

import pyarrow.parquet as pq

from backend.app.core.artifact_io import canonical_json, sha256_file, utc_now, write_json_atomic
from backend.app.core.storage_profile import resolve_serving_derived_path


SERVING_DIRECTORY = "china_equity"
SHARDS_DIRECTORY = "shards"
GENERATIONS_DIRECTORY = "generations"
POINTER_FILE = "current.json"
GENERATION_SCHEMA = "fr_china_equity_serving_generation_v1"
POINTER_SCHEMA = "fr_china_equity_serving_pointer_v1"
LEGACY_STORE_FILE = "equity_series_v1.sqlite"
LEGACY_RECEIPT_FILE = "build_receipt_v1.json"

SERVING_COLUMNS = [
    "logical_fact_key", "metric_id", "series_id", "economic_time",
    "normalized_value", "canonical_unit", "canonical_currency", "canonical_scale",
    "source_observation_key", "primary_time_role",
]


class ServingStoreError(RuntimeError):
    pass


def _is_serving_member(relative_path: str) -> bool:
    """The real serving member set.

    The production update materializer writes small immutable delta members
    named ``part-continuing-update-<delta_tag>.parquet`` for promoted facts;
    ordinary updates reuse the year members via hard links.  Serving must
    include every continuing-update-tagged member plus the exact year names.
    """
    if not relative_path.startswith("standard_facts/domain=equity/year="):
        return False
    name = Path(relative_path).name
    return (
        name == "part-a-share.parquet"
        or name == "part-authoritative-a-share-lifecycle.parquet"
        or name.startswith("part-continuing-update")
    )


def store_directory() -> Path:
    return resolve_serving_derived_path(SERVING_DIRECTORY)


def shards_directory() -> Path:
    return store_directory() / SHARDS_DIRECTORY


def generations_directory() -> Path:
    return store_directory() / GENERATIONS_DIRECTORY


def pointer_path() -> Path:
    return store_directory() / POINTER_FILE


def shard_file_name(source_content_sha256: str) -> str:
    return f"facts_{str(source_content_sha256)[:16]}.sqlite"


def _source_members(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    return sorted(
        (dict(row) for row in manifest.get("files", []) if _is_serving_member(str(row.get("relative_path") or ""))),
        key=lambda row: row["relative_path"],
    )


def _read_sqlite_change_counter(path: Path) -> int:
    """SQLite header bytes 24..28: the file change counter.

    Any write through SQLite itself increments it; together with the recorded
    size it is a cheap tripwire that an active shard has not been mutated.
    It is a change detector only, never the content identity.
    """
    with path.open("rb") as handle:
        header = handle.read(32)
    if len(header) < 32 or header[:16] != b"SQLite format 3\x00":
        raise ServingStoreError(f"shard is not a SQLite database: {path.name}")
    return int.from_bytes(header[24:28], "big")


def _verify_source_member_size(root: Path, member: Mapping[str, Any]) -> None:
    path = root / str(member["relative_path"])
    if not path.is_file() or path.stat().st_size != int(member.get("byte_count") or -1):
        raise ServingStoreError(f"source member unavailable or size mismatch: {member['relative_path']}")


def _extract_member(root: Path, member: Mapping[str, Any]) -> list[tuple]:
    """Read one manifest-bound member into the ten serving columns."""
    _verify_source_member_size(root, member)
    table = pq.ParquetFile(root / str(member["relative_path"])).read(columns=SERVING_COLUMNS)
    return [
        (
            str(row["series_id"]), str(row["metric_id"]), str(row["economic_time"]),
            str(row["logical_fact_key"]), str(row["normalized_value"]),
            str(row["canonical_unit"]), str(row["canonical_currency"]),
            str(row["canonical_scale"]), str(row["source_observation_key"]),
            str(row["primary_time_role"]),
        )
        for row in table.to_pylist()
    ]


def _reusable_existing_shard(target_dir: Path, name: str, source_hash: str) -> dict[str, Any] | None:
    """Return the recorded identity of an existing shard if it fully verifies.

    A shard built for the same source content by an earlier generation is
    reused when its bytes still match a recorded SHA-256 identity in any
    retained generation; this full re-verification happens only during the
    maintenance lifecycle, never on ordinary serving.  An orphaned or
    unverifiable file returns None so the caller rebuilds it from source.
    """
    final_path = target_dir / name
    if not final_path.is_file():
        return None
    generations_dir = target_dir.parent / GENERATIONS_DIRECTORY
    if not generations_dir.is_dir():
        return None
    for generation_file in generations_dir.glob("*/generation_v1.json"):
        try:
            generation = json.loads(generation_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for entry in (generation.get("member_shards") or {}).values():
            if (
                str(entry.get("shard_file")) == name
                and str(entry.get("source_content_sha256")) == source_hash
                and final_path.stat().st_size == int(entry.get("shard_bytes") or -1)
                and sha256_file(final_path) == str(entry.get("shard_sha256"))
            ):
                return dict(entry)
    return None


def build_shard(*, root: Path, member: Mapping[str, Any], target_dir: Path | None = None) -> dict[str, Any]:
    """Build one immutable shard file for one source member and identify it.

    Writes only to a not-yet-activated path; build pragmas are scoped to the
    disposable build artifact.  The finished shard is content-addressed by
    the source member hash and is never mutated afterwards.  An existing
    shard for the same source identity is reused only after its bytes verify
    against a recorded generation identity; otherwise it is rebuilt.
    """
    target_dir = target_dir or shards_directory()
    target_dir.mkdir(parents=True, exist_ok=True)
    name = shard_file_name(str(member["content_sha256"]))
    final_path = target_dir / name
    reusable = _reusable_existing_shard(target_dir, name, str(member["content_sha256"]))
    if reusable is not None:
        entry = dict(reusable)
        entry["reused_from_retained_generation"] = True
        return entry
    if final_path.is_file():
        # Orphaned or unverifiable file for the same source identity: nothing
        # active references it, so a deterministic rebuild is safe.
        final_path.unlink()
    rows = _extract_member(root, member)
    temporary = final_path.with_suffix(final_path.suffix + ".build")
    connection = sqlite3.connect(temporary)
    connection.execute("PRAGMA journal_mode=OFF")
    connection.execute("PRAGMA synchronous=OFF")
    connection.execute("PRAGMA page_size=8192")
    connection.execute("PRAGMA cache_size=-262144")
    connection.execute(
        "CREATE TABLE facts(series_id TEXT NOT NULL, metric_id TEXT NOT NULL,"
        " economic_time TEXT NOT NULL, logical_fact_key TEXT NOT NULL,"
        " normalized_value TEXT, canonical_unit TEXT, canonical_currency TEXT,"
        " canonical_scale TEXT, source_observation_key TEXT, primary_time_role TEXT)"
    )
    connection.executemany("INSERT INTO facts VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    connection.execute("CREATE INDEX idx_series ON facts(series_id, metric_id, economic_time)")
    connection.execute("CREATE INDEX idx_time ON facts(economic_time)")
    connection.commit()
    connection.close()
    temporary.replace(final_path)
    return {
        "relative_path": str(member["relative_path"]),
        "source_content_sha256": str(member["content_sha256"]),
        "source_byte_count": int(member.get("byte_count") or -1),
        "shard_file": name,
        "shard_sha256": sha256_file(final_path),
        "shard_bytes": final_path.stat().st_size,
        "row_count": len(rows),
        "economic_time_min": min((row[2] for row in rows), default=None),
        "economic_time_max": max((row[2] for row in rows), default=None),
        "sqlite_change_counter": _read_sqlite_change_counter(final_path),
        "built_at_utc": utc_now(),
    }


def _shard_tripwire_ok(target_dir: Path, entry: Mapping[str, Any]) -> bool:
    path = target_dir / str(entry["shard_file"])
    if not path.is_file():
        return False
    if path.stat().st_size != int(entry["shard_bytes"]):
        return False
    try:
        if _read_sqlite_change_counter(path) != int(entry["sqlite_change_counter"]):
            return False
    except ServingStoreError:
        return False
    return True


def _generation_hash(manifest: Mapping[str, Any]) -> str:
    unsigned = {key: value for key, value in manifest.items() if key != "generation_hash"}
    return hashlib.sha256(canonical_json(unsigned).encode("utf-8")).hexdigest()


def _time_interval(entry: Mapping[str, Any]) -> tuple[str, str] | None:
    """Missing/invalid old metadata must never exclude a potentially valid row."""
    low, high = entry.get("economic_time_min"), entry.get("economic_time_max")
    try:
        if not isinstance(low, str) or not isinstance(high, str):
            return None
        low_date, high_date = date.fromisoformat(low), date.fromisoformat(high)
        if low_date.isoformat() != low or high_date.isoformat() != high or low_date > high_date:
            return None
    except ValueError:
        return None
    return low, high


def _with_time_interval(entry: Mapping[str, Any], shard_dir: Path) -> dict[str, Any]:
    """Enrich a legacy manifest using two B-tree endpoint seeks, not a rebuild."""
    result = dict(entry)
    if _time_interval(entry) is not None:
        return result
    path = shard_dir / str(entry["shard_file"])
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        # An unrecognized legacy index retains conservative year-only routing.
        if [row[2] for row in connection.execute("PRAGMA index_info(idx_time)")] != ["economic_time"]:
            return result
        low = connection.execute("SELECT economic_time FROM facts INDEXED BY idx_time ORDER BY economic_time ASC LIMIT 1").fetchone()
        high = connection.execute("SELECT economic_time FROM facts INDEXED BY idx_time ORDER BY economic_time DESC LIMIT 1").fetchone()
    result.update(economic_time_min=low[0] if low else None, economic_time_max=high[0] if high else None)
    return result


def maintain_generation(
    *,
    release: Mapping[str, Any],
    snapshot_root: Path,
    manifest: Mapping[str, Any],
    manifest_sha256: str,
    database_generation_id: str,
    target_dir: Path | None = None,
) -> dict[str, Any]:
    """Build or rebase the serving generation for one release, then activate.

    Unchanged source members reuse their existing immutable shards (tripwire
    checked); changed or new members build only their own shards.  The new
    generation is written and hashed, then the pointer is replaced
    atomically.  Any failure before the pointer replacement leaves the
    previous generation active and all shards untouched.
    """
    target_dir = target_dir or store_directory()
    shards = target_dir / SHARDS_DIRECTORY
    shards.mkdir(parents=True, exist_ok=True)
    previous = load_current_generation(target_dir=target_dir)
    previous_shards = (previous or {}).get("member_shards", {}) if previous else {}
    members = _source_members(manifest)
    entries: dict[str, dict[str, Any]] = {}
    reused: list[str] = []
    built: list[str] = []
    bytes_written = 0
    total_rows = 0
    for member in members:
        relative = str(member["relative_path"])
        existing = previous_shards.get(relative)
        if (
            existing
            and str(existing.get("source_content_sha256")) == str(member["content_sha256"])
            and int(existing.get("source_byte_count") or -1) == int(member.get("byte_count") or -1)
            and _shard_tripwire_ok(shards, existing)
        ):
            entries[relative] = dict(existing)
            reused.append(relative)
        else:
            entry = build_shard(root=snapshot_root, member=member, target_dir=shards)
            if entry.get("reused_from_retained_generation"):
                reused.append(relative)
            else:
                built.append(relative)
                bytes_written += int(entry["shard_bytes"])
            entries[relative] = {
                key: value for key, value in entry.items() if key != "reused_from_retained_generation"
            }
        entries[relative] = _with_time_interval(entries[relative], shards)
        total_rows += int(entries[relative]["row_count"])
    generation = {
        "schema_version": GENERATION_SCHEMA,
        "release_id": release.get("release_id"),
        "release_hash": release.get("release_hash"),
        "snapshot_id": release.get("snapshot_id"),
        "database_generation_id": database_generation_id,
        "manifest_sha256": manifest_sha256,
        "member_shards": entries,
        "total_rows": total_rows,
        "built_at_utc": utc_now(),
        "source_fact_layer": "standard_facts (authoritative; this store is derived)",
    }
    gen_hash = _generation_hash(generation)
    generation["generation_hash"] = gen_hash
    generation_dir = target_dir / GENERATIONS_DIRECTORY / gen_hash
    generation_dir.mkdir(parents=True, exist_ok=True)
    write_json_atomic(generation_dir / "generation_v1.json", generation)
    write_json_atomic(
        target_dir / POINTER_FILE,
        {"schema_version": POINTER_SCHEMA, "generation_hash": gen_hash, "activated_at_utc": utc_now()},
    )
    return {
        "status": "activated",
        "generation_hash": gen_hash,
        "reused_members": reused,
        "built_members": built,
        "member_count": len(entries),
        "total_rows": total_rows,
        "bytes_written": bytes_written,
    }


def load_current_generation(target_dir: Path | None = None) -> dict[str, Any] | None:
    """Load the activated generation, self-checking its content hash."""
    target_dir = target_dir or store_directory()
    pointer = target_dir / POINTER_FILE
    if not pointer.is_file():
        return None
    try:
        value = json.loads(pointer.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    gen_hash = value.get("generation_hash") if isinstance(value, dict) else None
    if not isinstance(gen_hash, str) or len(gen_hash) != 64:
        return None
    return _load_generation_manifest(target_dir, gen_hash)


def _load_generation_manifest(target_dir: Path, gen_hash: str) -> dict[str, Any] | None:
    """Read an existing immutable generation; never activate or rebuild it."""
    if len(gen_hash) != 64 or any(character not in "0123456789abcdef" for character in gen_hash):
        return None
    manifest_path = target_dir / GENERATIONS_DIRECTORY / gen_hash / "generation_v1.json"
    if not manifest_path.is_file():
        return None
    try:
        generation = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(generation, dict) or generation.get("schema_version") != GENERATION_SCHEMA:
        return None
    if _generation_hash(generation) != gen_hash:
        return None
    return generation


def generation_binds(
    generation: Mapping[str, Any],
    *,
    release_id: str | None,
    release_hash: str,
    snapshot_id: str | None,
    database_generation_id: str | None,
    manifest_sha256: str,
    manifest: Mapping[str, Any],
    target_dir: Path | None = None,
) -> bool:
    """True when the generation binds the exact requested release/manifest."""
    if generation.get("release_hash") != release_hash:
        return False
    if release_id is not None and generation.get("release_id") != release_id:
        return False
    if snapshot_id is not None and generation.get("snapshot_id") != snapshot_id:
        return False
    if database_generation_id is not None and generation.get("database_generation_id") != database_generation_id:
        return False
    if generation.get("manifest_sha256") != manifest_sha256:
        return False
    shards = generation.get("member_shards")
    if not isinstance(shards, dict) or not shards:
        return False
    members = {str(m["relative_path"]): m for m in _source_members(manifest)}
    if set(shards) != set(members):
        return False
    for relative, entry in shards.items():
        member = members[relative]
        if str(entry.get("source_content_sha256")) != str(member.get("content_sha256")):
            return False
        if int(entry.get("source_byte_count") or -1) != int(member.get("byte_count") or -1):
            return False
    shard_dir = (target_dir or store_directory()) / SHARDS_DIRECTORY
    for entry in shards.values():
        if not _shard_tripwire_ok(shard_dir, entry):
            return False
    return True


def resolve_serving_binding(
    *,
    release_id: str | None,
    release_hash: str,
    snapshot_id: str | None,
    database_generation_id: str | None,
    manifest_sha256: str,
    manifest: Mapping[str, Any],
    target_dir: Path | None = None,
) -> dict[str, Any] | None:
    """Resolve an exact immutable binding, current first, then retained metadata.

    A request pinned before publication must not lose its existing B-tree
    generation merely because another release is now active. This changes no
    release authority and writes no pointer; every candidate must pass the
    same complete binding/hash/tripwire checks.
    """
    target_dir = target_dir or store_directory()
    generation = load_current_generation(target_dir=target_dir)
    def bound(candidate: Mapping[str, Any]) -> bool:
        return generation_binds(candidate,release_id=release_id,release_hash=release_hash,snapshot_id=snapshot_id,
            database_generation_id=database_generation_id,manifest_sha256=manifest_sha256,manifest=manifest,target_dir=target_dir)
    if generation is not None and bound(generation):
        return {"generation":generation,"shard_dir":target_dir/SHARDS_DIRECTORY}
    for directory in sorted((target_dir/GENERATIONS_DIRECTORY).glob("*")):
        if generation is not None and directory.name == generation["generation_hash"]:
            continue
        candidate = _load_generation_manifest(target_dir,directory.name)
        if candidate is not None and bound(candidate):
            return {"generation":candidate,"shard_dir":target_dir/SHARDS_DIRECTORY}
    return None


def member_shards_for_range(
    generation: Mapping[str, Any], start: str, end: str,
) -> list[dict[str, Any]]:
    """Shard entries of the members the production path would touch for a range."""
    start_year, end_year = int(start[:4]), int(end[:4])
    result = []
    for relative, entry in sorted((generation.get("member_shards") or {}).items()):
        if not relative.startswith("standard_facts/domain=equity/year="):
            continue
        try:
            year = int(relative.split("year=", 1)[1].split("/", 1)[0])
        except (ValueError, IndexError):
            continue
        if start_year <= year <= end_year and _is_serving_member(relative):
            interval = _time_interval(entry)
            if interval is not None and (interval[1] < start or interval[0] > end):
                continue
            selected = dict(entry)
            # The generation mapping key owns source membership. A reused
            # legacy shard may carry an older redundant relative_path value.
            selected["relative_path"] = relative
            result.append(selected)
    return result


def _query_one_shard(
    shard_dir: Path, entry: Mapping[str, Any], predicate: str, params: Sequence[Any],
) -> list[tuple]:
    """Run one read-only B-tree seek against one immutable shard.

    Each shard gets its own short-lived connection, so the number of shards
    a query touches is unbounded and never depends on SQLite's
    attached-database limit.  A tripwire failure refuses derived serving so
    the caller falls back to the production Parquet path.
    """
    if not _shard_tripwire_ok(shard_dir, entry):
        raise ServingStoreError("shard tripwire failed; refusing derived serving")
    path = shard_dir / str(entry["shard_file"])
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    try:
        return connection.execute(
            "SELECT series_id, metric_id, economic_time, logical_fact_key, normalized_value,"
            " canonical_unit, canonical_currency, canonical_scale, source_observation_key, primary_time_role"
            f" FROM facts WHERE {predicate}",
            params,
        ).fetchall()
    finally:
        connection.close()


def _as_rows(records: Sequence[tuple]) -> list[dict[str, Any]]:
    return [
        {
            "series_id": r[0], "metric_id": r[1], "economic_time": r[2],
            "logical_fact_key": r[3], "normalized_value": r[4], "canonical_unit": r[5],
            "canonical_currency": r[6], "canonical_scale": r[7],
            "source_observation_key": r[8], "primary_time_role": r[9],
        }
        for r in records
    ]


def query_series(
    *,
    shards: Sequence[Mapping[str, Any]],
    shard_dir: Path,
    series_id: str,
    metric_id: str,
    start: str,
    end: str,
) -> list[dict[str, Any]]:
    """Seek one series/metric range across any number of immutable shards.

    Shards are queried individually with their own read-only connections and
    the small per-shard result sets are merged afterwards, so B-tree seeks
    are preserved without an attached-database limit on the shard count.
    """
    merged: list[tuple] = []
    for entry in shards:
        merged.extend(_query_one_shard(
            shard_dir, entry,
            "series_id=? AND metric_id=? AND economic_time>=? AND economic_time<=?",
            (series_id, metric_id, start, end),
        ))
    merged.sort(key=lambda row: row[2])
    return _as_rows(merged)


def query_cross_section(
    *, shards: Sequence[Mapping[str, Any]], shard_dir: Path, economic_time: str,
) -> list[dict[str, Any]]:
    """Date cross-section across any number of immutable shards (index seeks)."""
    merged: list[tuple] = []
    for entry in shards:
        merged.extend(_query_one_shard(
            shard_dir, entry, "economic_time=?", (economic_time,),
        ))
    merged.sort(key=lambda row: (row[0], row[1]))
    return _as_rows(merged)


def verify_generation(generation: Mapping[str, Any], target_dir: Path | None = None) -> dict[str, Any]:
    """Explicit full content re-verification of every shard (lifecycle command)."""
    target_dir = target_dir or store_directory()
    shard_dir = target_dir / SHARDS_DIRECTORY
    verified = 0
    mismatches: list[str] = []
    for relative, entry in (generation.get("member_shards") or {}).items():
        path = shard_dir / str(entry["shard_file"])
        if not path.is_file():
            mismatches.append(f"{relative}: shard missing")
            continue
        if path.stat().st_size != int(entry["shard_bytes"]):
            mismatches.append(f"{relative}: size changed")
            continue
        if sha256_file(path) != str(entry["shard_sha256"]):
            mismatches.append(f"{relative}: content hash mismatch")
            continue
        with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)) as connection:
            if connection.execute("SELECT COUNT(*) FROM facts").fetchone()[0] != int(entry["row_count"]):
                mismatches.append(f"{relative}: row count mismatch")
                continue
        verified += 1
    return {
        "status": "verified" if not mismatches else "integrity_failure",
        "shards_verified": verified,
        "mismatches": mismatches,
    }


def migrate_legacy_single_file_store(target_dir: Path | None = None) -> dict[str, Any]:
    """One-time conversion of the pre-identity single-file store into shards.

    The legacy store was extracted under a verified release binding; its
    per-member tables are copied into content-addressed immutable shards,
    each of which is then hashed to establish the derived-artifact identity.
    The legacy files are removed only after the new generation is activated
    and verified.  This is an explicit lifecycle migration command, not
    ordinary serving work.
    """
    target_dir = target_dir or store_directory()
    legacy_db = target_dir / LEGACY_STORE_FILE
    legacy_receipt = target_dir / LEGACY_RECEIPT_FILE
    if not legacy_db.is_file() or not legacy_receipt.is_file():
        raise ServingStoreError("legacy single-file store is not present; nothing to migrate")
    receipt = json.loads(legacy_receipt.read_text(encoding="utf-8"))
    shards = target_dir / SHARDS_DIRECTORY
    shards.mkdir(parents=True, exist_ok=True)
    entries: dict[str, dict[str, Any]] = {}
    total_rows = 0
    with closing(sqlite3.connect(f"file:{legacy_db.as_posix()}?mode=ro", uri=True)) as legacy:
        legacy.execute("PRAGMA query_only=ON")
        meta = {
            str(row[0]): {"table_name": str(row[1]), "content_sha256": str(row[2]),
                          "byte_count": int(row[3]), "row_count": int(row[4])}
            for row in legacy.execute(
                "SELECT relative_path, table_name, content_sha256, byte_count, row_count FROM serving_store_meta"
            )
        }
        for relative, info in sorted(meta.items()):
            name = shard_file_name(info["content_sha256"])
            final_path = shards / name
            temporary = final_path.with_suffix(final_path.suffix + ".build")
            # Main connection is the legacy file opened read-only at the OS
            # level; the new shard attaches by plain path as the only
            # writable database, so the legacy bytes cannot be mutated.
            connection = sqlite3.connect(f"file:{legacy_db.as_posix()}?mode=ro", uri=True)
            connection.execute("PRAGMA page_size=8192")
            connection.execute("PRAGMA cache_size=-262144")
            connection.execute("ATTACH DATABASE ? AS shard", (str(temporary),))
            connection.execute(f"CREATE TABLE shard.facts AS SELECT * FROM main.{info['table_name']}")
            connection.execute("CREATE INDEX shard.idx_series ON facts(series_id, metric_id, economic_time)")
            connection.execute("CREATE INDEX shard.idx_time ON facts(economic_time)")
            connection.commit()
            connection.close()
            temporary.replace(final_path)
            entry = {
                "relative_path": relative,
                "source_content_sha256": info["content_sha256"],
                "source_byte_count": info["byte_count"],
                "shard_file": name,
                "shard_sha256": sha256_file(final_path),
                "shard_bytes": final_path.stat().st_size,
                "row_count": info["row_count"],
                "sqlite_change_counter": _read_sqlite_change_counter(final_path),
                "built_at_utc": utc_now(),
            }
            entries[relative] = entry
            total_rows += info["row_count"]
    generation = {
        "schema_version": GENERATION_SCHEMA,
        "release_id": receipt.get("release_id"),
        "release_hash": receipt.get("release_hash"),
        "snapshot_id": receipt.get("snapshot_id"),
        "database_generation_id": receipt.get("database_generation_id"),
        "manifest_sha256": receipt.get("manifest_sha256"),
        "member_shards": entries,
        "total_rows": total_rows,
        "built_at_utc": utc_now(),
        "source_fact_layer": "standard_facts (authoritative; this store is derived)",
    }
    gen_hash = _generation_hash(generation)
    generation["generation_hash"] = gen_hash
    generation_dir = target_dir / GENERATIONS_DIRECTORY / gen_hash
    generation_dir.mkdir(parents=True, exist_ok=True)
    write_json_atomic(generation_dir / "generation_v1.json", generation)
    verification = verify_generation(generation, target_dir=target_dir)
    if verification["status"] != "verified":
        raise ServingStoreError(f"migrated generation failed verification: {verification['mismatches']}")
    write_json_atomic(
        target_dir / POINTER_FILE,
        {"schema_version": POINTER_SCHEMA, "generation_hash": gen_hash, "activated_at_utc": utc_now()},
    )
    legacy_db.unlink(missing_ok=True)
    legacy_receipt.unlink(missing_ok=True)
    return {"status": "migrated", "generation_hash": gen_hash, "member_count": len(entries), "total_rows": total_rows}
