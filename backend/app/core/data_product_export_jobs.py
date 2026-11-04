"""Installation-local, release-pinned Data Explorer export ownership.

This is not the Update operation queue. Jobs only read immutable releases and
write disposable CSVs below one owned temporary-workspace namespace.
"""

from __future__ import annotations

import csv
import json
import os
import re
import secrets
import shutil
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.app.core.artifact_io import sha256_file, write_json_atomic
from backend.app.core.data_product_catalog import DAILY_DATASETS
from backend.app.core.data_product_identity import IDENTITY_DATASETS, identity_dataset_rows, validate_identity_filters
from backend.app.core.data_product_research_table import DataProductError, research_table
from backend.app.core.serving_release import PinnedServingRelease
from backend.app.core.storage_profile import resolve_temporary_workspace_path
from backend.app.core.writer_runtime_ownership import PROCESS_START_UTC, _pid_alive


OWNER = "fr_data_product_export_v1"
IDENTITY_FIELDS = {
    "fund.products": ("object_id", "subject_type", "display_name", "jurisdiction", "effective_start", "effective_end", "lifecycle_class", "lifecycle_classification_status"),
    "fund.share_classes": ("object_id", "subject_type", "display_name", "jurisdiction", "effective_start", "effective_end", "lifecycle_class", "lifecycle_classification_status"),
    "fund.listings": ("object_id", "subject_type", "display_name", "jurisdiction", "effective_start", "effective_end", "estimated_delisting_date", "lifecycle_class", "lifecycle_classification_status"),
    "fund.identifier_history": ("object_id", "subject_type", "alias_kind", "alias_value", "effective_start", "effective_end"),
    "equity.listings": ("object_id", "subject_type", "display_name", "external_code", "exchange", "market_jurisdiction", "listing_start_date", "listing_start_boundary", "listing_end_date", "estimated_delisting_date", "lifecycle_class", "lifecycle_classification_status"),
    "equity.identifier_history": ("object_id", "subject_type", "exchange", "alias_kind", "alias_value", "effective_start", "effective_end"),
}
_ACTIVE: set[str] = set()
_LOCK = threading.Lock()
_SLOTS = threading.BoundedSemaphore(2)
DAILY_FIELDS = ("catalog_version", "release_id", "release_hash", "dataset_id", "subject_type", "subject_id",
                "economic_time", "metric_id", "observation_status", "value", "unit", "currency", "scale",
                "time_role", "series_id", "provenance_json", "support_source_observation_id")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _root(root: Path | None = None) -> Path:
    selected = root or resolve_temporary_workspace_path("data_product_exports")
    return selected.resolve()


def _job_dir(job_id: str, *, root: Path | None = None) -> Path:
    if not re.fullmatch(r"fr_export_[a-f0-9]{32}", job_id):
        raise DataProductError("invalid_export_job_id", "export job identity is malformed")
    owner_root = _root(root)
    target = (owner_root / job_id).resolve()
    if target.parent != owner_root:
        raise DataProductError("invalid_export_job_id", "export job escapes its owner")
    return target


def _state(path: Path) -> dict[str, Any]:
    if not (path / "owner.json").is_file() or not (path / "job.json").is_file():
        raise DataProductError("export_job_not_found", "export job was not found", 404)
    marker = json.loads((path / "owner.json").read_text(encoding="utf-8"))
    if marker.get("owner") != OWNER or marker.get("job_id") != path.name:
        raise DataProductError("export_job_owner_invalid", "export job ownership is invalid", 409)
    return json.loads((path / "job.json").read_text(encoding="utf-8"))


def _save(path: Path, value: Mapping[str, Any]) -> None:
    write_json_atomic(path / "job.json", dict(value))


def create_identity_job(
    dataset_id: str, *, release: PinnedServingRelease, filters: Mapping[str, Any],
    fields: Sequence[str] | None = None, scope: str = "all_matching_filters",
    catalog_version: str, root: Path | None = None,
) -> dict[str, Any]:
    if dataset_id not in IDENTITY_DATASETS:
        raise DataProductError("logical_dataset_not_exposed", "dataset has no complete identity export contract", 409)
    validate_identity_filters(dataset_id, **filters)
    if scope not in {"all_matching_filters", "complete_logical_dataset"}:
        raise DataProductError("invalid_export_scope", "unsupported export scope")
    if scope == "complete_logical_dataset" and any(value not in (None, "", "All") for value in filters.values()):
        raise DataProductError("invalid_export_scope", "whole-dataset export cannot carry row filters")
    allowed = IDENTITY_FIELDS[dataset_id]
    selected = tuple(fields or allowed)
    if not selected or len(set(selected)) != len(selected) or any(field not in allowed for field in selected):
        raise DataProductError("invalid_export_fields", "selected fields are outside the logical dataset")
    if not _SLOTS.acquire(blocking=False):
        raise DataProductError("export_capacity_busy", "two local exports are already active", 409)
    job_id = "fr_export_" + secrets.token_hex(16)
    created: Path | None = None
    try:
        _root(root).mkdir(parents=True, exist_ok=True)
        path = _job_dir(job_id, root=root)
        path.mkdir(exist_ok=False)
        created = path
        write_json_atomic(path / "owner.json", {"owner": OWNER, "job_id": job_id, "created_at": _now()})
        state = {
            "schema_version": OWNER, "job_id": job_id, "status": "queued", "scope": scope,
            "dataset_id": dataset_id, "filters": dict(filters), "fields": list(selected),
            "release_id": release.release_id, "release_hash": release.release_hash,
            "snapshot_id": release.snapshot_id, "catalog_version": catalog_version,
            "owner_pid": os.getpid(), "owner_process_start": PROCESS_START_UTC,
            "created_at": _now(), "updated_at": _now(), "logical_row_count": None,
            "rows_written": 0, "bytes_written": 0,
            "output_owner": "installation_local_data_product_export_workspace",
            "download_route": f"/api/data-product/export-jobs/{job_id}/download",
        }
        _save(path, state)
        with _LOCK:
            _ACTIVE.add(job_id)
        return state
    except BaseException:
        if created is not None:
            try:
                shutil.rmtree(created)
            except OSError:
                pass
        _SLOTS.release()
        raise


def create_daily_job(
    dataset_id: str, *, release: PinnedServingRelease, catalog_version: str,
    universe: str, subject_type: str | None, subject_id: str,
    metric_ids: Sequence[str], start: str, end: str, root: Path | None = None,
) -> dict[str, Any]:
    selection = DAILY_DATASETS.get(dataset_id)
    if selection is None:
        raise DataProductError("logical_dataset_not_exposed", "dataset has no selected daily export contract", 409)
    selected_universe, selected_type, allowed_metrics = selection
    if universe != selected_universe or subject_type not in (None, selected_type):
        raise DataProductError("dataset_selection_mismatch", "selected subject does not match dataset")
    if not subject_id or len(subject_id) > 200 or not metric_ids or len(metric_ids) > 8 or len(set(metric_ids)) != len(metric_ids):
        raise DataProductError("invalid_export_selection", "select one durable subject and distinct supported metrics")
    if not set(metric_ids) <= allowed_metrics:
        raise DataProductError("unsupported_fields", "selected fields are outside the logical dataset")
    try:
        first, last = date.fromisoformat(start), date.fromisoformat(end)
    except ValueError as exc:
        raise DataProductError("invalid_date_range", "start/end must be ISO dates") from exc
    if first > last:
        raise DataProductError("invalid_date_range", "start follows end")
    if not _SLOTS.acquire(blocking=False):
        raise DataProductError("export_capacity_busy", "two local exports are already active", 409)
    job_id = "fr_export_" + secrets.token_hex(16)
    created: Path | None = None
    try:
        _root(root).mkdir(parents=True, exist_ok=True)
        path = _job_dir(job_id, root=root)
        path.mkdir(exist_ok=False)
        created = path
        write_json_atomic(path / "owner.json", {"owner": OWNER, "job_id": job_id, "created_at": _now()})
        state = {
            "schema_version": OWNER, "job_id": job_id, "status": "queued",
            "scope": "all_matching_selected_interval", "dataset_id": dataset_id,
            "filters": {"universe": selected_universe, "subject_type": selected_type,
                        "subject_id": subject_id, "metric_ids": list(metric_ids),
                        "start": start, "end": end},
            "fields": list(DAILY_FIELDS), "release_id": release.release_id,
            "release_hash": release.release_hash, "snapshot_id": release.snapshot_id,
            "catalog_version": catalog_version, "owner_pid": os.getpid(),
            "owner_process_start": PROCESS_START_UTC,
            "created_at": _now(), "updated_at": _now(),
            "logical_row_count": None, "rows_written": 0, "bytes_written": 0,
            "windows_total": ((last - first).days // 366) + 1, "windows_complete": 0,
            "output_owner": "installation_local_data_product_export_workspace",
            "download_route": f"/api/data-product/export-jobs/{job_id}/download",
        }
        _save(path, state)
        with _LOCK:
            _ACTIVE.add(job_id)
        return state
    except BaseException:
        if created is not None:
            try:
                shutil.rmtree(created)
            except OSError:
                pass
        _SLOTS.release()
        raise


def _daily_windows(start: str, end: str):
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    while first <= last:
        upper = first + timedelta(days=min(365, (last - first).days))
        yield first.isoformat(), upper.isoformat()
        first = upper + timedelta(days=1)


def run_daily_job(
    job_id: str, *, release: PinnedServingRelease, root: Path | None = None,
    table_reader=research_table,
) -> None:
    path = _job_dir(job_id, root=root)
    try:
        state = _state(path)
        if (state["release_id"], state["release_hash"]) != (release.release_id, release.release_hash):
            raise DataProductError("export_release_mismatch", "job release binding changed", 409)
        if (path / "cancel.requested").exists():
            state.update(status="cancelled", updated_at=_now(), finished_at=_now())
            _save(path, state)
            return
        state.update(status="running", updated_at=_now())
        _save(path, state)
        filters = state["filters"]
        logical_count = 0
        with (path / "result.partial").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(DAILY_FIELDS)
            for window_index, (start, end) in enumerate(_daily_windows(filters["start"], filters["end"]), 1):
                if (path / "cancel.requested").exists():
                    state.update(status="cancelled", updated_at=_now(), finished_at=_now())
                    _save(path, state)
                    return
                value = table_reader(
                    universe=filters["universe"], subject_type=filters["subject_type"],
                    subject_id=filters["subject_id"], metric_ids=filters["metric_ids"],
                    start=start, end=end, max_rows=5_000, release=release,
                )
                if value["status"] != "complete":
                    raise DataProductError("incomplete_field_retrieval", "failed field cannot be exported as complete", 409)
                series = {field["metric_id"]: field.get("series_id") for field in value["fields"]}
                for row in value["rows"]:
                    logical_count += 1
                    for metric in filters["metric_ids"]:
                        cell = row["cells"][metric]
                        writer.writerow([
                            state["catalog_version"], state["release_id"], state["release_hash"],
                            state["dataset_id"], filters["subject_type"], filters["subject_id"],
                            row["economic_time"], metric,
                            "returned" if cell is not None else "no_returned_observation",
                            cell.get("value") if cell else None, cell.get("unit") if cell else None,
                            cell.get("currency") if cell else None, cell.get("scale") if cell else None,
                            cell.get("time_role") if cell else None, series.get(metric),
                            json.dumps(cell.get("provenance"), ensure_ascii=False, sort_keys=True) if cell else None,
                            (cell.get("support_trace") or {}).get("source_observation_id") if cell else None,
                        ])
                state.update(logical_row_count=logical_count, rows_written=logical_count * len(filters["metric_ids"]),
                             windows_complete=window_index, bytes_written=stream.tell(), updated_at=_now())
                _save(path, state)
        (path / "result.partial").replace(path / "result.csv")
        state.update(status="complete", bytes_written=(path / "result.csv").stat().st_size,
                     output_sha256=sha256_file(path / "result.csv"),
                     updated_at=_now(), finished_at=_now())
        _save(path, state)
    except Exception as exc:
        try:
            state = _state(path)
            state.update(status="failed", error_code=(exc.code if isinstance(exc, DataProductError)
                                                      else "export_read_or_write_failed"),
                         updated_at=_now(), finished_at=_now())
            _save(path, state)
        except (DataProductError, OSError, ValueError):
            pass
    finally:
        with _LOCK:
            _ACTIVE.discard(job_id)
        _SLOTS.release()


def run_identity_job(job_id: str, *, release: PinnedServingRelease, root: Path | None = None) -> None:
    path = _job_dir(job_id, root=root)
    try:
        state = _state(path)
        if (state["release_id"], state["release_hash"]) != (release.release_id, release.release_hash):
            raise DataProductError("export_release_mismatch", "job release binding changed", 409)
        if (path / "cancel.requested").exists():
            state.update(status="cancelled", updated_at=_now(), finished_at=_now())
            _save(path, state)
            return
        state.update(status="running", updated_at=_now())
        _save(path, state)
        filters = dict(state["filters"])
        if state["scope"] == "complete_logical_dataset":
            filters["lifecycle"] = "All"
        rows = identity_dataset_rows(state["dataset_id"], release=release, **filters)
        state["logical_row_count"] = len(rows)
        _save(path, state)
        partial = path / "result.partial"
        with partial.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["catalog_version", "release_id", "release_hash", "dataset_id", *state["fields"]])
            for index, row in enumerate(rows, 1):
                if (path / "cancel.requested").exists():
                    state.update(status="cancelled", updated_at=_now(), finished_at=_now())
                    _save(path, state)
                    return
                writer.writerow([state["catalog_version"], state["release_id"], state["release_hash"],
                                 state["dataset_id"], *[row.get(field) for field in state["fields"]]])
                if index % 500 == 0:
                    state.update(rows_written=index, bytes_written=stream.tell(), updated_at=_now())
                    _save(path, state)
        partial.replace(path / "result.csv")
        state.update(status="complete", rows_written=len(rows),
                     bytes_written=(path / "result.csv").stat().st_size,
                     output_sha256=sha256_file(path / "result.csv"),
                     updated_at=_now(), finished_at=_now())
        _save(path, state)
    except Exception:
        try:
            state = _state(path)
            state.update(status="failed", error_code="export_read_or_write_failed",
                         updated_at=_now(), finished_at=_now())
            _save(path, state)
        except (DataProductError, OSError, ValueError):
            pass
    finally:
        with _LOCK:
            _ACTIVE.discard(job_id)
        _SLOTS.release()


def job_status(job_id: str, *, root: Path | None = None) -> dict[str, Any]:
    state = _state(_job_dir(job_id, root=root))
    with _LOCK:
        locally_active = job_id in _ACTIVE
    if state["status"] in {"queued", "running"} and not locally_active:
        if not _pid_alive(int(state.get("owner_pid") or 0)):
            return {**state, "status": "interrupted_restart_required",
                    "partial_output_downloadable": False}
        return {**state, "status": "owner_status_unconfirmed",
                "partial_output_downloadable": False}
    return state


def cancel_job(job_id: str, *, root: Path | None = None) -> dict[str, Any]:
    path = _job_dir(job_id, root=root)
    state = _state(path)
    if state["status"] in {"complete", "failed", "cancelled"}:
        return state
    (path / "cancel.requested").touch(exist_ok=True)
    return {**state, "cancel_requested": True}


def completed_output(job_id: str, *, root: Path | None = None) -> Path:
    path = _job_dir(job_id, root=root)
    state = _state(path)
    output = path / "result.csv"
    if state["status"] != "complete" or not output.is_file() or output.is_symlink() or output.resolve().parent != path:
        raise DataProductError("export_not_complete", "completed export is not available", 409)
    return output


def sweep_expired(*, root: Path | None = None, now: datetime | None = None) -> dict[str, int]:
    """Remove only owned, terminal, aged job directories; never live/unknown."""
    owner_root = _root(root)
    if not owner_root.is_dir():
        return {"removed_jobs": 0, "removed_bytes": 0}
    threshold = (now or datetime.now(timezone.utc)) - timedelta(days=7)
    removed = 0
    bytes_removed = 0
    for path in owner_root.iterdir():
        if not path.is_dir() or path.is_symlink() or not re.fullmatch(r"fr_export_[a-f0-9]{32}", path.name):
            continue
        if path.resolve().parent != owner_root:
            continue
        try:
            state = _state(path)
            completed_at = datetime.fromisoformat(str(state.get("finished_at") or "").replace("Z", "+00:00"))
        except (DataProductError, ValueError, TypeError, OSError):
            continue
        if state.get("status") not in {"complete", "failed", "cancelled"} or completed_at >= threshold:
            continue
        try:
            size = sum(member.stat().st_size for member in path.rglob("*") if member.is_file())
            shutil.rmtree(path)
        except OSError:
            continue
        removed += 1
        bytes_removed += size
    return {"removed_jobs": removed, "removed_bytes": bytes_removed}
