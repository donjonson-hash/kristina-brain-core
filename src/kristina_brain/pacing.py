"""
Физиологический ритм и тайминг ответа агента (ResponsePacingEngine — v0.5.0).
Рассчитывает естественную паузу перед ответом, рекомендуемую длину реплики
и флаг сенсорного любопытства для живого диалога.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ResponsePacing:
    delay_seconds: float
    verbosity_hint: str  # "concise" | "balanced" | "expansive"
    sensory_curiosity_high: bool


class ResponsePacingEngine:
    """Детерминированный расчёт ритма ответа без зависимости от конкретного мессенджера."""

    def __init__(
        self,
        *,
        min_delay_seconds: float = 12.0,
        max_delay_seconds: float = 75.0,
    ) -> None:
        if min_delay_seconds < 0.0 or max_delay_seconds < min_delay_seconds:
            raise ValueError("Invalid pacing delay bounds")
        self.min_delay_seconds = float(min_delay_seconds)
        self.max_delay_seconds = float(max_delay_seconds)

    def calculate(
        self,
        emotional_state: Mapping[str, Any],
        *,
        user_input_length: int = 0,
    ) -> ResponsePacing:
        vec = emotional_state.get("state", emotional_state)
        energy = float(vec.get("energy", 0.5))
        curiosity = float(vec.get("curiosity", 0.5))
        irritation = float(vec.get("irritation", 0.1))
        creativity = float(vec.get("creativity", 0.5))
        is_night = bool(emotional_state.get("is_night", False))

        span = self.max_delay_seconds - self.min_delay_seconds
        # Базовая пауза: высокая энергия и любопытство ускоряют ответ, усталость/ночь замедляют
        readiness = 0.55 * energy + 0.35 * curiosity - 0.25 * irritation
        norm_wait = max(0.0, min(1.0, 0.72 - 0.55 * readiness + (0.18 if is_night else 0.0)))

        # Учёт времени чтения длинного сообщения пользователя
        reading_bonus = min(span * 0.20, max(0.0, user_input_length - 60) * 0.04)
        raw_delay = self.min_delay_seconds + span * norm_wait + reading_bonus
        delay = round(max(self.min_delay_seconds, min(self.max_delay_seconds, raw_delay)), 1)

        if irritation >= 0.55 or (is_night and energy < 0.42):
            verbosity = "concise"
        elif curiosity >= 0.65 and energy >= 0.50 and creativity >= 0.50:
            verbosity = "expansive"
        else:
            verbosity = "balanced"

        return ResponsePacing(
            delay_seconds=delay,
            verbosity_hint=verbosity,
            sensory_curiosity_high=(curiosity >= 0.64 and irritation < 0.45),
        )
