"""
Слот устойчивых творческих черновиков и личных артефактов агента (CreativeArtifact — v0.9.0).
Связывает внутреннюю творческую жизнь агента с долговременным диалогом: черновики, заметки
и наблюдения не теряются за окном последних 20 реплик, а сохраняются с точными цитатами и статусом.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class CreativeArtifact:
    artifact_id: str
    scope_id: str
    title: str
    excerpt: str
    status_note: str  # напр. "черновик — правлю второй абзац" | "опубликовано"
    updated_at: datetime

    def format_for_prompt(self) -> str:
        return f"Твой активный черновик/проект «{self.title}» ({self.status_note}): «{self.excerpt[:260]}»."
