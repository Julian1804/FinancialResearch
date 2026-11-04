"""Durable serving-control verification receipts from the release lifecycle.

The full content hash of the Fund control member is an integrity-producing
lifecycle fact, not ordinary serving work:

- build/update computes ``sha256_file`` of the physical control file and
  records it in the immutable snapshot manifest member entry;
- publication verifies the retained dependency closure
  (``resolve_retained_consumer`` -> ``_verify_serving_binding``): the release
  descriptor hash, the manifest hash, the manifest-bound control identity,
  and the physical size, then stores the closure durably in the control-plane
  ``retained_external_consumer`` table under the release-retention schema;
- ordinary serving consumes that durable receipt instead of re-reading the
  multi-GB member.  The receipt is trusted only when it binds the exact
  release/manifest/member content identity of the request.  File size is
  checked only as a corruption tripwire; it is never treated as content
  proof.  Whenever the receipt is absent, unbound, inconsistent, or the
  tripwire fires, serving falls back to the full content verification.

No receipt is ever written by an ordinary read path: receipts are produced
only by the publication lifecycle that already owns release retention.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from typing import Any, Mapping

from backend.app.core.serving_release import PinnedServingRelease, release_content_hash
from backend.app.core.storage_profile import resolve_control_plane_path


SERVING_BINDING_SCHEMA = "fr_serving_release_retention_binding_v1"


def _stored_binding_matches(row: Mapping[str, Any]) -> bool:
    binding_json = str(row["binding_json"])
    if hashlib.sha256(binding_json.encode("utf-8")).hexdigest() != str(row["binding_sha256"]):
        return False
    try:
        binding = json.loads(binding_json)
    except json.JSONDecodeError:
        return False
    return isinstance(binding, dict)


RELEASE_RETENTION_CONSUMER_TYPES = (
    "serving_release",
    "serving_release_candidate",
    "serving_release_rollback",
)


def _load_serving_bindings() -> list[dict[str, Any]]:
    database = resolve_control_plane_path()
    if not database.is_file():
        return []
    with closing(sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                "SELECT * FROM retained_external_consumer "
                "WHERE status='retained' AND consumer_type IN (?,?,?)",
                RELEASE_RETENTION_CONSUMER_TYPES,
            ).fetchall()
        except sqlite3.OperationalError:
            # Older control databases predate the retention schema; without
            # the table there is no receipt and full verification applies.
            return []
    bindings = []
    for row in rows:
        stored = dict(row)
        if not _stored_binding_matches(stored):
            continue
        binding = json.loads(str(stored["binding_json"]))
        if binding.get("schema_version") != SERVING_BINDING_SCHEMA:
            continue
        binding["_stored_binding_sha256"] = stored["binding_sha256"]
        binding["_stored_snapshot_id"] = str(stored["snapshot_id"] or "")
        bindings.append(binding)
    return bindings


def resolve_serving_control_receipt(
    *,
    snapshot_id: str,
    manifest_sha256: str,
    control_relative_path: str,
    release: PinnedServingRelease | None = None,
) -> dict[str, Any] | None:
    """Resolve the publication receipt for one snapshot control member.

    The receipt is accepted only when a retained serving-release binding
    (a) has an intact stored binding hash,
    (b) binds this snapshot and this manifest content hash,
    (c) binds the pinned release content identity when one is supplied,
    (d) carries a snapshot-member control dependency for the requested path
        with content hash and byte count.

    Conflicting receipts for the same identity are refused so the caller
    falls back to full verification.
    """
    matches: list[dict[str, Any]] = []
    for binding in _load_serving_bindings():
        if binding.get("database_version_id") != snapshot_id:
            continue
        if binding.get("manifest_sha256") != manifest_sha256:
            continue
        if release is not None:
            descriptor = binding.get("release_descriptor")
            if not isinstance(descriptor, dict):
                continue
            if descriptor.get("release_content_hash") != release.release_hash:
                continue
            if release.release_id is not None and descriptor.get("release_id") != release.release_id:
                continue
            if release_content_hash(descriptor) != release.release_hash:
                continue
        control = binding.get("control_dependency")
        if not isinstance(control, dict):
            continue
        if control.get("owner") != "snapshot_member":
            continue
        if control.get("relative_path") != control_relative_path:
            continue
        content_sha256 = control.get("content_sha256")
        byte_count = control.get("byte_count")
        if not isinstance(content_sha256, str) or len(content_sha256) != 64:
            continue
        if byte_count is None:
            continue
        matches.append({
            "owner": "snapshot_member",
            "relative_path": control_relative_path,
            "content_sha256": content_sha256,
            "byte_count": int(byte_count),
        })
    distinct = {json.dumps(row, sort_keys=True): row for row in matches}
    if len(distinct) != 1:
        return None
    return dict(matches[0])
