"""
Онлайн-маршруты Синаптической Обсерватории (Neuro Studio v1.2.0).
- GET /neuro-studio: публичный веб-интерфейс реального времени (0 PII, 0 секретов).
- GET /v1/neuro/live/{scope_id}: живой числовой снимок сети и 5 нейромедиаторов без текста.
- POST /v1/neuro/sandbox-pulse: импульсы и сон Хебба для изолированного контура demo:sandbox
  (любой другой scope_id требует валидный BRAIN_CONTROL_API_KEY).
"""

from __future__ import annotations

import hmac
import os
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel, Field

from .neuro import NeuromodulatorField
from .neuro_studio_html import NEURO_STUDIO_HTML

SANDBOX_SCOPE = "demo:sandbox"


class SandboxPulseRequest(BaseModel):
    scope_id: str = Field(default=SANDBOX_SCOPE, max_length=64)
    action: Literal["pulse", "sleep", "reset"] = "pulse"
    stimuli: dict[str, float] = Field(default_factory=dict)
    reward_signal: float = 0.75


def _has_valid_api_key(request: Request, explicit_key: str | None = None) -> bool:
    raw_key = (
        explicit_key
        if explicit_key is not None
        else os.environ.get("BRAIN_CONTROL_API_KEY", "")
    )
    configured = raw_key.strip()
    if not configured:
        return False
    candidate = request.headers.get("x-api-key", "").strip()
    if not candidate:
        auth = request.headers.get("authorization", "").strip()
        if auth.lower().startswith("bearer "):
            candidate = auth[7:].strip()
    if not candidate:
        return False
    return hmac.compare_digest(candidate.encode("utf-8"), configured.encode("utf-8"))


async def _build_zero_pii_snapshot(
    engine: Any, scope_id: str, *, read_only: bool = False
) -> dict[str, Any]:
    fast_raw = await engine.emotions.get_emotional_state(scope_id)
    if read_only:
        mode_map = await engine.modes.snapshot_readonly(scope_id)
    else:
        mode_map = await engine.modes.snapshot(scope_id)
    is_quiet = bool(fast_raw.get("is_night", False))
    chem = NeuromodulatorField.from_brain_state(
        fast_raw,
        mode_map,
        is_quiet_hours=is_quiet,
    )
    graph = await engine.synapses.inspect_graph(scope_id, chem=chem, read_only=read_only)

    raw_vec = fast_raw.get("state", {})
    clean_emotions: dict[str, float] = {}
    if isinstance(raw_vec, Mapping):
        for k, v in raw_vec.items():
            if isinstance(v, (int, float)):
                clean_emotions[str(k)] = round(float(v), 4)

    clean_modes: dict[str, dict[str, float]] = {}
    for m_name, m_state in mode_map.items():
        clean_modes[str(m_name)] = {
            "amplitude": round(float(m_state.amplitude), 4),
            "baseline": round(float(m_state.baseline), 4),
            "deviation": round(float(m_state.deviation), 4),
        }

    return {
        "status": "online",
        "version": "1.2.0",
        "scope_id": scope_id,
        "server_time_utc": datetime.now(UTC).isoformat(),
        "is_quiet_hours": is_quiet,
        "pulse_seq": int(graph["pulse_seq"]),
        "neurotransmitters": chem.to_dict(),
        "fast_emotions": clean_emotions,
        "slow_modes": clean_modes,
        "neurons": graph["neurons"],
        "synapses": graph["synapses"],
        "last_packets": graph["last_packets"],
        "pii_redacted": True,
    }


def create_observatory_router(
    state_holder: Mapping[str, Any],
    *,
    expected_api_key: str | None = None,
) -> APIRouter:
    router = APIRouter(tags=["neuro-observatory"])

    def _engine() -> Any:
        eng = state_holder.get("engine")
        if eng is None:
            raise HTTPException(status_code=503, detail="BrainEngine is initializing")
        return eng

    @router.get("/neuro-studio", response_class=HTMLResponse)
    async def neuro_studio_page() -> Response:
        return HTMLResponse(content=NEURO_STUDIO_HTML)

    @router.get("/neuro-studio/api/live/{scope_id:path}")
    @router.get("/v1/neuro/live/{scope_id:path}")
    async def neuro_live_snapshot(scope_id: str) -> dict[str, Any]:
        clean_scope = (scope_id or "default").strip()[:64] or "default"
        return await _build_zero_pii_snapshot(_engine(), clean_scope, read_only=True)

    @router.post("/neuro-studio/api/sandbox-pulse")
    @router.post("/v1/neuro/sandbox-pulse")
    async def neuro_sandbox_pulse(
        payload: SandboxPulseRequest, request: Request
    ) -> dict[str, Any]:
        target_scope = (payload.scope_id or SANDBOX_SCOPE).strip()[:64] or SANDBOX_SCOPE
        if target_scope != SANDBOX_SCOPE and not _has_valid_api_key(request, expected_api_key):
            raise HTTPException(
                status_code=401,
                detail="Valid X-API-Key required to mutate non-sandbox neural scopes.",
            )

        eng = _engine()
        t0 = time.perf_counter()

        if payload.action == "reset":
            await eng.synapses.reset_circuit(target_scope)
            elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 3)
            snap = await _build_zero_pii_snapshot(eng, target_scope)
            return {
                "ok": True,
                "action": "reset",
                "engine_latency_ms": elapsed_ms,
                "snapshot": snap,
            }

        if payload.action == "sleep":
            rew = max(-1.0, min(1.0, float(payload.reward_signal)))
            raw_sleep = await eng.run_sleep_consolidation(target_scope, reward_signal=rew)
            elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 3)
            snap = await _build_zero_pii_snapshot(eng, target_scope)
            dream_raw = raw_sleep.get("dream_seed") if isinstance(raw_sleep, Mapping) else None
            vividness = 0.35
            if isinstance(dream_raw, Mapping) and isinstance(
                dream_raw.get("vividness"), (int, float)
            ):
                vividness = round(float(dream_raw["vividness"]), 4)
            return {
                "ok": True,
                "action": "sleep",
                "engine_latency_ms": elapsed_ms,
                "reward_signal": rew,
                "dream_vividness": vividness,
                "snapshot": snap,
            }

        clean_stimuli: dict[str, float] = {}
        for k, v in list(payload.stimuli.items())[:16]:
            if isinstance(v, (int, float)):
                clean_stimuli[str(k)[:48]] = max(0.0, min(1.0, float(v)))

        pulse_res = await eng.pulse_synapses(target_scope, clean_stimuli)
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 3)
        snap = await _build_zero_pii_snapshot(eng, target_scope)
        return {
            "ok": True,
            "action": "pulse",
            "engine_latency_ms": elapsed_ms,
            "pulse": pulse_res,
            "snapshot": snap,
        }

    return router


def mount_neuro_observatory(
    app: FastAPI,
    state_holder: Mapping[str, Any],
    *,
    expected_api_key: str | None = None,
) -> None:
    existing_paths = {getattr(r, "path", "") for r in app.routes}
    if "/neuro-studio" in existing_paths:
        return
    before_n = len(app.router.routes)
    obs_r = create_observatory_router(state_holder, expected_api_key=expected_api_key)
    app.include_router(obs_r)
    added = list(app.router.routes[before_n:])
    del app.router.routes[before_n:]
    app.router.routes[0:0] = added
    if "/" not in existing_paths:
        @app.get("/", include_in_schema=False)
        async def _root_to_studio() -> RedirectResponse:
            return RedirectResponse(url="/neuro-studio", status_code=307)
