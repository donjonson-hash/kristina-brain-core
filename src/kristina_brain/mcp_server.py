"""
Встроенный легковесный MCP-сервер (Model Context Protocol, JSON-RPC 2.0 поверх stdio)
без внешних тяжеловесных зависимостей.
Позволяет одной строкой конфига подключить BrainEngine к Hermes Agent (~/.hermes/config.yaml),
Claude Desktop, Cursor или любому MCP-совместимому агентному рантайму.

Инструменты (tools):
- brain_get_state: получить вектор 7 быстрых эмоций, 3 доминирующие медленные моды и строку контекста для LLM.
- brain_ingest_event: применить входящее событие с идемпотентностью по event_id.
- brain_decide_proactive: выполнить такт политики проактивности/тишины и записать shadow-телеметрию.
- brain_shadow_summary: получить сводку расхождений ShadowDecisionReport без PII.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

from .appraisal import Appraisal
from .engine import BrainEngine
from .llm_provider import FailoverLLMProvider, LLMProvider, OllamaChatProvider
from .profile import DEFAULT_KRISTINA_PROFILE, PersonaProfile
from .state_store import AsyncSQLiteStateStore

MCP_TOOLS_SCHEMA = [
    {
        "name": "brain_get_state",
        "description": "Read fast 7-axis emotional state, top 3 slow organism modes, and prompt modulation text for a scope_id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "scope_id": {"type": "string", "default": "default"},
            },
        },
    },
    {
        "name": "brain_ingest_event",
        "description": "Idempotently apply a user/environment event to fast emotions, 12 slow modes, and activity timers.",
        "inputSchema": {
            "type": "object",
            "required": ["scope_id", "event_id", "user_input"],
            "properties": {
                "scope_id": {"type": "string"},
                "event_id": {"type": "string"},
                "user_input": {"type": "string"},
                "reaction": {
                    "type": "string",
                    "enum": ["curiosity", "warmth", "concern", "frustration", "neutral"],
                },
                "intensity": {"type": "number", "minimum": 0.0, "maximum": 1.0, "default": 0.5},
                "reflection": {"type": "string", "default": ""},
            },
        },
    },
    {
        "name": "brain_decide_proactive",
        "description": "Run proactive outreach vs silence policy gate with persistent cooldowns and PII-free shadow A/B telemetry.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "scope_id": {"type": "string", "default": "default"},
                "commit_proactive_send": {"type": "boolean", "default": False},
            },
        },
    },
    {
        "name": "brain_get_world_context",
        "description": "Return counterparty physical location, resolved IANA timezone, dual-clock offset, and sensory environment cues.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "scope_id": {"type": "string", "default": "default"},
            },
        },
    },
    {
        "name": "brain_shadow_summary",
        "description": "Return aggregated A/B divergence metrics between fast-only baseline and 12 slow organism modes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "window_hours": {"type": "integer", "minimum": 1, "maximum": 720, "default": 24},
            },
        },
    },
]


class BrainMCPServer:
    """Асинхронный обработчик JSON-RPC 2.0 запросов протокола MCP."""

    def __init__(self, engine: BrainEngine) -> None:
        self.engine = engine

    async def handle_rpc(self, request: dict[str, Any]) -> dict[str, Any] | None:
        method = request.get("method")
        req_id = request.get("id")
        params = request.get("params") or {}

        # Notifications (без id) не требуют ответа
        if req_id is None:
            return None

        try:
            result: dict[str, Any]
            if method == "initialize":
                result = {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {"name": "kristina-brain-core", "version": "0.5.0"},
                    "capabilities": {"tools": {}},
                }
            elif method == "tools/list":
                result = {"tools": MCP_TOOLS_SCHEMA}
            elif method == "tools/call":
                tool_name = params.get("name")
                args = params.get("arguments") or {}
                payload = await self._dispatch_tool(str(tool_name), args)
                result = {
                    "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}],
                    "isError": False,
                }
            elif method == "ping":
                result = {}
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                }
            return {"jsonrpc": "2.0", "id": req_id, "result": result}
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32000, "message": str(exc)},
            }

    async def _dispatch_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name == "brain_get_state":
            scope_id = str(args.get("scope_id", "default"))
            fast = await self.engine.emotions.get_emotional_state(scope_id)
            dom = await self.engine.modes.dominant(scope_id, limit=3)
            return {
                "fast_state": fast,
                "dominant_slow_modes": [
                    {"name": m.name, "amplitude": m.amplitude, "baseline": m.baseline, "deviation": m.deviation}
                    for m in dom
                ],
            }

        if name == "brain_ingest_event":
            scope_id = str(args["scope_id"])
            event_id = str(args["event_id"])
            user_input = str(args["user_input"])
            explicit_reaction = args.get("reaction")
            appraisal = (
                Appraisal(
                    reaction=str(explicit_reaction),
                    intensity=float(args.get("intensity", 0.5)),
                    source_quote=user_input[:100],
                    interest_action="keep",
                    topic="mcp_event",
                    reflection=str(args.get("reflection", "")),
                )
                if explicit_reaction is not None or self.engine.appraiser is None
                else None
            )
            return await self.engine.ingest_message(
                scope_id=scope_id,
                event_id=event_id,
                user_input=user_input,
                explicit_appraisal=appraisal,
            )

        if name == "brain_decide_proactive":
            scope_id = str(args.get("scope_id", "default"))
            commit = bool(args.get("commit_proactive_send", False))
            return await self.engine.heartbeat_tick(scope_id, commit_proactive_send=commit)

        if name == "brain_get_world_context":
            scope_id = str(args.get("scope_id", "default"))
            return await self.engine.get_world_context(scope_id)

        if name == "brain_shadow_summary":
            hours = int(args.get("window_hours", 24))
            return await self.engine.shadow_telemetry.summary(window_hours=hours)

        raise ValueError(f"Unknown tool: {name}")


async def run_stdio_server() -> None:
    db_path = os.getenv("BRAIN_CORE_DB", "kristina_state.db")
    profile_path = os.getenv("BRAIN_CORE_PROFILE_JSON")
    profile = PersonaProfile.from_json_file(profile_path) if profile_path else DEFAULT_KRISTINA_PROFILE
    store = AsyncSQLiteStateStore(db_path)
    ollama_model = os.getenv("BRAIN_CORE_OLLAMA_MODEL")
    ollama_host = os.getenv("BRAIN_CORE_OLLAMA_HOST", "http://127.0.0.1:11434")
    llm: LLMProvider | None = None
    if ollama_model:
        models = [m.strip() for m in ollama_model.split(",") if m.strip()]
        providers = [OllamaChatProvider(model=m, host=ollama_host, think=False) for m in models]
        llm = providers[0] if len(providers) == 1 else FailoverLLMProvider(providers)
    engine = BrainEngine(store, llm=llm, profile=profile)
    await engine.start()
    server = BrainMCPServer(engine)

    loop = asyncio.get_running_loop()
    try:
        while True:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                break
            line_str = line.strip()
            if not line_str:
                continue
            req = json.loads(line_str)
            resp = await server.handle_rpc(req)
            if resp is not None:
                sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
                sys.stdout.flush()
    finally:
        await engine.shutdown()


def main() -> None:
    asyncio.run(run_stdio_server())


if __name__ == "__main__":
    main()
