"""
Google Gemini OCR Provider.

ADR-0003 Fallback 예외 정책:
- FALLBACK_ERRORS: NotFound, ServiceUnavailable, ResourceExhausted, ModelLoadError → fallback
- REJECT_IMMEDIATELY: InvalidArgument, PermissionDenied, Unauthenticated → 즉시 reject
"""

import logging
import os
from datetime import UTC, datetime
from typing import Any

from .base import OCRError, OCRProvider, OCRResult

logger = logging.getLogger(__name__)

# =============================================================================
# Exception Mapping
# =============================================================================

# ADR-0003: Fallback 타는 예외
FALLBACK_ERRORS: tuple[type[Exception], ...] = ()

# ADR-0003: 즉시 reject하는 예외
REJECT_IMMEDIATELY: tuple[type[Exception], ...] = ()

# Google API 예외 동적 로드
try:
    from google.api_core.exceptions import (
        InvalidArgument,
        NotFound,
        PermissionDenied,
        ResourceExhausted,
        ServiceUnavailable,
        Unauthenticated,
    )

    FALLBACK_ERRORS = (
        NotFound,           # 모델명 오류/미지원
        ServiceUnavailable,  # 5xx
        ResourceExhausted,   # 429 쿼터/레이트리밋
    )

    REJECT_IMMEDIATELY = (
        InvalidArgument,    # 입력 오류
        PermissionDenied,   # 인증 오류
        Unauthenticated,    # API 키 오류
    )
except ImportError:
    pass


class GeminiOCRProvider(OCRProvider):
    """
    Gemini OCR Provider.

    Usage:
        provider = GeminiOCRProvider(
            model="gemini-3-pro-preview",
            fallback="gemini-2.5-flash"
        )
        result = await provider.extract_text(image_bytes, "image/jpeg")
    """

    def __init__(
        self,
        model: str = "gemini-3-pro-preview",
        fallback: str | None = "gemini-2.5-flash",
        api_key: str | None = None,
    ):
        """
        Args:
            model: 기본 모델 ID (config에서 주입)
            fallback: Fallback 모델 (None이면 재시도 없이 실패)
            api_key: API 키 (환경변수 GOOGLE_API_KEY 사용 가능)
        """
        self.model = model
        self.fallback = fallback
        self.api_key = api_key or os.environ.get("GOOGLE_API_KEY")
        self._client: Any = None

    def _get_client(self) -> Any:
        """Gemini 클라이언트 (lazy init)."""
        if self._client is None:
            try:
                import google.generativeai as genai
                genai.configure(api_key=self.api_key)
                self._client = genai
            except ImportError as e:
                raise OCRError(
                    "GEMINI_NOT_INSTALLED",
                    "google-generativeai package not installed. "
                    "Run: pip install google-generativeai",
                ) from e
        return self._client

    async def extract_text(
        self,
        file_bytes: bytes,
        file_type: str,
    ) -> OCRResult:
        """
        이미지/PDF에서 텍스트 추출.

        ADR-0003 Fallback 정책:
        - FALLBACK_ERRORS → fallback 모델로 재시도
        - REJECT_IMMEDIATELY → 즉시 에러
        """
        model_requested = self.model

        # 1차 시도: 기본 모델
        try:
            result = await self._call_api(self.model, file_bytes, file_type)
            result.model_requested = model_requested
            result.model_used = self.model
            result.fallback_triggered = False
            return result

        except FALLBACK_ERRORS as e:
            # Fallback 시도
            logger.warning(
                f"Primary model ({self.model}) failed with fallback error: {e}. "
                f"Attempting fallback..."
            )

            if self.fallback is None:
                user_friendly_message = self._get_user_friendly_error_message(e)
                raise OCRError(
                    "NO_FALLBACK",
                    user_friendly_message,
                    model=self.model,
                ) from e

            try:
                logger.info(f"Trying fallback model: {self.fallback}")
                result = await self._call_api(self.fallback, file_bytes, file_type)
                result.model_requested = model_requested
                result.model_used = self.fallback
                result.fallback_triggered = True
                logger.info("Fallback model succeeded")
                return result
            except Exception as fallback_error:
                logger.error(f"Fallback model also failed: {fallback_error}")
                user_friendly_message = (
                    f"{self._get_user_friendly_error_message(fallback_error)} "
                    f"기본 모델과 대체 모델 모두 실패했습니다."
                )
                raise OCRError(
                    "FALLBACK_FAILED",
                    user_friendly_message,
                    primary_model=self.model,
                    fallback_model=self.fallback,
                ) from fallback_error

        except REJECT_IMMEDIATELY as e:
            # 즉시 실패 (인증/입력 오류)
            logger.error(f"Authentication or input error: {e}", exc_info=True)
            user_friendly_message = self._get_user_friendly_error_message(e)
            raise OCRError(
                "AUTH_OR_INPUT_ERROR",
                user_friendly_message,
                model=self.model,
            ) from e

        except Exception as e:
            # 기타 예외
            logger.error(f"OCR failed with unexpected error: {e}", exc_info=True)
            user_friendly_message = self._get_user_friendly_error_message(e)
            raise OCRError(
                "OCR_FAILED",
                user_friendly_message,
                model=self.model,
            ) from e

    def _get_user_friendly_error_message(self, error: Exception) -> str:
        """사용자 친화적인 에러 메시지 생성."""
        try:
            from google.api_core.exceptions import (
                InvalidArgument,
                PermissionDenied,
                ResourceExhausted,
                ServiceUnavailable,
                Unauthenticated,
            )

            if isinstance(error, Unauthenticated):
                return (
                    "Google API 인증에 실패했습니다. "
                    "GOOGLE_API_KEY 환경변수를 확인해주세요."
                )
            elif isinstance(error, PermissionDenied):
                return (
                    "이 작업을 수행할 권한이 없습니다. "
                    "API 키의 권한을 확인해주세요."
                )
            elif isinstance(error, ResourceExhausted):
                return (
                    "API 사용량 한도를 초과했습니다. "
                    "잠시 후 다시 시도하거나 할당량을 확인해주세요."
                )
            elif isinstance(error, ServiceUnavailable):
                return (
                    "Google API 서비스를 일시적으로 사용할 수 없습니다. "
                    "잠시 후 다시 시도해주세요."
                )
            elif isinstance(error, InvalidArgument):
                return (
                    "요청 형식이 올바르지 않습니다. "
                    "입력 파일의 형식과 크기를 확인해주세요."
                )
        except ImportError:
            pass

        # 기본 메시지
        error_str = str(error)
        if "api_key" in error_str.lower() or "api key" in error_str.lower():
            return "API 키 설정을 확인해주세요."
        elif "quota" in error_str.lower() or "limit" in error_str.lower():
            return "API 사용량 한도를 초과했습니다. 잠시 후 다시 시도해주세요."
        elif "connection" in error_str.lower():
            return "네트워크 연결 오류가 발생했습니다."
        elif "timeout" in error_str.lower():
            return "요청 시간이 초과되었습니다. 다시 시도해주세요."

        return f"OCR 처리 중 오류가 발생했습니다: {error_str}"

    async def _call_api(
        self,
        model: str,
        file_bytes: bytes,
        file_type: str,
    ) -> OCRResult:
        """실제 Gemini API 호출."""
        now = datetime.now(UTC).isoformat()

        try:
            genai = self._get_client()

            # 모델 인스턴스 생성
            model_instance = genai.GenerativeModel(model)

            # 이미지 데이터 구성
            image_part = {
                "mime_type": self._normalize_mime_type(file_type),
                "data": file_bytes,
            }

            # OCR 프롬프트
            prompt = """
            이 이미지에서 모든 텍스트를 추출해주세요.
            표가 있으면 표 구조를 유지해주세요.
            추출된 텍스트만 반환하고, 설명은 하지 마세요.
            """

            # API 호출 (sync → async wrapper)
            # 실제 구현에서는 async 버전 사용
            response = model_instance.generate_content([prompt, image_part])

            text = response.text if response.text else ""
            confidence = self._estimate_confidence(text)

            return OCRResult(
                success=True,
                text=text,
                confidence=confidence,
                processed_at=now,
            )

        except Exception:
            # 예외를 상위로 전파 (fallback 정책 적용)
            raise

    def _normalize_mime_type(self, file_type: str) -> str:
        """파일 타입을 MIME 타입으로 정규화."""
        mime_map = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".pdf": "application/pdf",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
            "pdf": "application/pdf",
        }

        file_type_lower = file_type.lower()

        # 이미 MIME 타입이면 그대로 반환
        if "/" in file_type_lower:
            return file_type_lower

        return mime_map.get(file_type_lower, "application/octet-stream")

    def _estimate_confidence(self, text: str) -> float:
        """
        OCR 결과 신뢰도 추정.

        간단한 휴리스틱:
        - 텍스트가 비어있으면 0.0
        - 길이와 특수문자 비율로 추정
        """
        if not text or len(text.strip()) == 0:
            return 0.0

        text = text.strip()

        # 너무 짧으면 낮은 신뢰도
        if len(text) < 10:
            return 0.3

        # 특수문자/깨진 문자 비율 체크
        weird_chars = sum(1 for c in text if ord(c) > 0xFFFF or c in "�□")
        weird_ratio = weird_chars / len(text)

        if weird_ratio > 0.1:
            return 0.5

        # 기본 높은 신뢰도
        return 0.9
