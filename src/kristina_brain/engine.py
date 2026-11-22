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
from .artifacts import CreativeArtifact
from .autonomy import (
    AutonomousDecision,
    DecisionEngine,
    DesireEngine,
    ShadowDecisionReport,
    evaluate_with_shadow,
)
from .clock import ClockProvider, SystemClock
from .dialogue import (
    apply_assistant_turn,
    apply_user_turn,
    dialogue_proactive_block_reason,
    empty_dialogue_state,
    is_repeated_question,
)
from .emotions import AsyncEmotionalCore, EmotionalEvent
from .intentions import DurableIntentionEngine
from .llm_provider import LLMProvider
from .modes import AsyncOrganismModes
from .neuro import NeuromodulatorField, SynapticGraphEngine
from .pacing import ResponsePacingEngine
from .priors import ColdStartPrior, PriorProvider
from .profile import DEFAULT_KRISTINA_PROFILE, PersonaProfile
from .shadow import AsyncShadowTelemetryStore
from .sleep import SleepConsolidationWorker
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
        prior_provider: PriorProvider | None = None,
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
        self.intentions = DurableIntentionEngine(store, clock=self.clock)
        self.prior_provider = prior_provider
        self.synapses = SynapticGraphEngine(store, clock=self.clock)
        self.sleep_worker = SleepConsolidationWorker(store, self.synapses, self.modes, clock=self.clock)
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

        dialogue_state = await self.store.get_dialogue_state(scope_id) or empty_dialogue_state()
        scheduled_intention = None
        if fast_state.get("event_applied", False):
            dialogue_state = apply_user_turn(
                dialogue_state,
                event_id=event_id,
                user_input=user_input,
                at=utc_now,
            )
            await self.store.save_dialogue_state(scope_id, dialogue_state)
            if appraisal is not None and appraisal.interest_action == "open" and appraisal.intensity >= 0.6:
                scheduled_intention = await self.intentions.schedule(
                    scope_id=scope_id,
                    source_event_id=event_id,
                    kind="topic_followup",
                    topic=appraisal.topic,
                    plan={"source_quote": appraisal.source_quote, "reaction": appraisal.reaction},
                )

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
        recent_intentions_list = await self.intentions.list_for_scope(scope_id, limit=3)
        intention_line = self.intentions.format_prompt_context(recent_intentions_list)
        artifacts = await self.store.list_artifacts(scope_id, limit=1)
        artifact_line = artifacts[0].format_for_prompt() if artifacts else ""
        extra_lines = [x for x in (dual_clock["prompt_line"], intention_line, artifact_line) if x]
        if extra_lines:
            fast_state = dict(fast_state)
            fast_state["for_llm"] = f"{fast_state['for_llm']} {' '.join(extra_lines)}"

        mode_snap = await self.modes.snapshot(scope_id)
        chem = NeuromodulatorField.from_brain_state(
            fast_state,
            mode_snap,
            is_quiet_hours=bool(fast_state["is_night"] or dual_clock["counterparty_is_night"]),
        )
        stim_map: dict[str, float] = {}
        if reaction == "warmth":
            stim_map["sensor_warmth"] = intensity
        elif reaction == "curiosity":
            stim_map["sensor_curiosity"] = intensity
        elif reaction in ("frustration", "concern"):
            stim_map["sensor_conflict"] = intensity
        neural_pulse = await self.synapses.propagate_stimuli(stim_map, chem, scope_id=scope_id, at=utc_now)
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
            "neural_pulse": neural_pulse,
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
            "dialogue_state": dialogue_state,
            "scheduled_intention_id": scheduled_intention.intention_id if scheduled_intention else None,
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
        dialogue_state = await self.store.get_dialogue_state(scope_id)
        dialogue_block = dialogue_proactive_block_reason(dialogue_state, utc_now)

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
        if dialogue_block is not None and effective.action == "message":
            effective = AutonomousDecision(
                action="none",
                intention=None,
                score=0.0,
                reason=dialogue_block,
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

    async def record_assistant_reply(
        self,
        *,
        scope_id: str,
        reply_id: str,
        reply_text: str,
        is_proactive: bool = False,
        pause_hours: float | None = None,
    ) -> dict[str, Any]:
        """
        Проверяет кандидат ответа/проактивного пинга на повтор уже заданного вопроса
        и фиксирует ход агента в эпизодическом состоянии диалога.
        """
        utc_now = self.clock.now_utc()
        state = await self.store.get_dialogue_state(scope_id) or empty_dialogue_state()
        repeated = is_repeated_question(reply_text, state)
        if repeated:
            return {
                "accepted": False,
                "reason": "repeated_question",
                "pending_question": state.get("pending_question"),
            }
        updated = apply_assistant_turn(
            state,
            reply_id=reply_id,
            reply_text=reply_text,
            at=utc_now,
            is_proactive=is_proactive,
        )
        if pause_hours is not None and pause_hours > 0:
            from datetime import timedelta as _td

            updated["pause_until"] = (utc_now + _td(hours=pause_hours)).isoformat()
        await self.store.save_dialogue_state(scope_id, updated)
        return {
            "accepted": True,
            "reason": "recorded",
            "pending_question": updated.get("pending_question"),
            "proactive_since_user": updated.get("proactive_since_user", 0),
        }

    async def save_artifact(
        self,
        *,
        scope_id: str,
        artifact_id: str,
        title: str,
        excerpt: str,
        status_note: str = "черновик в работе",
    ) -> CreativeArtifact:
        art = CreativeArtifact(
            artifact_id=artifact_id.strip(),
            scope_id=scope_id.strip(),
            title=title.strip(),
            excerpt=excerpt.strip(),
            status_note=status_note.strip(),
            updated_at=self.clock.now_utc(),
        )
        await self.store.upsert_artifact(art)
        return art

    async def get_artifacts(self, scope_id: str = "default", *, limit: int = 5) -> list[CreativeArtifact]:
        return await self.store.list_artifacts(scope_id, limit=limit)

    async def initialize_scope_with_prior(
        self,
        scope_id: str,
        metadata: Mapping[str, Any],
    ) -> ColdStartPrior:
        """Применяет внешний плагин PriorProvider (например, для холодного старта гостя отеля)."""
        if self.prior_provider is None:
            raise RuntimeError("No PriorProvider configured on this BrainEngine")
        now = self.clock.now_utc()
        prior = self.prior_provider.compute_prior(scope_id, metadata)
        snap = await self.modes.relax_to_baseline(scope_id, at=now)
        updates = []
        for mode_name, offset in prior.initial_mode_offsets.items():
            if mode_name in snap:
                st = snap[mode_name]
                clamped_amp = max(0.0, min(1.0, round(st.baseline + float(offset), 4)))
                updates.append(
                    {
                        "name": mode_name,
                        "baseline": st.baseline,
                        "amplitude": clamped_amp,
                        "phase": st.phase,
                        "half_life_hours": st.half_life_hours,
                        "updated_at": now.isoformat(),
                    }
                )
        if updates:
            await self.store.upsert_modes_atomic(scope_id, updates)
        await self.synapses.ensure_circuit(
            scope_id,
            initial_synapse_overrides=prior.initial_synapse_weights,
            at=now,
        )
        return prior

    async def pulse_synapses(
        self,
        scope_id: str,
        stimuli: Mapping[str, float],
    ) -> dict[str, Any]:
        """Прямой субсимвольный импульс в синаптическую сеть без вызова LLM (<1 мс)."""
        utc_now = self.clock.now_utc()
        fast = await self.emotions.get_emotional_state(scope_id)
        mode_snap = await self.modes.snapshot(scope_id)
        world = await self.get_world_context(scope_id)
        chem = NeuromodulatorField.from_brain_state(
            fast,
            mode_snap,
            is_quiet_hours=bool(fast["is_night"] or world["counterparty_is_night"]),
        )
        return await self.synapses.propagate_stimuli(stimuli, chem, scope_id=scope_id, at=utc_now)

    async def run_sleep_consolidation(
        self,
        scope_id: str = "default",
        *,
        reward_signal: float = 0.0,
    ) -> dict[str, Any]:
        """Запускает ночное обучение синапсов Хебба, дрейф baseline и синтез семени сна DreamSeed."""
        utc_now = self.clock.now_utc()
        fast = await self.emotions.get_emotional_state(scope_id)
        mode_snap = await self.modes.snapshot(scope_id)
        chem = NeuromodulatorField.from_brain_state(fast, mode_snap, is_quiet_hours=True)
        rep = await self.sleep_worker.consolidate(
            scope_id,
            reward_signal=reward_signal,
            chem=chem,
            at=utc_now,
        )
        return {
            "scope_id": rep.scope_id,
            "consolidated_at": rep.consolidated_at.isoformat(),
            "synapses_adjusted": rep.synapses_adjusted,
            "synapse_deltas": rep.synapse_deltas,
            "modes_drifted": rep.modes_drifted,
            "baseline_deltas": rep.baseline_deltas,
            "dream_seed": {
                "dominant_themes": list(rep.dream_seed.dominant_themes),
                "sensory_fragments": list(rep.dream_seed.sensory_fragments),
                "creative_draft_bridge": rep.dream_seed.creative_draft_bridge,
                "vividness": rep.dream_seed.vividness,
            }
            if rep.dream_seed
            else None,
        }
