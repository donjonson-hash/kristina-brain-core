"""Тесты модуля kristina_brain.drydock_math (ядро Drydock v1.3.0)."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from kristina_brain.drydock_math import (
    MERIT_OWED,
    ChainRole,
    MeritReason,
    MeritVerdict,
    ScoredSignal,
    WorkerResult,
    bonferroni_threshold,
    compute_drydock_readiness,
    run_cognitive_chain,
    two_proportion_p,
    verify_cognitive_chain,
    wilson_ci,
)


def test_drydock_core_invariants() -> None:
    weights = {"Core": 0.5, "Safety": 0.5}
    gated = ("Core", "Safety")
    s1 = [ScoredSignal("x1", "Critical safety alert", "critical", 0.9, "Safety")]
    s2 = [
        ScoredSignal("x1", "Critical #1", "critical", 0.95, "Safety"),
        ScoredSignal("x2", "Critical #2", "critical", 0.95, "Core"),
    ]
    r1 = compute_drydock_readiness(s1, category_weights=weights, gated_categories=gated)
    r2 = compute_drydock_readiness(s2, category_weights=weights, gated_categories=gated)
    assert r2["total"] < r1["total"] <= 6.9

    reason = MeritReason("sla_miss", "Breached SLA", decisive=True)
    verdict = MeritVerdict(MERIT_OWED, (reason,))
    assert verdict.owed is True

    lo, hi = wilson_ci(37, 48)
    assert 0.60 < lo < hi < 0.90
    assert two_proportion_p(37, 48, 17, 48) < bonferroni_threshold(0.05, 3)


def test_chain_verification() -> None:
    binding = {"scope_id": "u1"}
    goals: dict[ChainRole, str] = {
        "detector": "d",
        "researcher": "r",
        "experimenter": "e",
        "verifier": "v",
    }
    allowed: dict[ChainRole, set[str]] = {
        "detector": {"step"},
        "researcher": {"step"},
        "experimenter": {"step"},
        "verifier": {"step"},
    }

    def step_fn(st: dict[str, Any]) -> WorkerResult:
        st["step"] = int(st["step"]) + 1
        return st, "completed", "ok"

    workers: dict[ChainRole, Any] = {
        "detector": step_fn,
        "researcher": step_fn,
        "experimenter": step_fn,
        "verifier": step_fn,
    }
    res = run_cognitive_chain(
        {"scope_id": "u1", "step": 0},
        binding=binding,
        workers=workers,
        allowed_fields=allowed,
        goals=goals,
    )
    assert res["step"] == 4
    assert verify_cognitive_chain(res, binding=binding, goals=goals) is True
    bad = deepcopy(res)
    bad["step"] = 99
    assert verify_cognitive_chain(bad, binding=binding, goals=goals) is False


def test_js_float_to_int_roundtrip_preserves_chain_sha256() -> None:
    """Имитирует браузерный JSON.stringify (где 10.0 превращается в 10)."""
    binding = {"scope_id": "default", "pulse_seq": 42}
    goals: dict[ChainRole, str] = {
        "detector": "d",
        "researcher": "r",
        "experimenter": "e",
        "verifier": "v",
    }
    allowed: dict[ChainRole, set[str]] = {
        "detector": {"score"},
        "researcher": {"score"},
        "experimenter": {"score"},
        "verifier": {"ok"},
    }

    def w_score(st: dict[str, Any]) -> WorkerResult:
        st["score"] = 10.0
        return st, "completed", "ok"

    def w_ver(st: dict[str, Any]) -> WorkerResult:
        st["ok"] = True
        return st, "completed", "sealed"

    state = run_cognitive_chain(
        {"scope_id": "default", "score": 0.0, "ok": False},
        binding=binding,
        workers={
            "detector": w_score,
            "researcher": w_score,
            "experimenter": w_score,
            "verifier": w_ver,
        },
        allowed_fields=allowed,
        goals=goals,
    )
    # Simulate browser JSON.stringify turning 10.0 (float) into 10 (int)
    js_roundtripped = deepcopy(state)
    js_roundtripped["score"] = 10
    assert verify_cognitive_chain(js_roundtripped, binding=binding, goals=goals) is True

    # Any real mutation (10 -> 9.9 or ok -> False) is still strictly rejected
    tampered = deepcopy(js_roundtripped)
    tampered["score"] = 9.9
    assert verify_cognitive_chain(tampered, binding=binding, goals=goals) is False

