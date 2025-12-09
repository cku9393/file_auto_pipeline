"""
test_gemini.py - Gemini OCR Provider 테스트

ADR-0003 Fallback 예외 정책 검증:
- FALLBACK_ERRORS: NotFound, ServiceUnavailable, ResourceExhausted → fallback
- REJECT_IMMEDIATELY: InvalidArgument, PermissionDenied, Unauthenticated → 즉시 reject
"""

from unittest.mock import MagicMock, patch

import pytest

from src.app.providers.base import OCRError
from src.app.providers.gemini import (
    FALLBACK_ERRORS,
    REJECT_IMMEDIATELY,
    GeminiOCRProvider,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def provider():
    """기본 Gemini provider."""
    return GeminiOCRProvider(
        model="gemini-3-pro",
        fallback="gemini-2.5-flash",
        api_key="test-api-key",
    )


@pytest.fixture
def provider_no_fallback():
    """Fallback 없는 provider."""
    return GeminiOCRProvider(
        model="gemini-3-pro",
        fallback=None,
        api_key="test-api-key",
    )


# =============================================================================
# 초기화 테스트
# =============================================================================


class TestGeminiOCRProviderInit:
    """GeminiOCRProvider 초기화 테스트."""

    def test_init_with_defaults(self):
        """기본값으로 초기화."""
        provider = GeminiOCRProvider()

        assert provider.model == "gemini-3-pro-preview"
        assert provider.fallback == "gemini-2.5-flash"

    def test_init_with_custom_model(self):
        """커스텀 모델로 초기화."""
        provider = GeminiOCRProvider(model="custom-model", fallback="backup-model")

        assert provider.model == "custom-model"
        assert provider.fallback == "backup-model"

    def test_init_with_api_key(self):
        """API 키 설정."""
        provider = GeminiOCRProvider(api_key="my-api-key")

        assert provider.api_key == "my-api-key"

    def test_init_uses_env_api_key(self, monkeypatch):
        """환경변수에서 API 키 로드."""
        monkeypatch.setenv("GOOGLE_API_KEY", "env-api-key")

        provider = GeminiOCRProvider()

        assert provider.api_key == "env-api-key"

    def test_client_lazy_init(self, provider):
        """클라이언트는 lazy init."""
        assert provider._client is None


# =============================================================================
# Exception Mapping 테스트
# =============================================================================


class TestExceptionMapping:
    """예외 매핑 테스트."""

    def test_fallback_errors_defined(self):
        """FALLBACK_ERRORS 정의 확인."""
        # google.api_core 설치 시에만 tuple이 아닌 경우
        # 미설치 시 빈 tuple
        assert isinstance(FALLBACK_ERRORS, tuple)

    def test_reject_immediately_defined(self):
        """REJECT_IMMEDIATELY 정의 확인."""
        assert isinstance(REJECT_IMMEDIATELY, tuple)

    @pytest.mark.skipif(not FALLBACK_ERRORS, reason="google-api-core not installed")
    def test_fallback_errors_include_correct_exceptions(self):
        """FALLBACK_ERRORS에 올바른 예외 포함."""
        from google.api_core.exceptions import (
            NotFound,
            ResourceExhausted,
            ServiceUnavailable,
        )

        assert NotFound in FALLBACK_ERRORS
        assert ServiceUnavailable in FALLBACK_ERRORS
        assert ResourceExhausted in FALLBACK_ERRORS

    @pytest.mark.skipif(not REJECT_IMMEDIATELY, reason="google-api-core not installed")
    def test_reject_immediately_include_correct_exceptions(self):
        """REJECT_IMMEDIATELY에 올바른 예외 포함."""
        from google.api_core.exceptions import (
            InvalidArgument,
            PermissionDenied,
            Unauthenticated,
        )

        assert InvalidArgument in REJECT_IMMEDIATELY
        assert PermissionDenied in REJECT_IMMEDIATELY
        assert Unauthenticated in REJECT_IMMEDIATELY


# =============================================================================
# MIME Type 정규화 테스트
# =============================================================================


class TestNormalizeMimeType:
    """MIME 타입 정규화 테스트."""

    def test_extension_to_mime(self, provider):
        """확장자 → MIME 타입."""
        assert provider._normalize_mime_type(".jpg") == "image/jpeg"
        assert provider._normalize_mime_type(".jpeg") == "image/jpeg"
        assert provider._normalize_mime_type(".png") == "image/png"
        assert provider._normalize_mime_type(".pdf") == "application/pdf"

    def test_extension_without_dot(self, provider):
        """점 없는 확장자."""
        assert provider._normalize_mime_type("jpg") == "image/jpeg"
        assert provider._normalize_mime_type("png") == "image/png"
        assert provider._normalize_mime_type("pdf") == "application/pdf"

    def test_already_mime_type(self, provider):
        """이미 MIME 타입인 경우."""
        assert provider._normalize_mime_type("image/jpeg") == "image/jpeg"
        assert provider._normalize_mime_type("application/pdf") == "application/pdf"

    def test_unknown_extension(self, provider):
        """알 수 없는 확장자."""
        assert provider._normalize_mime_type(".xyz") == "application/octet-stream"

    def test_case_insensitive(self, provider):
        """대소문자 구분 없음."""
        assert provider._normalize_mime_type(".JPG") == "image/jpeg"
        assert provider._normalize_mime_type("PNG") == "image/png"


# =============================================================================
# Confidence 추정 테스트
# =============================================================================


class TestEstimateConfidence:
    """신뢰도 추정 테스트."""

    def test_empty_text_zero_confidence(self, provider):
        """빈 텍스트 → 0.0."""
        assert provider._estimate_confidence("") == 0.0
        assert provider._estimate_confidence("   ") == 0.0

    def test_short_text_low_confidence(self, provider):
        """짧은 텍스트 → 낮은 신뢰도."""
        assert provider._estimate_confidence("Hi") == 0.3

    def test_normal_text_high_confidence(self, provider):
        """일반 텍스트 → 높은 신뢰도."""
        text = "작업번호: WO-001, 라인: L1, 결과: PASS"
        assert provider._estimate_confidence(text) == 0.9

    def test_weird_chars_lower_confidence(self, provider):
        """깨진 문자 → 낮은 신뢰도."""
        # 대체 문자가 많으면 낮은 신뢰도
        text = "정상 텍스트" + "�" * 10
        confidence = provider._estimate_confidence(text)
        assert confidence < 0.9


# =============================================================================
# extract_text 테스트 (Mock)
# =============================================================================


class TestExtractText:
    """extract_text 메서드 테스트."""

    @pytest.mark.asyncio
    async def test_successful_extraction(self, provider):
        """성공적인 추출."""
        mock_response = MagicMock()
        mock_response.text = "WO-001\nLine: L1\nResult: PASS"

        mock_model = MagicMock()
        mock_model.generate_content.return_value = mock_response

        mock_genai = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model

        provider._client = mock_genai

        result = await provider.extract_text(b"image bytes", "image/jpeg")

        assert result.success is True
        assert "WO-001" in result.text
        assert result.model_requested == "gemini-3-pro"
        assert result.model_used == "gemini-3-pro"
        assert result.fallback_triggered is False

    @pytest.mark.asyncio
    @pytest.mark.skipif(not FALLBACK_ERRORS, reason="google-api-core not installed")
    async def test_fallback_on_service_unavailable(self, provider):
        """ServiceUnavailable → fallback 시도."""
        from google.api_core.exceptions import ServiceUnavailable

        mock_response = MagicMock()
        mock_response.text = "Fallback result"

        mock_model = MagicMock()
        # 첫 번째 호출: 예외, 두 번째 호출: 성공
        mock_model.generate_content.side_effect = [
            ServiceUnavailable("Service unavailable"),
            mock_response,
        ]

        mock_genai = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model

        provider._client = mock_genai

        result = await provider.extract_text(b"image bytes", "image/jpeg")

        assert result.success is True
        assert result.model_requested == "gemini-3-pro"
        assert result.model_used == "gemini-2.5-flash"
        assert result.fallback_triggered is True

    @pytest.mark.asyncio
    @pytest.mark.skipif(not FALLBACK_ERRORS, reason="google-api-core not installed")
    async def test_fallback_on_resource_exhausted(self, provider):
        """ResourceExhausted (쿼터/레이트리밋) → fallback 시도."""
        from google.api_core.exceptions import ResourceExhausted

        mock_response = MagicMock()
        mock_response.text = "Fallback result"

        mock_model = MagicMock()
        mock_model.generate_content.side_effect = [
            ResourceExhausted("Quota exceeded"),
            mock_response,
        ]

        mock_genai = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model

        provider._client = mock_genai

        result = await provider.extract_text(b"image bytes", "image/jpeg")

        assert result.fallback_triggered is True
        assert result.model_used == "gemini-2.5-flash"

    @pytest.mark.asyncio
    @pytest.mark.skipif(not REJECT_IMMEDIATELY, reason="google-api-core not installed")
    async def test_reject_on_invalid_argument(self, provider):
        """InvalidArgument → 즉시 reject (fallback 안 함)."""
        from google.api_core.exceptions import InvalidArgument

        mock_model = MagicMock()
        mock_model.generate_content.side_effect = InvalidArgument("Invalid input")

        mock_genai = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model

        provider._client = mock_genai

        with pytest.raises(OCRError) as exc_info:
            await provider.extract_text(b"image bytes", "image/jpeg")

        assert exc_info.value.code == "AUTH_OR_INPUT_ERROR"

    @pytest.mark.asyncio
    @pytest.mark.skipif(not REJECT_IMMEDIATELY, reason="google-api-core not installed")
    async def test_reject_on_permission_denied(self, provider):
        """PermissionDenied → 즉시 reject."""
        from google.api_core.exceptions import PermissionDenied

        mock_model = MagicMock()
        mock_model.generate_content.side_effect = PermissionDenied("Access denied")

        mock_genai = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model

        provider._client = mock_genai

        with pytest.raises(OCRError) as exc_info:
            await provider.extract_text(b"image bytes", "image/jpeg")

        assert exc_info.value.code == "AUTH_OR_INPUT_ERROR"

    @pytest.mark.asyncio
    @pytest.mark.skipif(not FALLBACK_ERRORS, reason="google-api-core not installed")
    async def test_no_fallback_configured_raises_error(self, provider_no_fallback):
        """Fallback 없을 때 1차 실패 → 에러."""
        from google.api_core.exceptions import ServiceUnavailable

        mock_model = MagicMock()
        mock_model.generate_content.side_effect = ServiceUnavailable("Down")

        mock_genai = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model

        provider_no_fallback._client = mock_genai

        with pytest.raises(OCRError) as exc_info:
            await provider_no_fallback.extract_text(b"image bytes", "image/jpeg")

        assert exc_info.value.code == "NO_FALLBACK"

    @pytest.mark.asyncio
    @pytest.mark.skipif(not FALLBACK_ERRORS, reason="google-api-core not installed")
    async def test_both_primary_and_fallback_fail(self, provider):
        """1차 + Fallback 모두 실패."""
        from google.api_core.exceptions import ServiceUnavailable

        mock_model = MagicMock()
        mock_model.generate_content.side_effect = ServiceUnavailable("Down")

        mock_genai = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model

        provider._client = mock_genai

        with pytest.raises(OCRError) as exc_info:
            await provider.extract_text(b"image bytes", "image/jpeg")

        assert exc_info.value.code == "FALLBACK_FAILED"

    @pytest.mark.asyncio
    async def test_generic_exception_raises_ocr_error(self, provider):
        """일반 예외 → OCR_FAILED."""
        mock_model = MagicMock()
        mock_model.generate_content.side_effect = RuntimeError("Unknown error")

        mock_genai = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model

        provider._client = mock_genai

        with pytest.raises(OCRError) as exc_info:
            await provider.extract_text(b"image bytes", "image/jpeg")

        assert exc_info.value.code == "OCR_FAILED"


# =============================================================================
# Client 초기화 테스트
# =============================================================================


class TestGetClient:
    """_get_client 메서드 테스트."""

    def test_raises_error_if_not_installed(self, provider):
        """google-generativeai 미설치 시 에러."""
        with patch.dict("sys.modules", {"google.generativeai": None}):
            with patch("builtins.__import__", side_effect=ImportError):
                with pytest.raises(OCRError) as exc_info:
                    provider._get_client()

                assert exc_info.value.code == "GEMINI_NOT_INSTALLED"
