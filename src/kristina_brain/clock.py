"""
Параметризованный провайдер времени и часовых поясов (закрытие AUD-06).
Убирает жёсткий хардкод ZoneInfo("Europe/Stockholm") из emotional_core и cognitive_appraisal.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo


@runtime_checkable
class ClockProvider(Protocol):
    """Контракт источника времени для детерминированных replay-тестов и мультитенантных часовых поясов."""

    def now_utc(self) -> datetime:
        """Текущий момент в UTC (aware datetime)."""
        ...

    def now_local(self, tz_name: str = "UTC") -> datetime:
        """Текущий момент в целевом часовом поясе агента или пользователя."""
        ...


class SystemClock:
    """Продакшен-источник системного времени."""

    def __init__(self, default_tz: str = "UTC") -> None:
        self.default_tz = default_tz
        ZoneInfo(default_tz)  # Валидируем IANA-идентификатор при старте (fail-fast)

    def now_utc(self) -> datetime:
        return datetime.now(UTC)

    def now_local(self, tz_name: str | None = None) -> datetime:
        target = ZoneInfo(tz_name or self.default_tz)
        return self.now_utc().astimezone(target)


class FixedClock:
    """Детерминированные часы для unit/replay-тестирования периодов полураспада и кулдаунов."""

    def __init__(self, fixed_utc: datetime, default_tz: str = "UTC") -> None:
        if fixed_utc.tzinfo is None:
            fixed_utc = fixed_utc.replace(tzinfo=UTC)
        self._current_utc = fixed_utc.astimezone(UTC)
        self.default_tz = default_tz
        ZoneInfo(default_tz)

    def advance(self, *, seconds: float = 0.0, minutes: float = 0.0, hours: float = 0.0) -> datetime:
        from datetime import timedelta

        self._current_utc = self._current_utc + timedelta(
            seconds=seconds,
            minutes=minutes,
            hours=hours,
        )
        return self._current_utc

    def set_utc(self, new_utc: datetime) -> None:
        if new_utc.tzinfo is None:
            new_utc = new_utc.replace(tzinfo=UTC)
        self._current_utc = new_utc.astimezone(UTC)

    def now_utc(self) -> datetime:
        return self._current_utc

    def now_local(self, tz_name: str | None = None) -> datetime:
        target = ZoneInfo(tz_name or self.default_tz)
        return self._current_utc.astimezone(target)
