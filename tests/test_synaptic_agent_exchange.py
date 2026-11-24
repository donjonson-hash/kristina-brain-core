"""
Интеграционные тесты синаптического обмена и онлайн-обсерватории (kristina-brain-core v1.2.0).
Проверяют:
1) Пакетную трассировку packet_trace (hop 1 -> hop 2) и счётчик pulse_seq.
2) Подавление подпорогового шума (0 токенов LLM).
3) Тормозной синапс ГАМК (-0.95) sensor_conflict -> gate_proactive_outreach.
4) Рефрактерное окно моторных шлюзов (REFRACTORY_BLOCKED).
5) Трёхфакторное обучение Хебба во сне и сохранность врождённых тормозов (plasticity=0.0).
6) Публичные zero-PII эндпоинты /neuro-studio и /neuro-studio/api/*.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from kristina_brain import (
    Appraisal,
    AsyncSQLiteStateStore,
    BrainEngine,
    FixedClock,
    SynapticGraphEngine,
)
from kristina_brain.control_plane import create_control_plane_app


@pytest.mark.asyncio
async def test_packet_trace_cascade_curiosity_to_creative_gate(tmp_path: Path) -> None:
    clock = FixedClock(datetime(2026, 11, 23, 12, 0, tzinfo=UTC))
    store = AsyncSQLiteStateStore(str(tmp_path / "brain.db"))
    engine = BrainEngine(store, clock=clock)
    await engine.start()
    try:
        pulse = await engine.pulse_synapses(
            "kristina",
            {"sensor_curiosity": 0.95, "sensor_warmth": 0.50},
        )
        assert pulse["pulse_seq"] == 1
        assert "gate_creative_imagination" in pulse["opened_motor_gates"]
        trace = pulse["packet_trace"]
        assert len(trace) >= 2
        hops = {int(pkt["hop"]) for pkt in trace}
        assert 1 in hops and 2 in hops
        fired_targets = {str(pkt["target_id"]) for pkt in trace if pkt["outcome"] == "FIRED"}
        assert "inter_creative_spark" in fired_targets
        assert "gate_creative_imagination" in fired_targets
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_subthreshold_noise_stays_silent(tmp_path: Path) -> None:
    clock = FixedClock(datetime(2026, 11, 23, 12, 0, tzinfo=UTC))
    store = AsyncSQLiteStateStore(str(tmp_path / "brain.db"))
    engine = BrainEngine(store, clock=clock)
    await engine.start()
    try:
        pulse = await engine.pulse_synapses("kristina", {"sensor_curiosity": 0.12})
        assert pulse["opened_motor_gates"] == []
        assert pulse["requires_llm_cortex"] is False
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_gaba_inhibitory_synapse_blocks_outreach_on_conflict(tmp_path: Path) -> None:
    clock = FixedClock(datetime(2026, 11, 23, 12, 0, tzinfo=UTC))
    store = AsyncSQLiteStateStore(str(tmp_path / "brain.db"))
    engine = BrainEngine(store, clock=clock)
    await engine.start()
    try:
        pulse = await engine.pulse_synapses(
            "kristina",
            {"sensor_warmth": 0.92, "sensor_silence_window": 0.85, "sensor_conflict": 0.95},
        )
        assert "gate_proactive_outreach" not in pulse["opened_motor_gates"]
        assert "gate_urgent_escalation" in pulse["opened_motor_gates"]
        inhibited = [p for p in pulse["packet_trace"] if p["outcome"] == "INHIBITED"]
        assert len(inhibited) >= 1
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_refractory_window_records_refractory_blocked_outcome(tmp_path: Path) -> None:
    clock = FixedClock(datetime(2026, 11, 23, 12, 0, tzinfo=UTC))
    store = AsyncSQLiteStateStore(str(tmp_path / "brain.db"))
    engine = BrainEngine(store, clock=clock)
    await engine.start()
    try:
        p1 = await engine.pulse_synapses("kristina", {"sensor_curiosity": 0.96})
        assert "gate_creative_imagination" in p1["opened_motor_gates"]

        clock.advance(seconds=1)
        p_fast = await engine.pulse_synapses("kristina", {"sensor_curiosity": 0.96})
        assert p_fast["opened_motor_gates"] == []
        assert p_fast["packet_trace"][0]["outcome"] == "REFRACTORY_BLOCKED"

        clock.advance(seconds=89)
        p2 = await engine.pulse_synapses("kristina", {"sensor_curiosity": 0.96})
        assert "gate_creative_imagination" not in p2["opened_motor_gates"]
        outcomes = {
            str(p["outcome"])
            for p in p2["packet_trace"]
            if p["target_id"] == "gate_creative_imagination"
        }
        assert "REFRACTORY_BLOCKED" in outcomes

        clock.advance(minutes=35)
        p3 = await engine.pulse_synapses("kristina", {"sensor_curiosity": 0.96})
        assert "gate_creative_imagination" in p3["opened_motor_gates"]
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_hebbian_sleep_preserves_pulse_seq_and_safety_brakes(tmp_path: Path) -> None:
    clock = FixedClock(datetime(2026, 11, 23, 12, 0, tzinfo=UTC))
    store = AsyncSQLiteStateStore(str(tmp_path / "brain.db"))
    engine = BrainEngine(store, clock=clock)
    synaptic = SynapticGraphEngine(store, clock=clock)
    await engine.start()
    try:
        _, before_edges = await synaptic.ensure_circuit("kristina", at=clock.now_utc())
        w_before = before_edges["sensor_curiosity->inter_creative_spark"].weight

        await engine.pulse_synapses("kristina", {"sensor_curiosity": 0.95})
        await engine.run_sleep_consolidation("kristina", reward_signal=0.88)

        graph = await synaptic.inspect_graph("kristina")
        assert graph["pulse_seq"] == 1
        after_map = {str(s["edge"]): float(s["weight"]) for s in graph["synapses"]}
        assert after_map["sensor_curiosity->inter_creative_spark"] > w_before
        assert after_map["sensor_conflict->gate_proactive_outreach"] == -0.95
    finally:
        await engine.shutdown()


def test_online_observatory_zero_pii_and_sandbox_isolation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_file = str(tmp_path / "cloud_observatory.db")
    secret_phrase = "Секретный номер паспорта 998877 и личное сообщение в Телеграм"

    async def _seed_private_turn() -> None:
        st = AsyncSQLiteStateStore(db_file)
        eng = BrainEngine(st)
        await eng.start()
        try:
            await eng.ingest_message(
                scope_id="default",
                event_id="priv-msg-1",
                user_input=secret_phrase,
                explicit_appraisal=Appraisal(
                    reaction="curiosity",
                    intensity=0.85,
                    source_quote=secret_phrase,
                    interest_action="open",
                    topic=secret_phrase,
                    reflection=secret_phrase,
                ),
            )
            await eng.pulse_synapses("default", {"sensor_curiosity": 0.91})
        finally:
            await eng.shutdown()

    asyncio.run(_seed_private_turn())

    monkeypatch.setenv("BRAIN_CORE_DB", db_file)
    monkeypatch.setenv("BRAIN_CONTROL_API_KEY", "prod-secret-observatory-key")

    sig = inspect.signature(create_control_plane_app)
    kwargs: dict[str, Any] = {}
    if "db_path" in sig.parameters:
        kwargs["db_path"] = db_file
    app = create_control_plane_app(**kwargs)

    with TestClient(app) as client:
        r_studio = client.get("/neuro-studio")
        assert r_studio.status_code == 200
        assert "Kristina Brain Core" in r_studio.text

        r_live = client.get("/neuro-studio/api/live/default")
        assert r_live.status_code == 200
        raw_text = r_live.text
        assert secret_phrase not in raw_text
        live_json = json.loads(raw_text)
        assert live_json["pii_redacted"] is True
        assert live_json["pulse_seq"] == 2
        assert len(live_json["neurons"]) >= 9

        r_sb = client.post(
            "/neuro-studio/api/sandbox-pulse",
            json={
                "scope_id": "demo:sandbox",
                "action": "pulse",
                "stimuli": {"sensor_curiosity": 0.92},
            },
        )
        assert r_sb.status_code == 200
        assert r_sb.json()["snapshot"]["pulse_seq"] == 1

        r_unauth = client.post(
            "/neuro-studio/api/sandbox-pulse",
            json={"scope_id": "default", "action": "pulse", "stimuli": {"sensor_warmth": 0.90}},
        )
        assert r_unauth.status_code == 401

        r_auth = client.post(
            "/neuro-studio/api/sandbox-pulse",
            headers={"X-API-Key": "prod-secret-observatory-key"},
            json={"scope_id": "default", "action": "pulse", "stimuli": {"sensor_warmth": 0.90}},
        )
        assert r_auth.status_code == 200
        assert r_auth.json()["snapshot"]["pulse_seq"] == 3


@pytest.mark.asyncio
async def test_concurrent_pulses_preserve_pulse_seq(tmp_path: Path) -> None:
    """Регрессия lost-update гонки RMW: N конкурентных импульсов на один scope дают ровно N.

    Без per-scope lock (`_lock_for`) 20 конкурентных pulse_synapses читали одно начальное
    значение pulse_seq и писали 1 (замер: LOST=19). Лок сериализует load->compute->persist.
    """
    clock = FixedClock(datetime(2026, 11, 23, 12, 0, tzinfo=UTC))
    store = AsyncSQLiteStateStore(str(tmp_path / "brain.db"))
    engine = BrainEngine(store, clock=clock)
    await engine.start()
    try:
        n = 20
        await asyncio.gather(
            *(engine.pulse_synapses("kristina", {"sensor_curiosity": 0.9}) for _ in range(n))
        )
        graph = await engine.synapses.inspect_graph("kristina")
        assert graph["pulse_seq"] == n, f"lost updates: expected {n}, got {graph['pulse_seq']}"
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_concurrent_register_custom_synapse_keeps_all_edges(tmp_path: Path) -> None:
    """Регрессия lost-update гонки RMW в register_custom_synapse: ни один синапс не теряется.

    Без per-scope lock конкурентные регистрации читали граф (ensure_circuit), добавляли
    свой синапс и целиком перезаписывали его (_persist) — выживал синапс последнего
    писателя. Лок сериализует load->compute->persist: все N ребер остаются в графе.
    """
    clock = FixedClock(datetime(2026, 11, 23, 12, 0, tzinfo=UTC))
    store = AsyncSQLiteStateStore(str(tmp_path / "brain.db"))
    engine = BrainEngine(store, clock=clock)
    await engine.start()
    try:
        n = 20
        await asyncio.gather(
            *(
                engine.synapses.register_custom_synapse(
                    "kristina",
                    source_id=f"sensor_custom_{i}",
                    target_id="inter_bridge",
                    weight=0.5,
                )
                for i in range(n)
            )
        )
        graph = await engine.synapses.inspect_graph("kristina")
        edges = {entry["edge"] for entry in graph["synapses"]}
        missing = [f"sensor_custom_{i}->inter_bridge" for i in range(n) if f"sensor_custom_{i}->inter_bridge" not in edges]
        assert not missing, f"lost synapses under concurrency: {missing}"
    finally:
        await engine.shutdown()


def test_online_observatory_live_get_is_read_only_and_openapi_builds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Публичный GET-снимок не пишет в БД, а /openapi.json собирается.

    Регрессии v1.2.0: (1) GET создавал нейрограф + 12 строк модов на каждый новый
    scope_id — анонимное размножение строк; (2) /openapi.json отдавал 500 из-за
    нерезолвимой аннотации `-> HTMLResponse` (fastapi импортируется в control_plane
    локально, имени нет в module globals) — /docs и /redoc были сломаны.
    """
    db_file = str(tmp_path / "obs_readonly.db")
    monkeypatch.setenv("BRAIN_CORE_DB", db_file)
    monkeypatch.setenv("BRAIN_CONTROL_API_KEY", "ro-test-key")

    sig = inspect.signature(create_control_plane_app)
    kwargs: dict[str, Any] = {}
    if "db_path" in sig.parameters:
        kwargs["db_path"] = db_file
    app = create_control_plane_app(**kwargs)

    with TestClient(app) as client:
        r_schema = client.get("/openapi.json")
        assert r_schema.status_code == 200, f"openapi schema broken: {r_schema.status_code}"

        con = sqlite3.connect(db_file)

        def counts() -> dict[str, int]:
            tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            return {
                t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in sorted(tables)
            }

        before = counts()
        for scope in ("probe:fresh-ro-1", "probe:fresh-ro-2"):
            r = client.get(f"/neuro-studio/api/live/{scope}")
            assert r.status_code == 200
            d = r.json()
            assert d["status"] == "online" and d["pii_redacted"] is True
            assert d["pulse_seq"] == 0
            assert len(d["neurons"]) >= 9  # шаблон показывается и без persist
        after = counts()
        assert before == after, f"GET mutated the store: {before} -> {after}"
        con.close()


@pytest.mark.asyncio
async def test_concurrent_multi_engine_pulses_preserve_pulse_seq(tmp_path: Path) -> None:
    """Регрессия межинстансной RMW-гонки: продакшен-форма live_synaptic_bridge.

    Мост создаёт НОВЫЙ BrainEngine на каждый Telegram-ход, а ходы конкурентны:
    per-scope _lock_for сериализует только внутри одного инстанса. Без CAS-коммита
    20 конкурентных импульсов через 20 разных engine на одну БД теряли ~8-9
    инкрементов pulse_seq (замер). С CAS-retry — ровно 20.
    """
    db = str(tmp_path / "shared.db")
    n = 20

    async def one_turn() -> None:
        store = AsyncSQLiteStateStore(db)
        engine = BrainEngine(store, clock=FixedClock(datetime(2026, 11, 23, 12, 0, tzinfo=UTC)))
        await engine.start()
        try:
            await engine.pulse_synapses("default", {"sensor_curiosity": 0.9})
        finally:
            await engine.shutdown()

    await asyncio.gather(*(one_turn() for _ in range(n)))

    store = AsyncSQLiteStateStore(db)
    engine = BrainEngine(store, clock=FixedClock(datetime(2026, 11, 23, 12, 0, tzinfo=UTC)))
    await engine.start()
    try:
        graph = await engine.synapses.inspect_graph("default")
        assert graph["pulse_seq"] == n, f"lost updates across engines: expected {n}, got {graph['pulse_seq']}"
    finally:
        await engine.shutdown()


@pytest.mark.asyncio
async def test_concurrent_multi_engine_register_keeps_all_edges(tmp_path: Path) -> None:
    """Регрессия межинстансной гонки register_custom_synapse: ни один синапс не теряется.

    20 конкурентных регистраций через 20 разных engine на одну БД: без CAS-коммита
    выживал синапс последнего писателя.
    """
    db = str(tmp_path / "shared.db")
    n = 20

    async def one_register(i: int) -> None:
        store = AsyncSQLiteStateStore(db)
        engine = BrainEngine(store, clock=FixedClock(datetime(2026, 11, 23, 12, 0, tzinfo=UTC)))
        await engine.start()
        try:
            await engine.synapses.register_custom_synapse(
                "default", source_id=f"sensor_x_{i}", target_id="inter_bridge", weight=0.5
            )
        finally:
            await engine.shutdown()

    await asyncio.gather(*(one_register(i) for i in range(n)))

    store = AsyncSQLiteStateStore(db)
    engine = BrainEngine(store, clock=FixedClock(datetime(2026, 11, 23, 12, 0, tzinfo=UTC)))
    await engine.start()
    try:
        graph = await engine.synapses.inspect_graph("default")
        edges = {entry["edge"] for entry in graph["synapses"]}
        missing = [f"sensor_x_{i}->inter_bridge" for i in range(n) if f"sensor_x_{i}->inter_bridge" not in edges]
        assert not missing, f"lost synapses across engines: {missing}"
    finally:
        await engine.shutdown()
