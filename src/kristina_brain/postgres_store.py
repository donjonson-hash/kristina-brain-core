"""
Облачная мультитенантная реализация StateStore поверх пула PostgreSQL (asyncpg — v0.7.0).
- Использует нативный JSONB, транзакционную идемпотентность и FOR UPDATE SKIP LOCKED
  при захвате фоновых намерений несколькими воркерами Control Plane.
- Не требует установленного asyncpg при работе в локальном SQLite-режиме (ленивый импорт).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .artifacts import CreativeArtifact
from .intentions import DurableIntention
from .state_store import AsyncSQLiteStateStore, ProactiveScheduleRecord, StateStore
from .world import WorldStateAnchor


def _dt_utc(val: Any) -> datetime | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.replace(tzinfo=UTC) if val.tzinfo is None else val.astimezone(UTC)
    dt = datetime.fromisoformat(str(val))
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _loads_if_str(val: Any, default: Any) -> Any:
    if val is None:
        return default
    if isinstance(val, (dict, list)):
        return val
    return json.loads(str(val))


POSTGRES_DDL_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS brain_emotional_state (
        scope_id TEXT PRIMARY KEY,
        payload JSONB NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS emotional_message_events (
        session_sha256 TEXT NOT NULL,
        event_id TEXT NOT NULL,
        input_sha256 TEXT NOT NULL,
        applied_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY (session_sha256, event_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS experiment_effects (
        scope_id TEXT NOT NULL DEFAULT 'default',
        experiment_id TEXT NOT NULL,
        outcome TEXT NOT NULL,
        applied_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY (scope_id, experiment_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS brain_organism_modes (
        scope_id TEXT NOT NULL,
        name TEXT NOT NULL,
        baseline DOUBLE PRECISION NOT NULL CHECK (baseline >= 0.0 AND baseline <= 1.0),
        amplitude DOUBLE PRECISION NOT NULL CHECK (amplitude >= 0.0 AND amplitude <= 1.0),
        phase DOUBLE PRECISION NOT NULL,
        half_life_hours DOUBLE PRECISION NOT NULL CHECK (half_life_hours > 0.0),
        updated_at TIMESTAMPTZ NOT NULL,
        version INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY (scope_id, name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS organism_mode_events (
        session_sha256 TEXT NOT NULL,
        event_id TEXT NOT NULL,
        payload_sha256 TEXT NOT NULL,
        deltas_json JSONB NOT NULL,
        applied_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY (session_sha256, event_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS proactive_runtime_state (
        scope_id TEXT PRIMARY KEY,
        last_user_activity TIMESTAMPTZ,
        last_proactive_at TIMESTAMPTZ,
        next_opportunity_at TIMESTAMPTZ,
        proactive_count_24h INTEGER NOT NULL DEFAULT 0,
        recent_intentions_json JSONB NOT NULL DEFAULT '[]'::jsonb,
        updated_at TIMESTAMPTZ NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS brain_world_anchors (
        scope_id TEXT PRIMARY KEY,
        counterparty_location TEXT,
        counterparty_timezone TEXT,
        environment_cues_json JSONB NOT NULL DEFAULT '[]'::jsonb,
        updated_at TIMESTAMPTZ NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS brain_dialogue_states (
        scope_id TEXT PRIMARY KEY,
        state_json JSONB NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS brain_durable_intentions (
        intention_id TEXT PRIMARY KEY,
        scope_id TEXT NOT NULL,
        source_event_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        topic TEXT NOT NULL,
        status TEXT NOT NULL CHECK (
            status IN ('planning','planned','running','completed','declined','failed','cancelled')
        ),
        created_at TIMESTAMPTZ NOT NULL,
        due_at TIMESTAMPTZ NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL,
        plan_json JSONB,
        result_json JSONB,
        reason TEXT,
        UNIQUE (scope_id, source_event_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_pg_brain_intentions_scope_updated ON brain_durable_intentions(scope_id, updated_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS shadow_decision_telemetry (
        observation_id TEXT PRIMARY KEY,
        payload_sha256 TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('proactive','creative')),
        scope_sha256 TEXT NOT NULL,
        opportunity_at TIMESTAMPTZ NOT NULL,
        observed_at TIMESTAMPTZ NOT NULL,
        baseline_action TEXT NOT NULL,
        baseline_intention TEXT,
        baseline_score DOUBLE PRECISION NOT NULL,
        baseline_reason TEXT NOT NULL,
        shadow_action TEXT NOT NULL,
        shadow_intention TEXT,
        shadow_score DOUBLE PRECISION NOT NULL,
        shadow_reason TEXT NOT NULL,
        decision_changed INTEGER NOT NULL CHECK (decision_changed IN (0,1)),
        action_changed INTEGER NOT NULL CHECK (action_changed IN (0,1)),
        intention_changed INTEGER NOT NULL CHECK (intention_changed IN (0,1)),
        max_abs_score_delta DOUBLE PRECISION NOT NULL,
        score_deltas_json JSONB NOT NULL,
        mode_deviations_json JSONB NOT NULL,
        shifted_modes_json JSONB NOT NULL,
        version INTEGER NOT NULL DEFAULT 1
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS brain_creative_artifacts (
        scope_id TEXT NOT NULL,
        artifact_id TEXT NOT NULL,
        title TEXT NOT NULL,
        excerpt TEXT NOT NULL,
        status_note TEXT NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL,
        PRIMARY KEY (scope_id, artifact_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS brain_neural_graphs (
        scope_id TEXT PRIMARY KEY,
        graph_json JSONB NOT NULL,
        updated_at TIMESTAMPTZ NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_pg_shadow_observed ON shadow_decision_telemetry(observed_at DESC)",
)


class AsyncPostgresStateStore:
    """Асинхронное облачное хранилище состояния поверх пула соединений asyncpg."""

    def __init__(
        self,
        dsn: str,
        *,
        min_pool_size: int = 2,
        max_pool_size: int = 20,
        pool: Any | None = None,
    ) -> None:
        self.dsn = dsn
        self.min_pool_size = int(min_pool_size)
        self.max_pool_size = int(max_pool_size)
        self._pool: Any | None = pool
        self._owns_pool = pool is None

    def __repr__(self) -> str:
        return f"AsyncPostgresStateStore(dsn='***REDACTED***', max_pool_size={self.max_pool_size})"

    async def _ensure_pool(self) -> Any:
        if self._pool is None:
            try:
                import asyncpg  # type: ignore[import-not-found]
            except ImportError as exc:
                raise RuntimeError(
                    "asyncpg is required for PostgreSQL mode: pip install 'kristina-brain-core[postgres]'"
                ) from exc
            self._pool = await asyncpg.create_pool(
                dsn=self.dsn,
                min_size=self.min_pool_size,
                max_size=self.max_pool_size,
            )
        return self._pool

    async def initialize(self) -> None:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn, conn.transaction():
            for ddl in POSTGRES_DDL_STATEMENTS:
                await conn.execute(ddl)

    async def close(self) -> None:
        if self._pool is not None and self._owns_pool:
            await self._pool.close()
            self._pool = None

    async def load_fast_state(self, scope_id: str = "default") -> dict[str, Any] | None:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT payload FROM brain_emotional_state WHERE scope_id = $1",
                scope_id,
            )
            if row is None:
                return None
            res: dict[str, Any] = _loads_if_str(row["payload"], {})
            return res

    async def save_fast_state_atomic(
        self,
        scope_id: str,
        payload: Mapping[str, Any],
        *,
        event_tuple: tuple[str, str, str, str] | None = None,
    ) -> bool:
        pool = await self._ensure_pool()
        serialized = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True)
        updated_dt = _dt_utc(payload.get("updated_at")) or datetime.now(UTC)

        async with pool.acquire() as conn, conn.transaction():
            if event_tuple is not None:
                session_sha, event_id, input_sha, applied_iso = event_tuple
                existing = await conn.fetchrow(
                    """
                    SELECT input_sha256 FROM emotional_message_events
                    WHERE session_sha256 = $1 AND event_id = $2
                    """,
                    session_sha,
                    event_id,
                )
                if existing is not None:
                    if existing["input_sha256"] != input_sha:
                        raise ValueError(f"Idempotency conflict for event_id={event_id}")
                    return False
                await conn.execute(
                    """
                    INSERT INTO emotional_message_events(session_sha256, event_id, input_sha256, applied_at)
                    VALUES ($1, $2, $3, $4)
                    """,
                    session_sha,
                    event_id,
                    input_sha,
                    _dt_utc(applied_iso) or updated_dt,
                )

            await conn.execute(
                """
                INSERT INTO brain_emotional_state(scope_id, payload, updated_at)
                VALUES ($1, $2::jsonb, $3)
                ON CONFLICT (scope_id) DO UPDATE SET
                    payload = EXCLUDED.payload,
                    updated_at = EXCLUDED.updated_at
                """,
                scope_id,
                serialized,
                updated_dt,
            )
            return True

    async def record_experiment_once(self, scope_id: str, experiment_id: str, outcome: str, applied_at: str) -> bool:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn, conn.transaction():
            status_tag: str = await conn.execute(
                """
                INSERT INTO experiment_effects(scope_id, experiment_id, outcome, applied_at)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (scope_id, experiment_id) DO NOTHING
                """,
                scope_id,
                experiment_id,
                outcome,
                _dt_utc(applied_at) or datetime.now(UTC),
            )
            return status_tag.endswith(" 1")

    async def load_modes(self, scope_id: str = "default") -> dict[str, dict[str, Any]]:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT name, baseline, amplitude, phase, half_life_hours, updated_at, version
                FROM brain_organism_modes
                WHERE scope_id = $1
                """,
                scope_id,
            )
            out: dict[str, dict[str, Any]] = {}
            for r in rows:
                d = dict(r)
                dt = _dt_utc(d["updated_at"])
                d["updated_at"] = dt.isoformat() if dt else datetime.now(UTC).isoformat()
                out[str(d["name"])] = d
            return out

    async def upsert_modes_atomic(
        self,
        scope_id: str,
        modes: Sequence[Mapping[str, Any]],
        *,
        mode_event: tuple[str, str, str, str, str] | None = None,
    ) -> bool:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn, conn.transaction():
            if mode_event is not None:
                s_sha, ev_id, p_sha, deltas_json, app_at = mode_event
                existing = await conn.fetchrow(
                    """
                    SELECT payload_sha256 FROM organism_mode_events
                    WHERE session_sha256 = $1 AND event_id = $2
                    """,
                    s_sha,
                    ev_id,
                )
                if existing is not None:
                    if existing["payload_sha256"] != p_sha:
                        raise ValueError(f"Mode event hash mismatch for event_id={ev_id}")
                    return False
                await conn.execute(
                    """
                    INSERT INTO organism_mode_events(session_sha256, event_id, payload_sha256, deltas_json, applied_at)
                    VALUES ($1, $2, $3, $4::jsonb, $5)
                    """,
                    s_sha,
                    ev_id,
                    p_sha,
                    deltas_json,
                    _dt_utc(app_at) or datetime.now(UTC),
                )

            for m in modes:
                await conn.execute(
                    """
                    INSERT INTO brain_organism_modes(
                        scope_id, name, baseline, amplitude, phase, half_life_hours, updated_at, version
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, 1)
                    ON CONFLICT (scope_id, name) DO UPDATE SET
                        baseline = EXCLUDED.baseline,
                        amplitude = EXCLUDED.amplitude,
                        phase = EXCLUDED.phase,
                        half_life_hours = EXCLUDED.half_life_hours,
                        updated_at = EXCLUDED.updated_at,
                        version = brain_organism_modes.version + 1
                    """,
                    scope_id,
                    str(m["name"]),
                    float(m["baseline"]),
                    float(m["amplitude"]),
                    float(m["phase"]),
                    float(m["half_life_hours"]),
                    _dt_utc(m["updated_at"]) or datetime.now(UTC),
                )
            return True

    async def get_proactive_schedule(self, scope_id: str) -> ProactiveScheduleRecord:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT last_user_activity, last_proactive_at, next_opportunity_at,
                       proactive_count_24h, recent_intentions_json
                FROM proactive_runtime_state
                WHERE scope_id = $1
                """,
                scope_id,
            )
            if row is None:
                return ProactiveScheduleRecord(
                    scope_id=scope_id,
                    last_user_activity=None,
                    last_proactive_at=None,
                    next_opportunity_at=None,
                )
            intents = tuple(_loads_if_str(row["recent_intentions_json"], []))
            return ProactiveScheduleRecord(
                scope_id=scope_id,
                last_user_activity=_dt_utc(row["last_user_activity"]),
                last_proactive_at=_dt_utc(row["last_proactive_at"]),
                next_opportunity_at=_dt_utc(row["next_opportunity_at"]),
                proactive_count_24h=int(row["proactive_count_24h"]),
                recent_intentions=intents,
            )

    async def upsert_proactive_schedule(self, record: ProactiveScheduleRecord) -> None:
        pool = await self._ensure_pool()
        recent_json = json.dumps(list(record.recent_intentions[-10:]), ensure_ascii=False)
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute(
                """
                INSERT INTO proactive_runtime_state(
                    scope_id, last_user_activity, last_proactive_at, next_opportunity_at,
                    proactive_count_24h, recent_intentions_json, updated_at
                )
                VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)
                ON CONFLICT (scope_id) DO UPDATE SET
                    last_user_activity = EXCLUDED.last_user_activity,
                    last_proactive_at = EXCLUDED.last_proactive_at,
                    next_opportunity_at = EXCLUDED.next_opportunity_at,
                    proactive_count_24h = EXCLUDED.proactive_count_24h,
                    recent_intentions_json = EXCLUDED.recent_intentions_json,
                    updated_at = EXCLUDED.updated_at
                """,
                record.scope_id,
                record.last_user_activity,
                record.last_proactive_at,
                record.next_opportunity_at,
                int(record.proactive_count_24h),
                recent_json,
                datetime.now(UTC),
            )

    async def get_world_anchor(self, scope_id: str) -> WorldStateAnchor:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT counterparty_location, counterparty_timezone, environment_cues_json, updated_at
                FROM brain_world_anchors
                WHERE scope_id = $1
                """,
                scope_id,
            )
            if row is None:
                return WorldStateAnchor(scope_id=scope_id)
            cues = tuple(_loads_if_str(row["environment_cues_json"], []))
            return WorldStateAnchor(
                scope_id=scope_id,
                counterparty_location=row["counterparty_location"],
                counterparty_timezone=row["counterparty_timezone"],
                environment_cues=cues,
                updated_at=_dt_utc(row["updated_at"]),
            )

    async def upsert_world_anchor(self, anchor: WorldStateAnchor) -> None:
        pool = await self._ensure_pool()
        cues_json = json.dumps(list(anchor.environment_cues[-5:]), ensure_ascii=False)
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute(
                """
                INSERT INTO brain_world_anchors(
                    scope_id, counterparty_location, counterparty_timezone, environment_cues_json, updated_at
                )
                VALUES ($1, $2, $3, $4::jsonb, $5)
                ON CONFLICT (scope_id) DO UPDATE SET
                    counterparty_location = EXCLUDED.counterparty_location,
                    counterparty_timezone = EXCLUDED.counterparty_timezone,
                    environment_cues_json = EXCLUDED.environment_cues_json,
                    updated_at = EXCLUDED.updated_at
                """,
                anchor.scope_id,
                anchor.counterparty_location,
                anchor.counterparty_timezone,
                cues_json,
                anchor.updated_at or datetime.now(UTC),
            )

    async def get_dialogue_state(self, scope_id: str) -> dict[str, Any] | None:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT state_json FROM brain_dialogue_states WHERE scope_id = $1",
                scope_id,
            )
            if row is None:
                return None
            res: dict[str, Any] = _loads_if_str(row["state_json"], {})
            return res

    async def save_dialogue_state(self, scope_id: str, state: Mapping[str, Any]) -> None:
        pool = await self._ensure_pool()
        payload = json.dumps(dict(state), ensure_ascii=False, allow_nan=False)
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute(
                """
                INSERT INTO brain_dialogue_states(scope_id, state_json, updated_at)
                VALUES ($1, $2::jsonb, $3)
                ON CONFLICT (scope_id) DO UPDATE SET
                    state_json = EXCLUDED.state_json,
                    updated_at = EXCLUDED.updated_at
                """,
                scope_id,
                payload,
                datetime.now(UTC),
            )

    @staticmethod
    def _decode_pg_intention(row: Any) -> DurableIntention:
        created = _dt_utc(row["created_at"]) or datetime.now(UTC)
        return DurableIntention(
            intention_id=str(row["intention_id"]),
            scope_id=str(row["scope_id"]),
            source_event_id=str(row["source_event_id"]),
            kind=str(row["kind"]),
            topic=str(row["topic"]),
            status=str(row["status"]),
            created_at=created,
            due_at=_dt_utc(row["due_at"]) or created,
            updated_at=_dt_utc(row["updated_at"]) or created,
            plan=_loads_if_str(row["plan_json"], None),
            result=_loads_if_str(row["result_json"], None),
            reason=row["reason"],
        )

    async def expire_overdue_intentions(self, scope_id: str, now_iso: str) -> int:
        pool = await self._ensure_pool()
        now_dt = _dt_utc(now_iso) or datetime.now(UTC)
        async with pool.acquire() as conn, conn.transaction():
            tag: str = await conn.execute(
                """
                UPDATE brain_durable_intentions
                SET status = 'failed', reason = status || '_timeout', updated_at = $1
                WHERE scope_id = $2 AND status IN ('planning', 'planned', 'running') AND due_at <= $1
                """,
                now_dt,
                scope_id,
            )
            parts = tag.split()
            return int(parts[-1]) if parts and parts[-1].isdigit() else 0

    async def create_intention_if_free(self, intention: DurableIntention) -> bool:
        pool = await self._ensure_pool()
        plan_str = json.dumps(intention.plan, ensure_ascii=False) if intention.plan is not None else None
        async with pool.acquire() as conn, conn.transaction():
            active = await conn.fetchrow(
                """
                SELECT 1 FROM brain_durable_intentions
                WHERE scope_id = $1 AND status IN ('planning', 'planned', 'running')
                LIMIT 1
                """,
                intention.scope_id,
            )
            if active is not None:
                return False
            tag: str = await conn.execute(
                """
                INSERT INTO brain_durable_intentions(
                    intention_id, scope_id, source_event_id, kind, topic, status,
                    created_at, due_at, updated_at, plan_json, result_json, reason
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, NULL, NULL)
                ON CONFLICT (scope_id, source_event_id) DO NOTHING
                """,
                intention.intention_id,
                intention.scope_id,
                intention.source_event_id,
                intention.kind,
                intention.topic,
                intention.status,
                intention.created_at,
                intention.due_at,
                intention.updated_at,
                plan_str,
            )
            return tag.endswith(" 1")

    async def claim_planned_intention(self, scope_id: str, now_iso: str, run_due_iso: str) -> DurableIntention | None:
        pool = await self._ensure_pool()
        now_dt = _dt_utc(now_iso) or datetime.now(UTC)
        due_dt = _dt_utc(run_due_iso) or now_dt
        async with pool.acquire() as conn, conn.transaction():
            running = await conn.fetchrow(
                "SELECT 1 FROM brain_durable_intentions WHERE scope_id = $1 AND status = 'running' LIMIT 1",
                scope_id,
            )
            if running is not None:
                return None

            cand = await conn.fetchrow(
                """
                SELECT intention_id FROM brain_durable_intentions
                WHERE scope_id = $1 AND status = 'planned'
                ORDER BY created_at ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
                """,
                scope_id,
            )
            if cand is None:
                return None

            row = await conn.fetchrow(
                """
                UPDATE brain_durable_intentions
                SET status = 'running', due_at = $1, updated_at = $2
                WHERE intention_id = $3
                RETURNING *
                """,
                due_dt,
                now_dt,
                cand["intention_id"],
            )
            return self._decode_pg_intention(row) if row else None

    async def finish_intention(
        self,
        intention_id: str,
        *,
        status: str,
        result: Mapping[str, Any] | None,
        reason: str | None,
        updated_at_iso: str,
    ) -> bool:
        pool = await self._ensure_pool()
        res_str = json.dumps(dict(result), ensure_ascii=False) if result is not None else None
        async with pool.acquire() as conn, conn.transaction():
            tag: str = await conn.execute(
                """
                UPDATE brain_durable_intentions
                SET status = $1, result_json = $2::jsonb, reason = $3, updated_at = $4
                WHERE intention_id = $5
                """,
                status,
                res_str,
                reason,
                _dt_utc(updated_at_iso) or datetime.now(UTC),
                intention_id,
            )
            return tag.endswith(" 1")

    async def list_intentions(self, scope_id: str, *, limit: int = 10) -> list[DurableIntention]:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM brain_durable_intentions
                WHERE scope_id = $1
                ORDER BY updated_at DESC
                LIMIT $2
                """,
                scope_id,
                int(limit),
            )
            return [self._decode_pg_intention(r) for r in rows]

    async def insert_shadow_telemetry_once(self, row: Mapping[str, Any]) -> bool:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn, conn.transaction():
            tag: str = await conn.execute(
                """
                INSERT INTO shadow_decision_telemetry(
                    observation_id, payload_sha256, kind, scope_sha256,
                    opportunity_at, observed_at,
                    baseline_action, baseline_intention, baseline_score, baseline_reason,
                    shadow_action, shadow_intention, shadow_score, shadow_reason,
                    decision_changed, action_changed, intention_changed,
                    max_abs_score_delta, score_deltas_json,
                    mode_deviations_json, shifted_modes_json, version
                )
                VALUES (
                    $1, $2, $3, $4, $5, $6,
                    $7, $8, $9, $10,
                    $11, $12, $13, $14,
                    $15, $16, $17, $18,
                    $19::jsonb, $20::jsonb, $21::jsonb, 1
                )
                ON CONFLICT (observation_id) DO NOTHING
                """,
                row["observation_id"],
                row["payload_sha256"],
                row["kind"],
                row["scope_sha256"],
                _dt_utc(row["opportunity_at"]) or datetime.now(UTC),
                _dt_utc(row["observed_at"]) or datetime.now(UTC),
                row["baseline_action"],
                row.get("baseline_intention"),
                float(row["baseline_score"]),
                row["baseline_reason"],
                row["shadow_action"],
                row.get("shadow_intention"),
                float(row["shadow_score"]),
                row["shadow_reason"],
                1 if row["decision_changed"] else 0,
                1 if row["action_changed"] else 0,
                1 if row["intention_changed"] else 0,
                float(row["max_abs_score_delta"]),
                str(row["score_deltas_json"]),
                str(row["mode_deviations_json"]),
                str(row["shifted_modes_json"]),
            )
            return tag.endswith(" 1")

    async def list_shadow_telemetry(
        self,
        *,
        limit: int = 100,
        kind: str | None = None,
        since_iso: str | None = None,
    ) -> list[dict[str, Any]]:
        pool = await self._ensure_pool()
        clauses: list[str] = []
        params: list[Any] = []
        if kind:
            params.append(kind)
            clauses.append(f"kind = ${len(params)}")
        if since_iso:
            params.append(_dt_utc(since_iso) or datetime.now(UTC))
            clauses.append(f"observed_at >= ${len(params)}")
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(int(limit))
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT * FROM shadow_decision_telemetry
                {where_sql}
                ORDER BY observed_at DESC
                LIMIT ${len(params)}
                """,
                *params,
            )
            return [dict(r) for r in rows]

    async def upsert_artifact(self, artifact: CreativeArtifact) -> None:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute(
                """
                INSERT INTO brain_creative_artifacts(
                    scope_id, artifact_id, title, excerpt, status_note, updated_at
                )
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (scope_id, artifact_id) DO UPDATE SET
                    title = EXCLUDED.title,
                    excerpt = EXCLUDED.excerpt,
                    status_note = EXCLUDED.status_note,
                    updated_at = EXCLUDED.updated_at
                """,
                artifact.scope_id,
                artifact.artifact_id,
                artifact.title[:160],
                artifact.excerpt[:2000],
                artifact.status_note[:160],
                artifact.updated_at,
            )

    async def list_artifacts(self, scope_id: str, *, limit: int = 5) -> list[CreativeArtifact]:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT scope_id, artifact_id, title, excerpt, status_note, updated_at
                FROM brain_creative_artifacts
                WHERE scope_id = $1
                ORDER BY updated_at DESC
                LIMIT $2
                """,
                scope_id,
                int(limit),
            )
            return [
                CreativeArtifact(
                    artifact_id=str(r["artifact_id"]),
                    scope_id=str(r["scope_id"]),
                    title=str(r["title"]),
                    excerpt=str(r["excerpt"]),
                    status_note=str(r["status_note"]),
                    updated_at=_dt_utc(r["updated_at"]) or datetime.now(UTC),
                )
                for r in rows
            ]

    async def load_neural_graph(self, scope_id: str) -> dict[str, Any] | None:
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT graph_json FROM brain_neural_graphs WHERE scope_id = $1",
                scope_id,
            )
            if row is None:
                return None
            res: dict[str, Any] = _loads_if_str(row["graph_json"], {})
            return res

    async def save_neural_graph(self, scope_id: str, graph: Mapping[str, Any]) -> None:
        pool = await self._ensure_pool()
        serialized = json.dumps(dict(graph), ensure_ascii=False)
        async with pool.acquire() as conn, conn.transaction():
            await conn.execute(
                """
                INSERT INTO brain_neural_graphs(scope_id, graph_json, updated_at)
                VALUES ($1, $2::jsonb, $3)
                ON CONFLICT (scope_id) DO UPDATE SET
                    graph_json = EXCLUDED.graph_json,
                    updated_at = EXCLUDED.updated_at
                """,
                scope_id,
                serialized,
                _dt_utc(graph.get("updated_at")) or datetime.now(UTC),
            )


def create_state_store(dsn_or_path: str | Path = "kristina_state.db") -> StateStore:
    """Универсальная фабрика: postgresql:// -> AsyncPostgresStateStore, иначе AsyncSQLiteStateStore."""
    raw = str(dsn_or_path).strip()
    if raw.startswith(("postgresql://", "postgres://")):
        return AsyncPostgresStateStore(raw)
    return AsyncSQLiteStateStore(raw)
