"""
Математическое и эпистемическое ядро Drydock (портировано из shipit для Brain Kristina):
1. Категорийные субскоры 10 - Σ(w_sev * conf) с перенормировкой весов строго по
   проверенным категориям (без мёртвого веса unexamined и reported_elsewhere).
2. Монотонное сжатие шкалы total * (GATED_MAX / 10.0) при провале защитной категории
   или уверенном critical (conf >= 0.70) без двойного штрафа.
3. Трёхзначная логика заслуги/долга (OWED / DELIVERED / UNDETERMINED) с decisive.
4. Доверительные интервалы Уилсона 95%, Z-тест двух долей (erfc) и Бонферрони.
5. Детерминированный 4-шаговый конвейер (detector -> researcher -> experimenter ->
   verifier) с иммутабельными копиями и SHA-256 квитанциями.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Literal

DRYDOCK_MATH_VERSION = "1.3.0"

SeverityLevel = Literal["critical", "high", "medium", "low"]
MeritConclusion = Literal["owed", "delivered", "undetermined"]
ChainRole = Literal["detector", "researcher", "experimenter", "verifier"]

SEVERITY_WEIGHTS: dict[str, float] = {
    "critical": 2.0,
    "high": 1.0,
    "medium": 0.4,
    "low": 0.1,
}

DEFAULT_GATE_THRESHOLD = 7.0
DEFAULT_GATED_MAX = 6.9
CRITICAL_GATE_MIN_CONFIDENCE = 0.70

MERIT_OWED: MeritConclusion = "owed"
MERIT_DELIVERED: MeritConclusion = "delivered"
MERIT_UNDETERMINED: MeritConclusion = "undetermined"

CHAIN_ROLES: tuple[ChainRole, ...] = (
    "detector",
    "researcher",
    "experimenter",
    "verifier",
)


@dataclass(frozen=True)
class ScoredSignal:
    """Нормализованный сигнал риска/отклонения для скоринга Drydock."""

    signal_id: str
    title: str
    severity: SeverityLevel
    confidence: float
    category: str
    origin_category: str | None = None
    contradicted: bool = False
    scope_invalidating: bool = False


@dataclass(frozen=True)
class MeritReason:
    """Единица доказательства в трёхзначной модели Merit."""

    code: str
    detail: str
    decisive: bool = False


@dataclass(frozen=True)
class MeritVerdict:
    """Вердикт самоаудита качества исполнения."""

    conclusion: MeritConclusion
    reasons: tuple[MeritReason, ...] = field(default_factory=tuple)

    @property
    def owed(self) -> bool:
        return self.conclusion == MERIT_OWED

    def as_dict(self) -> dict[str, Any]:
        return {
            "conclusion": self.conclusion,
            "owed": self.owed,
            "reasons": [
                {"code": r.code, "detail": r.detail, "decisive": r.decisive}
                for r in self.reasons
            ],
        }


def _category_subscore(signals: Sequence[ScoredSignal]) -> float:
    penalty = sum(
        SEVERITY_WEIGHTS[s.severity] * max(0.0, min(1.0, float(s.confidence)))
        for s in signals
    )
    return round(max(0.0, min(10.0, 10.0 - penalty)), 1)


def compute_drydock_readiness(
    signals: Sequence[ScoredSignal],
    *,
    category_weights: Mapping[str, float],
    gated_categories: Sequence[str],
    examined_categories: frozenset[str] | set[str] | None = None,
    gate_threshold: float = DEFAULT_GATE_THRESHOLD,
    gated_max: float = DEFAULT_GATED_MAX,
) -> dict[str, Any]:
    """Вычисляет многомерный индекс готовности по формуле Drydock."""
    categories = tuple(category_weights.keys())
    gated_set = frozenset(gated_categories)
    examined_set = (
        frozenset(categories)
        if examined_categories is None
        else frozenset(examined_categories)
    )

    active = [
        s for s in signals if not s.contradicted and s.category in category_weights
    ]
    by_cat: dict[str, float] = {
        cat: _category_subscore([s for s in active if s.category == cat])
        for cat in categories
    }

    reported_elsewhere: dict[str, list[str]] = {
        c: sorted(
            {s.category for s in active if s.origin_category == c and s.category != c}
        )
        for c in categories
        if not any(s.category == c for s in active)
        and any(s.origin_category == c for s in active)
    }

    counted = [
        c for c in categories if c in examined_set and c not in reported_elsewhere
    ]
    divisor = sum(float(category_weights[c]) for c in counted)
    mean_ungated = (
        sum(by_cat[c] * float(category_weights[c]) for c in counted) / divisor
        if divisor > 0.0
        else 10.0
    )

    reasons: list[dict[str, Any]] = [
        {"kind": "subscore", "category": c, "value": by_cat[c]}
        for c in gated_categories
        if c in counted and by_cat[c] < gate_threshold
    ]
    reasons.extend(
        {
            "kind": "critical",
            "category": s.category,
            "signal_id": s.signal_id,
            "title": s.title,
        }
        for s in active
        if s.severity == "critical"
        and float(s.confidence) >= CRITICAL_GATE_MIN_CONFIDENCE
        and s.category in gated_set
    )
    reasons.extend(
        {
            "kind": "scope_invalidating",
            "category": s.category,
            "signal_id": s.signal_id,
            "title": s.title,
        }
        for s in active
        if s.scope_invalidating
    )

    scaled_total = mean_ungated * (gated_max / 10.0) if reasons else mean_ungated
    total = round(scaled_total, 1)

    already_failing = {
        str(r["category"]) for r in reasons if r.get("kind") == "subscore"
    }
    capped = {
        str(r["category"])
        for r in reasons
        if r.get("kind") == "critical" and str(r.get("category")) in by_cat
    }
    for cat in capped - already_failing:
        by_cat[cat] = round(by_cat[cat] * (gated_max / 10.0), 1)

    if active and total == 10.0:
        total = 9.9

    unexamined = [
        c for c in categories if c not in counted and c not in reported_elsewhere
    ]
    unexamined_with_findings = [
        c for c in unexamined if any(s.category == c for s in active)
    ]

    return {
        "total": total,
        "mean_ungated": round(mean_ungated, 2),
        "gated": bool(reasons),
        "categories": by_cat,
        "gated_by": reasons,
        "counted": counted,
        "unexamined": unexamined,
        "unexamined_with_findings": unexamined_with_findings,
        "reported_elsewhere": reported_elsewhere,
    }


def wilson_ci(hits: int, total: int, *, z: float = 1.959964) -> tuple[float, float]:
    """95% доверительный интервал Уилсона строго внутри [0.0, 1.0]."""
    if total <= 0:
        return (0.0, 0.0)
    h = max(0, min(hits, total))
    p = h / total
    z2 = z * z
    denom = 1.0 + z2 / total
    centre = (p + z2 / (2.0 * total)) / denom
    rad = p * (1.0 - p) / total + z2 / (4.0 * total * total)
    margin = z * math.sqrt(rad) / denom
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def format_wilson_rate(hits: int, total: int) -> dict[str, Any]:
    """Возвращает долю и границы 95% интервала Уилсона в процентах."""
    if total <= 0:
        return {
            "hits": 0,
            "total": 0,
            "rate_pct": None,
            "ci95_low_pct": None,
            "ci95_high_pct": None,
            "label": "н/д",
        }
    low, high = wilson_ci(hits, total)
    pct = round((hits / total) * 100.0, 1)
    lo_pct = round(low * 100.0, 1)
    hi_pct = round(high * 100.0, 1)
    return {
        "hits": hits,
        "total": total,
        "rate_pct": pct,
        "ci95_low_pct": lo_pct,
        "ci95_high_pct": hi_pct,
        "label": f"{hits}/{total} = {pct}% [95% CI {lo_pct}–{hi_pct}%]",
    }


def two_proportion_p(hits_a: int, n_a: int, hits_b: int, n_b: int) -> float:
    """Двусторонний p-value равенства двух долей через math.erfc."""
    if n_a <= 0 or n_b <= 0:
        return 1.0
    pooled = (hits_a + hits_b) / (n_a + n_b)
    se = math.sqrt(pooled * (1.0 - pooled) * (1.0 / n_a + 1.0 / n_b))
    if se == 0.0:
        return 1.0
    z_stat = abs(hits_a / n_a - hits_b / n_b) / se
    return round(math.erfc(z_stat / math.sqrt(2.0)), 6)


def bonferroni_threshold(alpha: float = 0.05, comparisons: int = 1) -> float:
    """Поправка Бонферрони alpha / m для множественных проверок."""
    return round(alpha / max(1, int(comparisons)), 6)


def canonical_digest(value: Any) -> str:
    """Детерминированный SHA-256 канонического JSON без NaN."""
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _state_without_chain(state: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in state.items() if k != "cognitive_chain"}


WorkerResult = tuple[dict[str, Any], Literal["completed", "blocked"], str]
WorkerFn = Callable[[dict[str, Any]], WorkerResult]


def run_cognitive_chain(
    seed: Mapping[str, Any],
    *,
    binding: Mapping[str, Any],
    workers: Mapping[ChainRole, WorkerFn],
    allowed_fields: Mapping[ChainRole, set[str]],
    goals: Mapping[ChainRole, str],
    identity_fields: Sequence[str] = ("scope_id",),
) -> dict[str, Any]:
    """Выполняет 4-шаговый конвейер detector -> researcher -> experimenter -> verifier."""
    accepted: dict[str, Any] = deepcopy(dict(seed))
    queue: deque[ChainRole] = deque([CHAIN_ROLES[0]])
    receipts: list[dict[str, Any]] = []

    while queue and len(receipts) < len(CHAIN_ROLES):
        role = queue.popleft()
        before_sha = canonical_digest(_state_without_chain(accepted))
        status: Literal["completed", "blocked", "error"] = "error"
        reason = "worker_failed"
        attempts = 0

        try:
            if role != "verifier" and any(r["status"] == "error" for r in receipts):
                proposed = deepcopy(accepted)
                status = "blocked"
                reason = "upstream_task_failed"
            else:
                attempts = 1
                proposed, w_status, w_reason = workers[role](deepcopy(accepted))
                changed = {
                    k
                    for k in (accepted.keys() | proposed.keys())
                    if accepted.get(k) != proposed.get(k)
                }
                invalid_transition = (
                    w_status not in ("completed", "blocked")
                    or not w_reason
                    or not w_reason.isascii()
                    or not w_reason.replace("_", "").isalnum()
                    or len(w_reason) > 80
                    or any(proposed.get(k) != seed.get(k) for k in identity_fields)
                    or not (changed <= allowed_fields.get(role, set()))
                )
                if invalid_transition:
                    raise ValueError("Invalid cognitive worker transition")
                proposed = deepcopy(proposed)
                canonical_digest(_state_without_chain(proposed))
                accepted = proposed
                status = w_status
                reason = w_reason
        except (ValueError, TypeError, KeyError, RuntimeError):
            status = "error"
            reason = "worker_failed"

        if role == "verifier":
            accepted.pop("_pending_pulse", None)

        after_sha = canonical_digest(_state_without_chain(accepted))
        receipts.append(
            {
                "id": canonical_digest([dict(binding), role]),
                "agent": role,
                "goal": goals[role],
                "source": deepcopy(dict(binding)),
                "depends_on": [receipts[-1]["id"]] if receipts else [],
                "input_sha256": before_sha,
                "output_sha256": after_sha,
                "attempts": attempts,
                "max_attempts": 1,
                "status": status,
                "reason": reason,
            }
        )
        if len(receipts) < len(CHAIN_ROLES):
            queue.append(CHAIN_ROLES[len(receipts)])

    has_err = any(r["status"] == "error" for r in receipts)
    has_blk = any(r["status"] == "blocked" for r in receipts)
    chain_status = (
        "error" if has_err else ("waiting_for_evidence" if has_blk else "completed")
    )
    accepted["cognitive_chain"] = {
        "version": 1,
        "mode": "drydock_in_process_queue",
        "status": chain_status,
        "max_tasks": len(CHAIN_ROLES),
        "tasks": receipts,
    }
    return accepted


def verify_cognitive_chain(
    state: Mapping[str, Any],
    *,
    binding: Mapping[str, Any],
    goals: Mapping[ChainRole, str],
) -> bool:
    """Проверяет целостность SHA-256 цепочки квитанций и финального состояния."""
    chain = state.get("cognitive_chain")
    if not isinstance(chain, dict):
        return False
    tasks = chain.get("tasks")
    if (
        chain.get("version") != 1
        or chain.get("mode") != "drydock_in_process_queue"
        or chain.get("max_tasks") != len(CHAIN_ROLES)
        or not isinstance(tasks, list)
        or len(tasks) != len(CHAIN_ROLES)
    ):
        return False

    prev_task: dict[str, Any] | None = None
    for role, task in zip(CHAIN_ROLES, tasks, strict=True):
        if not isinstance(task, dict):
            return False
        exp_id = canonical_digest([dict(binding), role])
        exp_dep = [prev_task["id"]] if prev_task is not None else []
        if (
            task.get("id") != exp_id
            or task.get("agent") != role
            or task.get("goal") != goals.get(role)
            or task.get("source") != dict(binding)
            or task.get("depends_on") != exp_dep
            or task.get("status") not in ("completed", "blocked", "error")
        ):
            return False
        if prev_task is not None and task.get("input_sha256") != prev_task.get(
            "output_sha256"
        ):
            return False
        prev_task = task

    has_err = any(t["status"] == "error" for t in tasks)
    has_blk = any(t["status"] == "blocked" for t in tasks)
    expected_status = (
        "error" if has_err else ("waiting_for_evidence" if has_blk else "completed")
    )
    if chain.get("status") != expected_status:
        return False
    final_sha = canonical_digest(_state_without_chain(state))
    return bool(prev_task is not None and prev_task["output_sha256"] == final_sha)
