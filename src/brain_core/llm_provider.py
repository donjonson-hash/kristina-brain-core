"""
Унифицированный асинхронный контракт LLMProvider:
1. HTTPXChatCompletionsProvider — облачные OpenAI-совместимые API (DeepSeek, OpenAI, vLLM, OpenRouter)
   с поддержкой response_format={"type": "json_object"}.
2. OllamaChatProvider — нативный local-first провайдер Ollama (/api/chat) с поддержкой
   think=False (отключение холостого reasoning у Qwen3/DeepSeek-R1) и строгой грамматики format="json".
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

import httpx

logger = logging.getLogger(__name__)

MessageDict = dict[str, str]


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
        messages: Sequence[MessageDict],
        *,
        temperature: float = 0.7,
        max_tokens: int = 800,
        timeout: float | None = None,
        json_mode: bool = False,
    ) -> str: ...

    async def aclose(self) -> None: ...


class HTTPXChatCompletionsProvider:
    """Облачный OpenAI-совместимый провайдер (DeepSeek, OpenAI, vLLM, OpenRouter)."""

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
        logger.info("Initialized HTTPXChatCompletionsProvider (model=%s, key_len=%d)", self.model, len(self._api_key))

    def __repr__(self) -> str:
        return (
            f"HTTPXChatCompletionsProvider(model={self.model!r}, endpoint={self.endpoint!r}, api_key='***REDACTED***')"
        )

    async def complete(
        self,
        messages: Sequence[MessageDict],
        *,
        temperature: float = 0.7,
        max_tokens: int = 800,
        timeout: float | None = None,
        json_mode: bool = False,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": list(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

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


class OllamaChatProvider:
    """
    Нативный провайдер Ollama (/api/chat) для локальных и гибридных моделей (Qwen3, Llama 3.1, DeepSeek, GLM).
    Ключевое преимущество над /v1/chat/completions:
    - Передаёт `think: False` на уровне движка Ollama, убирая 7-секундный холостой прогон <think> на классификации.
    - Включает строгую грамматику `format: "json"` при `json_mode=True`, исключая обрыв JSON по num_predict.
    """

    def __init__(
        self,
        *,
        model: str = "qwen3:8b",
        host: str = "http://127.0.0.1:11434",
        think: bool = False,
        keep_alive: str | None = "15m",
        total_timeout: float = 35.0,
        connect_timeout: float = 5.0,
    ) -> None:
        self.model = model
        self.endpoint = f"{host.rstrip('/')}/api/chat"
        self.think = think
        self.keep_alive = keep_alive
        self.default_timeout = httpx.Timeout(total_timeout, connect=connect_timeout)
        self._client = httpx.AsyncClient(
            headers={"Content-Type": "application/json"},
            timeout=self.default_timeout,
        )
        logger.info("Initialized OllamaChatProvider (model=%s, think=%s)", self.model, self.think)

    def __repr__(self) -> str:
        return f"OllamaChatProvider(model={self.model!r}, endpoint={self.endpoint!r}, think={self.think!r})"

    async def complete(
        self,
        messages: Sequence[MessageDict],
        *,
        temperature: float = 0.7,
        max_tokens: int = 800,
        timeout: float | None = None,
        json_mode: bool = False,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": list(messages),
            "stream": False,
            "think": self.think,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if json_mode:
            payload["format"] = "json"
        if self.keep_alive is not None:
            payload["keep_alive"] = self.keep_alive

        req_timeout = (
            httpx.Timeout(timeout, connect=self.default_timeout.connect)
            if timeout is not None
            else self.default_timeout
        )
        try:
            resp = await self._client.post(self.endpoint, json=payload, timeout=req_timeout)
            if resp.status_code == 400 and "think" in resp.text.lower():
                # Авто-фолбэк для моделей, которые не поддерживают параметр think в Ollama API
                payload.pop("think", None)
                resp = await self._client.post(self.endpoint, json=payload, timeout=req_timeout)

            if resp.status_code != 200:
                raise LLMHTTPError(resp.status_code, resp.text)

            body = resp.json()
            msg = body.get("message") or {}
            content = msg.get("content")
            if not isinstance(content, str):
                raise LLMProviderError("Invalid Ollama response: message.content is not a string")
            return content
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(f"Ollama request timed out ({self.model})") from exc
        except httpx.HTTPError as exc:
            raise LLMProviderError(f"Ollama transport error: {exc}") from exc

    async def aclose(self) -> None:
        await self._client.aclose()


class FailoverLLMProvider:
    """
    Отказоустойчивый каскад провайдеров с Circuit Breaker:
    - Перманентные коды (HTTP 401/403/404/410) мгновенно выводят провайдер из ротации.
    - Временные сбои (429/5xx/Timeout/Network) переводят провайдер в cooldown (по умолчанию 120 с),
      чтобы не тратить время на повторные таймауты на каждом сообщении.
    """

    PERMANENT_DISABLE_CODES = frozenset({401, 403, 404, 410})

    def __init__(self, providers: Sequence[LLMProvider], *, cooldown_seconds: float = 120.0) -> None:
        if not providers:
            raise ValueError("FailoverLLMProvider requires at least one provider")
        self.providers = list(providers)
        self.cooldown_seconds = float(cooldown_seconds)
        self._disabled_until: dict[int, float] = {}

    async def complete(
        self,
        messages: Sequence[MessageDict],
        *,
        temperature: float = 0.7,
        max_tokens: int = 800,
        timeout: float | None = None,
        json_mode: bool = False,
    ) -> str:
        now = time.monotonic()
        last_err: Exception | None = None

        for idx, provider in enumerate(self.providers):
            blocked_until = self._disabled_until.get(idx, 0.0)
            if blocked_until > now:
                continue

            try:
                return await provider.complete(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout,
                    json_mode=json_mode,
                )
            except LLMHTTPError as exc:
                last_err = exc
                if exc.status_code in self.PERMANENT_DISABLE_CODES:
                    self._disabled_until[idx] = float("inf")
                    logger.warning(
                        "LLM provider #%d (%r) returned HTTP %d — permanently tripped circuit breaker",
                        idx + 1,
                        provider,
                        exc.status_code,
                    )
                else:
                    self._disabled_until[idx] = now + self.cooldown_seconds
                    logger.warning(
                        "LLM provider #%d (%r) failed (%s) — tripped for %.0fs",
                        idx + 1,
                        provider,
                        exc,
                        self.cooldown_seconds,
                    )
            except LLMProviderError as exc:
                last_err = exc
                self._disabled_until[idx] = now + self.cooldown_seconds
                logger.warning(
                    "LLM provider #%d (%r) failed (%s) — tripped for %.0fs",
                    idx + 1,
                    provider,
                    exc,
                    self.cooldown_seconds,
                )

        if last_err is not None:
            raise last_err
        raise LLMProviderError("All LLM providers in FailoverLLMProvider are currently circuit-broken")

    async def aclose(self) -> None:
        for provider in self.providers:
            await provider.aclose()
