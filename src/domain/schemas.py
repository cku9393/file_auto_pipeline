"""
Data schemas for the pipeline.

AGENTS.md 규칙:
- 필드명 통일: definition.yaml 키와 동일하게 사용
- Decimal 사용: 숫자 필드 float 금지
- NaN/Inf: 항상 reject
"""

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

# =============================================================================
# Core Schemas
# =============================================================================

@dataclass
class MeasurementRow:
    """측정 데이터 행."""
    item: str
    spec: str
    measured: Decimal  # float 금지, Decimal 사용
    unit: str | None = None
    result: str | None = None  # PASS/FAIL


@dataclass
class NormalizedPacket:
    """
    정규화된 패킷 데이터.

    필드명은 definition.yaml과 동일해야 함:
    - wo_no, line, part_no, lot, result (critical)
    - inspector, date, remark (reference)
    """
    # === Critical Fields (override_allowed=false) ===
    wo_no: str
    line: str
    part_no: str
    lot: str
    result: str  # PASS or FAIL (정규화됨)

    # === Reference Fields (override_allowed=true) ===
    inspector: str | None = None
    date: str | None = None
    remark: str | None = None

    # === Measurements ===
    measurements: list[MeasurementRow] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """JSON 직렬화용."""
        return {
            "wo_no": self.wo_no,
            "line": self.line,
            "part_no": self.part_no,
            "lot": self.lot,
            "result": self.result,
            "inspector": self.inspector,
            "date": self.date,
            "remark": self.remark,
            "measurements": [
                {
                    "item": m.item,
                    "spec": m.spec,
                    "measured": str(m.measured),  # Decimal → str
                    "unit": m.unit,
                    "result": m.result,
                }
                for m in self.measurements
            ],
        }


# =============================================================================
# Photo Schemas
# =============================================================================

@dataclass
class PhotoSlot:
    """사진 슬롯 정보."""
    key: str  # overview, label_serial, etc.
    basename: str  # 01_overview, 02_label_serial, etc.
    required: bool
    override_allowed: bool
    path: Path | None = None  # 매칭된 파일 경로


@dataclass
class MoveResult:
    """
    safe_move() 결과.

    AGENTS.md 규칙: 원인 보존, dst 충돌 해결, 원자성, fsync 경고
    """
    success: bool
    src: Path
    dst: Path | None = None
    operation: str | None = None  # copy, unlink_source
    errno_code: int | None = None
    error_message: str | None = None
    fsync_warning: bool = False


# =============================================================================
# Override/Logging Schemas
# =============================================================================

@dataclass
class OverrideLog:
    """
    Override 기록.

    override 로그 필수 키: field_or_slot, reason, user, timestamp
    """
    code: str  # OVERRIDE_APPLIED
    timestamp: str  # ISO 8601
    field_or_slot: str
    type: str  # field or photo
    reason: str
    user: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "timestamp": self.timestamp,
            "field_or_slot": self.field_or_slot,
            "type": self.type,
            "reason": self.reason,
            "user": self.user,
        }


@dataclass
class WarningLog:
    """
    경고 로그.

    경고 필수 컨텍스트: level, code, action_id, field_or_slot,
                       original_value, resolved_value, message
    """
    level: str = "warning"
    code: str = ""
    action_id: str = ""
    field_or_slot: str = ""
    original_value: str | None = None
    resolved_value: str | None = None
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "code": self.code,
            "action_id": self.action_id,
            "field_or_slot": self.field_or_slot,
            "original_value": self.original_value,
            "resolved_value": self.resolved_value,
            "message": self.message,
        }


@dataclass
class RunLog:
    """
    실행 로그.

    job/run 단위 실행 결과 및 메타데이터.
    """
    run_id: str
    job_id: str
    started_at: str  # ISO 8601
    finished_at: str | None = None
    result: str = "pending"  # pending, success, failed

    # Hashes
    packet_hash: str | None = None
    packet_full_hash: str | None = None

    # Events
    warnings: list[WarningLog] = field(default_factory=list)
    overrides: list[OverrideLog] = field(default_factory=list)

    # Error (if failed)
    error_code: str | None = None
    error_context: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "job_id": self.job_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "result": self.result,
            "packet_hash": self.packet_hash,
            "packet_full_hash": self.packet_full_hash,
            "warnings": [w.to_dict() for w in self.warnings],
            "overrides": [o.to_dict() for o in self.overrides],
            "error_code": self.error_code,
            "error_context": self.error_context,
        }


# =============================================================================
# Intake Session Schema (app/services/intake.py에서 사용)
# =============================================================================

@dataclass
class IntakeAttachment:
    """업로드된 파일 정보."""
    filename: str
    size: int
    path: str  # uploads/... 상대 경로


@dataclass
class IntakeMessage:
    """채팅 메시지."""
    role: str  # user, assistant
    content: str
    timestamp: str  # ISO 8601
    attachments: list[IntakeAttachment] = field(default_factory=list)


@dataclass
class OCRResult:
    """OCR 결과."""
    success: bool
    text: str | None = None
    confidence: float | None = None
    model_requested: str | None = None
    model_used: str | None = None
    fallback_triggered: bool = False
    processed_at: str | None = None
    error_message: str | None = None


@dataclass
class ExtractionResult:
    """LLM 추출 결과."""
    fields: dict[str, Any] = field(default_factory=dict)
    measurements: list[dict[str, Any]] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    confidence: float | None = None
    suggested_template_id: str | None = None
    model_requested: str | None = None
    model_used: str | None = None
    extracted_at: str | None = None


@dataclass
class UserCorrection:
    """사용자 수정 기록."""
    field: str
    original: Any | None
    corrected: Any
    corrected_at: str  # ISO 8601
    corrected_by: str = "user"


@dataclass
class IntakeSession:
    """
    Intake 세션 전체 (intake_session.json).

    불변성 규칙 (Append-Only):
    - messages 원문은 절대 수정 금지
    - 후처리 결과는 append 이벤트로만 추가
    - 원문 덮어쓰기 시도 시 에러 발생

    Note: ocr_results와 extraction_result는 providers.base의 타입도 허용합니다.
    (구조적으로 동일하지만 별도 모듈에 정의됨)
    """
    schema_version: str = "1.0"
    session_id: str = ""
    created_at: str = ""
    immutable: bool = True

    messages: list[IntakeMessage] = field(default_factory=list)
    ocr_results: dict[str, Any] = field(default_factory=dict)  # OCRResult or providers.base.OCRResult
    extraction_result: Any = None  # ExtractionResult or providers.base.ExtractionResult
    user_corrections: list[UserCorrection] = field(default_factory=list)
