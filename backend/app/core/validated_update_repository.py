"""Universe-neutral validated update-head persistence.

Read methods are intentionally side-effect free: they never create directories,
SQLite files, or tables. Schema creation belongs to the first explicit bootstrap
write, while later advancement remains guarded by the accepted CAS contract.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from backend.app.core.artifact_io import sha256_file
from backend.app.core.storage_profile import (
    resolve_control_plane_path,
    resolve_identity_state_path,
    resolve_unpublished_snapshot_path,
)


@dataclass(frozen=True)
class ValidatedUpdateHead:
    universe: str
    database_generation_id: str
    snapshot_id: str
    snapshot_manifest_sha256: str
    reality_owner_path: str
    reality_owner_sha256: str
    state_path: str
    state_sha256: str
    authoritative_cutoff: str
    predecessor_snapshot_id: str | None
    transaction_id: str
    run_id: str


class StaleUpdateHead(RuntimeError):
    pass


class ValidatedUpdateRepository:
    """Generation-scoped CAS owner shared by explicit Universe update flows."""

    def __init__(
        self,
        path: Path | None = None,
        *,
        identity_path: Path | None = None,
        snapshot_root: Callable[[str], Path] = resolve_unpublished_snapshot_path,
    ):
        self.path = path or resolve_control_plane_path()
        self.identity_path = identity_path
        self.snapshot_root = snapshot_root

    def _initialize_schema(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS validated_canonical_update_head(
                    universe TEXT PRIMARY KEY,
                    database_generation_id TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    snapshot_manifest_sha256 TEXT NOT NULL,
                    reality_owner_path TEXT NOT NULL,
                    reality_owner_sha256 TEXT NOT NULL,
                    state_path TEXT NOT NULL,
                    state_sha256 TEXT NOT NULL,
                    authoritative_cutoff TEXT NOT NULL,
                    predecessor_snapshot_id TEXT,
                    transaction_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS validated_canonical_update_history(
                    universe TEXT NOT NULL,
                    database_generation_id TEXT NOT NULL,
                    predecessor_snapshot_id TEXT,
                    successor_snapshot_id TEXT NOT NULL,
                    authoritative_cutoff TEXT NOT NULL,
                    transaction_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    snapshot_manifest_sha256 TEXT NOT NULL,
                    reality_owner_sha256 TEXT NOT NULL,
                    state_sha256 TEXT NOT NULL,
                    advanced_at_utc TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(universe, database_generation_id, successor_snapshot_id)
                );
                """
            )

    def _read_connection(self) -> sqlite3.Connection | None:
        if not self.path.is_file():
            return None
        return sqlite3.connect(f"file:{self.path.resolve().as_posix()}?mode=ro", uri=True)

    def database_generation_id(self) -> str:
        with closing(sqlite3.connect(self.identity_path or resolve_identity_state_path())) as connection:
            row = connection.execute(
                "SELECT database_generation_id FROM identity_state_metadata WHERE singleton_id=1"
            ).fetchone()
        if not row:
            raise RuntimeError("identity database generation is unavailable")
        return str(row[0])

    @staticmethod
    def _from_row(row: tuple[Any, ...]) -> ValidatedUpdateHead:
        return ValidatedUpdateHead(*row)

    def current(self, universe: str) -> ValidatedUpdateHead | None:
        connection = self._read_connection()
        if connection is None:
            return None
        try:
            row = connection.execute(
                """
                SELECT universe,database_generation_id,snapshot_id,
                       snapshot_manifest_sha256,reality_owner_path,reality_owner_sha256,
                       state_path,state_sha256,authoritative_cutoff,
                       predecessor_snapshot_id,transaction_id,run_id
                FROM validated_canonical_update_head WHERE universe=?
                """,
                (universe,),
            ).fetchone()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc).lower():
                raise
            return None
        finally:
            connection.close()
        return self._from_row(row) if row else None

    def bootstrap(self, head: ValidatedUpdateHead) -> ValidatedUpdateHead:
        if head.database_generation_id != self.database_generation_id():
            raise ValueError("seed head database generation differs from durable identity state")
        validate_head_files(head, snapshot_root=self.snapshot_root)
        self._initialize_schema()
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT snapshot_id FROM validated_canonical_update_head WHERE universe=?",
                (head.universe,),
            ).fetchone()
            if existing:
                connection.rollback()
                current = self.current(head.universe)
                if current is None or current.database_generation_id != head.database_generation_id:
                    raise ValueError("validated update head mixes database generations")
                return current
            connection.execute(
                """
                INSERT INTO validated_canonical_update_head(
                    universe,database_generation_id,snapshot_id,snapshot_manifest_sha256,
                    reality_owner_path,reality_owner_sha256,state_path,state_sha256,
                    authoritative_cutoff,predecessor_snapshot_id,transaction_id,run_id
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                tuple(asdict(head).values()),
            )
            connection.execute(
                """
                INSERT INTO validated_canonical_update_history(
                    universe,database_generation_id,predecessor_snapshot_id,
                    successor_snapshot_id,authoritative_cutoff,transaction_id,run_id,
                    snapshot_manifest_sha256,reality_owner_sha256,state_sha256
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    head.universe, head.database_generation_id, head.predecessor_snapshot_id,
                    head.snapshot_id, head.authoritative_cutoff, head.transaction_id, head.run_id,
                    head.snapshot_manifest_sha256, head.reality_owner_sha256, head.state_sha256,
                ),
            )
            connection.commit()
        return head

    def compare_and_swap(self, expected_snapshot_id: str, candidate: ValidatedUpdateHead) -> ValidatedUpdateHead:
        validate_head_files(candidate, snapshot_root=self.snapshot_root,
                            require_subject_graph_completion=candidate.universe == "CN_A_SHARE")
        if candidate.database_generation_id != self.database_generation_id():
            raise ValueError("candidate database generation differs from durable identity state")
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT snapshot_id,database_generation_id,authoritative_cutoff FROM validated_canonical_update_head WHERE universe=?",
                (candidate.universe,),
            ).fetchone()
            if not row or str(row[0]) != expected_snapshot_id:
                connection.rollback()
                raise StaleUpdateHead("validated update head changed before candidate advancement")
            if str(row[1]) != candidate.database_generation_id:
                connection.rollback()
                raise ValueError("candidate mixes database generations")
            if candidate.predecessor_snapshot_id != expected_snapshot_id:
                connection.rollback()
                raise ValueError("candidate does not name current validated head as predecessor")
            if candidate.authoritative_cutoff < str(row[2]):
                connection.rollback()
                raise ValueError("candidate authoritative cutoff moves backward")
            connection.execute(
                """
                INSERT INTO validated_canonical_update_history(
                    universe,database_generation_id,predecessor_snapshot_id,
                    successor_snapshot_id,authoritative_cutoff,transaction_id,run_id,
                    snapshot_manifest_sha256,reality_owner_sha256,state_sha256
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    candidate.universe, candidate.database_generation_id,
                    candidate.predecessor_snapshot_id, candidate.snapshot_id,
                    candidate.authoritative_cutoff, candidate.transaction_id, candidate.run_id,
                    candidate.snapshot_manifest_sha256, candidate.reality_owner_sha256,
                    candidate.state_sha256,
                ),
            )
            cursor = connection.execute(
                """
                UPDATE validated_canonical_update_head SET
                    database_generation_id=?,snapshot_id=?,snapshot_manifest_sha256=?,
                    reality_owner_path=?,reality_owner_sha256=?,state_path=?,state_sha256=?,
                    authoritative_cutoff=?,predecessor_snapshot_id=?,transaction_id=?,run_id=?,
                    updated_at_utc=CURRENT_TIMESTAMP
                WHERE universe=? AND snapshot_id=?
                """,
                (
                    candidate.database_generation_id, candidate.snapshot_id,
                    candidate.snapshot_manifest_sha256, candidate.reality_owner_path,
                    candidate.reality_owner_sha256, candidate.state_path, candidate.state_sha256,
                    candidate.authoritative_cutoff, candidate.predecessor_snapshot_id,
                    candidate.transaction_id, candidate.run_id, candidate.universe,
                    expected_snapshot_id,
                ),
            )
            if cursor.rowcount != 1:
                connection.rollback()
                raise StaleUpdateHead("validated update head compare-and-swap failed")
            connection.commit()
        return candidate

    def history(self, universe: str) -> list[dict[str, Any]]:
        connection = self._read_connection()
        if connection is None:
            return []
        try:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT * FROM validated_canonical_update_history WHERE universe=? ORDER BY rowid",
                (universe,),
            ).fetchall()
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc).lower():
                raise
            return []
        finally:
            connection.close()
        return [dict(row) for row in rows]


def validate_head_files(
    head: ValidatedUpdateHead,
    *,
    snapshot_root: Callable[[str], Path] = resolve_unpublished_snapshot_path,
    require_subject_graph_completion: bool = False,
) -> None:
    manifest = snapshot_root(head.snapshot_id) / "metadata/corrected_candidate_manifest_v1.json"
    if not manifest.is_file() or sha256_file(manifest) != head.snapshot_manifest_sha256:
        raise ValueError("validated update head manifest is missing or mismatched")
    for path_value, expected in (
        (head.reality_owner_path, head.reality_owner_sha256),
        (head.state_path, head.state_sha256),
    ):
        path = Path(path_value)
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError("validated update head compact state is missing or mismatched")
    state = json.loads(Path(head.state_path).read_text(encoding="utf-8"))
    identity_path = Path(state["identity_owner_path"])
    if not identity_path.is_file() or sha256_file(identity_path) != state["identity_owner_sha256"]:
        raise ValueError("validated update head identity owner is missing or mismatched")
    if require_subject_graph_completion:
        from backend.app.core.subject_graph_projection import verify_subject_graph_completion
        if not state.get("semantic_control_path"):
            raise ValueError("successor has no snapshot-local semantic control binding")
        verify_subject_graph_completion(snapshot_root(head.snapshot_id), control=Path(state["semantic_control_path"]))
