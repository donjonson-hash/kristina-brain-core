"""
Асинхронный движок 12 медленных внутренних мод организма AsyncOrganismModes.
- Сохраняет точный набор из 12 мод репозитория kristina-revolutionary с baseline и half_life_hours.
- Реализует экспоненциальное затухание амплитуды к baseline: A(t) = B + (A0 - B) * 0.5^(dt / half_life).
- Формирует OrganismProjection для передачи в DesireEngine (как в shadow-режиме, так и в активном режиме).
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from .clock import ClockProvider, SystemClock
from .profile import ModeSpec
from .state_store import StateStore


@dataclass(frozen=True)
class ModeDefinition:
    baseline: float
    half_life_hours: float


@dataclass(frozen=True)
class ModeState:
    name: str
    baseline: float
    amplitude: float
    phase: float
    half_life_hours: float
    updated_at: datetime

    @property
    def deviation(self) -> float:
        return round(self.amplitude - self.baseline, 4)


@dataclass(frozen=True)
class OrganismProjection:
    """Проекция 12 медленных мод на вектор желаний (talk, share, ask, be_alone)."""

    talk_bias: float
    share_bias: float
    ask_bias: float
    be_alone_bias: float
    mode_deviations: Mapping[str, float]
    shifted_modes: tuple[str, ...]


# Канонические 12 мод из organism_modes.py
DEFAULT_MODE_DEFINITIONS: Mapping[str, ModeDefinition] = {
    "core_741": ModeDefinition(baseline=0.60, half_life_hours=168.0),
    "aesthetic_drive": ModeDefinition(baseline=0.25, half_life_hours=336.0),
    "empathy_963": ModeDefinition(baseline=0.35, half_life_hours=96.0),
    "validation_need": ModeDefinition(baseline=0.30, half_life_hours=72.0),
    "social_overload": ModeDefinition(baseline=0.15, half_life_hours=18.0),
    "withdrawal_147": ModeDefinition(baseline=0.20, half_life_hours=36.0),
    "creativity_357": ModeDefinition(baseline=0.22, half_life_hours=48.0),
    "agency_exec": ModeDefinition(baseline=0.30, half_life_hours=96.0),
    "invisibility_wound": ModeDefinition(baseline=0.18, half_life_hours=240.0),
    "abandonment_wound": ModeDefinition(baseline=0.12, half_life_hours=336.0),
    "self_critique": ModeDefinition(baseline=0.20, half_life_hours=72.0),
    "crisis_957": ModeDefinition(baseline=0.08, half_life_hours=24.0),
}

# Отображение реакций/видов событий на сдвиги медленных мод
EVENT_KIND_DELTAS: Mapping[str, Mapping[str, float]] = {
    "warmth": {
        "empathy_963": 0.08,
        "abandonment_wound": -0.08,
        "invisibility_wound": -0.06,
        "withdrawal_147": -0.08,
        "crisis_957": -0.06,
    },
    "curiosity": {"creativity_357": 0.05, "agency_exec": 0.04, "aesthetic_drive": 0.03},
    "concern": {"empathy_963": 0.05, "crisis_957": 0.04, "self_critique": 0.03},
    "frustration": {"social_overload": 0.12, "withdrawal_147": 0.14, "crisis_957": 0.12, "abandonment_wound": 0.10},
    "ignored_outreach": {"invisibility_wound": 0.08, "withdrawal_147": 0.06, "validation_need": 0.04},
    "dense_burst": {"social_overload": 0.10, "withdrawal_147": 0.05},
    "neutral": {"social_overload": 0.01},
}


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, round(float(v), 5)))


def _decay_towards_baseline(amplitude: float, baseline: float, elapsed_hours: float, half_life_hours: float) -> float:
    if elapsed_hours <= 0.0:
        return _clamp01(amplitude)
    decay = math.pow(0.5, elapsed_hours / half_life_hours)
    return _clamp01(baseline + (amplitude - baseline) * decay)


class AsyncOrganismModes:
    """Неблокирующее управление 12 медленными модами в StateStore."""

    def __init__(
        self,
        store: StateStore,
        *,
        clock: ClockProvider | None = None,
        custom_specs: Mapping[str, ModeSpec] | None = None,
    ) -> None:
        self.store = store
        self.clock: ClockProvider = clock or SystemClock("UTC")
        merged: dict[str, ModeDefinition] = dict(DEFAULT_MODE_DEFINITIONS)
        if custom_specs:
            for name, spec in custom_specs.items():
                merged[name] = ModeDefinition(baseline=spec.baseline, half_life_hours=spec.half_life_hours)
        self.definitions: Mapping[str, ModeDefinition] = merged

    async def ensure_defaults(self, scope_id: str = "default", at: datetime | None = None) -> int:
        now = (at or self.clock.now_utc()).astimezone(UTC)
        existing = await self.store.load_modes(scope_id)
        missing = []
        for name, defn in self.definitions.items():
            if name not in existing:
                missing.append(
                    {
                        "name": name,
                        "baseline": defn.baseline,
                        "amplitude": defn.baseline,
                        "phase": 0.0,
                        "half_life_hours": defn.half_life_hours,
                        "updated_at": now.isoformat(),
                    }
                )
        if missing:
            await self.store.upsert_modes_atomic(scope_id, missing)
        return len(missing)

    async def relax_to_baseline(
        self,
        scope_id: str = "default",
        at: datetime | None = None,
    ) -> dict[str, ModeState]:
        await self.ensure_defaults(scope_id, at=at)
        now = (at or self.clock.now_utc()).astimezone(UTC)
        raw_map = await self.store.load_modes(scope_id)
        updates: list[dict[str, object]] = []
        result: dict[str, ModeState] = {}

        for name, row in raw_map.items():
            prev_dt = datetime.fromisoformat(str(row["updated_at"]))
            if prev_dt.tzinfo is None:
                prev_dt = prev_dt.replace(tzinfo=UTC)
            dt_hours = max(0.0, (now - prev_dt.astimezone(UTC)).total_seconds() / 3600.0)
            new_amp = _decay_towards_baseline(
                float(row["amplitude"]),
                float(row["baseline"]),
                dt_hours,
                float(row["half_life_hours"]),
            )
            state = ModeState(
                name=name,
                baseline=float(row["baseline"]),
                amplitude=new_amp,
                phase=float(row["phase"]),
                half_life_hours=float(row["half_life_hours"]),
                updated_at=now,
            )
            result[name] = state
            if dt_hours > 0.0:
                updates.append(
                    {
                        "name": name,
                        "baseline": state.baseline,
                        "amplitude": state.amplitude,
                        "phase": state.phase,
                        "half_life_hours": state.half_life_hours,
                        "updated_at": now.isoformat(),
                    }
                )

        if updates:
            await self.store.upsert_modes_atomic(scope_id, updates)
        return result

    async def snapshot(self, scope_id: str = "default") -> dict[str, ModeState]:
        return await self.relax_to_baseline(scope_id)

    async def snapshot_readonly(
        self, scope_id: str = "default", at: datetime | None = None
    ) -> dict[str, ModeState]:
        """Read-only снимок мод: decay амплитуд считается в памяти.

        Ничего не пишет и не сеет строки: отсутствующие моды показываются со
        значением baseline. Используется публичными GET-снимками обсерватории,
        чтобы чтение не мутировало состояние."""
        now = (at or self.clock.now_utc()).astimezone(UTC)
        raw_map = await self.store.load_modes(scope_id)
        result: dict[str, ModeState] = {}
        for name, defn in self.definitions.items():
            row = raw_map.get(name)
            if row is None:
                result[name] = ModeState(
                    name=name,
                    baseline=defn.baseline,
                    amplitude=defn.baseline,
                    phase=0.0,
                    half_life_hours=defn.half_life_hours,
                    updated_at=now,
                )
                continue
            prev_dt = datetime.fromisoformat(str(row["updated_at"]))
            if prev_dt.tzinfo is None:
                prev_dt = prev_dt.replace(tzinfo=UTC)
            dt_hours = max(0.0, (now - prev_dt.astimezone(UTC)).total_seconds() / 3600.0)
            new_amp = _decay_towards_baseline(
                float(row["amplitude"]),
                float(row["baseline"]),
                dt_hours,
                float(row["half_life_hours"]),
            )
            result[name] = ModeState(
                name=name,
                baseline=float(row["baseline"]),
                amplitude=new_amp,
                phase=float(row["phase"]),
                half_life_hours=float(row["half_life_hours"]),
                updated_at=now,
            )
        return result

    async def dominant(self, scope_id: str = "default", limit: int = 3) -> list[ModeState]:
        snap = await self.snapshot(scope_id)
        ranked = sorted(snap.values(), key=lambda m: abs(m.deviation), reverse=True)
        return ranked[: max(1, limit)]

    async def apply_message_event(
        self,
        *,
        scope_id: str = "default",
        session_sha256: str,
        event_id: str,
        input_sha256: str,
        kinds: Sequence[str],
        at: datetime | None = None,
    ) -> bool:
        now = (at or self.clock.now_utc()).astimezone(UTC)
        snap = await self.relax_to_baseline(scope_id, at=now)

        combined_deltas: dict[str, float] = {}
        for kind in kinds:
            for mode_name, d_val in EVENT_KIND_DELTAS.get(kind, {}).items():
                if mode_name in snap:
                    combined_deltas[mode_name] = round(combined_deltas.get(mode_name, 0.0) + d_val, 5)

        deltas_json = json.dumps(combined_deltas, sort_keys=True)
        payload_hash = hashlib.sha256(f"{input_sha256}:{deltas_json}".encode()).hexdigest()

        updated_rows = []
        for name, st in snap.items():
            delta = combined_deltas.get(name, 0.0)
            if delta != 0.0:
                updated_rows.append(
                    {
                        "name": name,
                        "baseline": st.baseline,
                        "amplitude": _clamp01(st.amplitude + delta),
                        "phase": st.phase,
                        "half_life_hours": st.half_life_hours,
                        "updated_at": now.isoformat(),
                    }
                )

        return await self.store.upsert_modes_atomic(
            scope_id,
            updated_rows,
            mode_event=(session_sha256, event_id, payload_hash, deltas_json, now.isoformat()),
        )

    async def project(self, scope_id: str = "default", at: datetime | None = None) -> OrganismProjection:
        """Строит проекцию отклонений 12 медленных мод на оси проактивного выбора."""
        snap = await self.relax_to_baseline(scope_id, at=at)
        devs = {name: st.deviation for name, st in snap.items()}

        def d(key: str) -> float:
            return devs.get(key, 0.0)

        # Конфликтно-защитный тормоз (долгая память ссоры через abandonment_wound t1/2=336h + withdrawal_147)
        conflict_brake = (
            1.15 * max(0.0, d("social_overload"))
            + 1.35 * max(0.0, d("withdrawal_147"))
            + 1.40 * max(0.0, d("crisis_957"))
            + 1.60 * max(0.0, d("abandonment_wound"))
        )
        rapport_boost = 0.85 * max(0.0, d("empathy_963")) + 0.55 * max(0.0, d("agency_exec"))

        talk_bias = round(rapport_boost + 0.25 * d("validation_need") - conflict_brake, 4)
        share_bias = round(
            0.65 * d("creativity_357")
            + 0.45 * d("aesthetic_drive")
            + 0.45 * d("agency_exec")
            - 0.45 * d("self_critique")
            - 0.85 * conflict_brake,
            4,
        )
        ask_bias = round(
            0.60 * d("agency_exec") + 0.50 * d("empathy_963") - 0.55 * d("invisibility_wound") - 0.90 * conflict_brake,
            4,
        )
        be_alone_bias = round(conflict_brake + 0.35 * max(0.0, d("invisibility_wound")), 4)

        shifted = tuple(sorted(name for name, val in devs.items() if abs(val) >= 0.03))
        return OrganismProjection(
            talk_bias=talk_bias,
            share_bias=share_bias,
            ask_bias=ask_bias,
            be_alone_bias=be_alone_bias,
            mode_deviations=devs,
            shifted_modes=shifted,
        )
