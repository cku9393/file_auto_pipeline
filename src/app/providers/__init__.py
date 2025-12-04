"""
AI Provider Abstraction.

모델 교체 가능하게 설계 (ADR-0003).
모델명은 config만 SSOT.
"""

from .anthropic import ClaudeProvider
from .base import ExtractionResult, LLMProvider, OCRProvider, OCRResult
from .gemini import GeminiOCRProvider

__all__ = [
    "LLMProvider",
    "OCRProvider",
    "OCRResult",
    "ExtractionResult",
    "ClaudeProvider",
    "GeminiOCRProvider",
]
