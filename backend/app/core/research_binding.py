from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence


ALLOWED_DISPOSITIONS = frozenset({"source_only", "canonical", "quarantine"})


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class InformationStateObservation:
    """Shared representation; domain code remains responsible for interpretation."""

    subject_id: str
    series_id: str
    reference_time: str
    value: str
    publication_time: str
    information_version_id: str
    source_id: str
    source_evidence_sha256: str
    disposition: str = "canonical"
    effective_time: str | None = None
    lineage_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not all((self.subject_id, self.series_id, self.reference_time, self.publication_time,
                    self.information_version_id, self.source_id, self.source_evidence_sha256)):
            raise ValueError("information-state observation has an empty required identity/time field")
        _parse_time(self.publication_time)
        if self.disposition not in ALLOWED_DISPOSITIONS:
            raise ValueError(f"unsupported disposition: {self.disposition}")
        if len(self.source_evidence_sha256) != 64:
            raise ValueError("source evidence must use a SHA-256 digest")

    @property
    def information_state_key(self) -> tuple[str, str, str]:
        return self.subject_id, self.series_id, self.reference_time

    def as_dict(self) -> dict[str, Any]:
        return {
            "subject_id": self.subject_id,
            "series_id": self.series_id,
            "reference_time": self.reference_time,
            "effective_time": self.effective_time,
            "value": self.value,
            "publication_time": self.publication_time,
            "information_version_id": self.information_version_id,
            "source_id": self.source_id,
            "source_evidence_sha256": self.source_evidence_sha256,
            "disposition": self.disposition,
            "lineage_ids": list(self.lineage_ids),
        }


def select_as_known(
    observations: Iterable[InformationStateObservation],
    *,
    knowledge_cutoff: str,
    dispositions: Sequence[str] = ("canonical",),
) -> list[InformationStateObservation]:
    """Return the latest eligible official information state per durable Series/reference time."""

    cutoff = _parse_time(knowledge_cutoff)
    allowed = set(dispositions)
    selected: dict[tuple[str, str, str], InformationStateObservation] = {}
    for row in observations:
        if row.disposition not in allowed or _parse_time(row.publication_time) > cutoff:
            continue
        key = row.information_state_key
        previous = selected.get(key)
        if previous is None or (
            _parse_time(row.publication_time), row.information_version_id
        ) > (
            _parse_time(previous.publication_time), previous.information_version_id
        ):
            selected[key] = row
    return sorted(selected.values(), key=lambda row: row.information_state_key)


def source_shape(value: Any) -> Any:
    """Describe observed JSON structure without depending on values or row count."""

    if isinstance(value, Mapping):
        return {str(key): source_shape(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        shapes = {canonical_json(source_shape(item)) for item in value[:100]}
        return {"type": "array", "item_shapes": [json.loads(item) for item in sorted(shapes)]}
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    return "string"


def source_shape_fingerprint(value: Any) -> dict[str, Any]:
    shape = source_shape(value)
    return {"shape": shape, "sha256": canonical_sha256(shape)}


def assert_source_shape(value: Any, expected_sha256: str) -> None:
    actual = source_shape_fingerprint(value)["sha256"]
    if actual != expected_sha256:
        raise ValueError(f"source schema drift: expected {expected_sha256}, found {actual}")


@dataclass(frozen=True)
class ResearchDatasetBinding:
    database_version_id: str
    manifest_sha256: str
    knowledge_cutoff: str
    query_spec: Mapping[str, Any]
    subject_selection: Mapping[str, Any]
    feature_definitions: Sequence[Mapping[str, Any]]
    label_definition: Mapping[str, Any]
    code_identity: Mapping[str, Any]
    parameter_identity: Mapping[str, Any]
    environment_identity: Mapping[str, Any]
    input_columns: tuple[str, ...]
    input_rows: tuple[Mapping[str, Any], ...]

    def __post_init__(self) -> None:
        if len(self.manifest_sha256) != 64:
            raise ValueError("manifest identity must be a SHA-256 digest")
        _parse_time(self.knowledge_cutoff)
        if not self.database_version_id or not self.input_columns or not self.input_rows:
            raise ValueError("research binding requires a version, columns, and non-empty input")
        columns = set(self.input_columns)
        for row in self.input_rows:
            if set(row) != columns:
                raise ValueError("research input row does not match the declared columns")

    @property
    def input_digest(self) -> str:
        return canonical_sha256({"columns": list(self.input_columns), "rows": list(self.input_rows)})

    @property
    def binding_digest(self) -> str:
        return canonical_sha256(self.as_dict(include_rows=False))

    def as_dict(self, *, include_rows: bool = True) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": "fr_research_dataset_binding_v1",
            "database_version_id": self.database_version_id,
            "manifest_sha256": self.manifest_sha256,
            "knowledge_cutoff": self.knowledge_cutoff,
            "query_spec": dict(self.query_spec),
            "subject_selection": dict(self.subject_selection),
            "feature_definitions": list(self.feature_definitions),
            "label_definition": dict(self.label_definition),
            "code_identity": dict(self.code_identity),
            "parameter_identity": dict(self.parameter_identity),
            "environment_identity": dict(self.environment_identity),
            "input_columns": list(self.input_columns),
            "input_row_count": len(self.input_rows),
            "input_digest": self.input_digest,
        }
        if include_rows:
            result["input_rows"] = list(self.input_rows)
        return result


def verify_research_binding(payload: Mapping[str, Any]) -> str:
    columns = tuple(str(value) for value in payload["input_columns"])
    rows = tuple(dict(row) for row in payload["input_rows"])
    digest = canonical_sha256({"columns": list(columns), "rows": list(rows)})
    if digest != payload["input_digest"]:
        raise ValueError("research input digest mismatch")
    if int(payload["input_row_count"]) != len(rows):
        raise ValueError("research input row count mismatch")
    return digest
