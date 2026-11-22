# kristina-brain-core

Асинхронный движок состояния, когнитивной предоценки, 12 медленных затухающих мод, политики проактивности/тишины и обезличенной shadow-телеметрии для автономных ИИ-агентов.

Выделен из проекта [donjonson-hash/kristina-revolutionary](https://github.com/donjonson-hash/kristina-revolutionary) с устранением всех блокировок `asyncio`, хардкода часовых поясов и зависимостей от Telegram.

## Быстрый старт (Python SDK)

```python
import asyncio
from brain_core import AsyncSQLiteStateStore, BrainEngine, DEFAULT_KRISTINA_PROFILE

async def main() -> None:
    store = AsyncSQLiteStateStore("agent_state.db")
    engine = BrainEngine(store, profile=DEFAULT_KRISTINA_PROFILE)
    await engine.start()
    try:
        res = await engine.ingest_message(
            scope_id="user:42",
            event_id="msg-1",
            user_input="Привет! Давай обсудим архитектуру.",
        )
        print(res["fast_state"]["for_llm"])
        tick = await engine.heartbeat_tick("user:42", commit_proactive_send=False)
        print(tick["effective_decision"])
    finally:
        await engine.shutdown()

asyncio.run(main())
```

## Запуск в режиме MCP-сервера (stdio JSON-RPC 2.0)

```bash
BRAIN_CORE_DB=./agent_state.db brain-core-mcp
```
