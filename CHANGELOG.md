# Changelog

## [1.0.0] — 2026-11-22 (General Availability)
- Promoted public SDK, 10-tool MCP server (`brain-core-mcp`), and Cloud Control Plane (`brain-core-cloud`) to **1.0.0 Production/Stable** API contract.
- Full end-to-end verification across Python SDK, stdio MCP, FastAPI Control Plane, SQLite WAL, and PostgreSQL (`asyncpg`) contracts.

## [0.9.0] — 2026-11-22
- Added 3 commercial vertical packs (`b2b_csm`, `ai_companion`, `game_npc`) via `load_vertical_pack()`.
- Added `CreativeArtifact` slot (`brain_save_artifact` / `brain_list_artifacts`) for multi-week draft and project continuity.

## [0.8.0] — 2026-11-22
- Added Commercial Cloud Control Plane (`brain-core-cloud`): FastAPI REST Gateway, constant-time API-key auth, live HTML console (`/dashboard`), zero-deploy `PersonaProfile` tuning, PII-free Shadow A/B ROI (`/v1/shadow/roi`), and HMAC-SHA256 webhooks.

## [0.7.0] — 2026-11-22
- Added `AsyncPostgresStateStore` (`asyncpg` JSONB + `FOR UPDATE SKIP LOCKED`), `create_state_store()` router, PEP 561 `py.typed`, and 500-tenant concurrency stress suite.

## [0.6.0] — 2026-11-22
- Added `EpisodicDialogueGate` (`is_repeated_question`, `awaiting_answer`, `awaiting_user_turn`) and multi-tenant `DurableIntentionEngine`.

## [0.5.0] — 2026-11-22
- Added `WorldStateAnchor`, `DualClockGate` (`counterparty_quiet_hours`), and `ResponsePacingEngine`.

## [0.4.0] — 2026-11-22
- Initial public Open-Core release: calibrated 7 fast emotions + 12 slow modes (`conflict_brake` + `rapport_gate`), `OllamaChatProvider` + `FailoverLLMProvider` circuit breaker, and PII-free `AsyncShadowTelemetryStore`.
