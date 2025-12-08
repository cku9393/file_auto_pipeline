"""
Error definitions for the pipeline.

AGENTS.md 규칙:
- 조용한 실패 금지 → PolicyRejectError로 명시적 실패
- NaN/Inf → 항상 reject
- critical 필드 누락 → reject
"""

from typing import Any


class PolicyRejectError(Exception):
    """
    파이프라인 정책 위반 시 발생하는 에러.

    즉시 중단이 필요한 경우에만 사용:
    - critical 필드 누락/파싱 실패
    - NaN/Inf 감지
    - required 사진 슬롯 누락
    - job.json mismatch
    - 락 timeout

    Usage:
        raise PolicyRejectError("PARSE_ERROR_CRITICAL", field="wo_no", cause=e)
    """

    def __init__(self, code: str, **context: Any) -> None:
        self.code = code
        self.context = context
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        ctx_str = ", ".join(f"{k}={v!r}" for k, v in self.context.items())
        return f"[{self.code}] {ctx_str}" if ctx_str else f"[{self.code}]"

    def to_dict(self) -> dict[str, Any]:
        """로그/JSON 직렬화용."""
        return {
            "code": self.code,
            **self.context,
        }


# =============================================================================
# Error Codes (spec.md / runbook.md 참조)
# =============================================================================

class ErrorCodes:
    """에러 코드 상수. 새 코드 추가 시 runbook.md에도 복구 방법 추가."""

    # === Ingest/Parse ===
    PARSE_ERROR_CRITICAL = "PARSE_ERROR_CRITICAL"
    PARSE_ERROR_REFERENCE = "PARSE_ERROR_REFERENCE"  # warning, not reject
    INVALID_DATA = "INVALID_DATA"  # NaN/Inf
    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"

    # === SSOT ===
    PACKET_JOB_MISMATCH = "PACKET_JOB_MISMATCH"
    JOB_JSON_LOCK_TIMEOUT = "JOB_JSON_LOCK_TIMEOUT"
    JOB_JSON_CORRUPT = "JOB_JSON_CORRUPT"

    # === Photos ===
    PHOTO_REQUIRED_MISSING = "PHOTO_REQUIRED_MISSING"
    PHOTO_DUPLICATE_AUTO_SELECTED = "PHOTO_DUPLICATE_AUTO_SELECTED"  # warning
    ARCHIVE_FAILED = "ARCHIVE_FAILED"

    # === Validation ===
    RESULT_INVALID_VALUE = "RESULT_INVALID_VALUE"
    OVERRIDE_NOT_ALLOWED = "OVERRIDE_NOT_ALLOWED"

    # === Override Reason 품질 검증 ===
    INVALID_OVERRIDE_REASON = "INVALID_OVERRIDE_REASON"  # 금지 토큰, 최소 길이 미달
    INVALID_OVERRIDE_CODE = "INVALID_OVERRIDE_CODE"      # 유효하지 않은 reason_code

    # === Render ===
    TEMPLATE_NOT_FOUND = "TEMPLATE_NOT_FOUND"
    RENDER_FAILED = "RENDER_FAILED"

    # === AI Parsing ===
    OCR_FAILED = "OCR_FAILED"
    EXTRACTION_FAILED = "EXTRACTION_FAILED"

    # === Intake ===
    INTAKE_SESSION_CORRUPT = "INTAKE_SESSION_CORRUPT"
    INTAKE_IMMUTABLE_VIOLATION = "INTAKE_IMMUTABLE_VIOLATION"
