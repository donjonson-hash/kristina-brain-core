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

from kristina_brain import (
    DEFAULT_KRISTINA_PROFILE,
    Appraisal,
    AsyncSQLiteStateStore,
    BigFiveTraits,
    BrainEngine,
    FixedClock,
    HTTPXChatCompletionsProvider,
    PersonaProfile,
)
from kristina_brain.llm_provider import FailoverLLMProvider, LLMHTTPError
from kristina_brain.mcp_server import BrainMCPServer


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
        json_mode: bool = False,
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

        logger = logging.getLogger("kristina_brain.llm_provider")
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
                    {
                        "brain_get_state",
                        "brain_ingest_event",
                        "brain_decide_proactive",
                        "brain_get_world_context",
                        "brain_record_reply",
                        "brain_schedule_intention",
                        "brain_list_intentions",
                        "brain_shadow_summary",
                    },
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

    async def test_think_strip_aliases_and_failover_circuit_breaker(self) -> None:
        """v0.3: Очистка <think>, алиас joy->warmth и отключение HTTP 410 провайдера с 1-й ошибки."""
        parsed = Appraisal.parse(
            '<think>Модель долго думает...</think>```json\n{"reaction":"joy","intensity":0.92,'
            '"source_quote":"Ура","interest_action":"keep","topic":"release","reflection":"ok"}\n```',
            "Ура!",
        )
        self.assertEqual(parsed.reaction, "warmth")
        self.assertAlmostEqual(parsed.intensity, 0.92, places=2)

        class Dead410Provider:
            def __init__(self) -> None:
                self.calls = 0

            async def complete(self, messages: Sequence[dict[str, str]], **kwargs: object) -> str:
                self.calls += 1
                raise LLMHTTPError(410, "model retired")

            async def aclose(self) -> None:
                return None

        dead = Dead410Provider()
        backup = FakeLLMProvider(
            '{"reaction":"curiosity","intensity":0.8,"source_quote":"q","interest_action":"keep","topic":"t","reflection":"r"}'
        )
        cascade = FailoverLLMProvider([dead, backup])

        for _ in range(4):
            out = await cascade.complete([{"role": "user", "content": "hi"}], json_mode=True)
            self.assertIn("curiosity", out)

        # Dead410Provider вызывается СТРОГО 1 раз, дальше мгновенно работает backup!
        self.assertEqual(dead.calls, 1)
        self.assertEqual(backup.calls, 4)

    async def test_b2b_conflict_brake_blocks_angry_client_and_recovers_after_resolution(self) -> None:
        """v0.4: 12 медленных мод блокируют проактивный пинг злого клиента (wants_space), пропускают тёплого и восстанавливаются после примирения."""
        base_profile = PersonaProfile.from_json_file("profiles/b2b_csm_profile.json")
        profile = PersonaProfile(
            persona_id=base_profile.persona_id,
            display_name=base_profile.display_name,
            timezone=base_profile.timezone,
            locale_city_label=base_profile.locale_city_label,
            night_hours=base_profile.night_hours,
            traits=base_profile.traits,
            proactive_threshold=0.52,
            proactive_cooldown_seconds=base_profile.proactive_cooldown_seconds,
            enable_slow_modes_in_decisions=True,
        )
        with tempfile.TemporaryDirectory() as tmp:
            store = AsyncSQLiteStateStore(Path(tmp) / "b2b.db")
            clock = FixedClock(datetime(2026, 11, 2, 9, 0, tzinfo=UTC), "Europe/Berlin")
            engine = BrainEngine(store, profile=profile, clock=clock)
            await engine.start()
            try:
                # Тёплый клиент vs разгневанный клиент vs холодный клиент
                await engine.ingest_message(
                    scope_id="acme",
                    event_id="e1",
                    user_input="Отличный онбординг!",
                    explicit_appraisal=Appraisal("warmth", 0.85, "Отличный", "keep", "onboarding", "ok"),
                )
                await engine.ingest_message(
                    scope_id="globex",
                    event_id="g1",
                    user_input="Прод лежит!",
                    explicit_appraisal=Appraisal("frustration", 1.0, "Прод лежит", "open", "outage", "angry"),
                )
                await engine.ingest_message(
                    scope_id="initech",
                    event_id="i1",
                    user_input="Ок, посмотрим позже",
                    explicit_appraisal=Appraisal("neutral", 0.3, "Ок", "keep", "ack", "cold"),
                )

                clock.advance(hours=24)
                await engine.ingest_message(
                    scope_id="acme",
                    event_id="e2",
                    user_input="Как подключить Enterprise SSO?",
                    explicit_appraisal=Appraisal("curiosity", 0.85, "SSO", "open", "sso", "upsell"),
                )
                await engine.ingest_message(
                    scope_id="globex",
                    event_id="g2",
                    user_input="Не вздумайте слать чекины, мы уходим!",
                    explicit_appraisal=Appraisal("frustration", 0.95, "уходим", "open", "churn", "furious"),
                )

                clock.advance(hours=52)
                t_acme = await engine.heartbeat_tick("acme", commit_proactive_send=True)
                t_glob = await engine.heartbeat_tick("globex", commit_proactive_send=True)
                t_init = await engine.heartbeat_tick("initech", commit_proactive_send=True)

                self.assertEqual(t_acme["effective_decision"]["action"], "message")
                self.assertEqual(t_glob["effective_decision"]["action"], "none")
                self.assertEqual(t_glob["effective_decision"]["reason"], "wants_space")
                self.assertEqual(t_init["effective_decision"]["action"], "none")
            finally:
                await engine.shutdown()

    async def test_v050_dual_clock_unawatuna_vs_stockholm_and_pacing(self) -> None:
        """v0.5.0: Стокгольм (21:00 вечера) не будит собеседника в Унаватуне (01:30 ночи Asia/Colombo) + считает pacing."""
        with tempfile.TemporaryDirectory() as tmp:
            store = AsyncSQLiteStateStore(Path(tmp) / "v050.db")
            # 10:20 UTC = 11:20 Стокгольм / 15:50 Коломбо (+4.5ч)
            clock = FixedClock(datetime(2026, 11, 22, 10, 20, tzinfo=UTC), "Europe/Stockholm")
            engine = BrainEngine(store, clock=clock)
            await engine.start()
            try:
                res = await engine.ingest_message(
                    scope_id="tg:unawatuna",
                    event_id="m-1",
                    user_input="Я пишу тебе со Шри-Ланки. Домик в Унаватуне на берегу океана, до воды 50 метров.",
                    explicit_appraisal=Appraisal(
                        reaction="warmth",
                        intensity=0.85,
                        source_quote="Домик в Унаватуне на берегу океана",
                        interest_action="keep",
                        topic="Шри-Ланка",
                        reflection="Тёплый живой контакт с океана",
                        detected_location="Унаватуна, Шри-Ланка",
                        detected_timezone=None,  # Проверяем авто-резолв Asia/Colombo по названию города!
                        environment_cue="домик на берегу океана, 50 метров до воды",
                    ),
                )
                self.assertEqual(res["world_anchor"]["counterparty_timezone"], "Asia/Colombo")
                self.assertAlmostEqual(res["world_anchor"]["offset_hours_diff"], 4.5, places=2)
                self.assertGreaterEqual(res["response_pacing"]["delay_seconds"], 12.0)
                self.assertIn("Asia/Colombo", res["fast_state"]["for_llm"])

                # Переводим часы на 20:00 UTC -> в Стокгольме 21:00 вечера (не ночь!), а в Унаватуне уже 01:30 ночи!
                clock.set_utc(datetime(2026, 11, 22, 20, 0, tzinfo=UTC))
                tick_late = await engine.heartbeat_tick("tg:unawatuna", commit_proactive_send=False)
                self.assertEqual(tick_late["effective_decision"]["action"], "none")
                self.assertEqual(tick_late["effective_decision"]["reason"], "counterparty_quiet_hours")
            finally:
                await engine.shutdown()

    async def test_v060_episodic_dialogue_gates_anti_repeat_and_durable_intentions(self) -> None:
        """v0.6.0: Антиповтор вопросов, блокировка пинга при открытом вопросе и жизненный цикл Durable Intentions."""
        profile = PersonaProfile(
            persona_id="companion_v06",
            display_name="Kristina",
            timezone="Europe/Stockholm",
            locale_city_label="Стокгольме",
            traits=BigFiveTraits(extraversion=0.9, openness=0.9, neuroticism=0.1),
            proactive_threshold=0.45,
            proactive_cooldown_seconds=1800,
            enable_slow_modes_in_decisions=True,
        )
        with tempfile.TemporaryDirectory() as tmp:
            store = AsyncSQLiteStateStore(Path(tmp) / "v060.db")
            clock = FixedClock(datetime(2026, 11, 22, 11, 0, tzinfo=UTC), "Europe/Stockholm")
            engine = BrainEngine(store, profile=profile, clock=clock)
            await engine.start()
            try:
                # 1. Входящее сообщение с высоким интересом автоматически создаёт DurableIntention
                ing = await engine.ingest_message(
                    scope_id="u:ocean",
                    event_id="ev-10",
                    user_input="Хочу построить автономного яхтенного навигатора на локальной LLM!",
                    explicit_appraisal=Appraisal(
                        reaction="curiosity",
                        intensity=0.88,
                        source_quote="автономного яхтенного навигатора",
                        interest_action="open",
                        topic="морская LLM-навигация",
                        reflection="Очень интересная инженерная тема",
                    ),
                )
                self.assertIsNotNone(ing["scheduled_intention_id"])

                # 2. Захватываем намерение в работу и завершаем его с результатом
                claimed = await engine.intentions.claim_next_planned("u:ocean")
                self.assertIsNotNone(claimed)
                assert claimed is not None
                self.assertEqual(claimed.status, "running")
                done = await engine.intentions.complete(
                    claimed.intention_id,
                    result={"summary": "Проверила офлайн-карты OpenSeaMap и NMEA 2000 поток"},
                )
                self.assertTrue(done)

                # 3. Агент отвечает вопросом про волны -> повторный похожий вопрос отбивается!
                r1 = await engine.record_assistant_reply(
                    scope_id="u:ocean",
                    reply_id="a-1",
                    reply_text="Крутая идея! А волны ночью реально слышно из домика на берегу океана?",
                    is_proactive=False,
                )
                self.assertTrue(r1["accepted"])

                r_dup = await engine.record_assistant_reply(
                    scope_id="u:ocean",
                    reply_id="a-2",
                    reply_text="Слушай, скажи: волны ночью реально слышно из домика на берегу океана?",
                    is_proactive=True,
                )
                self.assertFalse(r_dup["accepted"])
                self.assertEqual(r_dup["reason"], "repeated_question")

                # 4. Пока пользователь не ответил на открытый вопрос a-1, проактивный тик заблокирован awaiting_answer!
                clock.advance(hours=3)
                tick_blocked = await engine.heartbeat_tick("u:ocean", commit_proactive_send=False)
                self.assertEqual(tick_blocked["effective_decision"]["action"], "none")
                self.assertEqual(tick_blocked["effective_decision"]["reason"], "awaiting_answer")

                # 5. Пользователь отвечает -> вопрос закрывается в answered, блокировка снимается!
                await engine.ingest_message(
                    scope_id="u:ocean",
                    event_id="ev-11",
                    user_input="Да, прибой шумит всю ночь прямо под окнами!",
                    explicit_appraisal=Appraisal("warmth", 0.8, "прибой шумит", "keep", "океан", "ответил"),
                )
                clock.advance(hours=3)
                tick_unblocked = await engine.heartbeat_tick("u:ocean", commit_proactive_send=False)
                self.assertEqual(tick_unblocked["effective_decision"]["action"], "message")
            finally:
                await engine.shutdown()


if __name__ == "__main__":
    unittest.main()
