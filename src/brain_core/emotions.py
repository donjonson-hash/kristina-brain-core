"""
Неблокирующее быстрое эмоциональное ядро AsyncEmotionalCore.
- Сохраняет доменную физику 7 параметров состояния (energy, happiness, curiosity, anxiety,
  loneliness, creativity, irritation), Big Five и криптографическую идемпотентность SHA-256.
- Полностью отвязано от синхронного sqlite3, threading.RLock и хардкода Europe/Stockholm.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from .clock import ClockProvider, SystemClock
from .profile import DEFAULT_KRISTINA_PROFILE, PersonaProfile
from .state_store import StateStore

FAST_STATE_KEYS = (
    "energy",
    "happiness",
    "curiosity",
    "anxiety",
    "loneliness",
    "creativity",
    "irritation",
)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, round(float(value), 4)))


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class EmotionalEvent:
    """Идемпотентный ключ события сообщения (совместим с emotional_core.EmotionalEvent)."""

    session_sha256: str
    event_id: str
    input_sha256: str

    @classmethod
    def from_message(cls, session_id: str, event_id: str, user_input: str) -> EmotionalEvent:
        if not str(session_id).strip() or not str(event_id).strip():
            raise ValueError("session_id and event_id must be non-empty")
        return cls(
            session_sha256=_sha256_text(str(session_id)),
            event_id=str(event_id),
            input_sha256=_sha256_text(str(user_input)),
        )


REACTION_DELTAS: Mapping[str, Mapping[str, float]] = {
    "curiosity": {"curiosity": 0.16, "energy": 0.05, "loneliness": -0.08, "creativity": 0.07},
    "warmth": {"happiness": 0.15, "loneliness": -0.14, "anxiety": -0.08, "irritation": -0.08},
    "concern": {"anxiety": 0.12, "curiosity": 0.04, "happiness": -0.05, "loneliness": -0.04},
    "frustration": {"irritation": 0.18, "anxiety": 0.08, "happiness": -0.10, "energy": -0.05},
    "neutral": {"loneliness": -0.04, "curiosity": 0.02},
}


class AsyncEmotionalCore:
    """Асинхронное быстрое эмоциональное ядро для любого scope_id и профиля персоны."""

    def __init__(
        self,
        store: StateStore,
        *,
        profile: PersonaProfile = DEFAULT_KRISTINA_PROFILE,
        clock: ClockProvider | None = None,
    ) -> None:
        self.store = store
        self.profile = profile
        self.clock: ClockProvider = clock or SystemClock(profile.timezone)

    def _default_baseline_state(self) -> dict[str, float]:
        t = self.profile.traits
        return {
            "energy": _clamp01(0.55 + 0.15 * t.extraversion),
            "happiness": _clamp01(0.50 + 0.12 * t.agreeableness - 0.08 * t.neuroticism),
            "curiosity": _clamp01(0.48 + 0.22 * t.openness),
            "anxiety": _clamp01(0.18 + 0.25 * t.neuroticism),
            "loneliness": _clamp01(0.22 + 0.15 * t.extraversion),
            "creativity": _clamp01(0.45 + 0.25 * t.openness),
            "irritation": _clamp01(0.10 + 0.12 * t.neuroticism - 0.06 * t.agreeableness),
        }

    async def get_emotional_state(self, scope_id: str = "default") -> dict[str, Any]:
        stored = await self.store.load_fast_state(scope_id)
        local_now = self.clock.now_local(self.profile.timezone)
        utc_now = self.clock.now_utc()
        is_night = self.profile.is_night_at(local_now.hour)

        if stored and "state" in stored:
            vec = {k: _clamp01(stored["state"].get(k, 0.5)) for k in FAST_STATE_KEYS}
            updated_at = stored.get("updated_at", utc_now.isoformat())
            recent = list(stored.get("recent_experiences", []))[-10:]
        else:
            vec = self._default_baseline_state()
            updated_at = utc_now.isoformat()
            recent = []

        dominant_emotion = max(vec, key=lambda k: vec[k])
        dominant_value = vec[dominant_emotion]

        return {
            "scope_id": scope_id,
            "state": vec,
            "traits": self.profile.traits.to_dict(),
            "dominant_emotion": dominant_emotion,
            "dominant_value": dominant_value,
            "mood_description": self._describe_mood(vec, is_night=is_night),
            "for_llm": self._format_for_llm(vec, is_night=is_night, local_now=local_now),
            "updated_at": updated_at,
            "is_night": is_night,
            "timezone": self.profile.timezone,
            "recent_experiences": recent,
        }

    async def evolve(
        self,
        scope_id: str = "default",
        context: Mapping[str, Any] | None = None,
        *,
        reaction: str | None = None,
        intensity: float = 0.5,
        reflection: str | None = None,
        event: EmotionalEvent | None = None,
    ) -> dict[str, Any]:
        """
        Эволюционирует 7 быстрых параметров с учётом:
        1) времени с прошлого обновления (гомеостатический возврат к baseline + рост loneliness при молчании),
        2) циркадного окна ночи из PersonaProfile,
        3) когнитивной оценки входящего стимула (reaction + intensity),
        4) атомарной дедупликации по EmotionalEvent.
        """
        current = await self.get_emotional_state(scope_id)
        vec = dict(current["state"])
        baseline = self._default_baseline_state()
        utc_now = self.clock.now_utc()
        local_now = self.clock.now_local(self.profile.timezone)
        is_night = self.profile.is_night_at(local_now.hour)

        prev_dt = datetime.fromisoformat(str(current["updated_at"]))
        if prev_dt.tzinfo is None:
            prev_dt = prev_dt.replace(tzinfo=UTC)
        elapsed_hours = max(0.0, (utc_now - prev_dt.astimezone(UTC)).total_seconds() / 3600.0)

        # 1. Мягкая релаксация к личностному baseline (скорость ~12% в час)
        relax_factor = min(0.65, elapsed_hours * 0.12)
        if relax_factor > 0:
            for k in FAST_STATE_KEYS:
                vec[k] = _clamp01(vec[k] + (baseline[k] - vec[k]) * relax_factor)

        # 2. Естественная динамика паузы контакта и циркадного ритма
        hours_since_contact = float((context or {}).get("hours_since_contact", elapsed_hours))
        if hours_since_contact > 2.0:
            loneliness_drift = min(0.25, (hours_since_contact - 2.0) * 0.02 * self.profile.traits.extraversion)
            vec["loneliness"] = _clamp01(vec["loneliness"] + loneliness_drift)

        if is_night:
            vec["energy"] = _clamp01(vec["energy"] - 0.06)
            vec["creativity"] = _clamp01(vec["creativity"] + 0.03)

        # 3. Применение входящей когнитивной реакции
        recent = list(current.get("recent_experiences", []))
        if reaction:
            norm_reaction = reaction if reaction in REACTION_DELTAS else "neutral"
            scaled = max(0.05, min(1.0, float(intensity)))
            for param, delta in REACTION_DELTAS[norm_reaction].items():
                vec[param] = _clamp01(vec[param] + delta * scaled)
            if reflection:
                recent.append(
                    {
                        "at": utc_now.isoformat(),
                        "reaction": norm_reaction,
                        "intensity": round(scaled, 3),
                        "reflection": str(reflection)[:200],
                    }
                )
                recent = recent[-10:]

        payload = {
            "state": vec,
            "updated_at": utc_now.isoformat(),
            "recent_experiences": recent,
        }
        event_tuple = (
            (event.session_sha256, event.event_id, event.input_sha256, utc_now.isoformat())
            if event is not None
            else None
        )

        applied = await self.store.save_fast_state_atomic(
            scope_id,
            payload,
            event_tuple=event_tuple,
        )
        result = await self.get_emotional_state(scope_id)
        result["event_applied"] = applied
        return result

    async def record_experiment(self, experiment_id: str, outcome: str, *, scope_id: str = "default") -> bool:
        utc_now = self.clock.now_utc().isoformat()
        inserted = await self.store.record_experiment_once(scope_id, experiment_id, outcome, utc_now)
        if inserted:
            delta_reaction = "curiosity" if outcome == "success" else "concern"
            await self.evolve(scope_id, reaction=delta_reaction, intensity=0.35)
        return inserted

    def _describe_mood(self, vec: Mapping[str, float], *, is_night: bool) -> str:
        if is_night and vec["energy"] < 0.4:
            return "сонная, спокойная ночная атмосфера"
        if vec["irritation"] > 0.6:
            return "напряжённая, раздражённая"
        if vec["happiness"] > 0.68 and vec["energy"] > 0.6:
            return "тёплая, энергичная и вовлечённая"
        if vec["curiosity"] > 0.65:
            return "живой исследовательский интерес"
        if vec["loneliness"] > 0.6:
            return "нехватка общения, желание написать"
        return "ровное, естественное рабочее состояние"

    def _format_for_llm(self, vec: Mapping[str, float], *, is_night: bool, local_now: datetime) -> str:
        return (
            f"Локальное время ({self.profile.locale_city_label}): {local_now.strftime('%Y-%m-%d %H:%M')} "
            f"({'ночь' if is_night else 'день'}). "
            f"Состояние: energy={vec['energy']:.2f}, happiness={vec['happiness']:.2f}, "
            f"curiosity={vec['curiosity']:.2f}, anxiety={vec['anxiety']:.2f}, "
            f"loneliness={vec['loneliness']:.2f}, creativity={vec['creativity']:.2f}, "
            f"irritation={vec['irritation']:.2f}."
        )
