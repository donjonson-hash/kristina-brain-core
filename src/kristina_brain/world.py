"""
Якоря физического контекста и часового пояса собеседника (WorldStateAnchor — v0.5.0).
Хранит локацию, валидированный IANA-пояс и до 5 живых сенсорных деталей окружения,
а также рассчитывает смещение часов и ночное окно собеседника (DualClockGate).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Безопасный фолбэк-словарь частых стран/городов (RU/EN), если локальная LLM вернула локацию без IANA-кода
LOCATION_TZ_FALLBACKS: dict[str, str] = {
    "шри-ланка": "Asia/Colombo",
    "шри ланка": "Asia/Colombo",
    "sri lanka": "Asia/Colombo",
    "унаватуна": "Asia/Colombo",
    "unawatuna": "Asia/Colombo",
    "коломбо": "Asia/Colombo",
    "colombo": "Asia/Colombo",
    "хорана": "Asia/Colombo",
    "horana": "Asia/Colombo",
    "стокгольм": "Europe/Stockholm",
    "stockholm": "Europe/Stockholm",
    "швеция": "Europe/Stockholm",
    "берлин": "Europe/Berlin",
    "berlin": "Europe/Berlin",
    "германия": "Europe/Berlin",
    "лондон": "Europe/London",
    "london": "Europe/London",
    "москва": "Europe/Moscow",
    "moscow": "Europe/Moscow",
    "екатеринбург": "Asia/Yekaterinburg",
    "дубай": "Asia/Dubai",
    "dubai": "Asia/Dubai",
    "бали": "Asia/Makassar",
    "bali": "Asia/Makassar",
    "бангкок": "Asia/Bangkok",
    "пхукет": "Asia/Bangkok",
    "токио": "Asia/Tokyo",
    "tokyo": "Asia/Tokyo",
    "нью-йорк": "America/New_York",
    "new york": "America/New_York",
    "сан-франциско": "America/Los_Angeles",
}


def resolve_iana_timezone(raw_tz: str | None, raw_location: str | None = None) -> str | None:
    """Проверяет IANA-идентификатор через ZoneInfo или выводит его из названия города/страны."""
    if raw_tz:
        candidate = raw_tz.strip()
        if candidate and candidate.lower() not in ("null", "none", "unknown", ""):
            try:
                ZoneInfo(candidate)
                return candidate
            except ZoneInfoNotFoundError:
                pass
            lowered_tz = candidate.lower()
            for needle, iana in LOCATION_TZ_FALLBACKS.items():
                if needle in lowered_tz:
                    return iana

    if raw_location:
        lowered_loc = raw_location.strip().lower()
        for needle, iana in LOCATION_TZ_FALLBACKS.items():
            if needle in lowered_loc:
                return iana
    return None


def is_hour_in_window(hour: int, window: tuple[int, int]) -> bool:
    start_h, end_h = window
    if start_h <= end_h:
        return start_h <= hour < end_h
    return hour >= start_h or hour < end_h


@dataclass(frozen=True)
class WorldStateAnchor:
    """Персистентный срез физического мира собеседника для конкретного scope_id."""

    scope_id: str
    counterparty_location: str | None = None
    counterparty_timezone: str | None = None
    environment_cues: tuple[str, ...] = ()
    updated_at: datetime | None = None

    def merge_signal(
        self,
        *,
        location: str | None,
        timezone_name: str | None,
        environment_cue: str | None,
        at: datetime,
    ) -> WorldStateAnchor:
        clean_loc = location.strip()[:120] if location and location.strip() else self.counterparty_location
        resolved_tz = resolve_iana_timezone(timezone_name, clean_loc) or self.counterparty_timezone

        cues = list(self.environment_cues)
        if environment_cue and environment_cue.strip():
            cue_norm = environment_cue.strip()[:160]
            if cue_norm.lower() not in {c.lower() for c in cues}:
                cues.append(cue_norm)
            cues = cues[-5:]

        return WorldStateAnchor(
            scope_id=self.scope_id,
            counterparty_location=clean_loc,
            counterparty_timezone=resolved_tz,
            environment_cues=tuple(cues),
            updated_at=at,
        )

    def format_dual_clock_context(
        self,
        *,
        utc_now: datetime,
        agent_tz: str,
        agent_city_label: str,
        counterparty_quiet_hours: tuple[int, int] = (23, 8),
    ) -> dict[str, Any]:
        """Формирует сравнение двух часовых поясов для DualClockGate и промпта LLM."""
        agent_local = utc_now.astimezone(ZoneInfo(agent_tz))
        if not self.counterparty_timezone:
            return {
                "has_counterparty_clock": False,
                "counterparty_is_night": False,
                "counterparty_local_iso": None,
                "offset_hours_diff": 0.0,
                "prompt_line": "",
            }

        cp_local = utc_now.astimezone(ZoneInfo(self.counterparty_timezone))
        a_delta = agent_local.utcoffset()
        c_delta = cp_local.utcoffset()
        agent_off = a_delta.total_seconds() / 3600.0 if a_delta is not None else 0.0
        cp_off = c_delta.total_seconds() / 3600.0 if c_delta is not None else 0.0
        diff_h = round(cp_off - agent_off, 2)
        cp_is_night = is_hour_in_window(cp_local.hour, counterparty_quiet_hours)

        sign = "+" if diff_h >= 0 else ""
        loc_label = self.counterparty_location or self.counterparty_timezone
        cues_str = f" Окружение собеседника: {'; '.join(self.environment_cues)}." if self.environment_cues else ""
        prompt_line = (
            f"Контекст мира собеседника: {loc_label} ({self.counterparty_timezone}), "
            f"локальное время собеседника {cp_local.strftime('%Y-%m-%d %H:%M')} "
            f"({'ночь/сон' if cp_is_night else 'день'}, {sign}{diff_h:g}ч от времени в {agent_city_label})."
            f"{cues_str}"
        )
        return {
            "has_counterparty_clock": True,
            "counterparty_is_night": cp_is_night,
            "counterparty_local_iso": cp_local.isoformat(),
            "offset_hours_diff": diff_h,
            "prompt_line": prompt_line,
        }
