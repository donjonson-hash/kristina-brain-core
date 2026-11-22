"""
Декларативные профили персоны и матрица Big Five (закрытие AUD-06 + база под B2D SDK).
Позволяет конфигурировать любого агента (Кристина, языковой тьютор, игровой NPC, B2B CSM)
через JSON/словарь без редактирования Python-кода.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class BigFiveTraits:
    extraversion: float = 0.7
    neuroticism: float = 0.4
    openness: float = 0.8
    agreeableness: float = 0.6
    conscientiousness: float = 0.5

    def __post_init__(self) -> None:
        for attr in ("extraversion", "neuroticism", "openness", "agreeableness", "conscientiousness"):
            val = getattr(self, attr)
            if not (0.0 <= val <= 1.0):
                raise ValueError(f"BigFive trait '{attr}' must be in [0.0, 1.0], got {val}")

    def to_dict(self) -> dict[str, float]:
        return {
            "extraversion": self.extraversion,
            "neuroticism": self.neuroticism,
            "openness": self.openness,
            "agreeableness": self.agreeableness,
            "conscientiousness": self.conscientiousness,
        }


@dataclass(frozen=True)
class ModeSpec:
    baseline: float
    half_life_hours: float

    def __post_init__(self) -> None:
        if not (0.0 <= self.baseline <= 1.0):
            raise ValueError(f"baseline must be in [0.0, 1.0], got {self.baseline}")
        if self.half_life_hours <= 0.0:
            raise ValueError(f"half_life_hours must be > 0, got {self.half_life_hours}")


@dataclass(frozen=True)
class PersonaProfile:
    """Переносимая конфигурация агента для мультитенантного рантайма."""

    persona_id: str
    display_name: str
    timezone: str = "UTC"
    locale_city_label: str = "UTC"
    night_hours: tuple[int, int] = (23, 7)  # (start_hour, end_hour) в локальной таймзоне агента
    counterparty_night_hours: tuple[int, int] = (23, 8)  # не будить собеседника в его поясе
    pacing_min_delay_seconds: float = 12.0
    pacing_max_delay_seconds: float = 75.0
    traits: BigFiveTraits = field(default_factory=BigFiveTraits)
    proactive_threshold: float = 0.62
    proactive_cooldown_seconds: int = 7200
    enable_slow_modes_in_decisions: bool = False  # Флаг активации влияния 12 медленных мод (вместо только shadow)
    appraisal_system_prompt: str = (
        "You are an objective cognitive appraisal classifier for an autonomous agent. "
        "Evaluate the incoming user message and return strict JSON."
    )
    persona_system_prompt: str = "You are a helpful, context-aware autonomous agent."
    custom_modes: Mapping[str, ModeSpec] = field(default_factory=dict)

    def __post_init__(self) -> None:
        ZoneInfo(self.timezone)
        start_h, end_h = self.night_hours
        if not (0 <= start_h <= 23 and 0 <= end_h <= 23):
            raise ValueError(f"Invalid night_hours={self.night_hours}")
        if not (0.0 < self.proactive_threshold <= 1.0):
            raise ValueError(f"Invalid proactive_threshold={self.proactive_threshold}")
        if self.proactive_cooldown_seconds < 0:
            raise ValueError("proactive_cooldown_seconds must be >= 0")

    def is_night_at(self, local_hour: int) -> bool:
        start_h, end_h = self.night_hours
        if start_h <= end_h:
            return start_h <= local_hour < end_h
        return local_hour >= start_h or local_hour < end_h

    @classmethod
    def from_json_file(cls, path: str | Path) -> PersonaProfile:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> PersonaProfile:
        traits_raw = data.get("traits") or {}
        traits = BigFiveTraits(**traits_raw) if isinstance(traits_raw, Mapping) else BigFiveTraits()
        modes_raw = data.get("custom_modes") or {}
        modes: dict[str, ModeSpec] = {}
        if isinstance(modes_raw, Mapping):
            for k, v in modes_raw.items():
                if isinstance(v, Mapping):
                    modes[str(k)] = ModeSpec(
                        baseline=float(v["baseline"]),
                        half_life_hours=float(v["half_life_hours"]),
                    )
        nh = data.get("night_hours", [23, 7])
        night_tuple = (int(nh[0]), int(nh[1])) if isinstance(nh, (list, tuple)) and len(nh) == 2 else (23, 7)
        return cls(
            persona_id=str(data["persona_id"]),
            display_name=str(data.get("display_name", data["persona_id"])),
            timezone=str(data.get("timezone", "UTC")),
            locale_city_label=str(data.get("locale_city_label", data.get("timezone", "UTC"))),
            night_hours=night_tuple,
            counterparty_night_hours=(
                int(data.get("counterparty_night_hours", [23, 8])[0]),
                int(data.get("counterparty_night_hours", [23, 8])[1]),
            ),
            pacing_min_delay_seconds=float(data.get("pacing_min_delay_seconds", 12.0)),
            pacing_max_delay_seconds=float(data.get("pacing_max_delay_seconds", 75.0)),
            traits=traits,
            proactive_threshold=float(data.get("proactive_threshold", 0.62)),
            proactive_cooldown_seconds=int(data.get("proactive_cooldown_seconds", 7200)),
            enable_slow_modes_in_decisions=bool(data.get("enable_slow_modes_in_decisions", False)),
            appraisal_system_prompt=str(
                data.get(
                    "appraisal_system_prompt",
                    "Оцени входящее сообщение пользователя и верни строго валидный JSON по схеме Appraisal.",
                )
            ),
            persona_system_prompt=str(data.get("persona_system_prompt", "")),
            custom_modes=modes,
        )


# Эталонный профиль Кристины — сохраняет 100% поведение kristina-revolutionary, но как данные, а не хардкод
DEFAULT_KRISTINA_PROFILE = PersonaProfile(
    persona_id="kristina",
    display_name="Кристина",
    timezone="Europe/Stockholm",
    locale_city_label="Стокгольме",
    night_hours=(23, 7),
    traits=BigFiveTraits(
        extraversion=0.7,
        neuroticism=0.4,
        openness=0.8,
        agreeableness=0.6,
        conscientiousness=0.5,
    ),
    proactive_threshold=0.62,
    proactive_cooldown_seconds=7200,
    enable_slow_modes_in_decisions=False,
    appraisal_system_prompt=(
        "Ты модуль когнитивной предоценки персоны Кристины. "
        "Проанализируй реплику собеседника и верни строго JSON с ключами: "
        "reaction (curiosity|warmth|concern|frustration|neutral), intensity (0..1), "
        "source_quote, interest_action (keep|open|resolve|ignore), topic, reflection, "
        "а если собеседник упомянул где он находится или какая вокруг обстановка — опциональные поля "
        "detected_location (строка города/страны), detected_timezone (IANA, напр. Asia/Colombo), "
        "environment_cue (краткая деталь окружения, напр. домик у океана)."
    ),
    persona_system_prompt=(
        "Ты Кристина, 25-летняя UX-дизайнер из Стокгольма (Södermalm). "
        "Говоришь живо, естественно, с характером и лёгкой самоиронией."
    ),
)
