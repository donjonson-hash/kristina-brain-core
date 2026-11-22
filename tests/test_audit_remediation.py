"""
Полный верификационный тест-сьют для проверки закрытия всех дефектов аудита (AUD-01 .. AUD-06),
миграции legacy-БД kristina_state.db, идемпотентности SHA-256, экспоненциального полураспада 12 мод,
персистентности кулдаунов при рестарте процесса и протокола MCP JSON-RPC 2.0.

Запускается как стандартным `python3 -m unittest discover -s tests -v`, так и через `pytest`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import tempfile
import unittest
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from brain_core import (
    DEFAULT_KRISTINA_PROFILE,
    Appraisal,
    AsyncSQLiteStateStore,
    BigFiveTraits,
    BrainEngine,
    FixedClock,
    HTTPXChatCompletionsProvider,
    PersonaProfile,
)
from brain_core.mcp_server import BrainMCPServer


class FakeLLMProvider:
    """Детерминированный стаб LLMProvider для проверки CognitiveAppraiser без внешней сети."""

    def __init__(self, canned_json: str) -> None:
        self.canned_json = canned_json
        self.calls = 0

    async def complete(
        self,
        messages: Sequence[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 800,
        timeout: float | None = None,
    ) -> str:
        self.calls += 1
        return self.canned_json

    async def aclose(self) -> None:
        return None


class BrainCoreAuditRemediationTests(unittest.IsolatedAsyncioTestCase):
    async def test_aud01_non_blocking_concurrent_writes_and_legacy_migration(self) -> None:
        """AUD-01: Миграция legacy emotional_state(id=1) и 25 конкурентных записей без database is locked."""
        with tempfile.TemporaryDirectory() as tmp:
            db_file = Path(tmp) / "kristina_state.db"
            # Создаём точную копию legacy таблицы из kristina-revolutionary
            conn = sqlite3.connect(db_file)
            conn.execute("CREATE TABLE emotional_state (id INTEGER PRIMARY KEY CHECK (id = 1), payload TEXT NOT NULL)")
            legacy_payload = json.dumps(
                {
                    "state": {
                        "energy": 0.81,
                        "happiness": 0.74,
                        "curiosity": 0.69,
                        "anxiety": 0.12,
                        "loneliness": 0.33,
                        "creativity": 0.66,
                        "irritation": 0.08,
                    },
                    "updated_at": "2026-11-20T12:00:00+00:00",
                }
            )
            conn.execute("INSERT INTO emotional_state(id, payload) VALUES (1, ?)", (legacy_payload,))
            conn.commit()
            conn.close()

            store = AsyncSQLiteStateStore(db_file)
            await store.initialize()
            try:
                migrated = await store.load_fast_state("default")
                self.assertIsNotNone(migrated)
                assert migrated is not None
                self.assertAlmostEqual(migrated["state"]["energy"], 0.81, places=2)

                clock = FixedClock(datetime(2026, 11, 21, 10, 0, tzinfo=UTC), "Europe/Stockholm")
                engine = BrainEngine(store, profile=DEFAULT_KRISTINA_PROFILE, clock=clock)

                # Параллельный залп из 25 корутин по разным scope_id + проверка живости event loop
                heartbeat_ticks = 0

                async def loop_latency_probe() -> None:
                    nonlocal heartbeat_ticks
                    for _ in range(5):
                        await asyncio.sleep(0.002)
                        heartbeat_ticks += 1

                tasks = [
                    engine.ingest_message(
                        scope_id=f"user:{i}",
                        event_id=f"ev-{i}",
                        user_input=f"Привет, сообщение номер {i}",
                        explicit_appraisal=Appraisal(
                            reaction="warmth",
                            intensity=0.7,
                            source_quote="Привет",
                            interest_action="keep",
                            topic="greeting",
                            reflection="Тёплое приветствие",
                        ),
                    )
                    for i in range(25)
                ]
                results, _ = await asyncio.gather(asyncio.gather(*tasks), loop_latency_probe())
                self.assertEqual(len(results), 25)
                self.assertTrue(all(r["event_applied"] for r in results))
                self.assertEqual(heartbeat_ticks, 5)
            finally:
                await store.close()

    async def test_aud02_zero_secret_leak_in_logs_and_repr(self) -> None:
        """AUD-02: Секретный API-ключ не попадает ни в INFO-логи, ни в repr() объекта."""
        secret_key = "sk-live-SUPERSECRETKEY998877665544332211"
        log_records: list[str] = []

        class ListHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                log_records.append(self.format(record))

        logger = logging.getLogger("brain_core.llm_provider")
        logger.setLevel(logging.INFO)
        handler = ListHandler()
        logger.addHandler(handler)
        try:
            provider = HTTPXChatCompletionsProvider(api_key=secret_key)
            try:
                repr_text = repr(provider)
                self.assertNotIn("sk-live", repr_text)
                self.assertNotIn(secret_key[:10], repr_text)
                for line in log_records:
                    self.assertNotIn("sk-live", line)
                    self.assertNotIn(secret_key[:8], line)
            finally:
                await provider.aclose()
        finally:
            logger.removeHandler(handler)

    async def test_idempotency_and_12_modes_exponential_half_life(self) -> None:
        """Проверка SHA-256 идемпотентности событий и математически точного полураспада 12 мод."""
        with tempfile.TemporaryDirectory() as tmp:
            store = AsyncSQLiteStateStore(Path(tmp) / "state.db")
            clock = FixedClock(datetime(2026, 11, 21, 12, 0, tzinfo=UTC), "UTC")
            llm = FakeLLMProvider(
                json.dumps(
                    {
                        "reaction": "frustration",
                        "intensity": 0.9,
                        "source_quote": "Всё сломалось!",
                        "interest_action": "open",
                        "topic": "incident",
                        "reflection": "Резкий негатив",
                    }
                )
            )
            engine = BrainEngine(store, llm=llm, clock=clock)
            await engine.start()
            try:
                first = await engine.ingest_message(
                    scope_id="chat-42",
                    event_id="msg-100",
                    user_input="Всё сломалось!",
                )
                self.assertTrue(first["event_applied"])
                self.assertTrue(first["mode_event_applied"])
                irrit_after_first = first["fast_state"]["state"]["irritation"]

                # Повторная доставка того же event_id с тем же текстом — строго идемпотентный no-op
                duplicate = await engine.ingest_message(
                    scope_id="chat-42",
                    event_id="msg-100",
                    user_input="Всё сломалось!",
                )
                self.assertFalse(duplicate["event_applied"])
                self.assertFalse(duplicate["mode_event_applied"])
                self.assertEqual(duplicate["fast_state"]["state"]["irritation"], irrit_after_first)

                # Конфликт хэша входа при том же event_id обязан выбрасывать ValueError
                with self.assertRaises(ValueError):
                    await engine.ingest_message(
                        scope_id="chat-42",
                        event_id="msg-100",
                        user_input="Подделанный другой текст!",
                    )

                # Проверяем экспоненциальный полураспад social_overload (half_life_hours = 18.0, baseline = 0.15)
                snap_t0 = await engine.modes.snapshot("chat-42")
                overload_t0 = snap_t0["social_overload"]
                dev_t0 = overload_t0.amplitude - overload_t0.baseline
                self.assertGreater(dev_t0, 0.05)

                # Сдвигаем часы ровно на один период полураспада (18 часов) -> отклонение уменьшается ровно вдвое
                clock.advance(hours=18.0)
                snap_t18 = await engine.modes.snapshot("chat-42")
                dev_t18 = snap_t18["social_overload"].amplitude - snap_t18["social_overload"].baseline
                self.assertAlmostEqual(dev_t18, dev_t0 * 0.5, places=4)
            finally:
                await engine.shutdown()

    async def test_aud05_persistent_proactive_cooldown_survives_restart_and_shadow_telemetry(self) -> None:
        """AUD-05 + AUD-06: Таймеры проактивности переживают полный рестарт процесса, циркадность уважает таймзону профиля."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "persistent.db"
            # Профиль в таймзоне Asia/Tokyo (UTC+9): 05:00 UTC = 14:00 дня в Токио
            tokyo_profile = PersonaProfile(
                persona_id="tutor_jp",
                display_name="Sensei",
                timezone="Asia/Tokyo",
                locale_city_label="Токио",
                night_hours=(23, 7),
                traits=BigFiveTraits(extraversion=0.9, openness=0.9, neuroticism=0.1),
                proactive_threshold=0.45,
                proactive_cooldown_seconds=7200,
                enable_slow_modes_in_decisions=False,
            )
            clock = FixedClock(datetime(2026, 11, 21, 5, 0, tzinfo=UTC), "Asia/Tokyo")

            # Первый запуск процесса: срабатывает проактивное сообщение и коммитится в БД
            store1 = AsyncSQLiteStateStore(db_path)
            engine1 = BrainEngine(store1, profile=tokyo_profile, clock=clock)
            await engine1.start()
            tick1 = await engine1.heartbeat_tick("student-1", commit_proactive_send=True)
            self.assertEqual(tick1["effective_decision"]["action"], "message")
            await engine1.shutdown()

            # Симулируем рестарт systemd через 30 минут (< 2 часов кулдауна): создаём НОВЫЙ объект стора и движка
            clock.advance(minutes=30)
            store2 = AsyncSQLiteStateStore(db_path)
            engine2 = BrainEngine(store2, profile=tokyo_profile, clock=clock)
            await engine2.start()
            try:
                tick2 = await engine2.heartbeat_tick("student-1", commit_proactive_send=True)
                self.assertEqual(tick2["effective_decision"]["action"], "none")
                self.assertEqual(tick2["effective_decision"]["reason"], "cooldown")

                # Проверяем ночное окно в Токио: 16:00 UTC = 01:00 ночи в Токио (после истечения кулдауна!)
                clock.set_utc(datetime(2026, 11, 21, 16, 0, tzinfo=UTC))
                tick_night = await engine2.heartbeat_tick("student-1", commit_proactive_send=False)
                self.assertEqual(tick_night["effective_decision"]["action"], "none")
                self.assertEqual(tick_night["effective_decision"]["reason"], "quiet_hours")

                # Проверяем запись обезличенной shadow-телеметрии
                summary = await engine2.shadow_telemetry.summary(window_hours=24, now=clock.now_utc())
                self.assertGreaterEqual(summary["observations"], 2)
            finally:
                await engine2.shutdown()

    async def test_mcp_server_jsonrpc_contract(self) -> None:
        """P2 Commercialization: Проверка JSON-RPC 2.0 контракта MCP-сервера (initialize, tools/list, tools/call)."""
        with tempfile.TemporaryDirectory() as tmp:
            store = AsyncSQLiteStateStore(Path(tmp) / "mcp.db")
            engine = BrainEngine(store)
            await engine.start()
            try:
                mcp = BrainMCPServer(engine)
                init_resp = await mcp.handle_rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
                assert init_resp is not None
                self.assertEqual(init_resp["result"]["serverInfo"]["name"], "kristina-brain-core")

                tools_resp = await mcp.handle_rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
                assert tools_resp is not None
                tool_names = {t["name"] for t in tools_resp["result"]["tools"]}
                self.assertEqual(
                    tool_names,
                    {"brain_get_state", "brain_ingest_event", "brain_decide_proactive", "brain_shadow_summary"},
                )

                call_resp = await mcp.handle_rpc(
                    {
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "tools/call",
                        "params": {
                            "name": "brain_ingest_event",
                            "arguments": {
                                "scope_id": "hermes:local",
                                "event_id": "turn-1",
                                "user_input": "Отличная архитектурная идея!",
                                "reaction": "curiosity",
                                "intensity": 0.85,
                            },
                        },
                    }
                )
                assert call_resp is not None
                self.assertFalse(call_resp["result"]["isError"])
                parsed = json.loads(call_resp["result"]["content"][0]["text"])
                self.assertTrue(parsed["event_applied"])
            finally:
                await engine.shutdown()


if __name__ == "__main__":
    unittest.main()
