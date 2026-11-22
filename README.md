# kristina-brain-core

**Dual-timescale affective state, cognitive appraisal, proactive silence policy, and PII-free shadow telemetry engine for autonomous AI agents.**

Most AI agent frameworks solve *what an agent remembers* (passive RAG / context graphs). `kristina-brain-core` solves **when, why, and whether an autonomous agent should reach out or stay silent**:

- **Cognitive Appraisal Pre-Filter (`CognitiveAppraiser`)**: classifies incoming stimuli into normalized reactions (`warmth`, `curiosity`, `concern`, `frustration`, `neutral`) with `<think>` stripping and synonym normalization before mutating agent state.
- **Dual-Timescale State Physics (`AsyncEmotionalCore` + `AsyncOrganismModes`)**: combines 7 fast affective axes (Big Five baseline + circadian quiet hours) with **12 slow exponentially decaying organism modes** (`half_life_hours` from 18h to 336h) featuring a calibrated **conflict brake** and **rapport-gated outreach**.
- **Non-Blocking Multi-Tenant Persistence (`AsyncSQLiteStateStore`)**: serialized WAL-mode SQLite engine with cryptographic SHA-256 event idempotency and persistent outreach cooldowns that survive container/systemd restarts.
- **Hybrid Cloud → Local LLM Cascade (`FailoverLLMProvider` + `OllamaChatProvider`)**: native Ollama `/api/chat` (`think=False`, `format="json"`) and OpenAI-compatible HTTPX pool with automatic circuit breaker (instant permanent trip on `HTTP 401/403/404/410`, timed cooldown on `429/5xx`).
- **PII-Free Shadow A/B Telemetry (`AsyncShadowTelemetryStore`)**: compares baseline vs. 12-mode counterfactual decisions on live traffic without storing message text.
- **World State Anchors & Dual-Clock Quiet Hours (`WorldStateAnchor` + `DualClockGate`)**: single-pass extraction of counterparty location, IANA timezone, and sensory environment cues, preventing cross-timezone night wake-ups (`counterparty_quiet_hours`).
- **Physiological Response Pacing (`ResponsePacingEngine`)**: deterministic typing/reply delay (`delay_seconds`), verbosity hints, and sensory curiosity flags.
- **Built-in MCP Server (`brain-core-mcp`)**: zero-overhead JSON-RPC 2.0 stdio server for Hermes Agent, Claude Desktop, Cursor, and custom runtimes.

## Live Model & B2B Pilot Benchmarks (v0.6.0)

| Provider / Contour | JSON Validity | Appraisal Accuracy | Avg Latency | Role in Cascade |
| :--- | :---: | :---: | :---: | :--- |
| `glm-5.3-flash:cloud` (Ollama Cloud) | 5 / 5 | 5 / 5 | ~1.49 s | Fast primary classifier |
| `qwen3:8b` (Local GPU, `think=False`) | 5 / 5 | 5 / 5 | ~3.76 s | Private local fallback |
| `llama3.1:8b` (Local GPU) | 5 / 5 | 4 / 5 | ~3.34 s | Lightweight local option |

In a 14-day multi-tenant B2B Customer Success simulation across 3 polar accounts, the 12 slow modes corrected **75% of autonomous outreach decisions** — blocking unwanted check-ins to an angry churning account (`wants_space=0.859`) while nudging a warm Enterprise SSO lead (`intent=ask`) and keeping cold leads quiet.

## Installation

```bash
pip install "kristina-brain-core @ git+[https://github.com/donjonson-hash/kristina-brain-core.git@v0.6.0](https://github.com/donjonson-hash/kristina-brain-core.git@v0.6.0)"
import asyncio
from kristina_brain import (
    AsyncSQLiteStateStore,
    BrainEngine,
    DEFAULT_KRISTINA_PROFILE,
    FailoverLLMProvider,
    OllamaChatProvider,
)

async def main() -> None:
    store = AsyncSQLiteStateStore("agent_state.db")
    llm = FailoverLLMProvider([
        OllamaChatProvider(model="glm-5.3-flash:cloud", think=False),
        OllamaChatProvider(model="qwen3:8b", think=False),
    ])
    engine = BrainEngine(store, llm=llm, profile=DEFAULT_KRISTINA_PROFILE)
    await engine.start()
    try:
        res = await engine.ingest_message(
            scope_id="tenant:acme",
            event_id="msg-101",
            user_input="Great onboarding session — how do we enable Enterprise SSO?",
        )
        print(res["appraisal"], res["fast_state"]["for_llm"])

        tick = await engine.heartbeat_tick("tenant:acme", commit_proactive_send=False)
        print(tick["effective_decision"], tick["shadow_comparison"])
    finally:
        await engine.shutdown()

asyncio.run(main())
mcp_servers:
  kristina-brain:
    command: "/path/to/venv/bin/brain-core-mcp"
    args: []
    env:
      BRAIN_CORE_DB: "/home/user/.local/share/kristina-brain/state.db"
      BRAIN_CORE_OLLAMA_MODEL: "glm-5.3-flash:cloud,qwen3:8b"
License
Apache-2.0
