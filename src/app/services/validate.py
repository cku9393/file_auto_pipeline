"""
Validation Service: definition.yaml 기반 검증 + override 처리.

ADR-0003:
- LLM은 구조화 제안만, 최종 판정은 여기서
- override 로그 스키마 준수 (필수 키 체크)
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

from src.domain.errors import ErrorCodes, PolicyRejectError
from src.domain.schemas import OverrideLog

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
                        reason = overrides[field_name]
                        if requires_reason and not reason:
                            result.missing_required.append(field_name)
                            result.valid = False
                        else:
                            result.applied_overrides.append(
                                self._create_override_log(
                                    field_name, "field", reason, user
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
        reason: str,
        user: str,
    ) -> OverrideLog:
        """Override 로그 생성."""
        return OverrideLog(
            code="OVERRIDE_APPLIED",
            timestamp=datetime.now(UTC).isoformat(),
            field_or_slot=field_or_slot,
            type=override_type,
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
