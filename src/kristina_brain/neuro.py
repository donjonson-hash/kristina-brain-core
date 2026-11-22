"""
Субсимвольная нейронно-синаптическая сеть и поле 5 нейромедиаторов (SynapticGraphEngine — v1.1.0).
Работает за <1 мс с нулевым расходом LLM-токенов:
- Сенсорные и вставочные нейроны интегрируют импульсы с экспоненциальной утечкой потенциала.
- Возбуждающие (w > 0) и тормозные (w < 0) синапсы хранят след пригодности (eligibility_trace) для обучения.
- 5 нейромедиаторов (DA, NE, 5HT, OX, GABA) глобально сдвигают пороги моторных шлюзов.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

from .clock import ClockProvider, SystemClock
from .modes import ModeState

if TYPE_CHECKING:
    from .state_store import StateStore

NeuronKind = Literal["sensory", "inter", "motor_gate"]


def _clamp(val: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, round(float(val), 5)))


@dataclass(frozen=True)
class NeuromodulatorField:
    """Глобальный химический фон сети из 5 нейромедиаторов (все в диапазоне [0.0, 1.0])."""

    dopamine: float  # DA: исследовательский драйв, новизна, скорость обучения
    noradrenaline: float  # NE: собранность, срочность, фокус на инцидентах
    serotonin: float  # 5HT: эмоциональная устойчивость, плавность реакций
    oxytocin: float  # OX: глубина доверия и раппорта с собеседником
    gaba: float  # GABA: глобальное торможение, тишина и защита границ

    @classmethod
    def from_brain_state(
        cls,
        fast_state: Mapping[str, Any],
        mode_states: Mapping[str, ModeState],
        *,
        is_quiet_hours: bool = False,
    ) -> NeuromodulatorField:
        vec = fast_state.get("state", fast_state)
        energy = float(vec.get("energy", 0.5))
        happiness = float(vec.get("happiness", 0.5))
        curiosity = float(vec.get("curiosity", 0.5))
        anxiety = float(vec.get("anxiety", 0.2))
        irritation = float(vec.get("irritation", 0.1))

        def m_amp(name: str, default: float = 0.2) -> float:
            st = mode_states.get(name)
            return float(st.amplitude) if st is not None else default

        da = _clamp(0.45 * curiosity + 0.30 * m_amp("creativity_357") + 0.25 * m_amp("agency_exec"))
        ne = _clamp(0.42 * anxiety + 0.43 * m_amp("crisis_957", 0.08) + 0.25 * irritation + 0.10 * energy)
        serotonin = _clamp(0.50 * happiness + 0.35 * m_amp("core_741", 0.6) - 0.35 * irritation)
        ox = _clamp(
            0.65 * m_amp("empathy_963", 0.35)
            + 0.20 * happiness
            - 0.35 * m_amp("abandonment_wound", 0.12)
            - 0.25 * m_amp("invisibility_wound", 0.18)
        )
        gaba = _clamp(
            0.45 * m_amp("withdrawal_147", 0.20)
            + 0.40 * m_amp("social_overload", 0.15)
            + (0.45 if is_quiet_hours else 0.0)
        )
        return cls(
            dopamine=da,
            noradrenaline=ne,
            serotonin=serotonin,
            oxytocin=ox,
            gaba=gaba,
        )

    def to_dict(self) -> dict[str, float]:
        return {
            "DA": self.dopamine,
            "NE": self.noradrenaline,
            "5HT": self.serotonin,
            "OX": self.oxytocin,
            "GABA": self.gaba,
        }


@dataclass(frozen=True)
class NeuronNode:
    neuron_id: str
    kind: NeuronKind
    potential: float
    base_threshold: float
    leak_half_life_seconds: float
    refractory_seconds: float
    da_sensitivity: float = 0.20
    ox_sensitivity: float = 0.15
    gaba_sensitivity: float = 0.35
    ne_sensitivity: float = 0.10
    updated_at: datetime = datetime.fromtimestamp(0, tz=UTC)
    last_fired_at: datetime | None = None

    def effective_threshold(self, chem: NeuromodulatorField) -> float:
        shifted = (
            self.base_threshold
            - self.da_sensitivity * chem.dopamine
            - self.ox_sensitivity * chem.oxytocin
            + self.gaba_sensitivity * chem.gaba
            + self.ne_sensitivity * chem.noradrenaline
        )
        return _clamp(shifted, 0.15, 0.95)


@dataclass(frozen=True)
class SynapseEdge:
    source_id: str
    target_id: str
    weight: float  # [-1.0 .. +1.0]: >0 возбуждение, <0 торможение
    plasticity: float  # [0.0 .. 0.25]: 0.0 = жёсткий рефлекс безопасности
    eligibility_trace: float  # [0.0 .. 1.0]: след недавней передачи спайка
    trace_half_life_hours: float = 18.0
    updated_at: datetime = datetime.fromtimestamp(0, tz=UTC)

    @property
    def edge_key(self) -> str:
        return f"{self.source_id}->{self.target_id}"


@dataclass(frozen=True)
class SpikeEvent:
    neuron_id: str
    kind: NeuronKind
    amplitude: float
    effective_threshold: float
    fired_at: datetime


# Базовая эталонная микросхема агента (расширяется внешними проектами без форка ядра)
DEFAULT_NEURON_TEMPLATES: tuple[dict[str, Any], ...] = (
    # Сенсорный слой (0 токенов LLM)
    {
        "neuron_id": "sensor_warmth",
        "kind": "sensory",
        "base_threshold": 0.45,
        "leak_half_life_seconds": 900.0,
        "refractory_seconds": 5.0,
        "da_sensitivity": 0.10,
        "ox_sensitivity": 0.15,
        "gaba_sensitivity": 0.05,
        "ne_sensitivity": 0.0,
    },
    {
        "neuron_id": "sensor_curiosity",
        "kind": "sensory",
        "base_threshold": 0.45,
        "leak_half_life_seconds": 900.0,
        "refractory_seconds": 5.0,
        "da_sensitivity": 0.15,
        "ox_sensitivity": 0.05,
        "gaba_sensitivity": 0.05,
        "ne_sensitivity": 0.0,
    },
    {
        "neuron_id": "sensor_conflict",
        "kind": "sensory",
        "base_threshold": 0.40,
        "leak_half_life_seconds": 1800.0,
        "refractory_seconds": 2.0,
        "da_sensitivity": 0.0,
        "ox_sensitivity": 0.0,
        "gaba_sensitivity": 0.0,
        "ne_sensitivity": -0.15,
    },
    {
        "neuron_id": "sensor_silence_window",
        "kind": "sensory",
        "base_threshold": 0.50,
        "leak_half_life_seconds": 3600.0,
        "refractory_seconds": 60.0,
        "da_sensitivity": 0.10,
        "ox_sensitivity": 0.15,
        "gaba_sensitivity": 0.25,
        "ne_sensitivity": 0.0,
    },
    # Вставочный ассоциативный слой (0 токенов LLM)
    {
        "neuron_id": "inter_rapport_drive",
        "kind": "inter",
        "base_threshold": 0.52,
        "leak_half_life_seconds": 7200.0,
        "refractory_seconds": 30.0,
        "da_sensitivity": 0.18,
        "ox_sensitivity": 0.25,
        "gaba_sensitivity": 0.30,
        "ne_sensitivity": 0.10,
    },
    {
        "neuron_id": "inter_creative_spark",
        "kind": "inter",
        "base_threshold": 0.50,
        "leak_half_life_seconds": 10800.0,
        "refractory_seconds": 60.0,
        "da_sensitivity": 0.30,
        "ox_sensitivity": 0.10,
        "gaba_sensitivity": 0.20,
        "ne_sensitivity": 0.15,
    },
    # Моторные шлюзы (единственные узлы, дающие разрешение на вызов LLM или внешнее действие)
    {
        "neuron_id": "gate_proactive_outreach",
        "kind": "motor_gate",
        "base_threshold": 0.58,
        "leak_half_life_seconds": 3600.0,
        "refractory_seconds": 1800.0,
        "da_sensitivity": 0.20,
        "ox_sensitivity": 0.22,
        "gaba_sensitivity": 0.45,
        "ne_sensitivity": 0.15,
    },
    {
        "neuron_id": "gate_creative_imagination",
        "kind": "motor_gate",
        "base_threshold": 0.55,
        "leak_half_life_seconds": 7200.0,
        "refractory_seconds": 1800.0,
        "da_sensitivity": 0.32,
        "ox_sensitivity": 0.08,
        "gaba_sensitivity": 0.25,
        "ne_sensitivity": 0.20,
    },
    {
        "neuron_id": "gate_urgent_escalation",
        "kind": "motor_gate",
        "base_threshold": 0.62,
        "leak_half_life_seconds": 1800.0,
        "refractory_seconds": 300.0,
        "da_sensitivity": 0.0,
        "ox_sensitivity": 0.0,
        "gaba_sensitivity": 0.0,
        "ne_sensitivity": -0.30,
    },
)

DEFAULT_SYNAPSE_TEMPLATES: tuple[dict[str, Any], ...] = (
    # Обучаемые возбуждающие пути (plasticity > 0)
    {"source_id": "sensor_warmth", "target_id": "inter_rapport_drive", "weight": 0.72, "plasticity": 0.12},
    {"source_id": "sensor_silence_window", "target_id": "inter_rapport_drive", "weight": 0.55, "plasticity": 0.10},
    {"source_id": "inter_rapport_drive", "target_id": "gate_proactive_outreach", "weight": 0.78, "plasticity": 0.15},
    {"source_id": "sensor_curiosity", "target_id": "inter_creative_spark", "weight": 0.75, "plasticity": 0.14},
    {"source_id": "inter_creative_spark", "target_id": "gate_creative_imagination", "weight": 0.80, "plasticity": 0.15},
    # Врождённые тормозные и защитные рефлексы безопасности (plasticity = 0.0 -> не стираются!)
    {"source_id": "sensor_conflict", "target_id": "gate_proactive_outreach", "weight": -0.95, "plasticity": 0.0},
    {"source_id": "sensor_conflict", "target_id": "inter_rapport_drive", "weight": -0.80, "plasticity": 0.0},
    {"source_id": "sensor_conflict", "target_id": "gate_urgent_escalation", "weight": 0.88, "plasticity": 0.0},
)


def _decay_exp(val: float, dt_seconds: float, half_life_seconds: float) -> float:
    if dt_seconds <= 0.0 or val == 0.0:
        return val
    return val * math.pow(0.5, dt_seconds / max(1.0, half_life_seconds))


class SynapticGraphEngine:
    """Асинхронный менеджер нейронной микросхемы и синаптической передачи поверх StateStore."""

    def __init__(
        self,
        store: StateStore,
        *,
        clock: ClockProvider | None = None,
    ) -> None:
        self.store = store
        self.clock: ClockProvider = clock or SystemClock("UTC")

    async def ensure_circuit(
        self,
        scope_id: str = "default",
        *,
        initial_synapse_overrides: Mapping[str, float] | None = None,
        at: datetime | None = None,
    ) -> tuple[dict[str, NeuronNode], dict[str, SynapseEdge]]:
        now = (at or self.clock.now_utc()).astimezone(UTC)
        raw = await self.store.load_neural_graph(scope_id)

        if raw is None:
            neurons: dict[str, NeuronNode] = {}
            for nt in DEFAULT_NEURON_TEMPLATES:
                nid = str(nt["neuron_id"])
                neurons[nid] = NeuronNode(
                    neuron_id=nid,
                    kind=nt["kind"],
                    potential=0.05,
                    base_threshold=float(nt["base_threshold"]),
                    leak_half_life_seconds=float(nt["leak_half_life_seconds"]),
                    refractory_seconds=float(nt["refractory_seconds"]),
                    da_sensitivity=float(nt["da_sensitivity"]),
                    ox_sensitivity=float(nt["ox_sensitivity"]),
                    gaba_sensitivity=float(nt["gaba_sensitivity"]),
                    ne_sensitivity=float(nt["ne_sensitivity"]),
                    updated_at=now,
                    last_fired_at=None,
                )

            synapses: dict[str, SynapseEdge] = {}
            overrides = initial_synapse_overrides or {}
            for st in DEFAULT_SYNAPSE_TEMPLATES:
                key = f"{st['source_id']}->{st['target_id']}"
                w = _clamp(overrides.get(key, float(st["weight"])), -1.0, 1.0)
                synapses[key] = SynapseEdge(
                    source_id=str(st["source_id"]),
                    target_id=str(st["target_id"]),
                    weight=w,
                    plasticity=float(st["plasticity"]),
                    eligibility_trace=0.0,
                    updated_at=now,
                )
            await self._persist(scope_id, neurons, synapses, now)
            return neurons, synapses

        return self._deserialize(raw, now)

    @staticmethod
    def _deserialize(
        raw: Mapping[str, Any], fallback_now: datetime
    ) -> tuple[dict[str, NeuronNode], dict[str, SynapseEdge]]:
        neurons: dict[str, NeuronNode] = {}
        for nid, nd in (raw.get("neurons") or {}).items():
            lf = nd.get("last_fired_at")
            upd = nd.get("updated_at")
            neurons[str(nid)] = NeuronNode(
                neuron_id=str(nid),
                kind=nd["kind"],
                potential=float(nd["potential"]),
                base_threshold=float(nd["base_threshold"]),
                leak_half_life_seconds=float(nd["leak_half_life_seconds"]),
                refractory_seconds=float(nd["refractory_seconds"]),
                da_sensitivity=float(nd.get("da_sensitivity", 0.20)),
                ox_sensitivity=float(nd.get("ox_sensitivity", 0.15)),
                gaba_sensitivity=float(nd.get("gaba_sensitivity", 0.35)),
                ne_sensitivity=float(nd.get("ne_sensitivity", 0.10)),
                updated_at=datetime.fromisoformat(upd).astimezone(UTC) if upd else fallback_now,
                last_fired_at=datetime.fromisoformat(lf).astimezone(UTC) if lf else None,
            )

        synapses: dict[str, SynapseEdge] = {}
        for key, sd in (raw.get("synapses") or {}).items():
            upd_s = sd.get("updated_at")
            synapses[str(key)] = SynapseEdge(
                source_id=str(sd["source_id"]),
                target_id=str(sd["target_id"]),
                weight=float(sd["weight"]),
                plasticity=float(sd["plasticity"]),
                eligibility_trace=float(sd.get("eligibility_trace", 0.0)),
                trace_half_life_hours=float(sd.get("trace_half_life_hours", 18.0)),
                updated_at=datetime.fromisoformat(upd_s).astimezone(UTC) if upd_s else fallback_now,
            )
        return neurons, synapses

    async def _persist(
        self,
        scope_id: str,
        neurons: Mapping[str, NeuronNode],
        synapses: Mapping[str, SynapseEdge],
        now: datetime,
    ) -> None:
        payload = {
            "neurons": {
                nid: {
                    "kind": n.kind,
                    "potential": n.potential,
                    "base_threshold": n.base_threshold,
                    "leak_half_life_seconds": n.leak_half_life_seconds,
                    "refractory_seconds": n.refractory_seconds,
                    "da_sensitivity": n.da_sensitivity,
                    "ox_sensitivity": n.ox_sensitivity,
                    "gaba_sensitivity": n.gaba_sensitivity,
                    "ne_sensitivity": n.ne_sensitivity,
                    "updated_at": n.updated_at.isoformat(),
                    "last_fired_at": n.last_fired_at.isoformat() if n.last_fired_at else None,
                }
                for nid, n in neurons.items()
            },
            "synapses": {
                key: {
                    "source_id": s.source_id,
                    "target_id": s.target_id,
                    "weight": s.weight,
                    "plasticity": s.plasticity,
                    "eligibility_trace": s.eligibility_trace,
                    "trace_half_life_hours": s.trace_half_life_hours,
                    "updated_at": s.updated_at.isoformat(),
                }
                for key, s in synapses.items()
            },
            "updated_at": now.isoformat(),
        }
        await self.store.save_neural_graph(scope_id, payload)

    async def register_custom_synapse(
        self,
        scope_id: str,
        *,
        source_id: str,
        target_id: str,
        weight: float,
        plasticity: float = 0.12,
    ) -> SynapseEdge:
        now = self.clock.now_utc()
        neurons, synapses = await self.ensure_circuit(scope_id, at=now)
        edge = SynapseEdge(
            source_id=source_id,
            target_id=target_id,
            weight=_clamp(weight, -1.0, 1.0),
            plasticity=_clamp(plasticity, 0.0, 0.25),
            eligibility_trace=0.0,
            updated_at=now,
        )
        synapses[edge.edge_key] = edge
        await self._persist(scope_id, neurons, synapses, now)
        return edge

    async def propagate_stimuli(
        self,
        stimuli: Mapping[str, float],
        chem: NeuromodulatorField,
        *,
        scope_id: str = "default",
        at: datetime | None = None,
    ) -> dict[str, Any]:
        """
        Прогоняет внешние сенсорные токи через 3 слоя (sensory -> inter -> motor_gate) без LLM:
        1) Применяет экспоненциальную утечку мембранных потенциалов и следов пригодности.
        2) Выстреливает нейроны, пробившие порог effective_threshold(chem) вне рефрактерного окна.
        3) Передаёт взвешенные токи по синапсам и зажигает eligibility_trace = 1.0 на сработавших связях.
        """
        now = (at or self.clock.now_utc()).astimezone(UTC)
        neurons, synapses = await self.ensure_circuit(scope_id, at=now)

        # 1. Утечка потенциалов и затухание следов пригодности синапсов
        potentials: dict[str, float] = {}
        for nid, node in neurons.items():
            dt_s = max(0.0, (now - node.updated_at).total_seconds())
            potentials[nid] = _clamp(_decay_exp(node.potential, dt_s, node.leak_half_life_seconds))

        traces: dict[str, float] = {}
        for key, syn in synapses.items():
            dt_s = max(0.0, (now - syn.updated_at).total_seconds())
            traces[key] = _clamp(_decay_exp(syn.eligibility_trace, dt_s, syn.trace_half_life_hours * 3600.0))

        # 2. Впрыск внешних стимулов
        for stim_id, current in stimuli.items():
            if stim_id in potentials:
                potentials[stim_id] = _clamp(potentials[stim_id] + float(current))

        fired_spikes: list[SpikeEvent] = []
        fired_last_map: dict[str, datetime | None] = {nid: n.last_fired_at for nid, n in neurons.items()}

        # 3. Послойное распространение импульса: sensory -> inter -> motor_gate
        for layer_kind in ("sensory", "inter", "motor_gate"):
            layer_fired: list[SpikeEvent] = []
            for nid, node in neurons.items():
                if node.kind != layer_kind:
                    continue
                eff_th = node.effective_threshold(chem)
                last_f = fired_last_map[nid]
                in_refractory = last_f is not None and (now - last_f).total_seconds() < node.refractory_seconds
                if not in_refractory and potentials[nid] >= eff_th:
                    amp = potentials[nid]
                    spike = SpikeEvent(
                        neuron_id=nid,
                        kind=node.kind,
                        amplitude=round(amp, 4),
                        effective_threshold=round(eff_th, 4),
                        fired_at=now,
                    )
                    layer_fired.append(spike)
                    fired_spikes.append(spike)
                    potentials[nid] = 0.05  # Сброс мембраны после спайка
                    fired_last_map[nid] = now

            # Передача спайков этого слоя через исходящие синапсы в следующие слои
            for sp in layer_fired:
                for key, syn in synapses.items():
                    if syn.source_id == sp.neuron_id and syn.target_id in potentials:
                        potentials[syn.target_id] = _clamp(potentials[syn.target_id] + syn.weight * sp.amplitude)
                        if syn.plasticity > 0.0:
                            traces[key] = 1.0

        # 4. Сохраняем обновлённый граф в StateStore
        updated_neurons = {
            nid: NeuronNode(
                neuron_id=nid,
                kind=n.kind,
                potential=potentials[nid],
                base_threshold=n.base_threshold,
                leak_half_life_seconds=n.leak_half_life_seconds,
                refractory_seconds=n.refractory_seconds,
                da_sensitivity=n.da_sensitivity,
                ox_sensitivity=n.ox_sensitivity,
                gaba_sensitivity=n.gaba_sensitivity,
                ne_sensitivity=n.ne_sensitivity,
                updated_at=now,
                last_fired_at=fired_last_map[nid],
            )
            for nid, n in neurons.items()
        }
        updated_synapses = {
            key: SynapseEdge(
                source_id=s.source_id,
                target_id=s.target_id,
                weight=s.weight,
                plasticity=s.plasticity,
                eligibility_trace=traces[key],
                trace_half_life_hours=s.trace_half_life_hours,
                updated_at=now,
            )
            for key, s in synapses.items()
        }
        await self._persist(scope_id, updated_neurons, updated_synapses, now)

        opened_gates = [sp.neuron_id for sp in fired_spikes if sp.kind == "motor_gate"]
        return {
            "scope_id": scope_id,
            "neurotransmitters": chem.to_dict(),
            "fired_spikes": [
                {
                    "neuron_id": sp.neuron_id,
                    "kind": sp.kind,
                    "amplitude": sp.amplitude,
                    "threshold": sp.effective_threshold,
                }
                for sp in fired_spikes
            ],
            "opened_motor_gates": opened_gates,
            "requires_llm_cortex": len(opened_gates) > 0,
        }

    async def inspect_graph(self, scope_id: str = "default") -> dict[str, Any]:
        now = self.clock.now_utc()
        neurons, synapses = await self.ensure_circuit(scope_id, at=now)
        return {
            "scope_id": scope_id,
            "neurons": [
                {
                    "neuron_id": n.neuron_id,
                    "kind": n.kind,
                    "potential": round(n.potential, 4),
                    "base_threshold": n.base_threshold,
                }
                for n in neurons.values()
            ],
            "synapses": [
                {
                    "edge": s.edge_key,
                    "weight": round(s.weight, 4),
                    "plasticity": s.plasticity,
                    "eligibility_trace": round(s.eligibility_trace, 4),
                }
                for s in synapses.values()
            ],
        }
