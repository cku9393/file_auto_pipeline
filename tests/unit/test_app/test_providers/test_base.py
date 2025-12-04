"""
test_base.py - Provider 기본 클래스 테스트

ADR-0003 검증:
- OCRResult: model_requested + model_used 필수
- ExtractionResult: model_requested + model_used 필수
- fallback_triggered 추적
"""

import pytest

from src.app.providers.base import (
    OCRResult,
    ExtractionResult,
    ProviderError,
    OCRError,
    ExtractionError,
    LLMProvider,
    OCRProvider,
)


# =============================================================================
# OCRResult 테스트
# =============================================================================

class TestOCRResult:
    """OCRResult 데이터클래스 테스트."""

    def test_basic_creation(self):
        """기본 생성."""
        result = OCRResult(
            success=True,
            text="Hello World",
            confidence=0.95,
        )

        assert result.success is True
        assert result.text == "Hello World"
        assert result.confidence == 0.95

    def test_model_tracking_fields(self):
        """ADR-0003: model_requested + model_used 필수."""
        result = OCRResult(
            success=True,
            text="Extracted text",
            model_requested="gemini-3-pro",
            model_used="gemini-2.5-flash",
            fallback_triggered=True,
        )

        assert result.model_requested == "gemini-3-pro"
        assert result.model_used == "gemini-2.5-flash"
        assert result.fallback_triggered is True

    def test_fallback_not_triggered_by_default(self):
        """fallback_triggered 기본값 False."""
        result = OCRResult(success=True)

        assert result.fallback_triggered is False

    def test_error_fields(self):
        """에러 정보."""
        result = OCRResult(
            success=False,
            error_message="API call failed",
            error_code="QUOTA_EXCEEDED",
        )

        assert result.success is False
        assert result.error_message == "API call failed"
        assert result.error_code == "QUOTA_EXCEEDED"

    def test_to_dict(self):
        """dict 변환."""
        result = OCRResult(
            success=True,
            text="Test",
            confidence=0.8,
            model_requested="model-a",
            model_used="model-b",
            fallback_triggered=True,
            processed_at="2024-01-15T10:00:00Z",
        )

        d = result.to_dict()

        assert d["success"] is True
        assert d["text"] == "Test"
        assert d["confidence"] == 0.8
        assert d["model_requested"] == "model-a"
        assert d["model_used"] == "model-b"
        assert d["fallback_triggered"] is True
        assert d["processed_at"] == "2024-01-15T10:00:00Z"

    def test_to_dict_includes_all_keys(self):
        """to_dict()에 모든 키 포함."""
        result = OCRResult(success=True)
        d = result.to_dict()

        expected_keys = {
            "success", "text", "confidence",
            "model_requested", "model_used", "fallback_triggered",
            "processed_at", "error_message", "error_code",
        }
        assert set(d.keys()) == expected_keys


# =============================================================================
# ExtractionResult 테스트
# =============================================================================

class TestExtractionResult:
    """ExtractionResult 데이터클래스 테스트."""

    def test_basic_creation(self):
        """기본 생성."""
        result = ExtractionResult(
            success=True,
            fields={"wo_no": "WO-001", "line": "L1"},
        )

        assert result.success is True
        assert result.fields == {"wo_no": "WO-001", "line": "L1"}

    def test_model_tracking_fields(self):
        """ADR-0003: model_requested + model_used 필수."""
        result = ExtractionResult(
            success=True,
            fields={"wo_no": "WO-001"},
            model_requested="claude-opus-4-5-20251101",
            model_used="claude-opus-4-5-20251101",
        )

        assert result.model_requested == "claude-opus-4-5-20251101"
        assert result.model_used == "claude-opus-4-5-20251101"

    def test_measurements(self):
        """측정 데이터."""
        result = ExtractionResult(
            success=True,
            measurements=[
                {"item": "길이", "spec": "10±0.1", "measured": "10.05", "result": "PASS"},
                {"item": "폭", "spec": "5±0.1", "measured": "5.02", "result": "PASS"},
            ],
        )

        assert len(result.measurements) == 2
        assert result.measurements[0]["item"] == "길이"

    def test_missing_fields_list(self):
        """누락 필드 목록."""
        result = ExtractionResult(
            success=True,
            fields={"wo_no": "WO-001"},
            missing_fields=["line", "part_no"],
        )

        assert result.missing_fields == ["line", "part_no"]

    def test_warnings_list(self):
        """경고 목록."""
        result = ExtractionResult(
            success=True,
            warnings=["LOT 번호가 불명확함", "검사자 필드 누락"],
        )

        assert len(result.warnings) == 2

    def test_suggested_template_id(self):
        """템플릿 ID 제안."""
        result = ExtractionResult(
            success=True,
            suggested_template_id="customer_a_inspection",
        )

        assert result.suggested_template_id == "customer_a_inspection"

    def test_default_values(self):
        """기본값."""
        result = ExtractionResult()

        assert result.success is True
        assert result.fields == {}
        assert result.measurements == []
        assert result.missing_fields == []
        assert result.warnings == []
        assert result.confidence is None
        assert result.model_requested is None
        assert result.model_used is None

    def test_to_dict(self):
        """dict 변환."""
        result = ExtractionResult(
            success=True,
            fields={"wo_no": "WO-001"},
            measurements=[{"item": "길이", "measured": "10"}],
            missing_fields=["line"],
            warnings=["Warning 1"],
            confidence=0.95,
            suggested_template_id="test_template",
            model_requested="model-a",
            model_used="model-a",
            extracted_at="2024-01-15T10:00:00Z",
        )

        d = result.to_dict()

        assert d["success"] is True
        assert d["fields"] == {"wo_no": "WO-001"}
        assert d["measurements"] == [{"item": "길이", "measured": "10"}]
        assert d["missing_fields"] == ["line"]
        assert d["warnings"] == ["Warning 1"]
        assert d["confidence"] == 0.95
        assert d["suggested_template_id"] == "test_template"
        assert d["model_requested"] == "model-a"
        assert d["model_used"] == "model-a"
        assert d["extracted_at"] == "2024-01-15T10:00:00Z"

    def test_to_dict_includes_all_keys(self):
        """to_dict()에 모든 키 포함."""
        result = ExtractionResult()
        d = result.to_dict()

        expected_keys = {
            "success", "fields", "measurements", "missing_fields",
            "warnings", "confidence", "suggested_template_id",
            "model_requested", "model_used", "extracted_at", "error_message",
        }
        assert set(d.keys()) == expected_keys


# =============================================================================
# Provider Error 테스트
# =============================================================================

class TestProviderErrors:
    """Provider 에러 클래스 테스트."""

    def test_provider_error_basic(self):
        """ProviderError 기본."""
        error = ProviderError("TEST_ERROR", "Test message")

        assert error.code == "TEST_ERROR"
        assert error.message == "Test message"
        assert str(error) == "[TEST_ERROR] Test message"

    def test_provider_error_with_context(self):
        """ProviderError 컨텍스트."""
        error = ProviderError(
            "TEST_ERROR",
            "Test message",
            model="gemini-3-pro",
            file_size=1024,
        )

        assert error.context["model"] == "gemini-3-pro"
        assert error.context["file_size"] == 1024

    def test_ocr_error_is_provider_error(self):
        """OCRError는 ProviderError 상속."""
        error = OCRError("OCR_FAILED", "OCR failed")

        assert isinstance(error, ProviderError)
        assert isinstance(error, Exception)

    def test_extraction_error_is_provider_error(self):
        """ExtractionError는 ProviderError 상속."""
        error = ExtractionError("EXTRACTION_FAILED", "Extraction failed")

        assert isinstance(error, ProviderError)
        assert isinstance(error, Exception)


# =============================================================================
# Abstract Provider 테스트
# =============================================================================

class TestAbstractProviders:
    """Abstract Provider 인터페이스 테스트."""

    def test_llm_provider_is_abstract(self):
        """LLMProvider는 추상 클래스."""
        with pytest.raises(TypeError):
            LLMProvider()  # type: ignore

    def test_ocr_provider_is_abstract(self):
        """OCRProvider는 추상 클래스."""
        with pytest.raises(TypeError):
            OCRProvider()  # type: ignore

    def test_llm_provider_has_extract_fields(self):
        """LLMProvider는 extract_fields 메서드 필요."""
        assert hasattr(LLMProvider, "extract_fields")

    def test_llm_provider_has_complete(self):
        """LLMProvider는 complete 메서드 필요."""
        assert hasattr(LLMProvider, "complete")

    def test_ocr_provider_has_extract_text(self):
        """OCRProvider는 extract_text 메서드 필요."""
        assert hasattr(OCRProvider, "extract_text")
