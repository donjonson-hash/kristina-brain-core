"""
Движок устойчивых автономных намерений (DurableIntentionEngine — v0.6.0).
Позволяет агенту планировать фоновые исследования, эксперименты или отложенные задачи
между сессиями диалога с контролем дедлайнов (due_at), дедупликацией по источнику
и автоматической обратной связью в эмоциональное ядро.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from .clock import ClockProvider, SystemClock

if TYPE_CHECKING:
    from .state_store import StateStore

ALLOWED_INTENTION_STATUSES = frozenset(
    {"planning", "planned", "running", "completed", "declined", "failed", "cancelled"}
)
ACTIVE_INTENTION_STATUSES = frozenset({"planning", "planned", "running"})


@dataclass(frozen=True)
class DurableIntention:
    intention_id: str
    scope_id: str
    source_event_id: str
    kind: str  # напр. "topic_research" | "followup_prep" | "technical_check"
    topic: str
    status: str
    created_at: datetime
    due_at: datetime
    updated_at: datetime
    plan: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    reason: str | None = None


class DurableIntentionEngine:
    """Мультитенантный менеджер жизненного цикла автономных намерений поверх StateStore."""

    def __init__(
        self,
        store: StateStore,
        *,
        clock: ClockProvider | None = None,
        default_ttl_minutes: int = 45,
    ) -> None:
        self.store = store
        self.clock: ClockProvider = clock or SystemClock("UTC")
        self.default_ttl_minutes = max(1, int(default_ttl_minutes))

    async def schedule(
        self,
        *,
        scope_id: str,
        source_event_id: str,
        kind: str,
        topic: str,
        plan: dict[str, Any] | None = None,
        ttl_minutes: int | None = None,
    ) -> DurableIntention | None:
        """
        Планирует новое устойчивое намерение для scope_id, если у этого scope_id
        нет другого активного намерения и данный source_event_id ещё не планировался.
        """
        now = self.clock.now_utc()
        await self.store.expire_overdue_intentions(scope_id, now.isoformat())

        due = now + timedelta(minutes=ttl_minutes or self.default_ttl_minutes)
        intention = DurableIntention(
            intention_id=uuid.uuid4().hex,
            scope_id=scope_id,
            source_event_id=source_event_id,
            kind=kind.strip()[:64] or "general",
            topic=topic.strip()[:200] or "autonomous_task",
            status="planned",
            created_at=now,
            due_at=due,
            updated_at=now,
            plan=plan,
        )
        created = await self.store.create_intention_if_free(intention)
        return intention if created else None

    async def claim_next_planned(self, scope_id: str, *, run_ttl_minutes: int = 15) -> DurableIntention | None:
        """Переводит ближайшее planned-намерение в running с новым дедлайном выполнения."""
        now = self.clock.now_utc()
        await self.store.expire_overdue_intentions(scope_id, now.isoformat())
        run_due = now + timedelta(minutes=max(1, run_ttl_minutes))
        return await self.store.claim_planned_intention(scope_id, now.isoformat(), run_due.isoformat())

    async def complete(
        self,
        intention_id: str,
        *,
        result: dict[str, Any],
        status: str = "completed",
        reason: str | None = None,
    ) -> bool:
        if status not in ("completed", "failed", "declined", "cancelled"):
            raise ValueError(f"Invalid terminal status: {status}")
        now = self.clock.now_utc()
        return await self.store.finish_intention(
            intention_id,
            status=status,
            result=result,
            reason=reason,
            updated_at_iso=now.isoformat(),
        )

    async def list_for_scope(self, scope_id: str, *, limit: int = 10) -> list[DurableIntention]:
        now = self.clock.now_utc()
        await self.store.expire_overdue_intentions(scope_id, now.isoformat())
        return await self.store.list_intentions(scope_id, limit=limit)

    @staticmethod
    def format_prompt_context(intentions: list[DurableIntention]) -> str:
        if not intentions:
            return ""
        latest = intentions[0]
        if latest.status in ACTIVE_INTENTION_STATUSES:
            return f"Активное фоновое намерение ({latest.kind}): «{latest.topic}» [статус={latest.status}]."
        if latest.status == "completed" and latest.result:
            summary = str(latest.result.get("summary", ""))[:180]
            return f"Завершённое фоновое намерение по теме «{latest.topic}»: {summary}".strip()
        return ""
