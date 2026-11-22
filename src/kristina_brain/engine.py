"""
Главный оркестратор-фасад BrainEngine (v0.5.0).
Объединяет предоценку стимула, двухшкальное состояние (7 быстрых + 12 медленных мод),
якоря мира собеседника (WorldStateAnchor), пересечение двух часовых поясов (DualClockGate),
физиологический ритм ответа (ResponsePacingEngine) и приватную shadow-телеметрию.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import timedelta
from typing import Any

from .appraisal import Appraisal, CognitiveAppraiser
from .autonomy import (
    AutonomousDecision,
    DecisionEngine,
    DesireEngine,
    ShadowDecisionReport,
    evaluate_with_shadow,
)
from .clock import ClockProvider, SystemClock
from .emotions import AsyncEmotionalCore, EmotionalEvent
from .llm_provider import LLMProvider
from .modes import AsyncOrganismModes
from .pacing import ResponsePacingEngine
from .profile import DEFAULT_KRISTINA_PROFILE, PersonaProfile
from .shadow import AsyncShadowTelemetryStore
from .state_store import ProactiveScheduleRecord, StateStore
from .world import WorldStateAnchor


class BrainEngine:
    """Единая точка входа в автономный «мозг» агента (без зависимости от мессенджера)."""

    def __init__(
        self,
        store: StateStore,
        *,
        llm: LLMProvider | None = None,
        profile: PersonaProfile = DEFAULT_KRISTINA_PROFILE,
        clock: ClockProvider | None = None,
    ) -> None:
        self.store = store
        self.profile = profile
        self.clock: ClockProvider = clock or SystemClock(profile.timezone)
        self.llm = llm

        self.emotions = AsyncEmotionalCore(store, profile=profile, clock=self.clock)
        self.modes = AsyncOrganismModes(
            store,
            clock=self.clock,
            custom_specs=profile.custom_modes,
        )
        self.appraiser = CognitiveAppraiser(llm, profile=profile, clock=self.clock) if llm is not None else None
        self.desire_engine = DesireEngine()
        self.decision_engine = DecisionEngine(
            threshold=profile.proactive_threshold,
            cooldown=timedelta(seconds=profile.proactive_cooldown_seconds),
        )
        self.pacing_engine = ResponsePacingEngine(
            min_delay_seconds=profile.pacing_min_delay_seconds,
            max_delay_seconds=profile.pacing_max_delay_seconds,
        )
        self.shadow_telemetry = AsyncShadowTelemetryStore(store)

    async def start(self) -> None:
        await self.store.initialize()

    async def shutdown(self) -> None:
        if self.llm is not None:
            await self.llm.aclose()
        await self.store.close()

    async def get_world_context(self, scope_id: str = "default") -> dict[str, Any]:
        utc_now = self.clock.now_utc()
        anchor: WorldStateAnchor = await self.store.get_world_anchor(scope_id)
        dual = anchor.format_dual_clock_context(
            utc_now=utc_now,
            agent_tz=self.profile.timezone,
            agent_city_label=self.profile.locale_city_label,
            counterparty_quiet_hours=self.profile.counterparty_night_hours,
        )
        return {
            "scope_id": scope_id,
            "counterparty_location": anchor.counterparty_location,
            "counterparty_timezone": anchor.counterparty_timezone,
            "environment_cues": list(anchor.environment_cues),
            "updated_at": anchor.updated_at.isoformat() if anchor.updated_at else None,
            **dual,
        }

    async def ingest_message(
        self,
        *,
        scope_id: str,
        event_id: str,
        user_input: str,
        history: Sequence[Mapping[str, Any]] = (),
        explicit_appraisal: Appraisal | None = None,
    ) -> dict[str, Any]:
        utc_now = self.clock.now_utc()
        ev = EmotionalEvent.from_message(scope_id, event_id, user_input)

        appraisal = explicit_appraisal
        if appraisal is None and self.appraiser is not None:
            appraisal = await self.appraiser.assess_event(user_input, history=history)

        reaction = appraisal.reaction if appraisal else "neutral"
        intensity = appraisal.intensity if appraisal else 0.35
        reflection = appraisal.reflection if appraisal else None

        schedule = await self.store.get_proactive_schedule(scope_id)
        hours_since = (
            max(0.0, (utc_now - schedule.last_user_activity).total_seconds() / 3600.0)
            if schedule.last_user_activity
            else 0.0
        )

        fast_state = await self.emotions.evolve(
            scope_id,
            context={"hours_since_contact": hours_since},
            reaction=reaction,
            intensity=intensity,
            reflection=reflection,
            event=ev,
        )

        mode_applied = await self.modes.apply_message_event(
            scope_id=scope_id,
            session_sha256=ev.session_sha256,
            event_id=ev.event_id,
            input_sha256=ev.input_sha256,
            kinds=[reaction],
            at=utc_now,
        )

        # Обновляем якорь физического мира собеседника, если в реплике обнаружены локация/таймзона/детали окружения
        anchor = await self.store.get_world_anchor(scope_id)
        if fast_state.get("event_applied", False) and appraisal is not None:
            if appraisal.detected_location or appraisal.detected_timezone or appraisal.environment_cue:
                anchor = anchor.merge_signal(
                    location=appraisal.detected_location,
                    timezone_name=appraisal.detected_timezone,
                    environment_cue=appraisal.environment_cue,
                    at=utc_now,
                )
                await self.store.upsert_world_anchor(anchor)

        if fast_state.get("event_applied", False):
            await self.store.upsert_proactive_schedule(
                ProactiveScheduleRecord(
                    scope_id=scope_id,
                    last_user_activity=utc_now,
                    last_proactive_at=schedule.last_proactive_at,
                    next_opportunity_at=utc_now + timedelta(seconds=self.profile.proactive_cooldown_seconds),
                    proactive_count_24h=schedule.proactive_count_24h,
                    recent_intentions=schedule.recent_intentions,
                )
            )

        dual_clock = anchor.format_dual_clock_context(
            utc_now=utc_now,
            agent_tz=self.profile.timezone,
            agent_city_label=self.profile.locale_city_label,
            counterparty_quiet_hours=self.profile.counterparty_night_hours,
        )
        if dual_clock["prompt_line"]:
            fast_state = dict(fast_state)
            fast_state["for_llm"] = f"{fast_state['for_llm']} {dual_clock['prompt_line']}"

        pacing = self.pacing_engine.calculate(fast_state, user_input_length=len(user_input))
        dominant_modes = await self.modes.dominant(scope_id, limit=3)

        return {
            "scope_id": scope_id,
            "event_id": event_id,
            "event_applied": bool(fast_state.get("event_applied", False)),
            "mode_event_applied": mode_applied,
            "appraisal": {
                "reaction": appraisal.reaction,
                "intensity": appraisal.intensity,
                "topic": appraisal.topic,
                "interest_action": appraisal.interest_action,
                "reflection": appraisal.reflection,
                "detected_location": appraisal.detected_location,
                "detected_timezone": appraisal.detected_timezone,
                "environment_cue": appraisal.environment_cue,
            }
            if appraisal
            else None,
            "fast_state": fast_state,
            "response_pacing": {
                "delay_seconds": pacing.delay_seconds,
                "verbosity_hint": pacing.verbosity_hint,
                "sensory_curiosity_high": pacing.sensory_curiosity_high,
            },
            "world_anchor": {
                "counterparty_location": anchor.counterparty_location,
                "counterparty_timezone": anchor.counterparty_timezone,
                "environment_cues": list(anchor.environment_cues),
                **dual_clock,
            },
            "dominant_modes": [
                {"name": m.name, "amplitude": m.amplitude, "baseline": m.baseline, "deviation": m.deviation}
                for m in dominant_modes
            ],
        }

    async def heartbeat_tick(
        self,
        scope_id: str = "default",
        *,
        commit_proactive_send: bool = False,
    ) -> dict[str, Any]:
        utc_now = self.clock.now_utc()
        schedule = await self.store.get_proactive_schedule(scope_id)
        anchor = await self.store.get_world_anchor(scope_id)

        hours_since_contact = (
            max(0.0, (utc_now - schedule.last_user_activity).total_seconds() / 3600.0)
            if schedule.last_user_activity
            else 4.0
        )

        count_24h = schedule.proactive_count_24h
        if schedule.last_proactive_at and (utc_now - schedule.last_proactive_at) >= timedelta(hours=24):
            count_24h = 0

        fast_state = await self.emotions.evolve(
            scope_id,
            context={"hours_since_contact": hours_since_contact},
        )
        projection = await self.modes.project(scope_id, at=utc_now)
        dual_clock = anchor.format_dual_clock_context(
            utc_now=utc_now,
            agent_tz=self.profile.timezone,
            agent_city_label=self.profile.locale_city_label,
            counterparty_quiet_hours=self.profile.counterparty_night_hours,
        )

        ctx = {
            "hours_since_contact": hours_since_contact,
            "last_proactive": schedule.last_proactive_at,
            "proactive_count_24h": count_24h,
            "is_night": fast_state["is_night"],
            "counterparty_is_night": dual_clock["counterparty_is_night"],
        }

        report: ShadowDecisionReport = evaluate_with_shadow(
            self.desire_engine,
            self.decision_engine,
            fast_state,
            projection,
            context=ctx,
            now=utc_now,
        )

        await self.shadow_telemetry.record_once(
            kind="proactive",
            scope=scope_id,
            opportunity_at=utc_now,
            observed_at=utc_now,
            projection=projection,
            report=report,
        )

        effective: AutonomousDecision = (
            report.shadow if self.profile.enable_slow_modes_in_decisions else report.baseline
        )

        if commit_proactive_send and effective.action == "message":
            new_intentions = tuple(list(schedule.recent_intentions[-9:]) + [effective.intention or "talk"])
            await self.store.upsert_proactive_schedule(
                ProactiveScheduleRecord(
                    scope_id=scope_id,
                    last_user_activity=schedule.last_user_activity,
                    last_proactive_at=utc_now,
                    next_opportunity_at=utc_now + timedelta(seconds=self.profile.proactive_cooldown_seconds),
                    proactive_count_24h=count_24h + 1,
                    recent_intentions=new_intentions,
                )
            )

        for_llm = fast_state["for_llm"]
        if dual_clock["prompt_line"]:
            for_llm = f"{for_llm} {dual_clock['prompt_line']}"

        return {
            "scope_id": scope_id,
            "effective_decision": {
                "action": effective.action,
                "intention": effective.intention,
                "score": effective.score,
                "reason": effective.reason,
                "policy_mode": "slow_modes_enabled"
                if self.profile.enable_slow_modes_in_decisions
                else "baseline_fast_only",
            },
            "world_clock": dual_clock,
            "shadow_comparison": {
                "decision_changed": report.decision_changed,
                "max_abs_score_delta": report.max_abs_score_delta,
                "baseline_action": report.baseline.action,
                "shadow_action": report.shadow.action,
                "shifted_modes": list(projection.shifted_modes),
            },
            "fast_state_for_llm": for_llm,
        }
