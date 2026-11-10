"""Emergency kill switch (Item 2.5, Phase 1).

The kill switch makes the scheduler refuse to execute ANY job. It is intentionally
"sticky" and easy to engage by a human under pressure:

  * Sentinel file: presence of ``database/nexora_scheduler.KILL`` engages it.
  * Config flag: ``SchedulerConfig.kill_switch_engaged`` engages it.
  * Runtime flag: ``engage()`` sets an in-process flag (and, optionally, the file).

Checking is fail-closed: if the switch is engaged for ANY reason, the scheduler runs
nothing and reports why. Disengaging requires an explicit call (there is no auto-reset).

The kill switch NEVER touches the job queue DB (except by being read by the scheduler),
the production DB, or governance status.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import DEFAULT_CONFIG, KILL_SWITCH_FILE, SchedulerConfig


@dataclass
class KillSwitchState:
    engaged: bool
    reasons: list

    def as_dict(self) -> dict:
        return {"engaged": self.engaged, "reasons": list(self.reasons)}


class KillSwitch:
    def __init__(self, *, path: Path = KILL_SWITCH_FILE,
                 config: SchedulerConfig = DEFAULT_CONFIG) -> None:
        self.path = Path(path)
        self.config = config
        self._runtime_engaged = False

    def engage(self, reason: str = "manual", *, write_file: bool = False) -> None:
        self._runtime_engaged = True
        if write_file:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(reason, encoding="utf-8")

    def disengage(self, *, remove_file: bool = True) -> None:
        self._runtime_engaged = False
        if remove_file and self.path.exists():
            try:
                self.path.unlink()
            except OSError:
                pass

    def state(self) -> KillSwitchState:
        reasons = []
        if self.config.kill_switch_engaged:
            reasons.append("config.kill_switch_engaged=True")
        if self._runtime_engaged:
            reasons.append("runtime kill switch engaged")
        if self.path.exists():
            try:
                reasons.append(f"sentinel file present: {self.path}")
            except OSError:
                reasons.append("sentinel file present")
        return KillSwitchState(engaged=bool(reasons), reasons=reasons)

    def is_engaged(self) -> bool:
        return self.state().engaged
