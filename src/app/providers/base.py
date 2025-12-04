"""
AI Provider 추상 인터페이스.

ADR-0003:
- Provider 추상화로 모델 교체 가능
- model_requested + model_used 필수 기록
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

# =============================================================================
# Result Data Classes
# =============================================================================

@dataclass
class OCRResult:
    """
    OCR 결과.

    ADR-0003 필수 키:
    - model_requested: config에 설정된 모델
    - model_used: 실제 호출된 모델 (fallback 시 다를 수 있음)
    - fallback_triggered: fallback 발생 여부
    """
    success: bool
    text: str | None = None
    confidence: float | None = None

    # 모델 추적 (ADR-0003 필수)
    model_requested: str | None = None
    model_used: str | None = None
    fallback_triggered: bool = False

    processed_at: str | None = None
    error_message: str | None = None
    error_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "text": self.text,
            "confidence": self.confidence,
            "model_requested": self.model_requested,
            "model_used": self.model_used,
            "fallback_triggered": self.fallback_triggered,
            "processed_at": self.processed_at,
            "error_message": self.error_message,
            "error_code": self.error_code,
        }


@dataclass
class ExtractionResult:
    """
    LLM 추출 결과.

    ADR-0003:
    - LLM은 구조화 제안만, 최종 판정은 core/validate
    - model_requested + model_used 필수 기록
    """
    success: bool = True
    fields: dict[str, Any] = field(default_factory=dict)
    measurements: list[dict[str, Any]] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    confidence: float | None = None
    suggested_template_id: str | None = None

    # 모델 추적 (ADR-0003 필수)
    model_requested: str | None = None
    model_used: str | None = None

    extracted_at: str | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "fields": self.fields,
            "measurements": self.measurements,
            "missing_fields": self.missing_fields,
            "warnings": self.warnings,
            "confidence": self.confidence,
            "suggested_template_id": self.suggested_template_id,
            "model_requested": self.model_requested,
            "model_used": self.model_used,
            "extracted_at": self.extracted_at,
            "error_message": self.error_message,
        }


# =============================================================================
# Provider Exceptions
# =============================================================================

class ProviderError(Exception):
    """Provider 관련 에러."""

    def __init__(self, code: str, message: str, **context: Any) -> None:
        self.code = code
        self.message = message
        self.context = context
        super().__init__(f"[{code}] {message}")


class OCRError(ProviderError):
    """OCR 관련 에러."""
    pass


class ExtractionError(ProviderError):
    """LLM 추출 관련 에러."""
    pass


# =============================================================================
# Abstract Providers
# =============================================================================

class LLMProvider(ABC):
    """
    LLM Provider 추상 인터페이스.

    역할: 입력 정리/구조화 제안 (판정 권한 없음)
    """

    @abstractmethod
    async def extract_fields(
        self,
        user_input: str,
        ocr_text: str | None,
        definition: dict[str, Any],
        prompt_template: str,
    ) -> ExtractionResult:
        """
        사용자 입력에서 필드 추출.

        Args:
            user_input: 사용자 채팅 입력
            ocr_text: OCR로 추출된 텍스트 (있는 경우)
            definition: definition.yaml 내용
            prompt_template: 프롬프트 템플릿

        Returns:
            ExtractionResult
        """
        ...

    @abstractmethod
    async def complete(self, prompt: str, **kwargs: Any) -> str:
        """
        일반 완성 API.

        Args:
            prompt: 프롬프트
            **kwargs: 추가 옵션

        Returns:
            응답 텍스트
        """
        ...


class OCRProvider(ABC):
    """
    OCR Provider 추상 인터페이스.

    역할: 이미지/PDF → 텍스트 추출
    """

    @abstractmethod
    async def extract_text(
        self,
        file_bytes: bytes,
        file_type: str,
    ) -> OCRResult:
        """
        파일에서 텍스트 추출.

        Args:
            file_bytes: 파일 바이트
            file_type: MIME 타입 또는 확장자

        Returns:
            OCRResult

        ADR-0003 Fallback 정책:
        - FALLBACK_ERRORS → fallback 모델로 재시도
        - REJECT_IMMEDIATELY → 즉시 에러
        """
        ...
