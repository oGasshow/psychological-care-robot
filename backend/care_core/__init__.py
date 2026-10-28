"""Lightweight, DB/audio independent text analysis; never a medical assessment."""

from .core import (
    CoreAnalysisError,
    CoreSettings,
    ENGINE_VERSION,
    OLLAMA_ENGINE_VERSION,
    analyze,
    configuration,
    input_eligibility,
    local_preview,
    safety,
)

__all__ = [
    "CoreAnalysisError", "CoreSettings", "ENGINE_VERSION", "OLLAMA_ENGINE_VERSION",
    "analyze", "configuration", "input_eligibility", "local_preview", "safety",
]
