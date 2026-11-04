"""Universe-neutral physical snapshot manifest operations."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any, Mapping

from backend.app.core.storage_profile import resolve_unpublished_snapshot_path


NONPROMOTED_STANDARD_FACT_COUNT_FIELDS = (
    "nonpromoted_legacy_financial_fact_provenance_rows",
    "nonpromoted_legacy_fund_fact_provenance_rows",
)


def reconcile_manifest_aggregate_counts(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Derive aggregates from the final physical file inventory."""
    result = dict(manifest)
    files = [dict(row) for row in result.get("files", [])]
    paths = [str(row["relative_path"]) for row in files]
    if len(paths) != len(set(paths)):
        raise ValueError("manifest contains duplicate physical file paths")

    def rows_under(prefix: str) -> int:
        total = 0
        for row in files:
            if str(row["relative_path"]).startswith(prefix):
                count = int(row["row_count"])
                if count < 0:
                    raise ValueError(f"manifest row count is negative: {row['relative_path']}")
                total += count
        return total

    physical_standard_rows = rows_under("standard_facts/")
    physical_financial_rows = rows_under("standard_facts/domain=financial_statements/")
    source_observation_rows = rows_under("source_observations/")
    nonpromoted_by_field = {
        field: int(result.get(field, 0)) for field in NONPROMOTED_STANDARD_FACT_COUNT_FIELDS
    }
    if any(value < 0 for value in nonpromoted_by_field.values()):
        raise ValueError("declared non-promoted standard facts cannot be negative")
    nonpromoted_rows = sum(nonpromoted_by_field.values())
    nonpromoted_financial_rows = nonpromoted_by_field[
        "nonpromoted_legacy_financial_fact_provenance_rows"
    ]
    if nonpromoted_financial_rows > physical_financial_rows:
        raise ValueError("declared non-promoted financial facts exceed physical financial rows")
    if nonpromoted_rows > physical_standard_rows:
        raise ValueError("declared non-promoted standard facts exceed all physical standard rows")

    result.update(
        {
            "physical_standard_fact_row_count": physical_standard_rows,
            "canonical_financial_fact_rows": physical_financial_rows - nonpromoted_financial_rows,
            "accepted_fact_output_count": physical_standard_rows - nonpromoted_rows,
            "source_observation_count": source_observation_rows,
        }
    )
    return result


def clone_snapshot_from_manifest(
    predecessor_snapshot_id: str,
    successor_snapshot_id: str,
    *,
    predecessor_manifest_path: Path | None = None,
) -> dict[str, Any]:
    """Hard-link an immutable predecessor without rereading inherited payloads."""
    predecessor_root = resolve_unpublished_snapshot_path(predecessor_snapshot_id)
    successor_root = resolve_unpublished_snapshot_path(successor_snapshot_id)
    manifest_path = predecessor_manifest_path or predecessor_root / "metadata/corrected_candidate_manifest_v1.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    relative_paths = sorted(
        {row["relative_path"] for row in manifest.get("files", [])}
        | {row["relative_path"] for row in manifest.get("auxiliary_files", [])}
    )
    successor_root.mkdir(parents=True, exist_ok=True)
    linked = reused = 0
    logical_bytes = 0
    for relative in relative_paths:
        source = predecessor_root / relative
        target = successor_root / relative
        if not source.is_file():
            raise FileNotFoundError(source)
        logical_bytes += source.stat().st_size
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.stat().st_size != source.stat().st_size:
                raise RuntimeError(f"successor checkpoint conflicts with predecessor: {target}")
            reused += 1
        else:
            os.link(source, target)
            linked += 1
    previous_copy = successor_root / "metadata/predecessor_corrected_candidate_manifest_v1.json"
    if not previous_copy.exists():
        shutil.copy2(manifest_path, previous_copy)
    return {
        "predecessor_snapshot_id": predecessor_snapshot_id,
        "successor_snapshot_id": successor_snapshot_id,
        "inherited_file_count": len(relative_paths),
        "hard_links_created": linked,
        "checkpoint_files_reused": reused,
        "inherited_logical_bytes": logical_bytes,
        "inherited_bulk_payload_bytes_read": 0,
    }


def assert_new_snapshot_member_path(snapshot_root: Path, relative_path: str) -> Path:
    """Fail closed before a candidate writer can overwrite an inherited hard link."""
    root = snapshot_root.resolve()
    target = (root / relative_path).resolve()
    if not target.is_relative_to(root) or target == root:
        raise ValueError(f"snapshot member escapes root: {relative_path}")
    if target.exists():
        raise FileExistsError(f"snapshot member already exists: {target}")
    return target
