"""
Неблокирующий стор приватной Shadow-телеметрии решений без сохранения текста переписки (PII-free).
Совместим со схемой shadow_decision_telemetry репозитория kristina-revolutionary.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from .autonomy import ShadowDecisionReport
from .modes import OrganismProjection
from .state_store import StateStore


def shadow_time_bucket(at: datetime, minutes: int = 30) -> datetime:
    utc = at.astimezone(UTC)
    floored_minute = (utc.minute // minutes) * minutes
    return utc.replace(minute=floored_minute, second=0, microsecond=0)


class AsyncShadowTelemetryStore:
    """Асинхронная запись и агрегация A/B-расхождений между базовой политикой и 12 медленными модами."""

    def __init__(self, store: StateStore) -> None:
        self.store = store

    async def record_once(
        self,
        *,
        kind: str,
        scope: str,
        opportunity_at: datetime,
        observed_at: datetime,
        projection: OrganismProjection,
        report: ShadowDecisionReport,
    ) -> bool:
        if kind not in ("proactive", "creative"):
            raise ValueError(f"Invalid shadow telemetry kind={kind!r}")

        bucket = shadow_time_bucket(opportunity_at, minutes=30)
        scope_sha = hashlib.sha256(scope.encode("utf-8")).hexdigest()
        observation_id = hashlib.sha256(f"{kind}:{scope_sha}:{bucket.isoformat()}".encode()).hexdigest()[:32]

        score_deltas_json = json.dumps(dict(report.score_deltas), sort_keys=True)
        mode_devs_json = json.dumps(dict(projection.mode_deviations), sort_keys=True)
        shifted_json = json.dumps(list(projection.shifted_modes))

        payload_fingerprint = json.dumps(
            {
                "b_act": report.baseline.action,
                "s_act": report.shadow.action,
                "deltas": report.score_deltas,
                "modes": projection.shifted_modes,
            },
            sort_keys=True,
        )
        payload_sha = hashlib.sha256(payload_fingerprint.encode("utf-8")).hexdigest()

        row = {
            "observation_id": observation_id,
            "payload_sha256": payload_sha,
            "kind": kind,
            "scope_sha256": scope_sha,
            "opportunity_at": opportunity_at.astimezone(UTC).isoformat(),
            "observed_at": observed_at.astimezone(UTC).isoformat(),
            "baseline_action": report.baseline.action,
            "baseline_intention": report.baseline.intention,
            "baseline_score": report.baseline.score,
            "baseline_reason": report.baseline.reason,
            "shadow_action": report.shadow.action,
            "shadow_intention": report.shadow.intention,
            "shadow_score": report.shadow.score,
            "shadow_reason": report.shadow.reason,
            "decision_changed": report.decision_changed,
            "action_changed": report.baseline.action != report.shadow.action,
            "intention_changed": report.baseline.intention != report.shadow.intention,
            "max_abs_score_delta": report.max_abs_score_delta,
            "score_deltas_json": score_deltas_json,
            "mode_deviations_json": mode_devs_json,
            "shifted_modes_json": shifted_json,
        }
        return await self.store.insert_shadow_telemetry_once(row)

    async def summary(self, *, window_hours: int = 24, now: datetime | None = None) -> dict[str, Any]:
        ref = (now or datetime.now(UTC)).astimezone(UTC)
        since_iso = (ref - timedelta(hours=window_hours)).isoformat()
        rows = await self.store.list_shadow_telemetry(limit=1000, since_iso=since_iso)
        total = len(rows)
        if total == 0:
            return {
                "window_hours": window_hours,
                "observations": 0,
                "decision_changed_count": 0,
                "decision_changed_rate": 0.0,
                "action_changed_count": 0,
                "avg_max_abs_delta": 0.0,
            }
        changed = sum(int(r["decision_changed"]) for r in rows)
        act_changed = sum(int(r["action_changed"]) for r in rows)
        avg_delta = sum(float(r["max_abs_score_delta"]) for r in rows) / total
        return {
            "window_hours": window_hours,
            "observations": total,
            "decision_changed_count": changed,
            "decision_changed_rate": round(changed / total, 4),
            "action_changed_count": act_changed,
            "avg_max_abs_delta": round(avg_delta, 4),
        }
