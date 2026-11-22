"""
Commercial Cloud Control Plane MVP (v1.1.0) — FastAPI REST Gateway, Signed Webhooks & Live Dashboard.
Запускается командой `brain-core-cloud` (требует `pip install 'kristina-brain-core[cloud]'`).

Возможности платного контура ($29 Starter / $149 Pro):
- Защита эндпоинтов через API-ключ с константным временем сравнения (hmac.compare_digest).
- Визуализация всех 12 медленных мод (baseline vs amplitude vs deviation) и 7 быстрых эмоций.
- Аналитика ROI Shadow Telemetry без PII (доля скорректированных и предотвращённых касаний).
- Горячее редактирование параметров PersonaProfile (порог, кулдаун, таймзона, тумблер 12 мод) без деплоя.
- Подписанные исходящие вебхуки (HMAC-SHA256) для проактивных триггеров.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx

from .appraisal import Appraisal
from .clock import ClockProvider
from .engine import BrainEngine
from .llm_provider import FailoverLLMProvider, LLMProvider, OllamaChatProvider
from .postgres_store import create_state_store
from .profile import DEFAULT_KRISTINA_PROFILE, BigFiveTraits, PersonaProfile
from .state_store import StateStore

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kristina Brain Engine — Cloud Control Plane</title>
<style>
  :root {
    --bg: #0B0F17; --panel: #111827; --border: #1F2937; --text: #F3F4F6;
    --muted: #9CA3AF; --accent: #3B82F6; --teal: #14B8A6; --warn: #F59E0B; --danger: #EF4444;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: ui-sans-serif, system-ui, -apple-system, sans-serif; padding: 28px 36px; line-height: 1.5; }
  header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border); padding-bottom: 18px; margin-bottom: 24px; flex-wrap: wrap; gap: 12px; }
  h1 { font-size: 22px; font-weight: 700; letter-spacing: -0.02em; }
  .badge { font-family: ui-monospace, monospace; font-size: 12px; padding: 4px 10px; border: 1px solid var(--teal); color: var(--teal); border-radius: 999px; }
  .toolbar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
  input, select, button { background: var(--panel); color: var(--text); border: 1px solid var(--border); padding: 8px 12px; border-radius: 6px; font-size: 13px; }
  button { background: var(--accent); border-color: var(--accent); font-weight: 600; cursor: pointer; }
  button.secondary { background: var(--panel); border-color: var(--border); }
  .kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }
  .card { background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 18px; }
  .kpi-label { font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }
  .kpi-val { font-size: 28px; font-weight: 700; margin-top: 6px; font-family: ui-monospace, monospace; }
  .grid-2 { display: grid; grid-template-columns: 1.35fr 1fr; gap: 20px; margin-bottom: 24px; }
  h2 { font-size: 15px; font-weight: 600; margin-bottom: 14px; color: #E5E7EB; }
  .bar-row { display: grid; grid-template-columns: 155px 1fr 110px; align-items: center; gap: 10px; margin-bottom: 9px; font-size: 13px; }
  .bar-track { height: 9px; background: #1F2937; border-radius: 5px; position: relative; overflow: hidden; }
  .bar-fill { height: 100%; background: var(--accent); border-radius: 5px; }
  .bar-fill.pos { background: var(--teal); }
  .bar-fill.neg { background: var(--danger); }
  .mono { font-family: ui-monospace, monospace; font-size: 12px; color: var(--muted); text-align: right; }
  .form-row { display: flex; gap: 8px; margin-bottom: 10px; flex-wrap: wrap; }
  .form-row input[type="text"] { flex: 1; min-width: 200px; }
  pre { background: #070A10; border: 1px solid var(--border); border-radius: 6px; padding: 12px; font-size: 12px; overflow-x: auto; color: #D1D5DB; max-height: 220px; }
  @media (max-width: 960px) { .grid-2 { grid-template-columns: 1fr; } }
</style>
</head>
<body>
<header>
  <div>
    <h1>Kristina Brain Engine · Cloud Control Plane</h1>
    <div style="font-size:13px;color:var(--muted)">12 Slow Organism Modes · Dual-Clock Quiet Hours · PII-Free Shadow A/B ROI</div>
  </div>
  <div class="toolbar">
    <input id="apiKey" type="password" placeholder="API Key (if enabled)" style="width:170px">
    <input id="scopeId" type="text" value="hermes:syndiai" placeholder="scope_id" style="width:180px">
    <button onclick="refreshAll()">Refresh Telemetry</button>
    <button class="secondary" onclick="triggerHeartbeat()">Run Heartbeat Tick</button>
    <span class="badge" id="versionBadge">v1.1.0</span>
  </div>
</header>

<section class="kpis">
  <div class="card"><div class="kpi-label">Shadow Evaluations (24h)</div><div class="kpi-val" id="kpiObs">0</div></div>
  <div class="card"><div class="kpi-label">12-Mode Decision Lift</div><div class="kpi-val" id="kpiRate" style="color:var(--teal)">0.0%</div></div>
  <div class="card"><div class="kpi-label">Prevented / Flipped Actions</div><div class="kpi-val" id="kpiFlips" style="color:var(--warn)">0</div></div>
  <div class="card"><div class="kpi-label">Avg Max |Δ| Impulse</div><div class="kpi-val" id="kpiDelta">0.0000</div></div>
</section>

<section class="grid-2">
  <div class="card">
    <h2>12 Slow Organism Modes (Amplitude vs Baseline)</h2>
    <div id="modesContainer"></div>
  </div>
  <div class="card">
    <h2>7 Fast Affective Axes & Counterparty World Clock</h2>
    <div id="fastContainer"></div>
    <div style="margin-top:16px;padding-top:12px;border-top:1px solid var(--border);font-size:13px" id="worldBox"></div>
  </div>
</section>

<section class="grid-2">
  <div class="card">
    <h2>Live Event Simulator</h2>
    <div class="form-row">
      <input id="simText" type="text" value="Пишу из Унаватуны со Шри-Ланки, 50 метров до океана!">
      <select id="simReaction">
        <option value="">Auto LLM Appraisal</option>
        <option value="warmth">warmth</option>
        <option value="curiosity">curiosity</option>
        <option value="concern">concern</option>
        <option value="frustration">frustration</option>
        <option value="neutral">neutral</option>
      </select>
      <button onclick="sendSimEvent()">Ingest Event</button>
    </div>
    <pre id="simOutput">Ready.</pre>
  </div>
  <div class="card">
    <h2>Live Policy Tuning (Zero-Deploy PersonaProfile)</h2>
    <div class="form-row">
      <label style="font-size:13px;color:var(--muted)">Threshold <input id="profThresh" type="number" step="0.02" min="0.1" max="0.99" value="0.62" style="width:80px"></label>
      <label style="font-size:13px;color:var(--muted)">Cooldown (s) <input id="profCool" type="number" step="300" min="0" value="7200" style="width:95px"></label>
      <label style="font-size:13px;color:var(--muted)"><input id="profSlow" type="checkbox" checked> Enable 12 Slow Modes</label>
      <button class="secondary" onclick="saveProfile()">Apply Policy</button>
    </div>
    <pre id="profileOutput">Loading profile...</pre>
  </div>
</section>

<script>
function headers() {
  const h = { "Content-Type": "application/json" };
  const k = document.getElementById("apiKey").value.trim();
  if (k) h["X-API-Key"] = k;
  return h;
}
async function refreshAll() {
  const scope = encodeURIComponent(document.getElementById("scopeId").value.trim() || "default");
  const [stRes, roiRes, prRes] = await Promise.all([
    fetch(`/v1/state/${scope}`, { headers: headers() }),
    fetch(`/v1/shadow/roi?window_hours=24`, { headers: headers() }),
    fetch(`/v1/profile`, { headers: headers() })
  ]);
  if (roiRes.ok) {
    const roi = await roiRes.json();
    document.getElementById("kpiObs").textContent = roi.summary.observations;
    document.getElementById("kpiRate").textContent = (roi.summary.decision_changed_rate * 100).toFixed(1) + "%";
    document.getElementById("kpiFlips").textContent = roi.summary.action_changed_count;
    document.getElementById("kpiDelta").textContent = roi.summary.avg_max_abs_delta.toFixed(4);
  }
  if (stRes.ok) {
    const st = await stRes.json();
    document.getElementById("modesContainer").innerHTML = st.modes.map(m => {
      const pct = Math.round(m.amplitude * 100);
      const cls = m.deviation > 0.02 ? "pos" : (m.deviation < -0.02 ? "neg" : "");
      const sign = m.deviation >= 0 ? "+" : "";
      return `<div class="bar-row"><span>${m.name}</span><div class="bar-track"><div class="bar-fill ${cls}" style="width:${pct}%"></div></div><span class="mono">${m.amplitude.toFixed(2)} (${sign}${m.deviation.toFixed(2)})</span></div>`;
    }).join("");
    const fv = st.fast_state.state;
    document.getElementById("fastContainer").innerHTML = Object.keys(fv).map(k => {
      const pct = Math.round(fv[k] * 100);
      return `<div class="bar-row"><span>${k}</span><div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div><span class="mono">${fv[k].toFixed(2)}</span></div>`;
    }).join("");
    const w = st.world_context;
    document.getElementById("worldBox").textContent = w.counterparty_timezone
      ? `Counterparty: ${w.counterparty_location || "-"} (${w.counterparty_timezone}, offset ${w.offset_hours_diff >= 0 ? "+" : ""}${w.offset_hours_diff}h, night=${w.counterparty_is_night})`
      : "Counterparty world clock: not detected yet.";
  }
  if (prRes.ok) {
    const pr = await prRes.json();
    document.getElementById("profThresh").value = pr.proactive_threshold;
    document.getElementById("profCool").value = pr.proactive_cooldown_seconds;
    document.getElementById("profSlow").checked = pr.enable_slow_modes_in_decisions;
    document.getElementById("profileOutput").textContent = JSON.stringify(pr, null, 2);
  }
}
async function sendSimEvent() {
  const scope = document.getElementById("scopeId").value.trim() || "default";
  const text = document.getElementById("simText").value;
  const react = document.getElementById("simReaction").value || null;
  const body = { scope_id: scope, event_id: "sim-" + Date.now(), user_input: text, reaction: react };
  const res = await fetch("/v1/ingest", { method: "POST", headers: headers(), body: JSON.stringify(body) });
  document.getElementById("simOutput").textContent = JSON.stringify(await res.json(), null, 2);
  await refreshAll();
}
async function triggerHeartbeat() {
  const scope = encodeURIComponent(document.getElementById("scopeId").value.trim() || "default");
  const res = await fetch(`/v1/heartbeat/${scope}`, { method: "POST", headers: headers(), body: JSON.stringify({ commit_proactive_send: false }) });
  document.getElementById("simOutput").textContent = JSON.stringify(await res.json(), null, 2);
  await refreshAll();
}
async function saveProfile() {
  const body = {
    proactive_threshold: parseFloat(document.getElementById("profThresh").value),
    proactive_cooldown_seconds: parseInt(document.getElementById("profCool").value, 10),
    enable_slow_modes_in_decisions: document.getElementById("profSlow").checked
  };
  const res = await fetch("/v1/profile", { method: "PUT", headers: headers(), body: JSON.stringify(body) });
  document.getElementById("profileOutput").textContent = JSON.stringify(await res.json(), null, 2);
  await refreshAll();
}
refreshAll();
</script>
</body>
</html>
"""


def sign_webhook_payload(secret: str, raw_body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def create_control_plane_app(
    *,
    store: StateStore | None = None,
    llm: LLMProvider | None = None,
    profile: PersonaProfile = DEFAULT_KRISTINA_PROFILE,
    clock: ClockProvider | None = None,
    api_key: str | None = None,
    webhook_secret: str | None = None,
) -> Any:
    """Создаёт экземпляр FastAPI приложения Cloud Control Plane."""
    try:
        from fastapi import Body, Depends, FastAPI, Header, HTTPException
        from fastapi.responses import HTMLResponse, RedirectResponse, Response
    except ImportError as exc:
        raise RuntimeError("FastAPI is required for Control Plane: pip install 'kristina-brain-core[cloud]'") from exc

    resolved_store = store or create_state_store(os.getenv("BRAIN_CORE_DB", "kristina_state.db"))
    expected_key = api_key if api_key is not None else os.getenv("BRAIN_CONTROL_API_KEY")
    wh_secret = webhook_secret if webhook_secret is not None else os.getenv("BRAIN_WEBHOOK_SECRET", "")

    state_holder: dict[str, Any] = {
        "engine": BrainEngine(resolved_store, llm=llm, profile=profile, clock=clock),
    }

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        eng: BrainEngine = state_holder["engine"]
        await eng.start()
        try:
            yield
        finally:
            await eng.shutdown()

    app = FastAPI(
        title="Kristina Brain Engine — Cloud Control Plane",
        version="1.1.0",
        lifespan=lifespan,
    )

    async def verify_api_key(
        x_api_key: str | None = Header(default=None),
        authorization: str | None = Header(default=None),
    ) -> None:
        if not expected_key:
            return
        candidate = x_api_key or ""
        if not candidate and authorization and authorization.lower().startswith("bearer "):
            candidate = authorization[7:].strip()
        if not candidate or not hmac.compare_digest(candidate, expected_key):
            raise HTTPException(status_code=401, detail="Invalid or missing Control Plane API key")

    @app.get("/", include_in_schema=False)
    async def root_redirect() -> RedirectResponse:
        return RedirectResponse(url="/dashboard")

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon() -> Response:
        return Response(status_code=204)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "version": "1.1.0"}

    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard() -> HTMLResponse:
        return HTMLResponse(content=DASHBOARD_HTML)

    @app.get("/v1/profile", dependencies=[Depends(verify_api_key)])
    async def get_profile() -> dict[str, Any]:
        p: PersonaProfile = state_holder["engine"].profile
        return {
            "persona_id": p.persona_id,
            "display_name": p.display_name,
            "timezone": p.timezone,
            "night_hours": list(p.night_hours),
            "counterparty_night_hours": list(p.counterparty_night_hours),
            "proactive_threshold": p.proactive_threshold,
            "proactive_cooldown_seconds": p.proactive_cooldown_seconds,
            "enable_slow_modes_in_decisions": p.enable_slow_modes_in_decisions,
            "traits": p.traits.to_dict(),
        }

    @app.put("/v1/profile", dependencies=[Depends(verify_api_key)])
    async def update_profile(patch: dict[str, Any] = Body(...)) -> dict[str, Any]:
        old_eng: BrainEngine = state_holder["engine"]
        p = old_eng.profile
        updated = PersonaProfile(
            persona_id=p.persona_id,
            display_name=p.display_name,
            timezone=patch.get("timezone") or p.timezone,
            locale_city_label=p.locale_city_label,
            night_hours=p.night_hours,
            counterparty_night_hours=p.counterparty_night_hours,
            pacing_min_delay_seconds=p.pacing_min_delay_seconds,
            pacing_max_delay_seconds=p.pacing_max_delay_seconds,
            traits=BigFiveTraits(**p.traits.to_dict()),
            proactive_threshold=(
                float(patch["proactive_threshold"])
                if patch.get("proactive_threshold") is not None
                else p.proactive_threshold
            ),
            proactive_cooldown_seconds=(
                int(patch["proactive_cooldown_seconds"])
                if patch.get("proactive_cooldown_seconds") is not None
                else p.proactive_cooldown_seconds
            ),
            enable_slow_modes_in_decisions=(
                bool(patch["enable_slow_modes_in_decisions"])
                if patch.get("enable_slow_modes_in_decisions") is not None
                else p.enable_slow_modes_in_decisions
            ),
            appraisal_system_prompt=p.appraisal_system_prompt,
            persona_system_prompt=p.persona_system_prompt,
            custom_modes=p.custom_modes,
        )
        state_holder["engine"] = BrainEngine(
            old_eng.store,
            llm=old_eng.llm,
            profile=updated,
            clock=old_eng.clock,
        )
        return await get_profile()

    @app.post("/v1/ingest", dependencies=[Depends(verify_api_key)])
    async def ingest_endpoint(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        scope_id = str(body.get("scope_id", "")).strip()
        event_id = str(body.get("event_id", "")).strip()
        user_input = str(body.get("user_input", "")).strip()
        if not scope_id or not event_id or not user_input:
            raise HTTPException(status_code=422, detail="scope_id, event_id, and user_input are required")

        eng: BrainEngine = state_holder["engine"]
        reaction = body.get("reaction")
        explicit = (
            Appraisal(
                reaction=str(reaction),
                intensity=float(body.get("intensity", 0.6)),
                source_quote=user_input[:100],
                interest_action="keep",
                topic="api_event",
                reflection="",
                detected_location=body.get("detected_location"),
                detected_timezone=body.get("detected_timezone"),
                environment_cue=body.get("environment_cue"),
            )
            if reaction is not None
            else None
        )
        return await eng.ingest_message(
            scope_id=scope_id,
            event_id=event_id,
            user_input=user_input,
            explicit_appraisal=explicit,
        )

    @app.get("/v1/state/{scope_id:path}", dependencies=[Depends(verify_api_key)])
    async def state_endpoint(scope_id: str) -> dict[str, Any]:
        eng: BrainEngine = state_holder["engine"]
        fast = await eng.emotions.get_emotional_state(scope_id)
        modes_snap = await eng.modes.snapshot(scope_id)
        world = await eng.get_world_context(scope_id)
        intents = await eng.intentions.list_for_scope(scope_id, limit=5)
        ordered_modes = sorted(modes_snap.values(), key=lambda m: (-abs(m.deviation), m.name))
        return {
            "scope_id": scope_id,
            "fast_state": fast,
            "modes": [
                {
                    "name": m.name,
                    "amplitude": round(m.amplitude, 4),
                    "baseline": m.baseline,
                    "deviation": m.deviation,
                    "half_life_hours": m.half_life_hours,
                }
                for m in ordered_modes
            ],
            "world_context": world,
            "intentions": [
                {"intention_id": i.intention_id, "kind": i.kind, "topic": i.topic, "status": i.status} for i in intents
            ],
        }

    @app.post("/v1/heartbeat/{scope_id:path}", dependencies=[Depends(verify_api_key)])
    async def heartbeat_endpoint(scope_id: str, body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        eng: BrainEngine = state_holder["engine"]
        commit_send = bool(body.get("commit_proactive_send", False))
        webhook_url = body.get("webhook_url")
        tick = await eng.heartbeat_tick(scope_id, commit_proactive_send=commit_send)

        webhook_dispatched = False
        if isinstance(webhook_url, str) and webhook_url and tick["effective_decision"]["action"] == "message":
            raw_bytes = json.dumps(tick, ensure_ascii=False).encode("utf-8")
            wh_headers = {"Content-Type": "application/json"}
            if wh_secret:
                wh_headers["X-Brain-Signature"] = sign_webhook_payload(wh_secret, raw_bytes)
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(webhook_url, content=raw_bytes, headers=wh_headers)
                webhook_dispatched = 200 <= resp.status_code < 300

        tick["webhook_dispatched"] = webhook_dispatched
        return tick

    @app.get("/v1/shadow/roi", dependencies=[Depends(verify_api_key)])
    async def shadow_roi_endpoint(window_hours: int = 24, limit: int = 25) -> dict[str, Any]:
        eng: BrainEngine = state_holder["engine"]
        summary = await eng.shadow_telemetry.summary(window_hours=window_hours, now=eng.clock.now_utc())
        recent_rows = await eng.store.list_shadow_telemetry(limit=min(100, max(1, limit)))
        return {
            "summary": summary,
            "recent": recent_rows,
        }

    @app.get("/v1/neuro/{scope_id:path}", dependencies=[Depends(verify_api_key)])
    async def neuro_graph_endpoint(scope_id: str) -> dict[str, Any]:
        eng: BrainEngine = state_holder["engine"]
        return await eng.synapses.inspect_graph(scope_id)

    @app.post("/v1/sleep/{scope_id:path}", dependencies=[Depends(verify_api_key)])
    async def sleep_endpoint(scope_id: str, body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:
        eng: BrainEngine = state_holder["engine"]
        reward = float(body.get("reward_signal", 0.0))
        return await eng.run_sleep_consolidation(scope_id, reward_signal=reward)

    return app


def main() -> None:
    import uvicorn

    db_target = os.getenv("BRAIN_CORE_DB", "kristina_state.db")
    profile_path = os.getenv("BRAIN_CORE_PROFILE_JSON")
    profile = PersonaProfile.from_json_file(profile_path) if profile_path else DEFAULT_KRISTINA_PROFILE

    ollama_models = os.getenv("BRAIN_CORE_OLLAMA_MODEL", "")
    ollama_host = os.getenv("BRAIN_CORE_OLLAMA_HOST", "http://127.0.0.1:11434")
    llm: LLMProvider | None = None
    if ollama_models.strip():
        parts = [m.strip() for m in ollama_models.split(",") if m.strip()]
        provs = [OllamaChatProvider(model=m, host=ollama_host, think=False) for m in parts]
        llm = provs[0] if len(provs) == 1 else FailoverLLMProvider(provs)

    store = create_state_store(Path(db_target) if "://" not in db_target else db_target)
    app = create_control_plane_app(store=store, llm=llm, profile=profile)
    host = os.getenv("BRAIN_CONTROL_HOST", "127.0.0.1")
    port = int(os.getenv("BRAIN_CONTROL_PORT", "8080"))
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
