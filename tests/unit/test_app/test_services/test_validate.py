"""
test_validate.py - Validation 서비스 테스트

ADR-0003:
- LLM은 구조화 제안만, 최종 판정은 여기서
- override 로그 스키마 준수 (필수 키 체크)
"""

from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from src.app.services.validate import ValidationResult, ValidationService
from src.domain.errors import ErrorCodes, PolicyRejectError

# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def definition_path(tmp_path: Path) -> Path:
    """테스트용 definition.yaml."""
    definition = {
        "definition_version": "1.0.0",
        "fields": {
            "wo_no": {
                "type": "token",
                "importance": "critical",
                "override_allowed": False,
            },
            "line": {
                "type": "token",
                "importance": "critical",
                "override_allowed": True,
                "override_requires_reason": True,
            },
            "part_no": {
                "type": "token",
                "importance": "critical",
                "override_allowed": True,
                "override_requires_reason": False,
            },
            "lot": {
                "type": "token",
                "importance": "critical",
            },
            "result": {
                "type": "token",
                "importance": "critical",
            },
            "inspector": {
                "type": "token",
                "importance": "reference",
            },
            "measurement_value": {
                "type": "number",
                "importance": "reference",
            },
            "remark": {
                "type": "free_text",
                "importance": "optional",
            },
        },
        "validation": {
            "result_pass_aliases": ["PASS", "OK", "합격", "O"],
            "result_fail_aliases": ["FAIL", "NG", "불합격", "X"],
        },
        "measurement_table": {
            "validation": {
                "reject_nan_inf": True,
            },
        },
    }

    path = tmp_path / "definition.yaml"
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(definition, f, allow_unicode=True)

    return path


@pytest.fixture
def validation_service(definition_path: Path) -> ValidationService:
    """ValidationService 인스턴스."""
    return ValidationService(definition_path)


@pytest.fixture
def complete_fields() -> dict:
    """완전한 필드 데이터."""
    return {
        "wo_no": "WO-001",
        "line": "L1",
        "part_no": "PART-A",
        "lot": "LOT-001",
        "result": "PASS",
        "inspector": "홍길동",
    }


# =============================================================================
# 초기화 테스트
# =============================================================================

class TestValidationServiceInit:
    """ValidationService 초기화 테스트."""

    def test_init(self, definition_path):
        """기본 초기화."""
        service = ValidationService(definition_path)

        assert service.definition_path == definition_path

    def test_definition_lazy_load(self, validation_service):
        """definition은 lazy load."""
        assert validation_service._definition is None
        _ = validation_service.definition
        assert validation_service._definition is not None


# =============================================================================
# 값 정규화 테스트
# =============================================================================

class TestNormalizeValue:
    """_normalize_value 테스트."""

    def test_token_strips_and_collapses_spaces(self, validation_service):
        """token: strip + 연속 공백 정리."""
        result = validation_service._normalize_value("  WO  001  ", "token")

        assert result == "WO 001"

    def test_free_text_strips_only(self, validation_service):
        """free_text: strip만."""
        result = validation_service._normalize_value("  Hello  World  ", "free_text")

        assert result == "Hello  World"

    def test_number_converts_to_decimal(self, validation_service):
        """number: Decimal 변환."""
        result = validation_service._normalize_value("123.456", "number")

        assert result == Decimal("123.456")
        assert isinstance(result, Decimal)

    def test_number_normalizes(self, validation_service):
        """number: 정규화."""
        result = validation_service._normalize_value("10.00", "number")

        assert result == Decimal("10")

    def test_number_rejects_nan(self, validation_service):
        """number: NaN 거부."""
        with pytest.raises(ValueError) as exc_info:
            validation_service._normalize_value("NaN", "number")

        assert "NaN" in str(exc_info.value) or "Invalid" in str(exc_info.value)

    def test_number_rejects_inf(self, validation_service):
        """number: Inf 거부."""
        with pytest.raises(ValueError) as exc_info:
            validation_service._normalize_value("Infinity", "number")

        assert "Inf" in str(exc_info.value) or "Invalid" in str(exc_info.value)

    def test_number_rejects_invalid(self, validation_service):
        """number: 잘못된 값 거부."""
        with pytest.raises(ValueError) as exc_info:
            validation_service._normalize_value("not a number", "number")

        assert "Invalid" in str(exc_info.value)

    def test_none_returns_none(self, validation_service):
        """None → None."""
        result = validation_service._normalize_value(None, "token")

        assert result is None


# =============================================================================
# result 정규화 테스트
# =============================================================================

class TestNormalizeResult:
    """_normalize_result 테스트."""

    def test_pass_aliases(self, validation_service):
        """PASS aliases 정규화."""
        assert validation_service._normalize_result("PASS") == "PASS"
        assert validation_service._normalize_result("pass") == "PASS"
        assert validation_service._normalize_result("OK") == "PASS"
        assert validation_service._normalize_result("합격") == "PASS"
        assert validation_service._normalize_result("O") == "PASS"

    def test_fail_aliases(self, validation_service):
        """FAIL aliases 정규화."""
        assert validation_service._normalize_result("FAIL") == "FAIL"
        assert validation_service._normalize_result("fail") == "FAIL"
        assert validation_service._normalize_result("NG") == "FAIL"
        assert validation_service._normalize_result("불합격") == "FAIL"
        assert validation_service._normalize_result("X") == "FAIL"

    def test_invalid_value_raises_error(self, validation_service):
        """유효하지 않은 값 → 에러."""
        with pytest.raises(PolicyRejectError) as exc_info:
            validation_service._normalize_result("MAYBE")

        assert exc_info.value.code == ErrorCodes.RESULT_INVALID_VALUE


# =============================================================================
# validate 테스트 - 기본
# =============================================================================

class TestValidateBasic:
    """validate 기본 테스트."""

    def test_valid_complete_fields(self, validation_service, complete_fields):
        """완전한 필드 → valid."""
        result = validation_service.validate(complete_fields)

        assert result.valid is True
        assert result.missing_required == []
        assert result.invalid_values == []

    def test_normalizes_token_fields(self, validation_service):
        """token 필드 정규화."""
        fields = {
            "wo_no": "  WO  001  ",
            "line": "L1",
            "part_no": "P1",
            "lot": "LOT1",
            "result": "PASS",
        }

        result = validation_service.validate(fields)

        assert result.fields["wo_no"] == "WO 001"

    def test_normalizes_result_field(self, validation_service, complete_fields):
        """result 필드 정규화."""
        complete_fields["result"] = "합격"

        result = validation_service.validate(complete_fields)

        assert result.fields["result"] == "PASS"


# =============================================================================
# validate 테스트 - 누락 필드
# =============================================================================

class TestValidateMissingFields:
    """누락 필드 검증 테스트."""

    def test_missing_critical_field(self, validation_service):
        """critical 필드 누락 → invalid."""
        fields = {
            "wo_no": "WO-001",
            # line 누락
            "part_no": "P1",
            "lot": "LOT1",
            "result": "PASS",
        }

        result = validation_service.validate(fields)

        assert result.valid is False
        assert "line" in result.missing_required or "line" in result.overridable

    def test_missing_reference_field_is_warning(self, validation_service, complete_fields):
        """reference 필드 누락 → 경고만."""
        del complete_fields["inspector"]

        result = validation_service.validate(complete_fields)

        assert result.valid is True
        assert any("inspector" in w for w in result.warnings)

    def test_empty_value_treated_as_missing(self, validation_service, complete_fields):
        """빈 값은 누락으로 처리."""
        complete_fields["line"] = ""

        result = validation_service.validate(complete_fields)

        assert result.valid is False


# =============================================================================
# validate 테스트 - Override
# =============================================================================

class TestValidateOverride:
    """Override 검증 테스트."""

    def test_override_not_allowed(self, validation_service):
        """override_allowed=False → 에러."""
        fields = {
            # wo_no 누락 (override_allowed=False)
            "line": "L1",
            "part_no": "P1",
            "lot": "LOT1",
            "result": "PASS",
        }

        result = validation_service.validate(
            fields,
            overrides={"wo_no": "고객 요청"},  # 시도해도 무시
        )

        assert result.valid is False
        assert "wo_no" in result.missing_required

    def test_override_allowed_with_reason(self, validation_service):
        """override_allowed=True + 충분한 사유 → 통과."""
        fields = {
            "wo_no": "WO-001",
            # line 누락
            "part_no": "P1",
            "lot": "LOT1",
            "result": "PASS",
        }

        result = validation_service.validate(
            fields,
            overrides={"line": "MISSING_PHOTO: 현장 사진에서 해당 정보 확인이 불가능합니다"},
            user="operator1",
        )

        assert result.valid is True
        assert len(result.applied_overrides) == 1
        assert result.applied_overrides[0].field_or_slot == "line"
        assert result.applied_overrides[0].reason_code == "MISSING_PHOTO"
        assert "현장 사진에서 해당 정보 확인이 불가능합니다" in result.applied_overrides[0].reason_detail

    def test_override_requires_reason(self, validation_service):
        """override_requires_reason=True + 빈 사유 → 실패 (invalid_override_fields에 추가)."""
        fields = {
            "wo_no": "WO-001",
            # line 누락 (requires_reason=True)
            "part_no": "P1",
            "lot": "LOT1",
            "result": "PASS",
        }

        result = validation_service.validate(
            fields,
            overrides={"line": ""},  # 빈 사유
        )

        assert result.valid is False
        assert "line" in result.invalid_override_fields
        assert "line" in result.invalid_override_reasons

    def test_override_without_reason_when_not_required(self, validation_service):
        """override_requires_reason=False → 사유 없어도 통과."""
        fields = {
            "wo_no": "WO-001",
            "line": "L1",
            # part_no 누락 (requires_reason=False)
            "lot": "LOT1",
            "result": "PASS",
        }

        result = validation_service.validate(
            fields,
            overrides={"part_no": ""},  # 빈 사유도 허용
        )

        assert result.valid is True

    def test_overridable_fields_tracked(self, validation_service):
        """override 가능한 누락 필드 추적."""
        fields = {
            "wo_no": "WO-001",
            # line 누락 (override 가능)
            "part_no": "P1",
            "lot": "LOT1",
            "result": "PASS",
        }

        result = validation_service.validate(fields)

        assert "line" in result.overridable


# =============================================================================
# Override 로그 스키마 테스트
# =============================================================================

class TestOverrideLogSchema:
    """Override 로그 스키마 테스트."""

    def test_override_log_has_required_keys(self, validation_service):
        """override 로그 필수 키 확인 (신규 스키마)."""
        fields = {
            "wo_no": "WO-001",
            "part_no": "P1",
            "lot": "LOT1",
            "result": "PASS",
        }

        result = validation_service.validate(
            fields,
            overrides={"line": "DATA_UNAVAILABLE: 고객이 해당 데이터를 제공하지 않았습니다"},
            user="operator1",
        )

        override = result.applied_overrides[0]

        # 필수 키 확인 (신규 스키마)
        assert hasattr(override, "code")
        assert hasattr(override, "timestamp")
        assert hasattr(override, "field_or_slot")
        assert hasattr(override, "type")
        assert hasattr(override, "reason_code")
        assert hasattr(override, "reason_detail")
        assert hasattr(override, "reason")  # 호환용
        assert hasattr(override, "user")

        # 값 확인
        assert override.code == "OVERRIDE_APPLIED"
        assert override.field_or_slot == "line"
        assert override.type == "field"
        assert override.reason_code == "DATA_UNAVAILABLE"
        assert override.reason_detail == "고객이 해당 데이터를 제공하지 않았습니다"
        assert override.reason == "DATA_UNAVAILABLE: 고객이 해당 데이터를 제공하지 않았습니다"
        assert override.user == "operator1"

    def test_override_log_has_timestamp(self, validation_service):
        """override 로그에 timestamp 포함."""
        fields = {
            "wo_no": "WO-001",
            "part_no": "P1",
            "lot": "LOT1",
            "result": "PASS",
        }

        result = validation_service.validate(
            fields,
            overrides={"line": "현장 장비 문제로 인해 해당 정보를 확인할 수 없었습니다"},
        )

        override = result.applied_overrides[0]

        assert override.timestamp is not None
        # ISO 8601 형식 확인
        assert "T" in override.timestamp


# =============================================================================
# 측정 데이터 검증 테스트
# =============================================================================

class TestValidateMeasurements:
    """측정 데이터 검증 테스트."""

    def test_valid_measurements(self, validation_service, complete_fields):
        """유효한 측정 데이터."""
        measurements = [
            {"item": "길이", "spec": "10±0.1", "measured": "10.05", "result": "PASS"},
            {"item": "폭", "spec": "5±0.1", "measured": "5.02", "result": "PASS"},
        ]

        result = validation_service.validate(complete_fields, measurements=measurements)

        assert result.valid is True
        assert result.measurements[0]["measured"] == "10.05"

    def test_rejects_nan_in_measurements(self, validation_service, complete_fields):
        """측정값 NaN 거부."""
        measurements = [
            {"item": "길이", "measured": "NaN"},
        ]

        result = validation_service.validate(complete_fields, measurements=measurements)

        assert result.valid is False
        assert any("NaN" in str(v) for v in result.invalid_values)

    def test_rejects_inf_in_measurements(self, validation_service, complete_fields):
        """측정값 Inf 거부."""
        measurements = [
            {"item": "길이", "measured": "Infinity"},
        ]

        result = validation_service.validate(complete_fields, measurements=measurements)

        assert result.valid is False

    def test_rejects_invalid_number_in_measurements(self, validation_service, complete_fields):
        """측정값 잘못된 숫자 거부."""
        measurements = [
            {"item": "길이", "measured": "not a number"},
        ]

        result = validation_service.validate(complete_fields, measurements=measurements)

        assert result.valid is False
        assert any("Invalid" in str(v.get("error", "")) for v in result.invalid_values)

    def test_handles_none_measurement(self, validation_service, complete_fields):
        """측정값 None 허용."""
        measurements = [
            {"item": "길이", "measured": None},
        ]

        result = validation_service.validate(complete_fields, measurements=measurements)

        assert result.valid is True


# =============================================================================
# get_overridable_fields 테스트
# =============================================================================

class TestGetOverridableFields:
    """get_overridable_fields 테스트."""

    def test_returns_overridable_fields(self, validation_service):
        """override 가능 필드 목록."""
        fields = validation_service.get_overridable_fields()

        assert "line" in fields
        assert "part_no" in fields
        assert "wo_no" not in fields  # override_allowed=False


# =============================================================================
# ValidationResult 테스트
# =============================================================================

class TestValidationResult:
    """ValidationResult 데이터클래스 테스트."""

    def test_default_values(self):
        """기본값."""
        result = ValidationResult(valid=True)

        assert result.valid is True
        assert result.fields == {}
        assert result.measurements == []
        assert result.missing_required == []
        assert result.invalid_values == []
        assert result.warnings == []
        assert result.overridable == []
        assert result.applied_overrides == []
        # 신규 필드
        assert result.invalid_override_fields == []
        assert result.invalid_override_reasons == {}


# =============================================================================
# Override Reason 품질 검증 테스트 (TC1-TC4)
# =============================================================================

class TestOverrideReasonQuality:
    """
    Override 사유 품질 검증 테스트.

    면책 버튼 방지를 위한 테스트:
    - TC1: 금지 토큰 거절
    - TC2: 최소 길이 거절
    - TC3: 정상 통과 (신규 구조)
    - TC4: 레거시 문자열 파싱
    """

    def test_override_rejects_forbidden_tokens(self, validation_service):
        """TC1: 금지 토큰 거절 - 'ok', 'N/A', '-' 등은 실패."""
        fields = {
            "wo_no": "WO-001",
            "part_no": "P1",
            "lot": "LOT1",
            "result": "PASS",
            # line 누락
        }

        # 각 금지 토큰 테스트
        forbidden_reasons = ["ok", "OK", "N/A", "n/a", "-", "pass", "skip", "none"]

        for reason in forbidden_reasons:
            result = validation_service.validate(
                fields,
                overrides={"line": reason},
            )

            assert result.valid is False, f"'{reason}'이 통과하면 안됨"
            assert "line" in result.invalid_override_fields, f"'{reason}' 거절 실패"
            assert "금지 토큰" in result.invalid_override_reasons.get("line", ""), (
                f"'{reason}' 에러 메시지 확인"
            )

    def test_override_rejects_short_reason(self, validation_service):
        """TC2: 최소 길이 거절 - 10자 미만은 실패."""
        fields = {
            "wo_no": "WO-001",
            "part_no": "P1",
            "lot": "LOT1",
            "result": "PASS",
        }

        # 10자 미만 사유
        short_reasons = ["짧은사유", "short", "abc", "12345678"]  # 각각 10자 미만

        for reason in short_reasons:
            result = validation_service.validate(
                fields,
                overrides={"line": reason},
            )

            assert result.valid is False, f"짧은 사유 '{reason}'가 통과하면 안됨"
            assert "line" in result.invalid_override_fields
            assert "최소 길이" in result.invalid_override_reasons.get("line", "")

    def test_override_accepts_valid_new_format(self, validation_service):
        """TC3: 정상 통과 (신규 dict 구조)."""
        fields = {
            "wo_no": "WO-001",
            "part_no": "P1",
            "lot": "LOT1",
            "result": "PASS",
        }

        # 신규 구조: {"code": ..., "detail": ...}
        override_reason = {
            "code": "DATA_UNAVAILABLE",
            "detail": "고객이 해당 데이터를 제공하지 않았음",
        }

        result = validation_service.validate(
            fields,
            overrides={"line": override_reason},
            user="operator1",
        )

        assert result.valid is True
        assert len(result.applied_overrides) == 1

        override = result.applied_overrides[0]
        assert override.reason_code == "DATA_UNAVAILABLE"
        assert override.reason_detail == "고객이 해당 데이터를 제공하지 않았음"
        assert override.reason == "DATA_UNAVAILABLE: 고객이 해당 데이터를 제공하지 않았음"

    def test_override_parses_legacy_format(self, validation_service):
        """TC4: 레거시 문자열 파싱."""
        fields = {
            "wo_no": "WO-001",
            "part_no": "P1",
            "lot": "LOT1",
            "result": "PASS",
        }

        # 케이스 1: "CODE: detail" 형식
        result1 = validation_service.validate(
            fields,
            overrides={"line": "MISSING_PHOTO: 현장 촬영 누락으로 대체 자료 사용"},
        )

        assert result1.valid is True
        override1 = result1.applied_overrides[0]
        assert override1.reason_code == "MISSING_PHOTO"
        assert override1.reason_detail == "현장 촬영 누락으로 대체 자료 사용"

        # 케이스 2: "CODE|detail" 형식
        result2 = validation_service.validate(
            fields,
            overrides={"line": "DEVICE_FAILURE|장비 고장으로 인해 측정값을 확인할 수 없습니다"},
        )

        assert result2.valid is True
        override2 = result2.applied_overrides[0]
        assert override2.reason_code == "DEVICE_FAILURE"
        assert override2.reason_detail == "장비 고장으로 인해 측정값을 확인할 수 없습니다"

        # 케이스 3: prefix 없음 → code=OTHER
        result3 = validation_service.validate(
            fields,
            overrides={"line": "현장 사정으로 인해 해당 값을 확인할 수 없었습니다"},
        )

        assert result3.valid is True
        override3 = result3.applied_overrides[0]
        assert override3.reason_code == "OTHER"
        assert override3.reason_detail == "현장 사정으로 인해 해당 값을 확인할 수 없었습니다"


class TestOverrideReasonParsing:
    """Override 사유 파싱 함수 단위 테스트."""

    def test_parse_dict_format(self):
        """dict 형식 파싱."""
        from src.app.services.validate import parse_override_reason
        from src.domain.schemas import OverrideReasonCode

        result = parse_override_reason({
            "code": "CUSTOMER_REQUEST",
            "detail": "고객 요청에 따른 필드 생략",
        })

        assert result.code == OverrideReasonCode.CUSTOMER_REQUEST
        assert result.detail == "고객 요청에 따른 필드 생략"

    def test_parse_colon_format(self):
        """콜론 구분 문자열 파싱."""
        from src.app.services.validate import parse_override_reason
        from src.domain.schemas import OverrideReasonCode

        result = parse_override_reason("OCR_UNREADABLE: OCR 인식 불가능한 이미지")

        assert result.code == OverrideReasonCode.OCR_UNREADABLE
        assert result.detail == "OCR 인식 불가능한 이미지"

    def test_parse_pipe_format(self):
        """파이프 구분 문자열 파싱."""
        from src.app.services.validate import parse_override_reason
        from src.domain.schemas import OverrideReasonCode

        result = parse_override_reason("FIELD_NOT_APPLICABLE|해당 제품에는 적용되지 않는 필드")

        assert result.code == OverrideReasonCode.FIELD_NOT_APPLICABLE
        assert result.detail == "해당 제품에는 적용되지 않는 필드"

    def test_parse_no_prefix_defaults_to_other(self):
        """prefix 없으면 OTHER로 기본값."""
        from src.app.services.validate import parse_override_reason
        from src.domain.schemas import OverrideReasonCode

        result = parse_override_reason("단순히 사유만 작성한 경우입니다")

        assert result.code == OverrideReasonCode.OTHER
        assert result.detail == "단순히 사유만 작성한 경우입니다"

    def test_parse_unknown_code_becomes_other(self):
        """알 수 없는 코드는 OTHER로 처리."""
        from src.app.services.validate import parse_override_reason
        from src.domain.schemas import OverrideReasonCode

        result = parse_override_reason("UNKNOWN_CODE: 알 수 없는 코드와 상세 사유")

        assert result.code == OverrideReasonCode.OTHER
        assert "UNKNOWN_CODE" in result.detail  # 전체가 detail로


class TestForbiddenTokenDetection:
    """금지 토큰 검출 테스트."""

    def test_detects_common_forbidden_tokens(self):
        """일반 금지 토큰 검출."""
        from src.app.services.validate import is_forbidden_reason

        forbidden = ["ok", "OK", "n/a", "N/A", "none", "-", "pass", "skip", "test"]

        for token in forbidden:
            is_bad, detected = is_forbidden_reason(token)
            assert is_bad is True, f"'{token}'이 금지 토큰으로 검출되어야 함"

    def test_allows_legitimate_reasons(self):
        """정상 사유는 허용."""
        from src.app.services.validate import is_forbidden_reason

        legitimate = [
            "고객 요청에 따라 해당 필드를 생략합니다",
            "현장 사진에서 확인이 불가능했습니다",
            "장비 고장으로 측정할 수 없었습니다",
            "OCR 인식이 실패하여 수동 입력",
        ]

        for reason in legitimate:
            is_bad, _ = is_forbidden_reason(reason)
            assert is_bad is False, f"정상 사유 '{reason}'가 금지 토큰으로 인식됨"
