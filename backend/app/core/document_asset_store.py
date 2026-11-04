from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from backend.app.core.artifact_io import canonical_json, write_json_atomic
from backend.app.core.storage_profile import resolve_logical_layer_path


@dataclass(frozen=True)
class StoredDocumentAsset:
    document_asset_id: str
    content_sha256: str
    byte_count: int
    mime_type: str
    asset_path: str
    provenance_path: str
    reused_existing_asset: bool

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


class DocumentAssetStore:
    """Immutable document assets under FR's existing ``05_documents`` owner."""

    def __init__(self, owner_root: Path | None = None) -> None:
        self.owner_root = Path(owner_root) if owner_root is not None else resolve_logical_layer_path("documents")
        self.dataset_root = self.owner_root / "a_share_continuing_canonical_documents_v1"

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def store(
        self,
        source_path: Path,
        *,
        mime_type: str,
        provenance: Mapping[str, Any],
    ) -> StoredDocumentAsset:
        source_path = Path(source_path)
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        content_hash = self._sha256(source_path)
        suffix = ".pdf" if mime_type == "application/pdf" else ".bin"
        asset = self.dataset_root / "assets" / "sha256" / content_hash[:2] / f"{content_hash}{suffix}"
        provenance_hash = hashlib.sha256(canonical_json(dict(provenance)).encode("utf-8")).hexdigest()
        sidecar = self.dataset_root / "provenance" / "sha256" / provenance_hash[:2] / f"{provenance_hash}.json"
        reused = asset.is_file()
        if reused:
            if self._sha256(asset) != content_hash or asset.stat().st_size != source_path.stat().st_size:
                raise ValueError(f"content-addressed document asset is corrupt: {asset}")
        else:
            asset.parent.mkdir(parents=True, exist_ok=True)
            temporary = asset.with_name(f".{asset.name}.{os.getpid()}.tmp")
            shutil.copyfile(source_path, temporary)
            if self._sha256(temporary) != content_hash:
                temporary.unlink(missing_ok=True)
                raise ValueError("document asset changed during copy")
            os.replace(temporary, asset)
        sidecar_payload = {
            "schema_version": "fr_document_asset_provenance_v1",
            "document_asset_id": f"document_asset:sha256:{content_hash}",
            "content_sha256": content_hash,
            "byte_count": asset.stat().st_size,
            "mime_type": mime_type,
            "asset_path": str(asset),
            "provenance": dict(provenance),
        }
        if sidecar.is_file():
            prior = json.loads(sidecar.read_text(encoding="utf-8"))
            if canonical_json(prior) != canonical_json(sidecar_payload):
                raise ValueError(f"document provenance collision for {content_hash}")
        else:
            write_json_atomic(sidecar, sidecar_payload)
        return StoredDocumentAsset(
            document_asset_id=sidecar_payload["document_asset_id"],
            content_sha256=content_hash,
            byte_count=asset.stat().st_size,
            mime_type=mime_type,
            asset_path=str(asset),
            provenance_path=str(sidecar),
            reused_existing_asset=reused,
        )
