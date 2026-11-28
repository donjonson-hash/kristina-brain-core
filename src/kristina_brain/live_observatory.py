"""
Онлайн-маршруты Синаптической Обсерватории (Neuro Studio v1.3.0 × Drydock):
- GET /neuro-studio: публичный интерфейс реального времени (0 PII, 0 секретов).
- GET /v1/neuro/live/{scope_id}: живой числовой снимок сети, 5 нейромедиаторов,
  скоринга Drydock, трёхзначного вердикта Merit и 4-шаговой цепочки SHA-256.
- POST /v1/neuro/sandbox-pulse: импульсы и сон Хебба для demo:sandbox.
- POST /v1/neuro/drydock-eval: интерактивный расчёт Уилсона/Бонферрони, Gate и
  криптографическая верификация SHA-256 квитанций (Tamper Test).
"""

from __future__ import annotations

import hmac
import os
import time
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from .drydock_math import (
    DRYDOCK_MATH_VERSION,
    MERIT_DELIVERED,
    MERIT_OWED,
    MERIT_UNDETERMINED,
    ChainRole,
    MeritReason,
    MeritVerdict,
    ScoredSignal,
    SeverityLevel,
    WorkerResult,
    bonferroni_threshold,
    canonical_digest,
    compute_drydock_readiness,
    format_wilson_rate,
    run_cognitive_chain,
    two_proportion_p,
    verify_cognitive_chain,
)
from .neuro import NeuromodulatorField
from .neuro_studio_html import NEURO_STUDIO_HTML

OBSERVATORY_VERSION = "1.3.0"
SANDBOX_SCOPE = "demo:sandbox"

NEURAL_CATEGORY_WEIGHTS: dict[str, float] = {
    "Neural_Stability": 0.30,
    "Inhibitory_Shield": 0.30,
    "Modulator_Balance": 0.20,
    "Synaptic_Plasticity": 0.20,
}

NEURAL_GATED_CATEGORIES: tuple[str, ...] = (
    "Neural_Stability",
    "Inhibitory_Shield",
    "Modulator_Balance",
)

NEURAL_CHAIN_GOALS: dict[ChainRole, str] = {
    "detector": "inspect_zero_pii_synaptic_state",
    "researcher": "evaluate_modulators_and_gaba_shield",
    "experimenter": "compute_drydock_neural_readiness",
    "verifier": "seal_three_valued_merit_and_chain",
}

NEURAL_CHAIN_ALLOWED: dict[ChainRole, set[str]] = {
    "detector": {"detected_pulse", "gaba_brake_intact", "urgent_gate_fired"},
    "researcher": {"active_traces", "modulator_alert"},
    "experimenter": {"_pending_pulse", "drydock_readiness"},
    "verifier": {"_pending_pulse", "neural_merit", "verified"},
}


class SandboxPulseRequest(BaseModel):
    scope_id: str = Field(default=SANDBOX_SCOPE, max_length=64)
    action: Literal["pulse", "sleep", "reset"] = "pulse"
    stimuli: dict[str, float] = Field(default_factory=dict)
    reward_signal: float = 0.75


class DrydockSignalInput(BaseModel):
    signal_id: str = "sig-1"
    title: str = "Signal"
    severity: SeverityLevel = "medium"
    confidence: float = 0.90
    category: str = "Neural_Stability"
    origin_category: str | None = None
    contradicted: bool = False
    scope_invalidating: bool = False


class DrydockEvalRequest(BaseModel):
    mode: Literal["stats", "verify_chain", "readiness"] = "stats"
    hits_a: int = 105
    total_a: int = 144
    hits_b: int = 51
    total_b: int = 144
    alpha: float = 0.05
    comparisons: int = 3
    chain_state: dict[str, Any] = Field(default_factory=dict)
    signals: list[DrydockSignalInput] = Field(default_factory=list)
    examined_categories: list[str] | None = None


def _has_valid_api_key(request: Request, explicit_key: str | None = None) -> bool:
    raw_key = (
        explicit_key
        if explicit_key is not None
        else os.environ.get("BRAIN_CONTROL_API_KEY", "")
    )
    configured = raw_key.strip()
    if not configured:
        return False
    candidate = request.headers.get("x-api-key", "").strip()
    if not candidate:
        auth = request.headers.get("authorization", "").strip()
        if auth.lower().startswith("bearer "):
            candidate = auth[7:].strip()
    if not candidate:
        return False
    return hmac.compare_digest(candidate.encode("utf-8"), configured.encode("utf-8"))


def evaluate_neural_drydock(
    *,
    pulse_seq: int,
    chem_dict: Mapping[str, float],
    synapses: Sequence[Mapping[str, Any]],
    last_packets: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], MeritVerdict, dict[str, Any]]:
    """Строит сигналы Drydock и трёхзначный вердикт Merit по числовому состоянию графа."""
    signals: list[ScoredSignal] = []
    examined: set[str] = {
        "Neural_Stability",
        "Inhibitory_Shield",
        "Modulator_Balance",
    }
    if pulse_seq > 0:
        examined.add("Synaptic_Plasticity")

    brake = next(
        (
            s
            for s in synapses
            if s.get("edge") == "sensor_conflict->gate_proactive_outreach"
            or (
                s.get("source_id") == "sensor_conflict"
                and s.get("target_id") == "gate_proactive_outreach"
            )
        ),
        None,
    )
    brake_intact = (
        brake is not None
        and float(brake.get("weight", 0.0)) <= -0.90
        and float(brake.get("plasticity", 1.0)) == 0.0
    )
    if not brake_intact:
        signals.append(
            ScoredSignal(
                "gaba_brake_compromised",
                "Нарушен врождённый тормоз ГАМК (-0.95)",
                "critical",
                1.0,
                "Inhibitory_Shield",
                scope_invalidating=True,
            )
        )

    latest_pkts = [
        p for p in last_packets if pulse_seq > 0 and int(p.get("seq", -1)) == pulse_seq
    ]
    urgent_fired = any(
        p.get("target_id") == "gate_urgent_escalation" and p.get("outcome") == "FIRED"
        for p in latest_pkts
    )
    inhibited_cnt = sum(1 for p in latest_pkts if p.get("outcome") == "INHIBITED")
    refractory_cnt = sum(
        1 for p in latest_pkts if p.get("outcome") == "REFRACTORY_BLOCKED"
    )

    ne = float(chem_dict.get("NE", 0.2))
    serotonin = float(chem_dict.get("5HT", 0.5))
    oxytocin = float(chem_dict.get("OX", 0.4))

    if urgent_fired:
        signals.append(
            ScoredSignal(
                "urgent_escalation_gate",
                "Открыт моторный шлюз срочной эскалации (конфликт)",
                "critical",
                0.92,
                "Neural_Stability",
            )
        )
    if ne >= 0.75:
        signals.append(
            ScoredSignal(
                "ne_overload",
                "Пиковый выброс норадреналина (стресс-режим)",
                "critical",
                0.88,
                "Neural_Stability",
            )
        )
    elif ne >= 0.55:
        signals.append(
            ScoredSignal(
                "ne_elevated",
                "Повышенный фон норадреналина",
                "medium",
                0.75,
                "Neural_Stability",
            )
        )

    if inhibited_cnt > 0 and urgent_fired:
        signals.append(
            ScoredSignal(
                "gaba_conflict_suppression",
                "Тормозной синапс ГАМК погасил неуместную инициативу",
                "medium",
                0.85,
                "Inhibitory_Shield",
            )
        )
    if refractory_cnt > 0:
        signals.append(
            ScoredSignal(
                "refractory_guard_active",
                "Рефрактерный щит заблокировал повторный дубль импульса",
                "low",
                0.65,
                "Inhibitory_Shield",
            )
        )

    modulator_alert = serotonin < 0.25 or oxytocin < 0.18
    if modulator_alert:
        signals.append(
            ScoredSignal(
                "modulator_depletion",
                "Просадка серотонина / окситоцина в химическом фоне",
                "high",
                0.80,
                "Modulator_Balance",
            )
        )

    active_traces = sum(
        1 for s in synapses if float(s.get("eligibility_trace", 0.0)) >= 0.10
    )

    readiness = compute_drydock_readiness(
        signals,
        category_weights=NEURAL_CATEGORY_WEIGHTS,
        gated_categories=NEURAL_GATED_CATEGORIES,
        examined_categories=examined,
    )

    reasons: list[MeritReason] = []
    if not brake_intact:
        reasons.append(
            MeritReason(
                "gaba_shield_broken",
                "Тормозной синапс ГАМК повреждён — требуется вмешательство",
                decisive=True,
            )
        )
        merit = MeritVerdict(MERIT_OWED, tuple(reasons))
    elif pulse_seq == 0:
        reasons.append(
            MeritReason(
                "cold_circuit",
                "Контур в исходном состоянии (pulse_seq=0, импульсов ещё не было)",
                decisive=True,
            )
        )
        merit = MeritVerdict(MERIT_UNDETERMINED, tuple(reasons))
    elif urgent_fired or ne >= 0.75:
        reasons.append(
            MeritReason(
                "urgent_escalation_active",
                "Сработал шлюз срочной эскалации при конфликте — долг внимания активен",
                decisive=True,
            )
        )
        merit = MeritVerdict(MERIT_OWED, tuple(reasons))
    else:
        reasons.append(
            MeritReason(
                "synaptic_homeostasis_ok",
                "Тормозной щит ГАМК (-0.95) цел, импульсы обработаны без потерь",
                decisive=True,
            )
        )
        if active_traces > 0:
            reasons.append(
                MeritReason(
                    "hebbian_trace_armed",
                    f"Заряжено следов пластичности e(t): {active_traces}",
                    decisive=False,
                )
            )
        merit = MeritVerdict(MERIT_DELIVERED, tuple(reasons))

    facts = {
        "brake_intact": brake_intact,
        "urgent_fired": urgent_fired,
        "active_traces": active_traces,
        "modulator_alert": modulator_alert,
    }
    return readiness, merit, facts


def _neural_binding(scope_id: str, pulse_seq: int) -> dict[str, Any]:
    return {
        "engine": f"kristina-brain-core-v{OBSERVATORY_VERSION}",
        "scope_id": scope_id,
        "pulse_seq": int(pulse_seq),
    }


def build_neural_cognitive_chain(
    *,
    scope_id: str,
    pulse_seq: int,
    readiness: Mapping[str, Any],
    merit: MeritVerdict,
    facts: Mapping[str, Any],
) -> dict[str, Any]:
    """Запечатывает снимок мозга Кристины 4-шаговой цепочкой SHA-256 квитанций."""
    binding = _neural_binding(scope_id, pulse_seq)
    seed: dict[str, Any] = {
        "scope_id": scope_id,
        "pulse_seq": int(pulse_seq),
        "detected_pulse": False,
        "gaba_brake_intact": False,
        "urgent_gate_fired": False,
        "active_traces": 0,
        "modulator_alert": False,
        "drydock_readiness": {},
        "neural_merit": {},
        "verified": False,
    }

    def w_det(st: dict[str, Any]) -> WorkerResult:
        st["detected_pulse"] = int(pulse_seq) > 0
        st["gaba_brake_intact"] = bool(facts["brake_intact"])
        st["urgent_gate_fired"] = bool(facts["urgent_fired"])
        return st, "completed", "synaptic_state_inspected"

    def w_res(st: dict[str, Any]) -> WorkerResult:
        st["active_traces"] = int(facts["active_traces"])
        st["modulator_alert"] = bool(facts["modulator_alert"])
        return st, "completed", "modulators_evaluated"

    def w_exp(st: dict[str, Any]) -> WorkerResult:
        st["_pending_pulse"] = int(pulse_seq)
        st["drydock_readiness"] = dict(readiness)
        return st, "completed", "drydock_scored"

    def w_ver(st: dict[str, Any]) -> WorkerResult:
        st.pop("_pending_pulse", None)
        st["neural_merit"] = merit.as_dict()
        st["verified"] = True
        return st, "completed", "merit_and_sha256_sealed"

    return run_cognitive_chain(
        seed,
        binding=binding,
        workers={
            "detector": w_det,
            "researcher": w_res,
            "experimenter": w_exp,
            "verifier": w_ver,
        },
        allowed_fields=NEURAL_CHAIN_ALLOWED,
        goals=NEURAL_CHAIN_GOALS,
        identity_fields=("scope_id", "pulse_seq"),
    )


def verify_neural_chain_state(chain_state: Mapping[str, Any]) -> bool:
    """Криптографически проверяет 4-шаговую цепочку SHA-256 снимка Neuro Studio."""
    scope_id = chain_state.get("scope_id")
    pulse_seq = chain_state.get("pulse_seq")
    if not isinstance(scope_id, str) or not isinstance(pulse_seq, int):
        return False
    binding = _neural_binding(scope_id, pulse_seq)
    return verify_cognitive_chain(
        chain_state,
        binding=binding,
        goals=NEURAL_CHAIN_GOALS,
    )


async def _build_zero_pii_snapshot(engine: Any, scope_id: str) -> dict[str, Any]:
    fast_raw = await engine.emotions.get_emotional_state(scope_id)
    mode_map = await engine.modes.snapshot(scope_id)
    is_quiet = bool(fast_raw.get("is_night", False))
    chem = NeuromodulatorField.from_brain_state(
        fast_raw,
        mode_map,
        is_quiet_hours=is_quiet,
    )
    graph = await engine.synapses.inspect_graph(scope_id, chem=chem)

    raw_vec = fast_raw.get("state", {})
    clean_emotions: dict[str, float] = {}
    if isinstance(raw_vec, Mapping):
        for k, v in raw_vec.items():
            if isinstance(v, (int, float)):
                clean_emotions[str(k)] = round(float(v), 4)

    clean_modes: dict[str, dict[str, float]] = {}
    for m_name, m_state in mode_map.items():
        clean_modes[str(m_name)] = {
            "amplitude": round(float(m_state.amplitude), 4),
            "baseline": round(float(m_state.baseline), 4),
            "deviation": round(float(m_state.deviation), 4),
        }

    pulse_seq = int(graph["pulse_seq"])
    chem_dict = chem.to_dict()
    synapses_list = list(graph["synapses"])
    packets_list = list(graph["last_packets"])

    readiness, merit, facts = evaluate_neural_drydock(
        pulse_seq=pulse_seq,
        chem_dict=chem_dict,
        synapses=synapses_list,
        last_packets=packets_list,
    )
    chain_state = build_neural_cognitive_chain(
        scope_id=scope_id,
        pulse_seq=pulse_seq,
        readiness=readiness,
        merit=merit,
        facts=facts,
    )
    chain_ok = verify_neural_chain_state(chain_state)
    no_chain = {k: v for k, v in chain_state.items() if k != "cognitive_chain"}

    return {
        "status": "online",
        "version": OBSERVATORY_VERSION,
        "scope_id": scope_id,
        "server_time_utc": datetime.now(UTC).isoformat(),
        "is_quiet_hours": is_quiet,
        "pulse_seq": pulse_seq,
        "neurotransmitters": chem_dict,
        "fast_emotions": clean_emotions,
        "slow_modes": clean_modes,
        "neurons": graph["neurons"],
        "synapses": synapses_list,
        "last_packets": packets_list,
        "drydock": {
            "math_version": DRYDOCK_MATH_VERSION,
            "category_weights": dict(NEURAL_CATEGORY_WEIGHTS),
            "gated_categories": list(NEURAL_GATED_CATEGORIES),
            "readiness": readiness,
            "merit": merit.as_dict(),
            "chain_verified": chain_ok,
            "state_sha256": canonical_digest(no_chain),
            "chain_state": chain_state,
            "cognitive_chain": chain_state["cognitive_chain"],
        },
        "pii_redacted": True,
    }


def create_observatory_router(
    state_holder: Mapping[str, Any],
    *,
    expected_api_key: str | None = None,
) -> APIRouter:
    router = APIRouter(tags=["neuro-observatory"])

    def _engine() -> Any:
        eng = state_holder.get("engine")
        if eng is None:
            raise HTTPException(status_code=503, detail="BrainEngine is initializing")
        return eng

    @router.get("/neuro-studio", response_class=HTMLResponse)
    async def neuro_studio_page() -> HTMLResponse:
        return HTMLResponse(content=NEURO_STUDIO_HTML)

    @router.get("/neuro-studio/api/live/{scope_id:path}")
    @router.get("/v1/neuro/live/{scope_id:path}")
    async def neuro_live_snapshot(scope_id: str) -> dict[str, Any]:
        clean_scope = (scope_id or "default").strip()[:64] or "default"
        return await _build_zero_pii_snapshot(_engine(), clean_scope)

    @router.post("/neuro-studio/api/drydock-eval")
    @router.post("/v1/neuro/drydock-eval")
    async def neuro_drydock_eval(payload: DrydockEvalRequest) -> dict[str, Any]:
        t0 = time.perf_counter()
        if payload.mode == "verify_chain":
            verified = verify_neural_chain_state(payload.chain_state)
            elapsed = round((time.perf_counter() - t0) * 1000.0, 3)
            return {
                "ok": True,
                "mode": "verify_chain",
                "chain_verified": verified,
                "engine_latency_ms": elapsed,
            }

        if payload.mode == "readiness":
            sigs = [
                ScoredSignal(
                    signal_id=s.signal_id[:48],
                    title=s.title[:120],
                    severity=s.severity,
                    confidence=max(0.0, min(1.0, float(s.confidence))),
                    category=s.category,
                    origin_category=s.origin_category,
                    contradicted=s.contradicted,
                    scope_invalidating=s.scope_invalidating,
                )
                for s in payload.signals[:32]
            ]
            exam = (
                frozenset(payload.examined_categories)
                if payload.examined_categories is not None
                else None
            )
            res = compute_drydock_readiness(
                sigs,
                category_weights=NEURAL_CATEGORY_WEIGHTS,
                gated_categories=NEURAL_GATED_CATEGORIES,
                examined_categories=exam,
            )
            elapsed = round((time.perf_counter() - t0) * 1000.0, 3)
            return {
                "ok": True,
                "mode": "readiness",
                "readiness": res,
                "engine_latency_ms": elapsed,
            }

        na = max(0, min(100_000, int(payload.total_a)))
        nb = max(0, min(100_000, int(payload.total_b)))
        ha = max(0, min(na, int(payload.hits_a)))
        hb = max(0, min(nb, int(payload.hits_b)))
        m_cmp = max(1, min(100, int(payload.comparisons)))
        alpha = max(0.0001, min(0.5, float(payload.alpha)))

        wa = format_wilson_rate(ha, na)
        wb = format_wilson_rate(hb, nb)
        p_val = two_proportion_p(ha, na, hb, nb)
        alpha_bonf = bonferroni_threshold(alpha, m_cmp)
        elapsed = round((time.perf_counter() - t0) * 1000.0, 3)
        return {
            "ok": True,
            "mode": "stats",
            "wilson_a": wa,
            "wilson_b": wb,
            "two_proportion_p": p_val,
            "bonferroni_alpha": alpha_bonf,
            "comparisons": m_cmp,
            "significant": p_val < alpha_bonf,
            "engine_latency_ms": elapsed,
        }

    @router.post("/neuro-studio/api/sandbox-pulse")
    @router.post("/v1/neuro/sandbox-pulse")
    async def neuro_sandbox_pulse(
        payload: SandboxPulseRequest, request: Request
    ) -> dict[str, Any]:
        target_scope = (payload.scope_id or SANDBOX_SCOPE).strip()[:64] or SANDBOX_SCOPE
        if target_scope != SANDBOX_SCOPE and not _has_valid_api_key(
            request, expected_api_key
        ):
            raise HTTPException(
                status_code=401,
                detail="Valid X-API-Key required to mutate non-sandbox neural scopes.",
            )

        eng = _engine()
        t0 = time.perf_counter()

        if payload.action == "reset":
            await eng.synapses.reset_circuit(target_scope)
            elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 3)
            snap = await _build_zero_pii_snapshot(eng, target_scope)
            return {
                "ok": True,
                "action": "reset",
                "engine_latency_ms": elapsed_ms,
                "snapshot": snap,
            }

        if payload.action == "sleep":
            rew = max(-1.0, min(1.0, float(payload.reward_signal)))
            raw_sleep = await eng.run_sleep_consolidation(
                target_scope, reward_signal=rew
            )
            elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 3)
            snap = await _build_zero_pii_snapshot(eng, target_scope)
            dream_raw = (
                raw_sleep.get("dream_seed") if isinstance(raw_sleep, Mapping) else None
            )
            vividness = 0.35
            if isinstance(dream_raw, Mapping) and isinstance(
                dream_raw.get("vividness"), (int, float)
            ):
                vividness = round(float(dream_raw["vividness"]), 4)
            return {
                "ok": True,
                "action": "sleep",
                "engine_latency_ms": elapsed_ms,
                "reward_signal": rew,
                "dream_vividness": vividness,
                "snapshot": snap,
            }

        clean_stimuli: dict[str, float] = {}
        for k, v in list(payload.stimuli.items())[:16]:
            if isinstance(v, (int, float)):
                clean_stimuli[str(k)[:48]] = max(0.0, min(1.0, float(v)))

        pulse_res = await eng.pulse_synapses(target_scope, clean_stimuli)
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 3)
        snap = await _build_zero_pii_snapshot(eng, target_scope)
        return {
            "ok": True,
            "action": "pulse",
            "engine_latency_ms": elapsed_ms,
            "pulse": pulse_res,
            "snapshot": snap,
        }

    return router


def mount_neuro_observatory(
    app: FastAPI,
    state_holder: Mapping[str, Any],
    *,
    expected_api_key: str | None = None,
) -> None:
    existing_paths = {getattr(r, "path", "") for r in app.routes}
    if "/neuro-studio" in existing_paths:
        return
    before_n = len(app.router.routes)
    obs_r = create_observatory_router(state_holder, expected_api_key=expected_api_key)
    app.include_router(obs_r)
    added = list(app.router.routes[before_n:])
    del app.router.routes[before_n:]
    app.router.routes[0:0] = added
    if "/" not in existing_paths:

        @app.get("/", include_in_schema=False)
        async def _root_to_studio() -> RedirectResponse:
            return RedirectResponse(url="/neuro-studio", status_code=307)
