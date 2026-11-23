"""
Kristina / SomaCore Brain Engine — выделенное асинхронное ядро состояния,
когнитивной оценки, 12 медленных мод, политики проактивности и shadow-телеметрии.
Нулевая зависимость от python-telegram-bot.
"""

from .appraisal import Appraisal, CognitiveAppraiser
from .artifacts import CreativeArtifact
from .autonomy import (
    AutonomousDecision,
    DecisionEngine,
    DesireEngine,
    ShadowDecisionReport,
    evaluate_with_shadow,
)
from .clock import ClockProvider, FixedClock, SystemClock
from .control_plane import create_control_plane_app, sign_webhook_payload
from .dialogue import dialogue_proactive_block_reason, is_repeated_question
from .emotions import FAST_STATE_KEYS, AsyncEmotionalCore, EmotionalEvent
from .engine import BrainEngine
from .intentions import DurableIntention, DurableIntentionEngine
from .llm_provider import (
    FailoverLLMProvider,
    HTTPXChatCompletionsProvider,
    LLMProvider,
    LLMProviderError,
    OllamaChatProvider,
)
from .modes import DEFAULT_MODE_DEFINITIONS, AsyncOrganismModes, ModeDefinition, ModeState, OrganismProjection
from .neuro import NeuromodulatorField, NeuronNode, SpikeEvent, SynapseEdge, SynapticGraphEngine
from .pacing import ResponsePacing, ResponsePacingEngine
from .packs import AI_COMPANION_PACK, B2B_CSM_PACK, GAME_NPC_PACK, VERTICAL_PACKS, load_vertical_pack
from .postgres_store import AsyncPostgresStateStore, create_state_store
from .priors import ColdStartPrior, PriorProvider
from .profile import DEFAULT_KRISTINA_PROFILE, BigFiveTraits, ModeSpec, PersonaProfile
from .shadow import AsyncShadowTelemetryStore
from .sleep import DreamSeed, SleepConsolidationReport, SleepConsolidationWorker
from .state_store import (
    AsyncSQLiteStateStore,
    ProactiveScheduleRecord,
    StateStore,
)
from .world import WorldStateAnchor, resolve_iana_timezone

__all__ = [
    "ClockProvider",
    "SystemClock",
    "FixedClock",
    "PersonaProfile",
    "BigFiveTraits",
    "ModeSpec",
    "DEFAULT_KRISTINA_PROFILE",
    "LLMProvider",
    "HTTPXChatCompletionsProvider",
    "FailoverLLMProvider",
    "OllamaChatProvider",
    "LLMProviderError",
    "StateStore",
    "AsyncPostgresStateStore",
    "AsyncSQLiteStateStore",
    "create_state_store",
    "ProactiveScheduleRecord",
    "EmotionalEvent",
    "AsyncEmotionalCore",
    "FAST_STATE_KEYS",
    "ModeDefinition",
    "ModeState",
    "OrganismProjection",
    "AsyncOrganismModes",
    "DEFAULT_MODE_DEFINITIONS",
    "AI_COMPANION_PACK",
    "Appraisal",
    "B2B_CSM_PACK",
    "CreativeArtifact",
    "GAME_NPC_PACK",
    "VERTICAL_PACKS",
    "load_vertical_pack",
    "CognitiveAppraiser",
    "AutonomousDecision",
    "ShadowDecisionReport",
    "DesireEngine",
    "DecisionEngine",
    "evaluate_with_shadow",
    "AsyncShadowTelemetryStore",
    "BrainEngine",
    "ColdStartPrior",
    "DreamSeed",
    "NeuromodulatorField",
    "NeuronNode",
    "PriorProvider",
    "SleepConsolidationReport",
    "SleepConsolidationWorker",
    "SpikeEvent",
    "SynapseEdge",
    "SynapticGraphEngine",
    "create_control_plane_app",
    "sign_webhook_payload",
    "DurableIntention",
    "DurableIntentionEngine",
    "dialogue_proactive_block_reason",
    "is_repeated_question",
    "ResponsePacing",
    "ResponsePacingEngine",
    "WorldStateAnchor",
    "resolve_iana_timezone",
]

__version__ = "1.2.0"
