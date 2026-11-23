"""
Ночная консолидация памяти, пластичность синапсов и семена снов (SleepConsolidationWorker — v1.1.0).
Запускается без LLM и выполняет три фундаментальных процесса развития организма:
1. Трёхфакторное правило Хебба (Pre × Post × Reward × DA) на синапсах с активным eligibility_trace.
2. Медленный пластичный сдвиг baseline 12 мод (±0.015 за ночь) в сторону прожитого опыта.
3. Синтез ассоциативного семени сновидения (DreamSeed) из активных мод, сенсорных якорей и черновиков.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from .clock import ClockProvider, SystemClock
from .neuro import NeuromodulatorField, SynapseEdge, SynapticGraphEngine, _clamp

if TYPE_CHECKING:
    from .modes import AsyncOrganismModes
    from .state_store import StateStore


@dataclass(frozen=True)
class DreamSeed:
    """Субсимвольная заготовка ночного сна для последующего литературного раскрытия писателем-агентом."""

    dominant_themes: tuple[str, ...]
    sensory_fragments: tuple[str, ...]
    creative_draft_bridge: str | None
    vividness: float


@dataclass(frozen=True)
class SleepConsolidationReport:
    scope_id: str
    consolidated_at: datetime
    synapses_adjusted: int
    synapse_deltas: dict[str, float]
    modes_drifted: int
    baseline_deltas: dict[str, float]
    dream_seed: DreamSeed | None


class SleepConsolidationWorker:
    """Ночной интегратор опыта для самообучения синапсов и воображения (снов)."""

    MAX_NIGHTLY_BASELINE_DRIFT = 0.015

    def __init__(
        self,
        store: StateStore,
        synaptic_engine: SynapticGraphEngine,
        modes_engine: AsyncOrganismModes,
        *,
        clock: ClockProvider | None = None,
    ) -> None:
        self.store = store
        self.synaptic_engine = synaptic_engine
        self.modes_engine = modes_engine
        self.clock: ClockProvider = clock or SystemClock("UTC")

    async def consolidate(
        self,
        scope_id: str = "default",
        *,
        reward_signal: float = 0.0,
        chem: NeuromodulatorField | None = None,
        at: datetime | None = None,
    ) -> SleepConsolidationReport:
        """Публичная точка входа: сериализует сонную консолидацию по scope_id с импульсами."""
        async with self.synaptic_engine._lock_for(scope_id):
            return await self._consolidate_unlocked(
                scope_id, reward_signal=reward_signal, chem=chem, at=at
            )

    async def _consolidate_unlocked(
        self,
        scope_id: str = "default",
        *,
        reward_signal: float = 0.0,
        chem: NeuromodulatorField | None = None,
        at: datetime | None = None,
    ) -> SleepConsolidationReport:
        now = (at or self.clock.now_utc()).astimezone(UTC)
        bounded_reward = max(-1.0, min(1.0, float(reward_signal)))
        da_gain = 0.5 + 0.5 * (chem.dopamine if chem is not None else 0.5)

        # 1. Трёхфакторная пластичность синапсов (врождённые рефлексы с plasticity=0 неприкосновенны!)
        neurons, synapses = await self.synaptic_engine.ensure_circuit(scope_id, at=now)
        synapse_deltas: dict[str, float] = {}
        new_synapses: dict[str, SynapseEdge] = {}

        for key, syn in synapses.items():
            if syn.plasticity > 0.0 and syn.eligibility_trace >= 0.01 and abs(bounded_reward) > 1e-6:
                raw_dw = syn.plasticity * bounded_reward * syn.eligibility_trace * (1.0 - abs(syn.weight)) * da_gain
                new_w = _clamp(syn.weight + raw_dw, -1.0, 1.0)
                actual_dw = round(new_w - syn.weight, 5)
                if abs(actual_dw) > 1e-6:
                    synapse_deltas[key] = actual_dw
                new_synapses[key] = SynapseEdge(
                    source_id=syn.source_id,
                    target_id=syn.target_id,
                    weight=new_w,
                    plasticity=syn.plasticity,
                    eligibility_trace=round(syn.eligibility_trace * 0.25, 5),
                    trace_half_life_hours=syn.trace_half_life_hours,
                    updated_at=now,
                )
            else:
                new_synapses[key] = SynapseEdge(
                    source_id=syn.source_id,
                    target_id=syn.target_id,
                    weight=syn.weight,
                    plasticity=syn.plasticity,
                    eligibility_trace=round(syn.eligibility_trace * 0.5, 5),
                    trace_half_life_hours=syn.trace_half_life_hours,
                    updated_at=now,
                )

        await self.synaptic_engine._persist(scope_id, neurons, new_synapses, now)

        # 2. Медленный гомеостатический дрейф baseline 12 мод (характер меняется от прожитого!)
        snap = await self.modes_engine.relax_to_baseline(scope_id, at=now)
        baseline_deltas: dict[str, float] = {}
        updated_mode_rows: list[dict[str, Any]] = []

        for name, st in snap.items():
            dev = st.amplitude - st.baseline
            if abs(dev) >= 0.015:
                drift = max(
                    -self.MAX_NIGHTLY_BASELINE_DRIFT,
                    min(self.MAX_NIGHTLY_BASELINE_DRIFT, dev * 0.05),
                )
                new_base = _clamp(st.baseline + drift, 0.02, 0.92)
                actual_b_delta = round(new_base - st.baseline, 5)
                if abs(actual_b_delta) >= 1e-5:
                    baseline_deltas[name] = actual_b_delta
                    updated_mode_rows.append(
                        {
                            "name": name,
                            "baseline": new_base,
                            "amplitude": st.amplitude,
                            "phase": st.phase,
                            "half_life_hours": st.half_life_hours,
                            "updated_at": now.isoformat(),
                        }
                    )

        if updated_mode_rows:
            await self.store.upsert_modes_atomic(scope_id, updated_mode_rows)

        # 3. REM-фаза: сборка семени сновидения (сплетение доминирующих мод, мира собеседника и черновиков)
        dream_seed: DreamSeed | None = None
        creativity_amp = snap["creativity_357"].amplitude if "creativity_357" in snap else 0.22
        aesthetic_amp = snap["aesthetic_drive"].amplitude if "aesthetic_drive" in snap else 0.25
        vividness = _clamp(0.50 * creativity_amp + 0.30 * aesthetic_amp + 0.20 * (chem.dopamine if chem else 0.5))

        if vividness >= 0.22:
            top_modes = sorted(snap.values(), key=lambda m: (-abs(m.deviation), -m.amplitude))[:2]
            anchor = await self.store.get_world_anchor(scope_id)
            artifacts = await self.store.list_artifacts(scope_id, limit=1)
            sensory_list = list(anchor.environment_cues[:3])
            if anchor.counterparty_location and anchor.counterparty_location not in sensory_list:
                sensory_list.insert(0, anchor.counterparty_location)
            bridge = f"{artifacts[0].title}: {artifacts[0].excerpt[:120]}" if artifacts else None
            dream_seed = DreamSeed(
                dominant_themes=tuple(m.name for m in top_modes),
                sensory_fragments=tuple(sensory_list),
                creative_draft_bridge=bridge,
                vividness=round(vividness, 4),
            )

        return SleepConsolidationReport(
            scope_id=scope_id,
            consolidated_at=now,
            synapses_adjusted=len(synapse_deltas),
            synapse_deltas=synapse_deltas,
            modes_drifted=len(baseline_deltas),
            baseline_deltas=baseline_deltas,
            dream_seed=dream_seed,
        )
