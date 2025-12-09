"""
Run logging: run log schema, events, warnings

AGENTS.md 규칙:
- 경고 필수 컨텍스트: level, code, action_id, field_or_slot,
                    original_value, resolved_value, message
- override 로그 필수 키: field_or_slot, reason, user, timestamp
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.core.ids import generate_run_id
from src.core.ssot_job import atomic_write_json
from src.domain.schemas import OverrideLog, RunLog, WarningLog

# =============================================================================
# Run Log Management
# =============================================================================


def create_run_log(job_id: str) -> RunLog:
    """
    새 RunLog 생성.

    Args:
        job_id: Job ID

    Returns:
        초기화된 RunLog
    """
    now = datetime.now(UTC).isoformat()
    run_id = generate_run_id()

    return RunLog(
        run_id=run_id,
        job_id=job_id,
        started_at=now,
        result="pending",
    )


def emit_warning(
    run_log: RunLog,
    code: str,
    action_id: str,
    field_or_slot: str,
    message: str,
    original_value: str | None = None,
    resolved_value: str | None = None,
) -> None:
    """
    경고 이벤트 기록.

    Args:
        run_log: RunLog 인스턴스
        code: 경고 코드
        action_id: 액션 ID (예: photo_select_01_overview)
        field_or_slot: 필드 또는 슬롯 이름
        message: 경고 메시지
        original_value: 원래 값
        resolved_value: 해결된 값
    """
    warning = WarningLog(
        level="warning",
        code=code,
        action_id=action_id,
        field_or_slot=field_or_slot,
        original_value=original_value,
        resolved_value=resolved_value,
        message=message,
    )
    run_log.warnings.append(warning)


def emit_override(
    run_log: RunLog,
    field_or_slot: str,
    override_type: str,
    reason_code: str,
    reason_detail: str,
    user: str,
) -> None:
    """
    Override 이벤트 기록.

    Args:
        run_log: RunLog 인스턴스
        field_or_slot: 필드 또는 슬롯 이름
        override_type: "field" 또는 "photo"
        reason_code: Override 사유 코드 (OverrideReasonCode 값)
        reason_detail: Override 상세 사유
        user: 사용자 ID/이름
    """
    now = datetime.now(UTC).isoformat()

    # 호환용 reason 필드 생성
    reason = f"{reason_code}: {reason_detail}"

    override = OverrideLog(
        code="OVERRIDE_APPLIED",
        timestamp=now,
        field_or_slot=field_or_slot,
        type=override_type,
        reason_code=reason_code,
        reason_detail=reason_detail,
        reason=reason,
        user=user,
    )
    run_log.overrides.append(override)


def complete_run_log(
    run_log: RunLog,
    success: bool,
    packet_hash: str | None = None,
    packet_full_hash: str | None = None,
    error_code: str | None = None,
    error_context: dict[str, Any] | None = None,
) -> None:
    """
    RunLog 완료 처리.

    Args:
        run_log: RunLog 인스턴스
        success: 성공 여부
        packet_hash: 판정 동일성 해시
        packet_full_hash: 전체 해시
        error_code: 에러 코드 (실패 시)
        error_context: 에러 컨텍스트 (실패 시)
    """
    now = datetime.now(UTC).isoformat()
    run_log.finished_at = now
    run_log.result = "success" if success else "failed"
    run_log.packet_hash = packet_hash
    run_log.packet_full_hash = packet_full_hash

    if not success:
        run_log.error_code = error_code
        run_log.error_context = error_context


def save_run_log(run_log: RunLog, logs_dir: Path) -> Path:
    """
    RunLog를 파일로 저장.

    Args:
        run_log: RunLog 인스턴스
        logs_dir: logs/ 디렉터리 경로

    Returns:
        저장된 파일 경로
    """
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"run_{run_log.run_id}.json"
    atomic_write_json(log_path, run_log.to_dict())
    return log_path


def load_run_log(log_path: Path) -> dict[str, Any]:
    """
    RunLog 파일 로드.

    Args:
        log_path: 로그 파일 경로

    Returns:
        RunLog 데이터 (dict)
    """
    data: dict[str, Any] = json.loads(log_path.read_text(encoding="utf-8"))
    return data


def list_run_logs(logs_dir: Path) -> list[Path]:
    """
    logs/ 디렉터리의 모든 run log 파일 목록.

    Args:
        logs_dir: logs/ 디렉터리 경로

    Returns:
        로그 파일 경로 목록 (최신순)
    """
    if not logs_dir.exists():
        return []

    logs = list(logs_dir.glob("run_*.json"))
    logs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return logs
