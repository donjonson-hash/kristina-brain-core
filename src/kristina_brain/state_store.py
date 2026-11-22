"""
Единый неблокирующий слой хранения состояния агента StateStore (закрытие AUD-01 и AUD-05).
- Переносит все дисковые транзакции SQLite из главного потока asyncio в выделенный
  сериализованный исполнитель (или использует aiosqlite/asyncpg без блокировки event loop).
- Включает режим WAL, busy_timeout=5000 и мультитенантный ключ scope_id (поддержка тысяч агентов/юзеров в одной БД,
  а также обратную совместимость с таблицами id=1 из kristina_state.db).
- Хранит таймеры и антиспам-кулдауны проактивности (last_user_activity, last_proactive, next_opportunity_at)
  в таблице proactive_runtime_state вместо RAM-словарей bot.py (AUD-05).
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import (
    Any,
    Protocol,
    TypeVar,
    runtime_checkable,
)

from .intentions import DurableIntention
from .world import WorldStateAnchor

T = TypeVar("T")


@dataclass(frozen=True)
class ProactiveScheduleRecord:
    """Персистентное состояние проактивности чата/сессии (замена RAM-словарей bot.py — AUD-05)."""

    scope_id: str
    last_user_activity: datetime | None
    last_proactive_at: datetime | None
    next_opportunity_at: datetime | None
    proactive_count_24h: int = 0
    recent_intentions: tuple[str, ...] = ()


@runtime_checkable
class StateStore(Protocol):
    """Асинхронный протокол хранилища состояния мозга (SQLite WAL / PostgreSQL)."""

    async def initialize(self) -> None: ...
    async def close(self) -> None: ...

    # --- Быстрое эмоциональное состояние + идемпотентность ---
    async def load_fast_state(self, scope_id: str) -> dict[str, Any] | None: ...
    async def save_fast_state_atomic(
        self,
        scope_id: str,
        payload: Mapping[str, Any],
        *,
        event_tuple: tuple[str, str, str, str] | None = None,
    ) -> bool:
        """
        Атомарно сохраняет состояние. Если передан event_tuple=(session_sha256, event_id, input_sha256, applied_at),
        проверяет идемпотентность в одной транзакции: возвращает False, если событие уже применялось.
        """
        ...

    async def record_experiment_once(
        self, scope_id: str, experiment_id: str, outcome: str, applied_at: str
    ) -> bool: ...

    # --- 12 медленных мод организма ---
    async def load_modes(self, scope_id: str) -> dict[str, dict[str, Any]]: ...
    async def upsert_modes_atomic(
        self,
        scope_id: str,
        modes: Sequence[Mapping[str, Any]],
        *,
        mode_event: tuple[str, str, str, str, str] | None = None,
    ) -> bool: ...

    # --- Персистентные кулдауны проактивности (AUD-05) ---
    async def get_proactive_schedule(self, scope_id: str) -> ProactiveScheduleRecord: ...
    async def upsert_proactive_schedule(self, record: ProactiveScheduleRecord) -> None: ...

    # --- Якоря физического контекста и часового пояса собеседника (v0.5.0) ---
    async def get_world_anchor(self, scope_id: str) -> WorldStateAnchor: ...
    async def upsert_world_anchor(self, anchor: WorldStateAnchor) -> None: ...

    # --- Эпизодическое состояние диалога и Durable Intentions (v0.6.0) ---
    async def get_dialogue_state(self, scope_id: str) -> dict[str, Any] | None: ...
    async def save_dialogue_state(self, scope_id: str, state: Mapping[str, Any]) -> None: ...
    async def create_intention_if_free(self, intention: DurableIntention) -> bool: ...
    async def expire_overdue_intentions(self, scope_id: str, now_iso: str) -> int: ...
    async def claim_planned_intention(
        self, scope_id: str, now_iso: str, run_due_iso: str
    ) -> DurableIntention | None: ...
    async def finish_intention(
        self,
        intention_id: str,
        *,
        status: str,
        result: Mapping[str, Any] | None,
        reason: str | None,
        updated_at_iso: str,
    ) -> bool: ...
    async def list_intentions(self, scope_id: str, *, limit: int = 10) -> list[DurableIntention]: ...

    # --- Приватная Shadow-телеметрия решений без PII ---
    async def insert_shadow_telemetry_once(self, row: Mapping[str, Any]) -> bool: ...
    async def list_shadow_telemetry(
        self,
        *,
        limit: int = 100,
        kind: str | None = None,
        since_iso: str | None = None,
    ) -> list[dict[str, Any]]: ...


def _parse_iso_utc(raw: str | None) -> datetime | None:
    if not raw:
        return None
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


class AsyncSQLiteStateStore:
    """
    Высоконадежная асинхронная реализация StateStore поверх SQLite в режиме WAL:
    - Все операции выполняются в выделенном однопоточном пуле (Single-Writer Serialized Executor),
      поэтому главный asyncio event loop НЕ блокируется ни на микросекунду (AUD-01 fix),
      и при этом исключены гонки `sqlite3.OperationalError: database is locked`.
    - Не требует внешних C-расширений сверх стандартной библиотеки Python (совместимо и с aiosqlite-окружением).
    - Автоматически мигрирует legacy-строку `emotional_state(id=1)` из kristina_state.db при первом запуске.
    """

    def __init__(self, db_path: str | Path = "kristina_state.db") -> None:
        self.db_path = str(db_path)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="brain-sqlite-wal")
        self._conn: sqlite3.Connection | None = None
        self._closed = False

    async def _run(self, fn: Callable[[sqlite3.Connection], T]) -> T:
        if self._closed:
            raise RuntimeError("AsyncSQLiteStateStore is closed")
        loop = asyncio.get_running_loop()

        def _task() -> T:
            if self._conn is None:
                conn = sqlite3.connect(self.db_path, timeout=10.0, isolation_level=None)
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA journal_mode=WAL;")
                conn.execute("PRAGMA synchronous=NORMAL;")
                conn.execute("PRAGMA foreign_keys=ON;")
                conn.execute("PRAGMA busy_timeout=5000;")
                self._conn = conn
            return fn(self._conn)

        return await loop.run_in_executor(self._executor, _task)

    async def initialize(self) -> None:
        def _init_schema(conn: sqlite3.Connection) -> None:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                # 1. Мультитенантная таблица быстрого состояния
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS brain_emotional_state (
                        scope_id TEXT PRIMARY KEY,
                        payload TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                # Бесшовная миграция legacy таблицы emotional_state(id=1) из kristina-revolutionary
                legacy_exists = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='emotional_state'"
                ).fetchone()
                if legacy_exists:
                    legacy_row = conn.execute("SELECT payload FROM emotional_state WHERE id = 1").fetchone()
                    if legacy_row:
                        conn.execute(
                            """
                            INSERT OR IGNORE INTO brain_emotional_state(scope_id, payload, updated_at)
                            VALUES ('default', ?, ?)
                            """,
                            (legacy_row["payload"], datetime.now(UTC).isoformat()),
                        )

                # 2. Идемпотентный журнал событий (совместим со схемой emotional_message_events)
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS emotional_message_events (
                        session_sha256 TEXT NOT NULL,
                        event_id TEXT NOT NULL,
                        input_sha256 TEXT NOT NULL,
                        applied_at TEXT NOT NULL,
                        PRIMARY KEY (session_sha256, event_id)
                    )
                    """
                )

                # 3. Эффекты экспериментов
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS experiment_effects (
                        scope_id TEXT NOT NULL DEFAULT 'default',
                        experiment_id TEXT NOT NULL,
                        outcome TEXT NOT NULL,
                        applied_at TEXT NOT NULL,
                        PRIMARY KEY (scope_id, experiment_id)
                    )
                    """
                )

                # 4. Мультитенантные 12 медленных мод организма
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS brain_organism_modes (
                        scope_id TEXT NOT NULL,
                        name TEXT NOT NULL,
                        baseline REAL NOT NULL CHECK (baseline >= 0.0 AND baseline <= 1.0),
                        amplitude REAL NOT NULL CHECK (amplitude >= 0.0 AND amplitude <= 1.0),
                        phase REAL NOT NULL,
                        half_life_hours REAL NOT NULL CHECK (half_life_hours > 0.0),
                        updated_at TEXT NOT NULL,
                        version INTEGER NOT NULL DEFAULT 1,
                        PRIMARY KEY (scope_id, name)
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS organism_mode_events (
                        session_sha256 TEXT NOT NULL,
                        event_id TEXT NOT NULL,
                        payload_sha256 TEXT NOT NULL,
                        deltas_json TEXT NOT NULL,
                        applied_at TEXT NOT NULL,
                        PRIMARY KEY (session_sha256, event_id)
                    )
                    """
                )

                # 5. Персистентное состояние проактивности и антиспам-кулдаунов (AUD-05 fix)
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS proactive_runtime_state (
                        scope_id TEXT PRIMARY KEY,
                        last_user_activity TEXT,
                        last_proactive_at TEXT,
                        next_opportunity_at TEXT,
                        proactive_count_24h INTEGER NOT NULL DEFAULT 0,
                        recent_intentions_json TEXT NOT NULL DEFAULT '[]',
                        updated_at TEXT NOT NULL
                    )
                    """
                )

                # 5b. Якоря физического мира и таймзоны собеседника (v0.5.0)
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS brain_world_anchors (
                        scope_id TEXT PRIMARY KEY,
                        counterparty_location TEXT,
                        counterparty_timezone TEXT,
                        environment_cues_json TEXT NOT NULL DEFAULT '[]',
                        updated_at TEXT NOT NULL
                    )
                    """
                )

                # 5c. Эпизодическое состояние диалога и открытых вопросов (v0.6.0)
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS brain_dialogue_states (
                        scope_id TEXT PRIMARY KEY,
                        state_json TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )

                # 5d. Устойчивые автономные намерения (Durable Intentions — v0.6.0)
                conn.execute(
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
                        created_at TEXT NOT NULL,
                        due_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        plan_json TEXT,
                        result_json TEXT,
                        reason TEXT,
                        UNIQUE (scope_id, source_event_id)
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_brain_intentions_scope_updated ON brain_durable_intentions(scope_id, updated_at DESC)"
                )

                # 6. Shadow Decision Telemetry (совместима со схемой shadow_telemetry.py)
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS shadow_decision_telemetry (
                        observation_id TEXT PRIMARY KEY,
                        payload_sha256 TEXT NOT NULL,
                        kind TEXT NOT NULL CHECK (kind IN ('proactive','creative')),
                        scope_sha256 TEXT NOT NULL,
                        opportunity_at TEXT NOT NULL,
                        observed_at TEXT NOT NULL,
                        baseline_action TEXT NOT NULL,
                        baseline_intention TEXT,
                        baseline_score REAL NOT NULL,
                        baseline_reason TEXT NOT NULL,
                        shadow_action TEXT NOT NULL,
                        shadow_intention TEXT,
                        shadow_score REAL NOT NULL,
                        shadow_reason TEXT NOT NULL,
                        decision_changed INTEGER NOT NULL CHECK (decision_changed IN (0,1)),
                        action_changed INTEGER NOT NULL CHECK (action_changed IN (0,1)),
                        intention_changed INTEGER NOT NULL CHECK (intention_changed IN (0,1)),
                        max_abs_score_delta REAL NOT NULL,
                        score_deltas_json TEXT NOT NULL,
                        mode_deviations_json TEXT NOT NULL,
                        shifted_modes_json TEXT NOT NULL,
                        version INTEGER NOT NULL DEFAULT 1
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_shadow_decision_observed ON shadow_decision_telemetry(observed_at)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_shadow_decision_kind_observed ON shadow_decision_telemetry(kind, observed_at)"
                )
                conn.execute("COMMIT;")
            except Exception:
                conn.execute("ROLLBACK;")
                raise

        await self._run(_init_schema)

    async def close(self) -> None:
        if self._closed:
            return

        def _close_conn(conn: sqlite3.Connection) -> None:
            conn.close()

        if self._conn is not None:
            await self._run(_close_conn)
            self._conn = None
        self._closed = True
        self._executor.shutdown(wait=True)

    async def load_fast_state(self, scope_id: str = "default") -> dict[str, Any] | None:
        def _op(conn: sqlite3.Connection) -> dict[str, Any] | None:
            row = conn.execute(
                "SELECT payload FROM brain_emotional_state WHERE scope_id = ?",
                (scope_id,),
            ).fetchone()
            return json.loads(row["payload"]) if row else None

        return await self._run(_op)

    async def save_fast_state_atomic(
        self,
        scope_id: str,
        payload: Mapping[str, Any],
        *,
        event_tuple: tuple[str, str, str, str] | None = None,
    ) -> bool:
        serialized = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True)
        now_iso = str(payload.get("updated_at") or datetime.now(UTC).isoformat())

        def _op(conn: sqlite3.Connection) -> bool:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                if event_tuple is not None:
                    session_sha, event_id, input_sha, applied_at = event_tuple
                    existing = conn.execute(
                        """
                        SELECT input_sha256 FROM emotional_message_events
                        WHERE session_sha256 = ? AND event_id = ?
                        """,
                        (session_sha, event_id),
                    ).fetchone()
                    if existing is not None:
                        conn.execute("ROLLBACK;")
                        if existing["input_sha256"] != input_sha:
                            raise ValueError(f"Idempotency conflict for event_id={event_id}: different input_sha256")
                        return False

                    conn.execute(
                        """
                        INSERT INTO emotional_message_events(session_sha256, event_id, input_sha256, applied_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (session_sha, event_id, input_sha, applied_at),
                    )

                conn.execute(
                    """
                    INSERT INTO brain_emotional_state(scope_id, payload, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(scope_id) DO UPDATE SET
                        payload = excluded.payload,
                        updated_at = excluded.updated_at
                    """,
                    (scope_id, serialized, now_iso),
                )
                conn.execute("COMMIT;")
                return True
            except Exception:
                if conn.in_transaction:
                    conn.execute("ROLLBACK;")
                raise

        return await self._run(_op)

    async def record_experiment_once(
        self,
        scope_id: str,
        experiment_id: str,
        outcome: str,
        applied_at: str,
    ) -> bool:
        def _op(conn: sqlite3.Connection) -> bool:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO experiment_effects(scope_id, experiment_id, outcome, applied_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (scope_id, experiment_id, outcome, applied_at),
                )
                conn.execute("COMMIT;")
                return cur.rowcount == 1
            except Exception:
                if conn.in_transaction:
                    conn.execute("ROLLBACK;")
                raise

        return await self._run(_op)

    async def load_modes(self, scope_id: str = "default") -> dict[str, dict[str, Any]]:
        def _op(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
            rows = conn.execute(
                """
                SELECT name, baseline, amplitude, phase, half_life_hours, updated_at, version
                FROM brain_organism_modes
                WHERE scope_id = ?
                """,
                (scope_id,),
            ).fetchall()
            return {row["name"]: dict(row) for row in rows}

        return await self._run(_op)

    async def upsert_modes_atomic(
        self,
        scope_id: str,
        modes: Sequence[Mapping[str, Any]],
        *,
        mode_event: tuple[str, str, str, str, str] | None = None,
    ) -> bool:
        def _op(conn: sqlite3.Connection) -> bool:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                if mode_event is not None:
                    s_sha, ev_id, p_sha, deltas_json, app_at = mode_event
                    existing = conn.execute(
                        """
                        SELECT payload_sha256 FROM organism_mode_events
                        WHERE session_sha256 = ? AND event_id = ?
                        """,
                        (s_sha, ev_id),
                    ).fetchone()
                    if existing is not None:
                        conn.execute("ROLLBACK;")
                        if existing["payload_sha256"] != p_sha:
                            raise ValueError(f"Mode event hash mismatch for event_id={ev_id}")
                        return False
                    conn.execute(
                        """
                        INSERT INTO organism_mode_events(session_sha256, event_id, payload_sha256, deltas_json, applied_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (s_sha, ev_id, p_sha, deltas_json, app_at),
                    )

                for m in modes:
                    conn.execute(
                        """
                        INSERT INTO brain_organism_modes(
                            scope_id, name, baseline, amplitude, phase, half_life_hours, updated_at, version
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                        ON CONFLICT(scope_id, name) DO UPDATE SET
                            baseline = excluded.baseline,
                            amplitude = excluded.amplitude,
                            phase = excluded.phase,
                            half_life_hours = excluded.half_life_hours,
                            updated_at = excluded.updated_at,
                            version = brain_organism_modes.version + 1
                        """,
                        (
                            scope_id,
                            m["name"],
                            float(m["baseline"]),
                            float(m["amplitude"]),
                            float(m["phase"]),
                            float(m["half_life_hours"]),
                            str(m["updated_at"]),
                        ),
                    )
                conn.execute("COMMIT;")
                return True
            except Exception:
                if conn.in_transaction:
                    conn.execute("ROLLBACK;")
                raise

        return await self._run(_op)

    async def get_proactive_schedule(self, scope_id: str) -> ProactiveScheduleRecord:
        def _op(conn: sqlite3.Connection) -> ProactiveScheduleRecord:
            row = conn.execute(
                """
                SELECT last_user_activity, last_proactive_at, next_opportunity_at,
                       proactive_count_24h, recent_intentions_json
                FROM proactive_runtime_state
                WHERE scope_id = ?
                """,
                (scope_id,),
            ).fetchone()
            if row is None:
                return ProactiveScheduleRecord(
                    scope_id=scope_id,
                    last_user_activity=None,
                    last_proactive_at=None,
                    next_opportunity_at=None,
                    proactive_count_24h=0,
                    recent_intentions=(),
                )
            intentions = tuple(json.loads(row["recent_intentions_json"] or "[]"))
            return ProactiveScheduleRecord(
                scope_id=scope_id,
                last_user_activity=_parse_iso_utc(row["last_user_activity"]),
                last_proactive_at=_parse_iso_utc(row["last_proactive_at"]),
                next_opportunity_at=_parse_iso_utc(row["next_opportunity_at"]),
                proactive_count_24h=int(row["proactive_count_24h"]),
                recent_intentions=intentions,
            )

        return await self._run(_op)

    async def upsert_proactive_schedule(self, record: ProactiveScheduleRecord) -> None:
        now_iso = datetime.now(UTC).isoformat()
        recent_json = json.dumps(list(record.recent_intentions[-10:]), ensure_ascii=False)

        def _op(conn: sqlite3.Connection) -> None:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                conn.execute(
                    """
                    INSERT INTO proactive_runtime_state(
                        scope_id, last_user_activity, last_proactive_at, next_opportunity_at,
                        proactive_count_24h, recent_intentions_json, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(scope_id) DO UPDATE SET
                        last_user_activity = excluded.last_user_activity,
                        last_proactive_at = excluded.last_proactive_at,
                        next_opportunity_at = excluded.next_opportunity_at,
                        proactive_count_24h = excluded.proactive_count_24h,
                        recent_intentions_json = excluded.recent_intentions_json,
                        updated_at = excluded.updated_at
                    """,
                    (
                        record.scope_id,
                        record.last_user_activity.isoformat() if record.last_user_activity else None,
                        record.last_proactive_at.isoformat() if record.last_proactive_at else None,
                        record.next_opportunity_at.isoformat() if record.next_opportunity_at else None,
                        int(record.proactive_count_24h),
                        recent_json,
                        now_iso,
                    ),
                )
                conn.execute("COMMIT;")
            except Exception:
                if conn.in_transaction:
                    conn.execute("ROLLBACK;")
                raise

        await self._run(_op)

    async def insert_shadow_telemetry_once(self, row: Mapping[str, Any]) -> bool:
        def _op(conn: sqlite3.Connection) -> bool:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                existing = conn.execute(
                    "SELECT payload_sha256 FROM shadow_decision_telemetry WHERE observation_id = ?",
                    (row["observation_id"],),
                ).fetchone()
                if existing is not None:
                    conn.execute("ROLLBACK;")
                    return False

                conn.execute(
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
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (
                        row["observation_id"],
                        row["payload_sha256"],
                        row["kind"],
                        row["scope_sha256"],
                        row["opportunity_at"],
                        row["observed_at"],
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
                        row["score_deltas_json"],
                        row["mode_deviations_json"],
                        row["shifted_modes_json"],
                    ),
                )
                conn.execute("COMMIT;")
                return True
            except Exception:
                if conn.in_transaction:
                    conn.execute("ROLLBACK;")
                raise

        return await self._run(_op)

    async def list_shadow_telemetry(
        self,
        *,
        limit: int = 100,
        kind: str | None = None,
        since_iso: str | None = None,
    ) -> list[dict[str, Any]]:
        def _op(conn: sqlite3.Connection) -> list[dict[str, Any]]:
            clauses: list[str] = []
            params: list[Any] = []
            if kind:
                clauses.append("kind = ?")
                params.append(kind)
            if since_iso:
                clauses.append("observed_at >= ?")
                params.append(since_iso)
            where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            params.append(int(limit))
            rows = conn.execute(
                f"""
                SELECT * FROM shadow_decision_telemetry
                {where_sql}
                ORDER BY observed_at DESC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
            return [dict(r) for r in rows]

        return await self._run(_op)

    async def get_world_anchor(self, scope_id: str) -> WorldStateAnchor:
        def _op(conn: sqlite3.Connection) -> WorldStateAnchor:
            row = conn.execute(
                """
                SELECT counterparty_location, counterparty_timezone, environment_cues_json, updated_at
                FROM brain_world_anchors
                WHERE scope_id = ?
                """,
                (scope_id,),
            ).fetchone()
            if row is None:
                return WorldStateAnchor(scope_id=scope_id)
            cues = tuple(json.loads(row["environment_cues_json"] or "[]"))
            return WorldStateAnchor(
                scope_id=scope_id,
                counterparty_location=row["counterparty_location"],
                counterparty_timezone=row["counterparty_timezone"],
                environment_cues=cues,
                updated_at=_parse_iso_utc(row["updated_at"]),
            )

        return await self._run(_op)

    async def upsert_world_anchor(self, anchor: WorldStateAnchor) -> None:
        now_iso = (anchor.updated_at or datetime.now(UTC)).isoformat()
        cues_json = json.dumps(list(anchor.environment_cues[-5:]), ensure_ascii=False)

        def _op(conn: sqlite3.Connection) -> None:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                conn.execute(
                    """
                    INSERT INTO brain_world_anchors(
                        scope_id, counterparty_location, counterparty_timezone, environment_cues_json, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(scope_id) DO UPDATE SET
                        counterparty_location = excluded.counterparty_location,
                        counterparty_timezone = excluded.counterparty_timezone,
                        environment_cues_json = excluded.environment_cues_json,
                        updated_at = excluded.updated_at
                    """,
                    (
                        anchor.scope_id,
                        anchor.counterparty_location,
                        anchor.counterparty_timezone,
                        cues_json,
                        now_iso,
                    ),
                )
                conn.execute("COMMIT;")
            except Exception:
                if conn.in_transaction:
                    conn.execute("ROLLBACK;")
                raise

        await self._run(_op)

    @staticmethod
    def _decode_intention_row(row: sqlite3.Row) -> DurableIntention:
        created = _parse_iso_utc(row["created_at"]) or datetime.now(UTC)
        due = _parse_iso_utc(row["due_at"]) or created
        updated = _parse_iso_utc(row["updated_at"]) or created
        return DurableIntention(
            intention_id=str(row["intention_id"]),
            scope_id=str(row["scope_id"]),
            source_event_id=str(row["source_event_id"]),
            kind=str(row["kind"]),
            topic=str(row["topic"]),
            status=str(row["status"]),
            created_at=created,
            due_at=due,
            updated_at=updated,
            plan=json.loads(row["plan_json"]) if row["plan_json"] else None,
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            reason=row["reason"],
        )

    async def get_dialogue_state(self, scope_id: str) -> dict[str, Any] | None:
        def _op(conn: sqlite3.Connection) -> dict[str, Any] | None:
            row = conn.execute(
                "SELECT state_json FROM brain_dialogue_states WHERE scope_id = ?",
                (scope_id,),
            ).fetchone()
            return json.loads(row["state_json"]) if row else None

        return await self._run(_op)

    async def save_dialogue_state(self, scope_id: str, state: Mapping[str, Any]) -> None:
        payload = json.dumps(dict(state), ensure_ascii=False, allow_nan=False)
        now_iso = datetime.now(UTC).isoformat()

        def _op(conn: sqlite3.Connection) -> None:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                conn.execute(
                    """
                    INSERT INTO brain_dialogue_states(scope_id, state_json, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(scope_id) DO UPDATE SET
                        state_json = excluded.state_json,
                        updated_at = excluded.updated_at
                    """,
                    (scope_id, payload, now_iso),
                )
                conn.execute("COMMIT;")
            except Exception:
                if conn.in_transaction:
                    conn.execute("ROLLBACK;")
                raise

        await self._run(_op)

    async def expire_overdue_intentions(self, scope_id: str, now_iso: str) -> int:
        def _op(conn: sqlite3.Connection) -> int:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                cur = conn.execute(
                    """
                    UPDATE brain_durable_intentions
                    SET status = 'failed', reason = status || '_timeout', updated_at = ?
                    WHERE scope_id = ? AND status IN ('planning', 'planned', 'running') AND due_at <= ?
                    """,
                    (now_iso, scope_id, now_iso),
                )
                conn.execute("COMMIT;")
                return cur.rowcount
            except Exception:
                if conn.in_transaction:
                    conn.execute("ROLLBACK;")
                raise

        return await self._run(_op)

    async def create_intention_if_free(self, intention: DurableIntention) -> bool:
        plan_str = json.dumps(intention.plan, ensure_ascii=False) if intention.plan is not None else None

        def _op(conn: sqlite3.Connection) -> bool:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                active = conn.execute(
                    """
                    SELECT 1 FROM brain_durable_intentions
                    WHERE scope_id = ? AND status IN ('planning', 'planned', 'running')
                    LIMIT 1
                    """,
                    (intention.scope_id,),
                ).fetchone()
                if active is not None:
                    conn.execute("ROLLBACK;")
                    return False

                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO brain_durable_intentions(
                        intention_id, scope_id, source_event_id, kind, topic, status,
                        created_at, due_at, updated_at, plan_json, result_json, reason
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
                    """,
                    (
                        intention.intention_id,
                        intention.scope_id,
                        intention.source_event_id,
                        intention.kind,
                        intention.topic,
                        intention.status,
                        intention.created_at.isoformat(),
                        intention.due_at.isoformat(),
                        intention.updated_at.isoformat(),
                        plan_str,
                    ),
                )
                conn.execute("COMMIT;")
                return cur.rowcount == 1
            except Exception:
                if conn.in_transaction:
                    conn.execute("ROLLBACK;")
                raise

        return await self._run(_op)

    async def claim_planned_intention(self, scope_id: str, now_iso: str, run_due_iso: str) -> DurableIntention | None:
        def _op(conn: sqlite3.Connection) -> DurableIntention | None:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                running = conn.execute(
                    "SELECT 1 FROM brain_durable_intentions WHERE scope_id = ? AND status = 'running' LIMIT 1",
                    (scope_id,),
                ).fetchone()
                if running is not None:
                    conn.execute("ROLLBACK;")
                    return None

                cand = conn.execute(
                    """
                    SELECT * FROM brain_durable_intentions
                    WHERE scope_id = ? AND status = 'planned'
                    ORDER BY created_at ASC LIMIT 1
                    """,
                    (scope_id,),
                ).fetchone()
                if cand is None:
                    conn.execute("ROLLBACK;")
                    return None

                conn.execute(
                    """
                    UPDATE brain_durable_intentions
                    SET status = 'running', due_at = ?, updated_at = ?
                    WHERE intention_id = ?
                    """,
                    (run_due_iso, now_iso, cand["intention_id"]),
                )
                updated_row = conn.execute(
                    "SELECT * FROM brain_durable_intentions WHERE intention_id = ?",
                    (cand["intention_id"],),
                ).fetchone()
                conn.execute("COMMIT;")
                return self._decode_intention_row(updated_row) if updated_row else None
            except Exception:
                if conn.in_transaction:
                    conn.execute("ROLLBACK;")
                raise

        return await self._run(_op)

    async def finish_intention(
        self,
        intention_id: str,
        *,
        status: str,
        result: Mapping[str, Any] | None,
        reason: str | None,
        updated_at_iso: str,
    ) -> bool:
        res_str = json.dumps(dict(result), ensure_ascii=False) if result is not None else None

        def _op(conn: sqlite3.Connection) -> bool:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                cur = conn.execute(
                    """
                    UPDATE brain_durable_intentions
                    SET status = ?, result_json = ?, reason = ?, updated_at = ?
                    WHERE intention_id = ?
                    """,
                    (status, res_str, reason, updated_at_iso, intention_id),
                )
                conn.execute("COMMIT;")
                return cur.rowcount == 1
            except Exception:
                if conn.in_transaction:
                    conn.execute("ROLLBACK;")
                raise

        return await self._run(_op)

    async def list_intentions(self, scope_id: str, *, limit: int = 10) -> list[DurableIntention]:
        def _op(conn: sqlite3.Connection) -> list[DurableIntention]:
            rows = conn.execute(
                """
                SELECT * FROM brain_durable_intentions
                WHERE scope_id = ?
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (scope_id, int(limit)),
            ).fetchall()
            return [self._decode_intention_row(r) for r in rows]

        return await self._run(_op)
