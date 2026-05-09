"""Wall-clock budget tracking."""
from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class Budget:
    total_seconds: float
    started_at: float = 0.0

    def start(self) -> None:
        self.started_at = time.monotonic()

    def elapsed(self) -> float:
        return time.monotonic() - self.started_at

    def remaining(self) -> float:
        return max(0.0, self.total_seconds - self.elapsed())

    def expired(self) -> bool:
        return self.elapsed() >= self.total_seconds
