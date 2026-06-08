from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CostTracker:
    estimated_usd: float = 0.0

    def add(self, value: float | None) -> None:
        if value is not None:
            self.estimated_usd += value

    def total_or_none(self) -> float | None:
        return self.estimated_usd if self.estimated_usd > 0 else None
