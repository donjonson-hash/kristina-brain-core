"""
Унифицированный асинхронный контракт LLMProvider (закрытие AUD-02 + AUD-04 + единый адаптер).
Заменяет зоопарк из трёх разных клиентов (ai_client.py, brain_llm_integration.py, avatar_platform/llm_adapter.py).
Поддерживает любой OpenAI-совместимый эндпоинт (DeepSeek, OpenAI, vLLM, Ollama, OpenRouter).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

import httpx

logger = logging.getLogger(__name__)


class LLMProviderError(RuntimeError):
    """Типизированная ошибка провайдера LLM (не маскируется разговорным текстом)."""


class LLMHTTPError(LLMProviderError):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail[:300]
        super().__init__(f"LLM HTTP {status_code}: {self.detail}")


class LLMTimeoutError(LLMProviderError):
    """Превышен лимит ожидания ответа LLM."""


@runtime_checkable
class LLMProvider(Protocol):
    """Протокол BYO-LLM для ядра мозга агента."""

    async def complete(
        self,
        messages: Sequence[MappingLike],
        *,
        temperature: float = 0.7,
        max_tokens: int = 800,
        timeout: float | None = None,
    ) -> str: ...

    async def aclose(self) -> None: ...


MappingLike = dict[str, str]


class HTTPXChatCompletionsProvider:
    """
    Production-провайдер на базе пула httpx.AsyncClient:
    - Строгие таймауты connect/read/write (никаких 300-секундных зависаний).
    - Переиспользование TCP/TLS соединений (keep-alive pool).
    - Нулевая утечка API-ключей в логи (AUD-02).
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = "https://api.deepseek.com/v1",
        model: str = "deepseek-chat",
        total_timeout: float = 25.0,
        connect_timeout: float = 5.0,
        max_connections: int = 20,
    ) -> None:
        resolved_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        if not resolved_key:
            raise ValueError("API key is required (pass api_key or set DEEPSEEK_API_KEY)")

        self._api_key = resolved_key
        self.endpoint = f"{base_url.rstrip('/')}/chat/completions"
        self.model = model
        self.default_timeout = httpx.Timeout(total_timeout, connect=connect_timeout)
        self._client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            timeout=self.default_timeout,
            limits=httpx.Limits(max_connections=max_connections, max_keepalive_connections=10),
        )
        logger.info(
            "Initialized HTTPXChatCompletionsProvider (model=%s, key_len=%d)",
            self.model,
            len(self._api_key),
        )

    def __repr__(self) -> str:
        # Защита от случайной распечатки объекта в traceback/логах
        return (
            f"HTTPXChatCompletionsProvider(model={self.model!r}, endpoint={self.endpoint!r}, api_key='***REDACTED***')"
        )

    async def complete(
        self,
        messages: Sequence[dict[str, str]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 800,
        timeout: float | None = None,
    ) -> str:
        payload = {
            "model": self.model,
            "messages": list(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        req_timeout = (
            httpx.Timeout(timeout, connect=self.default_timeout.connect)
            if timeout is not None
            else self.default_timeout
        )
        try:
            resp = await self._client.post(self.endpoint, json=payload, timeout=req_timeout)
            if resp.status_code != 200:
                raise LLMHTTPError(resp.status_code, resp.text)
            body = resp.json()
            choices = body.get("choices") or []
            if not choices or "message" not in choices[0]:
                raise LLMProviderError("Invalid completion response: missing choices[0].message")
            content = choices[0]["message"].get("content")
            if not isinstance(content, str):
                raise LLMProviderError("Invalid completion response: content is not a string")
            return content
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(f"LLM request timed out ({self.model})") from exc
        except httpx.HTTPError as exc:
            raise LLMProviderError(f"LLM transport error: {exc}") from exc

    async def aclose(self) -> None:
        await self._client.aclose()
