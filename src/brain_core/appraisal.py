"""
Модуль когнитивной предоценки входящих стимулов CognitiveAppraiser.
- Поддерживает канонические 5 реакций + словарь частых синонимов LLM (joy -> warmth и др.).
- Очищает <think>...</think> блоки гибридных моделей и логирует деградации провайдера.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .clock import ClockProvider, SystemClock
from .llm_provider import LLMProvider, LLMProviderError
from .profile import DEFAULT_KRISTINA_PROFILE, PersonaProfile

logger = logging.getLogger(__name__)

ALLOWED_REACTIONS = frozenset({"curiosity", "warmth", "concern", "frustration", "neutral"})
ALLOWED_INTEREST_ACTIONS = frozenset({"keep", "open", "resolve", "ignore"})

REACTION_ALIASES: Mapping[str, str] = {
    "joy": "warmth",
    "happy": "warmth",
    "happiness": "warmth",
    "gratitude": "warmth",
    "affection": "warmth",
    "positive": "warmth",
    "interest": "curiosity",
    "interested": "curiosity",
    "curious": "curiosity",
    "intrigue": "curiosity",
    "worry": "concern",
    "worried": "concern",
    "anxiety": "concern",
    "anxious": "concern",
    "fear": "concern",
    "alarm": "concern",
    "anger": "frustration",
    "angry": "frustration",
    "annoyance": "frustration",
    "irritation": "frustration",
    "irritated": "frustration",
    "upset": "frustration",
    "calm": "neutral",
    "ack": "neutral",
}

_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)


@dataclass(frozen=True)
class Appraisal:
    reaction: str
    intensity: float
    source_quote: str
    interest_action: str
    topic: str
    reflection: str
    dialogue: dict[str, Any] | None = None

    @classmethod
    def parse(cls, raw: str, user_input: str) -> Appraisal:
        """Строгий парсинг и нормализация JSON-ответа LLM с маппингом синонимов."""
        cleaned = _THINK_BLOCK_RE.sub("", raw).strip()
        fence_match = _JSON_FENCE_RE.search(cleaned)
        if fence_match:
            cleaned = fence_match.group(1)
        elif not cleaned.startswith("{"):
            brace_start = cleaned.find("{")
            brace_end = cleaned.rfind("}")
            if brace_start != -1 and brace_end > brace_start:
                cleaned = cleaned[brace_start : brace_end + 1]

        data = json.loads(cleaned)
        if not isinstance(data, Mapping):
            raise ValueError("Appraisal JSON must be an object")

        raw_reaction = str(data.get("reaction", "neutral")).strip().lower()
        reaction = REACTION_ALIASES.get(raw_reaction, raw_reaction)
        if reaction not in ALLOWED_REACTIONS:
            reaction = "neutral"

        raw_intensity = float(data.get("intensity", 0.4))
        intensity = max(0.0, min(1.0, round(raw_intensity, 4)))

        interest_action = str(data.get("interest_action", "keep")).strip().lower()
        if interest_action not in ALLOWED_INTEREST_ACTIONS:
            interest_action = "keep"

        quote = str(data.get("source_quote") or user_input[:120]).strip()
        topic = str(data.get("topic") or "general").strip()[:120]
        reflection = str(data.get("reflection") or "").strip()[:300]
        dialogue = data.get("dialogue")
        if dialogue is not None and not isinstance(dialogue, dict):
            dialogue = None

        return cls(
            reaction=reaction,
            intensity=intensity,
            source_quote=quote,
            interest_action=interest_action,
            topic=topic,
            reflection=reflection,
            dialogue=dialogue,
        )


class CognitiveAppraiser:
    """Платформенно-независимый оценщик событий поверх протокола LLMProvider."""

    def __init__(
        self,
        llm: LLMProvider,
        *,
        profile: PersonaProfile = DEFAULT_KRISTINA_PROFILE,
        clock: ClockProvider | None = None,
    ) -> None:
        self.llm = llm
        self.profile = profile
        self.clock: ClockProvider = clock or SystemClock(profile.timezone)

    def build_context_header(
        self,
        *,
        interest: Mapping[str, Any] | None = None,
        history: Sequence[Mapping[str, Any]] = (),
    ) -> str:
        local_now = self.clock.now_local(self.profile.timezone)
        parts = [
            f"Текущее локальное время ({self.profile.locale_city_label}, {self.profile.timezone}): "
            f"{local_now.isoformat()}. Оцени ТОЛЬКО последнее входящее сообщение пользователя "
            "(история дана лишь для контекста). Допустимые значения поля reaction СТРОГО из списка: "
            "curiosity, warmth, concern, frustration, neutral.",
        ]
        if interest:
            parts.append(f"Текущий фокус интереса: {json.dumps(dict(interest), ensure_ascii=False)}")
        if history:
            trimmed = [
                {"role": str(m.get("role", "user")), "content": str(m.get("content", ""))[:300]} for m in history[-6:]
            ]
            parts.append(f"Краткая история диалога: {json.dumps(trimmed, ensure_ascii=False)}")
        return "\n".join(parts)

    async def assess_event(
        self,
        user_input: str,
        *,
        history: Sequence[Mapping[str, Any]] = (),
        interest: Mapping[str, Any] | None = None,
        dialogue: Mapping[str, Any] | None = None,
    ) -> Appraisal | None:
        if not user_input or not user_input.strip():
            return None

        user_block = (
            f"{self.build_context_header(interest=interest, history=history)}\n"
            f"Входящее сообщение пользователя: {json.dumps(user_input, ensure_ascii=False)}"
        )
        messages = [
            {"role": "system", "content": self.profile.appraisal_system_prompt},
            {"role": "user", "content": user_block},
        ]

        try:
            raw = await self.llm.complete(
                messages,
                temperature=0.2,
                max_tokens=900 if dialogue is not None else 450,
                timeout=25.0,
                json_mode=True,
            )
            return Appraisal.parse(raw, user_input)
        except LLMProviderError as exc:
            logger.warning("CognitiveAppraiser LLM error: %s", exc)
            return None
        except (ValueError, json.JSONDecodeError) as exc:
            logger.warning("CognitiveAppraiser JSON parse error: %s", exc)
            return None
