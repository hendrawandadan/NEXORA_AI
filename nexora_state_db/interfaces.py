from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from .models import ArtifactCreate, AuditLogCreate, TrainingJobCreate, TrainingRunCreate


class TrainingJobRepository(ABC):
    @abstractmethod
    def create_job(self, job: TrainingJobCreate) -> int:
        raise NotImplementedError

    @abstractmethod
    def queue_planned_job(self, job_id: int, actor: str) -> None:
        """Explicitly approve a PLANNED job for the execution queue."""
        raise NotImplementedError

    @abstractmethod
    def create_dataset(
        self,
        symbol: str,
        timeframe: str,
        path: str,
        bars: int,
        status: str,
    ) -> int:
        raise NotImplementedError

    @abstractmethod
    def link_job_dataset(self, job_id: int, dataset_id: int, role: str = "train") -> None:
        raise NotImplementedError


class TrainingRunRepository(ABC):
    @abstractmethod
    def create_run(self, run: TrainingRunCreate) -> int:
        raise NotImplementedError

    @abstractmethod
    def claim_next_queued_run(self, job_id: Optional[int] = None) -> Optional[int]:
        raise NotImplementedError


class CheckpointRepository(ABC):
    @abstractmethod
    def append_checkpoint(
        self,
        run_id: int,
        to_status: str,
        actor: str,
        note: str = "",
        metadata_json: str = "{}",
    ) -> int:
        raise NotImplementedError


class ArtifactRepository(ABC):
    @abstractmethod
    def create_artifact(self, artifact: ArtifactCreate) -> int:
        raise NotImplementedError


class AuditLogRepository(ABC):
    @abstractmethod
    def create_audit_log(self, log: AuditLogCreate) -> int:
        raise NotImplementedError
