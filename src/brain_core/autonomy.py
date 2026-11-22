"""
Движок проактивной автономии, политики тишины и Shadow A/B-сравнения (autonomy.py + shadow.py).
Полностью совместим с контрактами DesireEngine, DecisionEngine, AutonomousDecision и ShadowDecisionReport.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .modes import OrganismProjection


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, round(float(value), 4)))


@dataclass(frozen=True)
class AutonomousDecision:
    action: str  # "none" | "message"
    intention: str | None  # "talk" | "share" | "ask" | None
    score: float
    reason: str


@dataclass(frozen=True)
class ShadowDecisionReport:
    baseline: AutonomousDecision
    shadow: AutonomousDecision
    baseline_desires: Mapping[str, float]
    shadow_desires: Mapping[str, float]
    score_deltas: Mapping[str, float]
    decision_changed: bool
    max_abs_score_delta: float


class DesireEngine:
    """Вычисляет вектор внутренних побуждений агента (talk, share, ask, be_alone)."""

    def calculate(
        self,
        emotional_state: Mapping[str, Any],
        context: Mapping[str, Any] | None = None,
    ) -> dict[str, float]:
        vec = emotional_state.get("state", emotional_state)
        energy = float(vec.get("energy", 0.5))
        curiosity = float(vec.get("curiosity", 0.5))
        loneliness = float(vec.get("loneliness", 0.2))
        creativity = float(vec.get("creativity", 0.5))
        irritation = float(vec.get("irritation", 0.1))
        anxiety = float(vec.get("anxiety", 0.2))

        ctx = context or {}
        hours_since = float(ctx.get("hours_since_contact", 0.0))
        contact_factor = min(0.30, max(0.0, (hours_since - 1.5) * 0.03))

        talk = 0.45 * loneliness + 0.30 * energy + contact_factor - 0.35 * irritation
        share = 0.50 * creativity + 0.25 * energy + 0.15 * loneliness - 0.25 * anxiety
        ask = 0.55 * curiosity + 0.20 * energy + 0.5 * contact_factor - 0.30 * irritation
        be_alone = 0.50 * irritation + 0.35 * anxiety + 0.30 * (1.0 - energy)

        proj: OrganismProjection | None = ctx.get("organism_projection")
        if isinstance(proj, OrganismProjection):
            talk += proj.talk_bias
            share += proj.share_bias
            ask += proj.ask_bias
            be_alone += proj.be_alone_bias

        return {
            "talk": _clamp01(talk),
            "share": _clamp01(share),
            "ask": _clamp01(ask),
            "be_alone": _clamp01(be_alone),
        }


class DecisionEngine:
    """Шлюз проактивного выбора: написать пользователю или соблюсти политику тишины."""

    def __init__(
        self,
        threshold: float = 0.62,
        cooldown: timedelta = timedelta(hours=2),
        max_proactive_per_24h: int = 3,
    ) -> None:
        self.threshold = float(threshold)
        self.cooldown = cooldown
        self.max_proactive_per_24h = int(max_proactive_per_24h)

    def decide(
        self,
        desires: Mapping[str, float],
        context: Mapping[str, Any] | None = None,
        now: datetime | None = None,
    ) -> AutonomousDecision:
        current_now = (now or datetime.now(UTC)).astimezone(UTC)
        ctx = context or {}

        # 1. Жёсткий суточный лимит антиспама
        count_24h = int(ctx.get("proactive_count_24h", 0))
        if count_24h >= self.max_proactive_per_24h:
            return AutonomousDecision(action="none", intention=None, score=0.0, reason="daily_cap_reached")

        # 2. Проверка персистентного кулдауна (из StateStore, а не RAM)
        last_proactive = ctx.get("last_proactive")
        if isinstance(last_proactive, str):
            last_proactive = datetime.fromisoformat(last_proactive)
        if isinstance(last_proactive, datetime):
            if last_proactive.tzinfo is None:
                last_proactive = last_proactive.replace(tzinfo=UTC)
            if current_now - last_proactive.astimezone(UTC) < self.cooldown:
                return AutonomousDecision(action="none", intention=None, score=0.0, reason="cooldown")

        # 3. Циркадный фильтр ночи (не будить собеседника)
        if bool(ctx.get("is_night", False)):
            return AutonomousDecision(action="none", intention=None, score=0.0, reason="quiet_hours")

        # 4. Потребность в дистанции / покое
        be_alone = float(desires.get("be_alone", 0.0))
        outreach_candidates = {k: float(desires.get(k, 0.0)) for k in ("talk", "share", "ask")}
        best_intention, best_score = max(outreach_candidates.items(), key=lambda kv: kv[1])

        if be_alone >= 0.58 or be_alone >= best_score:
            return AutonomousDecision(
                action="none",
                intention=None,
                score=round(be_alone, 4),
                reason="wants_space",
            )

        if best_score <= 0.20:
            return AutonomousDecision(action="none", intention=None, score=round(best_score, 4), reason="no_desire")

        if best_score < self.threshold:
            return AutonomousDecision(
                action="none",
                intention=best_intention,
                score=round(best_score, 4),
                reason="impulse_too_weak",
            )

        return AutonomousDecision(
            action="message",
            intention=best_intention,
            score=round(best_score, 4),
            reason="strong_internal_impulse",
        )


def evaluate_with_shadow(
    desire_engine: DesireEngine,
    decision_engine: DecisionEngine,
    emotional_state: Mapping[str, Any],
    projection: OrganismProjection,
    *,
    context: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> ShadowDecisionReport:
    """Сравнивает базовое решение (только быстрые эмоции) и shadow-решение (с учётом 12 медленных мод)."""
    base_ctx = dict(context or {})
    base_ctx.pop("organism_projection", None)

    shadow_ctx = dict(base_ctx)
    shadow_ctx["organism_projection"] = projection

    base_desires = desire_engine.calculate(emotional_state, base_ctx)
    shadow_desires = desire_engine.calculate(emotional_state, shadow_ctx)

    base_dec = decision_engine.decide(base_desires, base_ctx, now=now)
    shadow_dec = decision_engine.decide(shadow_desires, shadow_ctx, now=now)

    deltas = {k: round(shadow_desires[k] - base_desires[k], 4) for k in ("talk", "share", "ask", "be_alone")}
    max_abs = max((abs(v) for v in deltas.values()), default=0.0)
    changed = (base_dec.action != shadow_dec.action) or (base_dec.intention != shadow_dec.intention)

    return ShadowDecisionReport(
        baseline=base_dec,
        shadow=shadow_dec,
        baseline_desires=base_desires,
        shadow_desires=shadow_desires,
        score_deltas=deltas,
        decision_changed=changed,
        max_abs_score_delta=round(max_abs, 4),
    )
