"""Disk-backed normalized payloads for ordinary China Equity updates.

The discovery plan remains a compact, deterministic control document. Large
normalized daily rows live in bounded Parquet chunks referenced by a hashed
manifest. The checkpoint is operational scratch: it permits a builder retry to
reuse fully committed batches while an incomplete in-memory batch is replayed.
"""

from __future__ import annotations

import hashlib
import gzip
import json
import os
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

import pyarrow as pa
import pyarrow.parquet as pq


SCHEMA_VERSION = "fr_china_equity_bounded_plan_payload_v1"
FAMILIES = ("daily_observations", "daily_source_details")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


class BoundedPlanPayloadWriter:
    """Accumulate at most one bounded batch before an atomic Parquet flush."""

    def __init__(self, root: Path, *, maximum_buffered_rows: int = 100_000, maximum_buffered_scopes: int = 16):
        if maximum_buffered_rows < 1 or maximum_buffered_scopes < 1:
            raise ValueError("bounded payload limits must be positive")
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.checkpoint_path = self.root / "checkpoint.json"
        self.manifest_path = self.root / "manifest.json"
        self.coverage_path = self.root / "coverage_evidence.ndjson.gz"
        self.maximum_buffered_rows = maximum_buffered_rows
        self.maximum_buffered_scopes = maximum_buffered_scopes
        checkpoint = json.loads(self.checkpoint_path.read_text(encoding="utf-8")) if self.checkpoint_path.is_file() else {}
        if checkpoint and checkpoint.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("unsupported bounded plan checkpoint schema")
        self.chunks: dict[str, list[dict[str, Any]]] = {
            family: list((checkpoint.get("chunks") or {}).get(family) or []) for family in FAMILIES
        }
        self.completed_scopes: dict[str, dict[str, Any]] = dict(checkpoint.get("completed_scopes") or {})
        self.coverage_evidence_count = 0
        if self.coverage_path.is_file():
            with gzip.open(self.coverage_path, "rt", encoding="utf-8") as handle:
                self.coverage_evidence_count = sum(1 for line in handle if line.strip())
        self.buffers: dict[str, list[dict[str, Any]]] = {family: [] for family in FAMILIES}
        self.pending_scopes: dict[str, dict[str, Any]] = {}
        self.pending_coverage: list[dict[str, Any]] = []
        self.schemas: dict[str, pa.Schema] = {}
        for family in FAMILIES:
            if self.chunks[family]:
                first = self.root / self.chunks[family][0]["relative_path"]
                self.schemas[family] = pq.ParquetFile(first).schema_arrow

    def completed_scope(self, scope_key: str, source_sha256: str) -> dict[str, Any] | None:
        value = self.completed_scopes.get(scope_key)
        if value is None:
            return None
        if value.get("source_sha256") != source_sha256:
            raise ValueError(f"retained response changed for completed bounded scope: {scope_key}")
        return dict(value)

    def append_scope(
        self,
        *,
        scope_key: str,
        source_sha256: str,
        daily_observations: Iterable[Mapping[str, Any]],
        daily_source_details: Iterable[Mapping[str, Any]],
        coverage_evidence: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if scope_key in self.completed_scopes or scope_key in self.pending_scopes:
            raise ValueError(f"bounded payload scope appended more than once: {scope_key}")
        observations = [dict(row) for row in daily_observations]
        details = [dict(row) for row in daily_source_details]
        self.buffers["daily_observations"].extend(observations)
        self.buffers["daily_source_details"].extend(details)
        self.pending_coverage.extend(coverage_evidence)
        summary = {
            "source_sha256": source_sha256,
            "daily_observation_count": len(observations),
            "daily_source_detail_count": len(details),
        }
        self.pending_scopes[scope_key] = summary
        buffered = sum(len(rows) for rows in self.buffers.values())
        if buffered >= self.maximum_buffered_rows or len(self.pending_scopes) >= self.maximum_buffered_scopes:
            self.flush()
        return summary

    def _write_family_chunk(self, family: str, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        index = len(self.chunks[family])
        relative = Path("chunks") / family / f"part-{index:06d}.parquet"
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        schema = self.schemas.get(family)
        table = pa.Table.from_pylist(rows, schema=schema)
        if schema is None:
            schema = table.schema
            self.schemas[family] = schema
        temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        pq.write_table(table, temporary, compression="zstd", version="2.6", row_group_size=65_536)
        os.replace(temporary, target)
        self.chunks[family].append({
            "relative_path": relative.as_posix(),
            "row_count": table.num_rows,
            "byte_count": target.stat().st_size,
            "sha256": _sha256(target),
            "schema": [{"name": field.name, "type": str(field.type), "nullable": field.nullable} for field in schema],
        })

    def flush(self) -> None:
        if not self.pending_scopes and not any(self.buffers.values()):
            return
        for family in FAMILIES:
            self._write_family_chunk(family, self.buffers[family])
            self.buffers[family] = []
        if self.pending_coverage:
            with gzip.open(self.coverage_path, "at", encoding="utf-8") as handle:
                for row in self.pending_coverage:
                    handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            self.coverage_evidence_count += len(self.pending_coverage)
            self.pending_coverage = []
        self.completed_scopes.update(self.pending_scopes)
        self.pending_scopes = {}
        _write_json_atomic(self.checkpoint_path, {
            "schema_version": SCHEMA_VERSION,
            "chunks": self.chunks,
            "completed_scopes": self.completed_scopes,
            "completed_scope_count": len(self.completed_scopes),
        })

    def finalize(self) -> dict[str, Any]:
        self.flush()
        families = {
            family: {
                "row_count": sum(int(row["row_count"]) for row in self.chunks[family]),
                "chunk_count": len(self.chunks[family]),
                "byte_count": sum(int(row["byte_count"]) for row in self.chunks[family]),
                "chunks": self.chunks[family],
            }
            for family in FAMILIES
        }
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "completed_scope_count": len(self.completed_scopes),
            "maximum_buffered_rows": self.maximum_buffered_rows,
            "maximum_buffered_scopes": self.maximum_buffered_scopes,
            "coverage_evidence_count": self.coverage_evidence_count,
            "coverage_evidence_sha256": _sha256(self.coverage_path) if self.coverage_path.is_file() else None,
            "families": families,
        }
        _write_json_atomic(self.manifest_path, manifest)
        return {
            "schema_version": SCHEMA_VERSION,
            "manifest_relative_path": self.manifest_path.name,
            "manifest_sha256": _sha256(self.manifest_path),
            "manifest_byte_count": self.manifest_path.stat().st_size,
            "completed_scope_count": len(self.completed_scopes),
            "coverage_evidence_count": self.coverage_evidence_count,
            "coverage_evidence_sha256": manifest["coverage_evidence_sha256"],
            "families": {
                family: {key: value for key, value in data.items() if key != "chunks"}
                for family, data in families.items()
            },
        }


def resolve_payload_manifest(plan_path: Path, plan: Mapping[str, Any]) -> tuple[Path, dict[str, Any]] | None:
    reference = plan.get("bounded_daily_payload")
    if not reference:
        return None
    root = plan_path.parent / str(reference["root_relative_path"])
    manifest_path = root / str(reference["manifest_relative_path"])
    if not manifest_path.is_file() or _sha256(manifest_path) != reference["manifest_sha256"]:
        raise ValueError("bounded plan payload manifest is missing or changed")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported bounded plan payload manifest")
    return root, manifest


def bounded_payload_count(plan: Mapping[str, Any], family: str) -> int:
    reference = plan.get("bounded_daily_payload") or {}
    return int(((reference.get("families") or {}).get(family) or {}).get("row_count") or 0)


def iter_plan_coverage(plan_path: Path, plan: Mapping[str, Any]) -> Iterator[dict[str, Any]]:
    reference = plan.get("bounded_daily_payload") or {}
    relative = reference.get("coverage_evidence_relative_path")
    if relative:
        root = plan_path.parent / str(reference.get("root_relative_path") or ".")
        with gzip.open(root / str(relative), "rt", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    yield json.loads(line)
        for row in plan.get("financial_coverage_evidence", []) or []:
            yield dict(row)
        return
    value = plan.get("coverage_evidence") or []
    if isinstance(value, list):
        yield from (dict(row) for row in value)


def iter_plan_rows(
    plan_path: Path,
    plan: Mapping[str, Any],
    family: str,
    *,
    batch_size: int = 65_536,
) -> Iterator[list[dict[str, Any]]]:
    if family not in FAMILIES:
        for row in plan.get(family, []):
            yield [dict(row)]
        return
    resolved = resolve_payload_manifest(plan_path, plan)
    if resolved is None:
        rows = list(plan.get(family, []))
        for start in range(0, len(rows), batch_size):
            yield [dict(row) for row in rows[start : start + batch_size]]
        return
    root, manifest = resolved
    observed = 0
    for entry in manifest["families"][family]["chunks"]:
        path = root / entry["relative_path"]
        if not path.is_file() or path.stat().st_size != int(entry["byte_count"]) or _sha256(path) != entry["sha256"]:
            raise ValueError(f"bounded plan payload chunk is missing or changed: {entry['relative_path']}")
        parquet = pq.ParquetFile(path)
        rows_in_chunk = 0
        for batch in parquet.iter_batches(batch_size=batch_size):
            values = pa.Table.from_batches([batch]).to_pylist()
            rows_in_chunk += len(values)
            observed += len(values)
            yield values
        if rows_in_chunk != int(entry["row_count"]):
            raise ValueError(f"bounded plan payload row count changed: {entry['relative_path']}")
    if observed != int(manifest["families"][family]["row_count"]):
        raise ValueError(f"bounded plan payload family count changed: {family}")
