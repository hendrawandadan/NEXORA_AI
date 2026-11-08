from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class TrainingJobCreate:
    job_key: str
    scope: str
    symbol: Optional[str]
    timeframe: str
    horizon: int
    status: str
    config_json: str
    legacy_status: Optional[str] = None
    legacy_action: Optional[str] = None
    legacy_reference: Optional[str] = None
    legacy_source: Optional[str] = None
    migration_source_hash: Optional[str] = None
    # Dual-target contract (v5+). Defaults to T1 for backward compatibility with
    # the legacy close->close pipeline; callers must set T3 explicitly.
    target_type: str = "T1"


@dataclass(frozen=True)
class TrainingRunCreate:
    job_id: int
    run_uid: str
    run_index: int
    status: str
    training_config_json: str


@dataclass(frozen=True)
class ArtifactCreate:
    run_id: int
    artifact_type: str
    path: str
    sha256: str
    size_bytes: int
    is_temporary: bool


@dataclass(frozen=True)
class AuditLogCreate:
    entity_type: str
    entity_id: str
    action: str
    old_state: Optional[str]
    new_state: Optional[str]
    payload_json: str
    actor: str
