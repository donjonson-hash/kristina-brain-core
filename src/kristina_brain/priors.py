"""
Нейтральный протокол холодного старта (ColdStartPrior / PriorProvider — v1.1.0).
Позволяет внешним экспериментальным проектам (например, гостиничной платформе)
передавать начальные смещения 12 мод и весов синапсов нового scope_id без смешения
доменной логики с базовым ядром Кристины.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class ColdStartPrior:
    archetype_tag: str
    initial_mode_offsets: Mapping[str, float] = field(default_factory=dict)
    initial_synapse_weights: Mapping[str, float] = field(default_factory=dict)
    prior_confidence: float = 0.28
    operational_brief: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not (0.0 <= self.prior_confidence <= 1.0):
            raise ValueError(f"prior_confidence must be in [0.0, 1.0], got {self.prior_confidence}")


@runtime_checkable
class PriorProvider(Protocol):
    """Внешний плагин вычисления стартовой гипотезы до первого диалога с человеком."""

    def compute_prior(self, scope_id: str, metadata: Mapping[str, Any]) -> ColdStartPrior: ...
