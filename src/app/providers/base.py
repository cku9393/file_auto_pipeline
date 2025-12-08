"""
AI Provider 추상 인터페이스.

ADR-0003:
- Provider 추상화로 모델 교체 가능
- model_requested + model_used 필수 기록

재현성 메타데이터:
- provider, model_params, request_id, prompt_hash 등 기록
- "조건부 재현성": 동일 파라미터로 유사 결과 기대 가능
"""

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# =============================================================================
# Raw Storage Configuration
# =============================================================================

class RawStorageLevel(str, Enum):
    """
    AI raw 데이터 저장 레벨.

    none: prompt/response 저장 안 함
    minimal: prompt_hash + response_hash만 (용량 절약)
    full: prompt/response 원문 저장 (재현성 최대)
    """
    NONE = "none"
    MINIMAL = "minimal"
    FULL = "full"


@dataclass
class AIRawStorageConfig:
    """
    AI raw 데이터 저장 설정.

    운영에서 코드로 강제되는 보안/용량 정책.
    """
    # 저장 레벨
    storage_level: RawStorageLevel = RawStorageLevel.FULL

    # 크기 제한 (bytes) - 초과 시 truncation
    max_raw_size: int = 1024 * 1024  # 1MB

    # PII 마스킹 활성화
    mask_pii: bool = False

    # 마스킹 패턴 (정규식)
    pii_patterns: list[str] = field(default_factory=lambda: [
        r'\d{6}-\d{7}',              # 주민번호
        r'\d{3}-\d{4}-\d{4}',        # 전화번호
        r'\d{3}-\d{3,4}-\d{4}',      # 전화번호 변형
        r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',  # 이메일
        r'\d{3,4}-\d{4}-\d{4}-\d{4}',  # 카드번호
    ])


@dataclass
class LLMCallParams:
    """
    LLM 호출 파라미터 기록.

    재현성에 영향을 주는 모든 파라미터.
    """
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    stop_sequences: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
            "stop_sequences": self.stop_sequences,
        }


@dataclass
class PromptComponents:
    """
    프롬프트 구성 요소 분리 저장.

    시스템 템플릿과 유저 입력을 분리하여 보안 리스크 감소.
    """
    template_id: str | None = None       # 사용된 템플릿 ID
    template_version: str | None = None  # 템플릿 버전
    user_variables: dict[str, str] = field(default_factory=dict)  # 유저 입력 변수
    rendered_prompt: str | None = None   # 렌더링된 전체 프롬프트 (옵션)
    prompt_hash: str | None = None       # 프롬프트 해시 (검색/중복 제거용)

    def to_dict(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "template_version": self.template_version,
            "user_variables": self.user_variables,
            "rendered_prompt": self.rendered_prompt,
            "prompt_hash": self.prompt_hash,
        }


def compute_hash(content: str) -> str:
    """SHA-256 해시 계산."""
    return f"sha256:{hashlib.sha256(content.encode()).hexdigest()[:16]}"

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

    조건부 재현성:
    - 동일 파라미터로 유사 결과를 기대할 수 있음
    - 완전한 재현은 보장하지 않음 (LLM 특성상)

    필수 메타데이터:
    - provider: 사용된 제공자 (anthropic, openai 등)
    - model_params: 호출 파라미터 (temperature, max_tokens 등)
    - request_id: API 요청 ID (가능한 경우)
    - prompt_hash: 프롬프트 해시 (검색/중복 제거용)
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

    # === 조건부 재현성 메타데이터 (신규) ===
    # Provider 정보
    provider: str | None = None  # "anthropic", "openai", "regex" 등

    # 호출 파라미터 (재현성에 영향)
    model_params: dict[str, Any] | None = None  # temperature, top_p, max_tokens 등

    # API 요청 추적
    request_id: str | None = None  # API 응답의 request_id (있는 경우)

    # === Raw 저장 (storage_level에 따라 조건부) ===
    # full: 원문 저장, minimal: hash만, none: 저장 안 함
    llm_raw_output: str | None = None       # API 응답 원문 (또는 truncated)
    llm_raw_output_hash: str | None = None  # 응답 해시 (minimal 모드용)
    llm_raw_truncated: bool = False         # truncation 발생 여부

    # 프롬프트 분리 저장 (보안)
    prompt_template_id: str | None = None    # 템플릿 ID
    prompt_template_version: str | None = None  # 템플릿 버전
    prompt_user_variables: dict[str, str] | None = None  # 유저 입력 변수
    prompt_rendered: str | None = None       # 렌더링된 프롬프트 (full 모드)
    prompt_hash: str | None = None           # 프롬프트 해시

    # 하위 호환용 (deprecated, prompt_rendered로 대체)
    prompt_used: str | None = None

    # === 정규식 추출용 메타데이터 ===
    extraction_method: str | None = None  # "llm", "regex"
    regex_version: str | None = None      # 정규식 규칙 버전/해시

    def to_dict(self) -> dict[str, Any]:
        result = {
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
            # 재현성 메타데이터
            "provider": self.provider,
            "model_params": self.model_params,
            "request_id": self.request_id,
            # Raw 저장
            "llm_raw_output": self.llm_raw_output,
            "llm_raw_output_hash": self.llm_raw_output_hash,
            "llm_raw_truncated": self.llm_raw_truncated,
            # 프롬프트 분리
            "prompt_template_id": self.prompt_template_id,
            "prompt_template_version": self.prompt_template_version,
            "prompt_user_variables": self.prompt_user_variables,
            "prompt_rendered": self.prompt_rendered,
            "prompt_hash": self.prompt_hash,
            # 하위 호환
            "prompt_used": self.prompt_used,
            # 추출 방법
            "extraction_method": self.extraction_method,
            "regex_version": self.regex_version,
        }
        # None 값 제거 (용량 절약)
        return {k: v for k, v in result.items() if v is not None}


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
