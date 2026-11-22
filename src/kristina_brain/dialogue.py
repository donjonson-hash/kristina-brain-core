"""
Эпизодические гейты диалога и детектор повторных вопросов (EpisodicDialogueGate — v0.6.0).
Портирует и обобщает проверенные инварианты dialogue_state.py для любого мессенджера/CRM:
- Запрещает слать второе проактивное сообщение подряд без ответа человека (awaiting_user_turn).
- Запрещает дёргать человека, если уже задан открытый вопрос (awaiting_answer).
- Уважает явную просьбу о паузе (user_requested_space).
- Отсекает повторяющиеся вопросы по клаузам '?' и SequenceMatcher >= 0.82.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher
from typing import Any


def empty_dialogue_state() -> dict[str, Any]:
    return {
        "version": 1,
        "revision": 0,
        "scene": None,
        "pause_until": None,
        "pending_question": None,
        "closed_questions": [],
        "proactive_since_user": 0,
        "last_user_at": None,
        "last_user_event_id": None,
        "last_proactive_at": None,
    }


def extract_question_clauses(text: str) -> list[str]:
    """Извлекает вопросительные клаузы (до 8 штук) из текста реплики."""
    if not isinstance(text, str) or "?" not in text:
        return []
    clauses: list[str] = []
    start = 0
    for idx, ch in enumerate(text[:12000]):
        if ch in ".!?…\n":
            if ch == "?":
                segment = text[start : idx + 1].strip()
                if segment:
                    clauses.append(segment)
                    if len(clauses) == 8:
                        break
            start = idx + 1
    return clauses


def _normalize_clause(value: str) -> str:
    return " ".join(re.findall(r"\w+", value.casefold()))


def is_repeated_question(candidate_text: str, state: Mapping[str, Any] | None) -> bool:
    """Проверяет, не дублирует ли кандидат уже открытый или недавно закрытый вопрос."""
    if not candidate_text or "?" not in candidate_text:
        return False

    st = state or empty_dialogue_state()
    previous = list(st.get("closed_questions") or [])
    pending = st.get("pending_question")
    if isinstance(pending, Mapping):
        previous.append(dict(pending))

    old_norms = [
        _normalize_clause(clause)
        for q in previous
        if isinstance(q, Mapping) and isinstance(q.get("text"), str)
        for clause in extract_question_clauses(str(q["text"]))
    ]
    if not old_norms:
        return False

    for clause in extract_question_clauses(candidate_text):
        cand = _normalize_clause(clause)
        if not cand:
            continue
        for ref in old_norms:
            if not ref:
                continue
            if cand == ref:
                return True
            if min(len(cand), len(ref)) >= 18:
                if cand in ref or ref in cand:
                    return True
                if SequenceMatcher(None, cand, ref).ratio() >= 0.82:
                    return True
    return False


def dialogue_proactive_block_reason(
    state: Mapping[str, Any] | None,
    now: datetime,
) -> str | None:
    """Возвращает причину блокировки проактивного пинга по состоянию эпизода диалога (или None)."""
    if not state:
        return None
    utc_now = now.astimezone(UTC)

    pause_raw = state.get("pause_until")
    if isinstance(pause_raw, str) and pause_raw:
        pause_dt = datetime.fromisoformat(pause_raw)
        if pause_dt.tzinfo is None:
            pause_dt = pause_dt.replace(tzinfo=UTC)
        if pause_dt.astimezone(UTC) > utc_now:
            return "user_requested_space"

    if int(state.get("proactive_since_user", 0)) >= 1:
        return "awaiting_user_turn"

    pending = state.get("pending_question")
    if isinstance(pending, Mapping) and pending.get("status") == "open":
        asked_raw = pending.get("asked_at")
        last_user_raw = state.get("last_user_at")
        if isinstance(asked_raw, str):
            asked_dt = datetime.fromisoformat(asked_raw).astimezone(UTC)
            if not isinstance(last_user_raw, str):
                return "awaiting_answer"
            user_dt = datetime.fromisoformat(last_user_raw).astimezone(UTC)
            if asked_dt >= user_dt:
                return "awaiting_answer"

    return None


def apply_user_turn(
    state: Mapping[str, Any] | None,
    *,
    event_id: str,
    user_input: str,
    at: datetime,
    pause_hours: float | None = None,
    scene_label: str | None = None,
) -> dict[str, Any]:
    """Обновляет эпизод при входящем сообщении собеседника: закрывает открытый вопрос и сбрасывает счётчик пингов."""
    nxt = deepcopy(dict(state)) if state else empty_dialogue_state()
    ts = at.astimezone(UTC).isoformat()

    nxt["revision"] = int(nxt.get("revision", 0)) + 1
    nxt["proactive_since_user"] = 0
    nxt["last_user_at"] = ts
    nxt["last_user_event_id"] = event_id

    if pause_hours is not None and pause_hours > 0:
        nxt["pause_until"] = (at.astimezone(UTC) + timedelta(hours=pause_hours)).isoformat()
    else:
        nxt["pause_until"] = None

    if scene_label:
        nxt["scene"] = {"label": scene_label[:120], "updated_at": ts}

    # Если висел открытый вопрос ассистента — ответ пользователя переводит его в answered
    pending = nxt.get("pending_question")
    if isinstance(pending, Mapping):
        closed_item = {
            **dict(pending),
            "status": "answered",
            "answer_excerpt": user_input[:160],
            "answered_at": ts,
        }
        closed_list = list(nxt.get("closed_questions") or [])
        closed_list.append(closed_item)
        nxt["closed_questions"] = closed_list[-8:]
        nxt["pending_question"] = None

    return nxt


def apply_assistant_turn(
    state: Mapping[str, Any] | None,
    *,
    reply_id: str,
    reply_text: str,
    at: datetime,
    is_proactive: bool = False,
) -> dict[str, Any]:
    """Фиксирует ответ или проактивный пинг агента и регистрирует новые вопросительные клаузы."""
    nxt = deepcopy(dict(state)) if state else empty_dialogue_state()
    ts = at.astimezone(UTC).isoformat()
    nxt["revision"] = int(nxt.get("revision", 0)) + 1

    if is_proactive:
        nxt["proactive_since_user"] = int(nxt.get("proactive_since_user", 0)) + 1
        nxt["last_proactive_at"] = ts

    clauses = extract_question_clauses(reply_text)
    if clauses:
        prev_pending = nxt.get("pending_question")
        if isinstance(prev_pending, Mapping):
            closed_list = list(nxt.get("closed_questions") or [])
            closed_list.append({**dict(prev_pending), "status": "superseded", "superseded_at": ts})
            nxt["closed_questions"] = closed_list[-8:]
        nxt["pending_question"] = {
            "id": f"q:{reply_id}",
            "text": " ".join(clauses)[:2000],
            "status": "open",
            "asked_at": ts,
            "is_proactive": is_proactive,
        }

    return nxt
