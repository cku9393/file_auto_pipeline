"""
Validation Service: definition.yaml 기반 검증 + override 처리.

ADR-0003:
- LLM은 구조화 제안만, 최종 판정은 여기서
- override 로그 스키마 준수 (필수 키 체크)

Override 품질 검증:
- reason_code: OverrideReasonCode enum 값만 허용
- reason_detail: 최소 10자, 금지 토큰 거절
- 레거시 문자열 파싱 지원 ("CODE: detail" 또는 "CODE|detail")
"""

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

from src.domain.errors import ErrorCodes, PolicyRejectError
from src.domain.schemas import OverrideLog, OverrideReasonCode

# =============================================================================
# Override Reason 검증 상수
# =============================================================================

# 금지 토큰 (대소문자/공백 변형 무시)
FORBIDDEN_TOKENS = frozenset([
    "ok", "okay", "n/a", "na", "none", "-", "skip", "pass", "test",
    ".", "..", "...", "x", "xx", "xxx", "ㅇ", "ㅇㅇ", "ㅇㅇㅇ",
])

# 최소 상세 사유 길이
MIN_REASON_DETAIL_LENGTH = 10


# =============================================================================
# Override Reason 파싱 결과
# =============================================================================

@dataclass
class ParsedOverrideReason:
    """파싱된 override 사유."""
    code: OverrideReasonCode
    detail: str
    raw: str  # 원본 입력


@dataclass
class OverrideReasonError:
    """Override 사유 검증 실패 정보."""
    field: str
    error_type: str  # "forbidden_token", "min_length", "invalid_code"
    message: str
    raw_value: Any


# =============================================================================
# Override Reason 검증 함수
# =============================================================================

def parse_override_reason(raw: Any) -> ParsedOverrideReason:
    """
    Override 사유 파싱.

    지원 형식:
    1. 신규 구조: {"code": "MISSING_PHOTO", "detail": "현장 촬영 누락으로 대체 자료 사용"}
    2. 레거시 문자열:
       - "MISSING_PHOTO: 현장 촬영 누락으로 대체 자료 사용"
       - "MISSING_PHOTO|현장 촬영 누락으로 대체 자료 사용"
       - "현장 사정으로 값 누락" → code=OTHER, detail=원문

    Args:
        raw: 원본 입력 (dict 또는 str)

    Returns:
        ParsedOverrideReason
    """
    raw_str = str(raw) if not isinstance(raw, dict) else ""

    # 1. 신규 구조 (dict)
    if isinstance(raw, dict):
        code_str = str(raw.get("code", "OTHER")).upper()
        detail = str(raw.get("detail", "")).strip()

        try:
            code = OverrideReasonCode(code_str)
        except ValueError:
            code = OverrideReasonCode.OTHER

        return ParsedOverrideReason(code=code, detail=detail, raw=str(raw))

    # 2. 레거시 문자열 파싱
    raw_str = str(raw).strip()

    # "CODE: detail" 또는 "CODE|detail" 형식 파싱
    # 패턴: 대문자+언더스코어로 시작하고 : 또는 | 로 구분
    pattern = r"^([A-Z][A-Z0-9_]*)\s*[:|]\s*(.+)$"
    match = re.match(pattern, raw_str)

    if match:
        code_str = match.group(1)
        detail = match.group(2).strip()

        try:
            code = OverrideReasonCode(code_str)
        except ValueError:
            # 유효하지 않은 코드면 OTHER로 처리, 전체를 detail로
            code = OverrideReasonCode.OTHER
            detail = raw_str
    else:
        # prefix 없음 → code=OTHER, detail=원문
        code = OverrideReasonCode.OTHER
        detail = raw_str

    return ParsedOverrideReason(code=code, detail=detail, raw=raw_str)


def is_forbidden_reason(detail: str) -> tuple[bool, str | None]:
    """
    금지 토큰 검사.

    Args:
        detail: 상세 사유

    Returns:
        (금지 여부, 발견된 토큰 또는 None)
    """
    # 정규화: 소문자, 공백 제거
    normalized = detail.lower().strip()
    normalized_no_space = re.sub(r"\s+", "", normalized)

    # 정확히 일치하는 경우만 금지
    if normalized in FORBIDDEN_TOKENS or normalized_no_space in FORBIDDEN_TOKENS:
        return True, normalized

    return False, None


def validate_override_reason(
    field_name: str,
    raw: Any,
    require_reason: bool = True,
) -> tuple[ParsedOverrideReason | None, OverrideReasonError | None]:
    """
    Override 사유 검증.

    검증 규칙:
    1. 금지 토큰 거절
    2. 최소 길이 검증 (10자)
    3. 코드 유효성 검증

    Args:
        field_name: 필드명
        raw: 원본 입력
        require_reason: 사유 필수 여부

    Returns:
        (ParsedOverrideReason, None) 성공 시
        (None, OverrideReasonError) 실패 시
    """
    # 빈 값 체크
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        if require_reason:
            return None, OverrideReasonError(
                field=field_name,
                error_type="empty_reason",
                message="Override 사유가 비어 있습니다",
                raw_value=raw,
            )
        return None, None

    # 파싱
    parsed = parse_override_reason(raw)

    # 1. 금지 토큰 검사
    is_forbidden, token = is_forbidden_reason(parsed.detail)
    if is_forbidden:
        return None, OverrideReasonError(
            field=field_name,
            error_type="forbidden_token",
            message=f"금지 토큰 포함: '{token}'",
            raw_value=raw,
        )

    # 2. 최소 길이 검사
    if len(parsed.detail) < MIN_REASON_DETAIL_LENGTH:
        return None, OverrideReasonError(
            field=field_name,
            error_type="min_length",
            message=f"최소 길이 미달: {len(parsed.detail)}자 (최소 {MIN_REASON_DETAIL_LENGTH}자)",
            raw_value=raw,
        )

    return parsed, None

# =============================================================================
# Validation Result
# =============================================================================

@dataclass
class ValidationResult:
    """검증 결과."""
    valid: bool
    fields: dict[str, Any] = field(default_factory=dict)
    measurements: list[dict[str, Any]] = field(default_factory=list)

    # 문제 목록
    missing_required: list[str] = field(default_factory=list)
    invalid_values: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    # Override 필요 목록
    overridable: list[str] = field(default_factory=list)

    # 적용된 Override
    applied_overrides: list[OverrideLog] = field(default_factory=list)

    # Override 검증 실패 (error_context용)
    invalid_override_fields: list[str] = field(default_factory=list)
    invalid_override_reasons: dict[str, str] = field(default_factory=dict)


# =============================================================================
# Validation Service
# =============================================================================

class ValidationService:
    """
    검증 서비스.

    definition.yaml 기반으로 필드/사진 검증.
    """

    def __init__(self, definition_path: Path):
        """
        Args:
            definition_path: definition.yaml 경로
        """
        self.definition_path = definition_path
        self._definition: dict | None = None

    @property
    def definition(self) -> dict:
        """definition.yaml 로드 (lazy)."""
        if self._definition is None:
            with open(self.definition_path, encoding="utf-8") as f:
                self._definition = yaml.safe_load(f)
        return self._definition

    def validate(
        self,
        fields: dict[str, Any],
        measurements: list[dict[str, Any]] | None = None,
        overrides: dict[str, str] | None = None,
        user: str = "system",
    ) -> ValidationResult:
        """
        필드 검증.

        Args:
            fields: 추출된 필드
            measurements: 측정 데이터
            overrides: {field_name: reason} override 사유
            user: 사용자 ID

        Returns:
            ValidationResult
        """
        result = ValidationResult(valid=True)
        result.fields = dict(fields)
        result.measurements = list(measurements or [])

        overrides = overrides or {}
        field_defs = self.definition.get("fields", {})

        # 필드별 검증
        for field_name, field_config in field_defs.items():
            value = fields.get(field_name)
            importance = field_config.get("importance", "reference")
            override_allowed = field_config.get("override_allowed", True)
            requires_reason = field_config.get("override_requires_reason", True)

            # 값 정규화
            if value is not None:
                field_type = field_config.get("type", "token")
                try:
                    result.fields[field_name] = self._normalize_value(value, field_type)
                except ValueError as e:
                    result.invalid_values.append({
                        "field": field_name,
                        "value": value,
                        "error": str(e),
                    })
                    result.valid = False
                    continue

            # 누락 체크
            if value is None or value == "":
                if importance == "critical":
                    # Override 가능?
                    if override_allowed and field_name in overrides:
                        raw_reason = overrides[field_name]

                        # Override 사유 품질 검증
                        parsed, error = validate_override_reason(
                            field_name, raw_reason, require_reason=requires_reason
                        )

                        if error:
                            # 검증 실패 → 거절
                            result.invalid_override_fields.append(field_name)
                            result.invalid_override_reasons[field_name] = error.message
                            result.valid = False
                        elif parsed:
                            # 검증 통과 → override 적용
                            result.applied_overrides.append(
                                self._create_override_log(
                                    field_name, "field", parsed, user
                                )
                            )
                        elif not requires_reason:
                            # 사유 불필요 케이스 (현재 코드에서는 드뭄)
                            result.applied_overrides.append(
                                self._create_override_log(
                                    field_name, "field", None, user
                                )
                            )
                    elif override_allowed:
                        result.overridable.append(field_name)
                        result.valid = False
                    else:
                        result.missing_required.append(field_name)
                        result.valid = False
                else:
                    # reference 필드는 null 허용 (경고만)
                    result.warnings.append(f"Optional field '{field_name}' is missing")

        # result 필드 정규화
        if "result" in result.fields:
            result.fields["result"] = self._normalize_result(result.fields["result"])

        # 측정 데이터 검증
        if result.measurements:
            self._validate_measurements(result)

        return result

    def _normalize_value(self, value: Any, field_type: str) -> Any:
        """
        값 정규화.

        AGENTS.md 규칙:
        - token: strip + 연속 공백 → 단일 공백
        - free_text: strip만
        - number: Decimal 변환
        """
        if value is None:
            return None

        value_str = str(value)

        if field_type == "token":
            # strip + 연속 공백 정리
            import re
            normalized = value_str.strip()
            normalized = re.sub(r"\s+", " ", normalized)
            return normalized

        elif field_type == "free_text":
            # strip만
            return value_str.strip()

        elif field_type == "number":
            # Decimal 변환
            try:
                decimal_value = Decimal(value_str).normalize()

                # NaN/Inf 체크
                if decimal_value.is_nan() or decimal_value.is_infinite():
                    raise ValueError(f"NaN/Inf not allowed: {value}")

                return decimal_value

            except InvalidOperation as e:
                raise ValueError(f"Invalid number: {value}") from e

        return value_str

    def _normalize_result(self, value: str) -> str:
        """
        result 필드 정규화.

        definition.yaml의 result_pass_aliases, result_fail_aliases 기반.
        """
        validation = self.definition.get("validation", {})
        pass_aliases = validation.get("result_pass_aliases", ["PASS", "OK", "합격", "O"])
        fail_aliases = validation.get("result_fail_aliases", ["FAIL", "NG", "불합격", "X"])

        value_upper = str(value).strip().upper()

        if value_upper in [a.upper() for a in pass_aliases]:
            return "PASS"
        elif value_upper in [a.upper() for a in fail_aliases]:
            return "FAIL"
        else:
            raise PolicyRejectError(
                ErrorCodes.RESULT_INVALID_VALUE,
                value=value,
                valid_values=pass_aliases + fail_aliases,
            )

    def _validate_measurements(self, result: ValidationResult) -> None:
        """측정 데이터 검증."""
        meas_config = self.definition.get("measurement_table", {})
        reject_nan_inf = meas_config.get("validation", {}).get("reject_nan_inf", True)

        for i, row in enumerate(result.measurements):
            measured = row.get("measured")

            if measured is None:
                continue

            # Decimal 변환
            try:
                decimal_value = Decimal(str(measured)).normalize()

                if reject_nan_inf and (decimal_value.is_nan() or decimal_value.is_infinite()):
                    result.invalid_values.append({
                        "field": f"measurements[{i}].measured",
                        "value": measured,
                        "error": "NaN/Inf not allowed",
                    })
                    result.valid = False
                else:
                    result.measurements[i]["measured"] = str(decimal_value)

            except InvalidOperation:
                result.invalid_values.append({
                    "field": f"measurements[{i}].measured",
                    "value": measured,
                    "error": "Invalid number",
                })
                result.valid = False

    def _create_override_log(
        self,
        field_or_slot: str,
        override_type: str,
        parsed_reason: ParsedOverrideReason | None,
        user: str,
    ) -> OverrideLog:
        """
        Override 로그 생성.

        Args:
            field_or_slot: 필드 또는 슬롯 이름
            override_type: "field" 또는 "photo"
            parsed_reason: 파싱된 override 사유 (None이면 사유 불필요 케이스)
            user: 사용자 ID

        Returns:
            OverrideLog
        """
        if parsed_reason:
            reason_code = parsed_reason.code.value
            reason_detail = parsed_reason.detail
            reason = f"{reason_code}: {reason_detail}"
        else:
            reason_code = OverrideReasonCode.OTHER.value
            reason_detail = "(사유 불필요)"
            reason = reason_detail

        return OverrideLog(
            code="OVERRIDE_APPLIED",
            timestamp=datetime.now(UTC).isoformat(),
            field_or_slot=field_or_slot,
            type=override_type,
            reason_code=reason_code,
            reason_detail=reason_detail,
            reason=reason,
            user=user,
        )

    def get_overridable_fields(self) -> list[str]:
        """override 가능한 필드 목록."""
        return [
            name
            for name, config in self.definition.get("fields", {}).items()
            if config.get("override_allowed", True)
        ]
