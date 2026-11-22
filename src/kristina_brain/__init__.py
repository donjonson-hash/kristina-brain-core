"""
Kristina / SomaCore Brain Engine — выделенное асинхронное ядро состояния,
когнитивной оценки, 12 медленных мод, политики проактивности и shadow-телеметрии.
Нулевая зависимость от python-telegram-bot.
"""

from .appraisal import Appraisal, CognitiveAppraiser
from .autonomy import (
    AutonomousDecision,
    DecisionEngine,
    DesireEngine,
    ShadowDecisionReport,
    evaluate_with_shadow,
)
from .clock import ClockProvider, FixedClock, SystemClock
from .emotions import FAST_STATE_KEYS, AsyncEmotionalCore, EmotionalEvent
from .engine import BrainEngine
from .llm_provider import (
    FailoverLLMProvider,
    HTTPXChatCompletionsProvider,
    LLMProvider,
    LLMProviderError,
    OllamaChatProvider,
)
from .modes import DEFAULT_MODE_DEFINITIONS, AsyncOrganismModes, ModeDefinition, ModeState, OrganismProjection
from .pacing import ResponsePacing, ResponsePacingEngine
from .profile import DEFAULT_KRISTINA_PROFILE, BigFiveTraits, ModeSpec, PersonaProfile
from .shadow import AsyncShadowTelemetryStore
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
    "AsyncSQLiteStateStore",
    "ProactiveScheduleRecord",
    "EmotionalEvent",
    "AsyncEmotionalCore",
    "FAST_STATE_KEYS",
    "ModeDefinition",
    "ModeState",
    "OrganismProjection",
    "AsyncOrganismModes",
    "DEFAULT_MODE_DEFINITIONS",
    "Appraisal",
    "CognitiveAppraiser",
    "AutonomousDecision",
    "ShadowDecisionReport",
    "DesireEngine",
    "DecisionEngine",
    "evaluate_with_shadow",
    "AsyncShadowTelemetryStore",
    "BrainEngine",
    "ResponsePacing",
    "ResponsePacingEngine",
    "WorldStateAnchor",
    "resolve_iana_timezone",
]

__version__ = "0.5.0"
