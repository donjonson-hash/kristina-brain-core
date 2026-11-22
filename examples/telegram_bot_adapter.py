"""
Референс-адаптер интеграции выделенного пакета `brain_core` обратно в Telegram-бота `bot.py`
репозитория kristina-revolutionary без потери текущей функциональности и без RAM-словарей.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional, Sequence

from brain_core import (
    AsyncSQLiteStateStore,
    BrainEngine,
    DEFAULT_KRISTINA_PROFILE,
    HTTPXChatCompletionsProvider,
)


class TelegramBrainRuntimeAdapter:
    """
    Заменяет в bot.py связку:
      - синхронного EmotionalCore + OrganismModes + ShadowTelemetryStore
      - глобальных RAM-словарей (last_user_activity, last_proactive, next_proactive_opportunity)
    на единый неблокирующий BrainEngine с сохранением состояния между рестартами systemd.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        resolved_db = db_path or os.getenv("KRISTINA_STATE_DB", "kristina_state.db")
        store = AsyncSQLiteStateStore(resolved_db)
        llm = HTTPXChatCompletionsProvider(
            api_key=os.getenv("BRAIN_DEEPSEEK_API_KEY") or os.getenv("DEEPSEEK_API_KEY"),
            model="deepseek-chat",
        )
        self.engine = BrainEngine(store, llm=llm, profile=DEFAULT_KRISTINA_PROFILE)

    async def post_init(self) -> None:
        """Подключить в ApplicationBuilder().post_init(...) в bot.py."""
        await self.engine.start()

    async def post_shutdown(self) -> None:
        """Подключить в ApplicationBuilder().post_shutdown(...) в bot.py."""
        await self.engine.shutdown()

    async def on_telegram_message(
        self,
        *,
        chat_id: int,
        message_id: int,
        text: str,
        history: Sequence[Dict[str, Any]] = (),
    ) -> Dict[str, Any]:
        """Вызывается в обработчике входящего сообщения Telegram."""
        return await self.engine.ingest_message(
            scope_id=f"tg:{chat_id}",
            event_id=f"msg:{message_id}",
            user_input=text,
            history=history,
        )

    async def on_minute_heartbeat(self, chat_id: int) -> Optional[Dict[str, Any]]:
        """
        Вызывается в минутном job_queue Telegram-бота.
        Возвращает решение с intention и контекстом для генерации проактивной реплики,
        либо None, если сработала политика тишины / кулдаун / ночное окно.
        """
        tick = await self.engine.heartbeat_tick(
            scope_id=f"tg:{chat_id}",
            commit_proactive_send=True,
        )
        if tick["effective_decision"]["action"] == "message":
            return tick
        return None
