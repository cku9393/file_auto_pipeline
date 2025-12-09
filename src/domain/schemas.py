"""
Data schemas for the pipeline.

AGENTS.md 규칙:
- 필드명 통일: definition.yaml 키와 동일하게 사용
- Decimal 사용: 숫자 필드 float 금지
- NaN/Inf: 항상 reject
"""

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

# =============================================================================
# Override Reason Code (품질 검증용)
# =============================================================================

class OverrideReasonCode(str, Enum):
    """
    Override 사유 코드.

    override가 "면책 버튼"이 되는 것을 방지하기 위해
    구조화된 사유 코드를 강제합니다.
    """
    MISSING_PHOTO = "MISSING_PHOTO"           # 사진 누락
    DATA_UNAVAILABLE = "DATA_UNAVAILABLE"     # 데이터 미제공
    CUSTOMER_REQUEST = "CUSTOMER_REQUEST"     # 고객 요청
    DEVICE_FAILURE = "DEVICE_FAILURE"         # 장비 고장
    OCR_UNREADABLE = "OCR_UNREADABLE"         # OCR 인식 불가
    FIELD_NOT_APPLICABLE = "FIELD_NOT_APPLICABLE"  # 해당 필드 미적용
    OTHER = "OTHER"                           # 기타 (detail 필수)

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
    override_requires_reason: bool = True  # 사유 필수 여부
    path: Path | None = None  # 매칭된 파일 경로
    description: str = ""  # 슬롯 설명
    prefer_order: list[str] | None = None  # 파일명 내 우선순위 키워드
    # 슬롯 매칭 검증용 OCR 키워드 (label_serial 등 핵심 슬롯용)
    verify_keywords: list[str] | None = None


class SlotMatchConfidence(str, Enum):
    """
    슬롯 매칭 신뢰도.

    자동 매칭이 틀리면 조용히 잘못된 문서가 나오는 문제를 방지.
    """
    HIGH = "high"          # 정확한 basename 매칭 + (선택) OCR 키워드 확인됨
    MEDIUM = "medium"      # basename 매칭만 됨, 핵심 슬롯은 경고 권장
    LOW = "low"            # 부분 매칭, 사용자 확인 필요
    AMBIGUOUS = "ambiguous"  # 여러 슬롯에 매칭 가능, fail-fast 또는 사용자 확인


@dataclass
class SlotMatchResult:
    """
    슬롯 매칭 결과.

    자동 매칭 시 confidence와 함께 반환하여
    모호한 매칭을 감지하고 사용자 확인을 유도.
    """
    slot: PhotoSlot | None
    confidence: SlotMatchConfidence
    matched_by: str = ""  # "basename_exact", "basename_prefix", "key_prefix"
    warning: str | None = None  # 모호한 매칭 시 경고 메시지
    alternative_slots: list[str] | None = None  # 다른 가능한 슬롯들
    ocr_verified: bool = False  # OCR 키워드로 검증됨

    @property
    def is_reliable(self) -> bool:
        """신뢰할 수 있는 매칭인지."""
        return self.confidence in (SlotMatchConfidence.HIGH, SlotMatchConfidence.MEDIUM)

    @property
    def needs_user_confirmation(self) -> bool:
        """사용자 확인이 필요한지."""
        return self.confidence in (SlotMatchConfidence.LOW, SlotMatchConfidence.AMBIGUOUS)


@dataclass
class PhotoProcessingLog:
    """
    사진 처리 로그.

    run log에 photo_processing 배열로 기록됨.
    """
    slot_id: str
    action: str  # mapped, skipped, archived, override
    raw_path: str | None = None  # 원본 파일 경로
    derived_path: str | None = None  # derived 파일 경로
    archived_path: str | None = None  # 아카이브된 경로 (_trash)
    warning: str | None = None  # 중복 선택 등 경고
    override_reason: str | None = None  # override 시 사유
    timestamp: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "slot_id": self.slot_id,
            "action": self.action,
            "raw_path": self.raw_path,
            "derived_path": self.derived_path,
            "archived_path": self.archived_path,
            "warning": self.warning,
            "override_reason": self.override_reason,
            "timestamp": self.timestamp,
        }


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

    override 로그 필수 키: field_or_slot, reason_code, reason_detail, user, timestamp

    reason 필드는 호환성을 위해 "CODE: detail" 형태로 유지됩니다.
    """
    code: str  # OVERRIDE_APPLIED
    timestamp: str  # ISO 8601
    field_or_slot: str
    type: str  # field or photo
    reason_code: str  # OverrideReasonCode 값 (e.g., "MISSING_PHOTO")
    reason_detail: str  # 상세 사유 (최소 10자)
    reason: str  # 호환용: "CODE: detail" 형태
    user: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "timestamp": self.timestamp,
            "field_or_slot": self.field_or_slot,
            "type": self.type,
            "reason_code": self.reason_code,
            "reason_detail": self.reason_detail,
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

    # Photo processing (mapped, skipped, archived, override)
    photo_processing: list["PhotoProcessingLog"] = field(default_factory=list)

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
            "photo_processing": [p.to_dict() for p in self.photo_processing],
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
class PhotoMapping:
    """사진 슬롯 매핑 정보."""
    slot_key: str
    filename: str
    raw_path: str
    mapped_at: str  # ISO 8601


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
    photo_mappings: list[PhotoMapping] = field(default_factory=list)  # 사진 슬롯 매핑
