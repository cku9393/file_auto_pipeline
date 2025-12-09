"""
test_logging.py - RunLog 관리 테스트

DoD:
- run log 스키마대로 저장
- 경고/override 이벤트 기록
"""

from datetime import UTC, datetime
from pathlib import Path

from src.core.logging import (
    complete_run_log,
    create_run_log,
    emit_override,
    emit_warning,
    list_run_logs,
    load_run_log,
    save_run_log,
)

# =============================================================================
# create_run_log 테스트
# =============================================================================

class TestCreateRunLog:
    """create_run_log 함수 테스트."""

    def test_creates_with_job_id(self):
        """job_id로 RunLog 생성."""
        run_log = create_run_log("JOB-001")

        assert run_log.job_id == "JOB-001"
        assert run_log.run_id.startswith("RUN-")
        assert run_log.result == "pending"

    def test_has_started_at(self):
        """started_at 타임스탬프 포함."""
        before = datetime.now(UTC)
        run_log = create_run_log("JOB-001")
        after = datetime.now(UTC)

        started = datetime.fromisoformat(run_log.started_at)
        assert before <= started <= after

    def test_empty_warnings_and_overrides(self):
        """초기 warnings/overrides는 빈 리스트."""
        run_log = create_run_log("JOB-001")

        assert run_log.warnings == []
        assert run_log.overrides == []


# =============================================================================
# emit_warning 테스트
# =============================================================================

class TestEmitWarning:
    """emit_warning 함수 테스트."""

    def test_adds_warning_to_list(self):
        """경고가 리스트에 추가됨."""
        run_log = create_run_log("JOB-001")

        emit_warning(
            run_log,
            code="PHOTO_DUPLICATE_AUTO_SELECTED",
            action_id="photo_select_01_overview",
            field_or_slot="overview",
            message="Multiple files for slot",
            original_value="01_overview.jpg, 01_overview.png",
            resolved_value="01_overview.jpg",
        )

        assert len(run_log.warnings) == 1
        warning = run_log.warnings[0]
        assert warning.code == "PHOTO_DUPLICATE_AUTO_SELECTED"
        assert warning.action_id == "photo_select_01_overview"
        assert warning.field_or_slot == "overview"
        assert warning.level == "warning"

    def test_multiple_warnings(self):
        """여러 경고 추가."""
        run_log = create_run_log("JOB-001")

        emit_warning(run_log, "CODE1", "action1", "field1", "msg1")
        emit_warning(run_log, "CODE2", "action2", "field2", "msg2")

        assert len(run_log.warnings) == 2

    def test_warning_has_required_fields(self):
        """경고 필수 컨텍스트 포함."""
        run_log = create_run_log("JOB-001")

        emit_warning(
            run_log,
            code="TEST_CODE",
            action_id="test_action",
            field_or_slot="test_field",
            message="test message",
            original_value="orig",
            resolved_value="resolved",
        )

        warning = run_log.warnings[0]
        # AGENTS.md 필수 컨텍스트 확인
        assert warning.level == "warning"
        assert warning.code == "TEST_CODE"
        assert warning.action_id == "test_action"
        assert warning.field_or_slot == "test_field"
        assert warning.original_value == "orig"
        assert warning.resolved_value == "resolved"
        assert warning.message == "test message"


# =============================================================================
# emit_override 테스트
# =============================================================================

class TestEmitOverride:
    """emit_override 함수 테스트."""

    def test_adds_override_to_list(self):
        """override가 리스트에 추가됨 (신규 스키마)."""
        run_log = create_run_log("JOB-001")

        emit_override(
            run_log,
            field_or_slot="inspector",
            override_type="field",
            reason_code="DATA_UNAVAILABLE",
            reason_detail="담당자 정보가 제공되지 않았습니다",
            user="admin",
        )

        assert len(run_log.overrides) == 1
        override = run_log.overrides[0]
        assert override.field_or_slot == "inspector"
        assert override.type == "field"
        assert override.reason_code == "DATA_UNAVAILABLE"
        assert override.reason_detail == "담당자 정보가 제공되지 않았습니다"
        assert override.reason == "DATA_UNAVAILABLE: 담당자 정보가 제공되지 않았습니다"
        assert override.user == "admin"

    def test_override_has_timestamp(self):
        """override에 타임스탬프 포함."""
        run_log = create_run_log("JOB-001")

        before = datetime.now(UTC)
        emit_override(run_log, "field", "field", "OTHER", "상세 사유 테스트입니다", "user")
        after = datetime.now(UTC)

        override = run_log.overrides[0]
        ts = datetime.fromisoformat(override.timestamp)
        assert before <= ts <= after

    def test_override_code_applied(self):
        """override 코드는 OVERRIDE_APPLIED."""
        run_log = create_run_log("JOB-001")
        emit_override(run_log, "field", "field", "MISSING_PHOTO", "사진 누락 사유", "user")

        assert run_log.overrides[0].code == "OVERRIDE_APPLIED"


# =============================================================================
# complete_run_log 테스트
# =============================================================================

class TestCompleteRunLog:
    """complete_run_log 함수 테스트."""

    def test_success_completion(self):
        """성공 완료 처리."""
        run_log = create_run_log("JOB-001")

        complete_run_log(
            run_log,
            success=True,
            packet_hash="abc123",
            packet_full_hash="def456",
        )

        assert run_log.result == "success"
        assert run_log.finished_at is not None
        assert run_log.packet_hash == "abc123"
        assert run_log.packet_full_hash == "def456"

    def test_failure_completion(self):
        """실패 완료 처리."""
        run_log = create_run_log("JOB-001")

        complete_run_log(
            run_log,
            success=False,
            error_code="PARSE_ERROR_CRITICAL",
            error_context={"field": "wo_no"},
        )

        assert run_log.result == "failed"
        assert run_log.error_code == "PARSE_ERROR_CRITICAL"
        assert run_log.error_context == {"field": "wo_no"}

    def test_finished_at_set(self):
        """finished_at 설정됨."""
        run_log = create_run_log("JOB-001")

        before = datetime.now(UTC)
        complete_run_log(run_log, success=True)
        after = datetime.now(UTC)

        finished = datetime.fromisoformat(run_log.finished_at)
        assert before <= finished <= after


# =============================================================================
# save_run_log / load_run_log 테스트
# =============================================================================

class TestSaveLoadRunLog:
    """save_run_log / load_run_log 함수 테스트."""

    def test_save_creates_file(self, tmp_path: Path):
        """파일 생성됨."""
        logs_dir = tmp_path / "logs"
        run_log = create_run_log("JOB-001")

        log_path = save_run_log(run_log, logs_dir)

        assert log_path.exists()
        assert log_path.parent == logs_dir
        assert "run_" in log_path.name
        assert log_path.suffix == ".json"

    def test_save_creates_directory(self, tmp_path: Path):
        """디렉터리 자동 생성."""
        logs_dir = tmp_path / "nested" / "logs"
        run_log = create_run_log("JOB-001")

        save_run_log(run_log, logs_dir)

        assert logs_dir.exists()

    def test_load_returns_dict(self, tmp_path: Path):
        """load_run_log는 dict 반환."""
        logs_dir = tmp_path / "logs"
        run_log = create_run_log("JOB-001")
        emit_warning(run_log, "CODE", "action", "field", "msg")
        complete_run_log(run_log, success=True)

        log_path = save_run_log(run_log, logs_dir)
        loaded = load_run_log(log_path)

        assert isinstance(loaded, dict)
        assert loaded["job_id"] == "JOB-001"
        assert loaded["result"] == "success"

    def test_round_trip_preserves_data(self, tmp_path: Path):
        """저장 → 로드 시 데이터 보존."""
        logs_dir = tmp_path / "logs"
        run_log = create_run_log("JOB-001")

        emit_warning(
            run_log,
            code="WARN_CODE",
            action_id="action",
            field_or_slot="field",
            message="warning message",
            original_value="orig",
            resolved_value="resolved",
        )

        emit_override(
            run_log,
            field_or_slot="inspector",
            override_type="field",
            reason_code="DATA_UNAVAILABLE",
            reason_detail="데이터 미제공으로 인한 필드 생략",
            user="user",
        )

        complete_run_log(
            run_log,
            success=True,
            packet_hash="hash1",
            packet_full_hash="hash2",
        )

        log_path = save_run_log(run_log, logs_dir)
        loaded = load_run_log(log_path)

        # 기본 필드
        assert loaded["job_id"] == run_log.job_id
        assert loaded["run_id"] == run_log.run_id
        assert loaded["result"] == "success"
        assert loaded["packet_hash"] == "hash1"
        assert loaded["packet_full_hash"] == "hash2"

        # 경고
        assert len(loaded["warnings"]) == 1
        assert loaded["warnings"][0]["code"] == "WARN_CODE"

        # Override
        assert len(loaded["overrides"]) == 1
        assert loaded["overrides"][0]["field_or_slot"] == "inspector"


# =============================================================================
# list_run_logs 테스트
# =============================================================================

class TestListRunLogs:
    """list_run_logs 함수 테스트."""

    def test_returns_empty_for_nonexistent(self, tmp_path: Path):
        """존재하지 않는 디렉터리는 빈 리스트."""
        logs_dir = tmp_path / "nonexistent"

        result = list_run_logs(logs_dir)

        assert result == []

    def test_returns_empty_for_empty_dir(self, tmp_path: Path):
        """빈 디렉터리는 빈 리스트."""
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()

        result = list_run_logs(logs_dir)

        assert result == []

    def test_lists_run_log_files(self, tmp_path: Path):
        """run_*.json 파일 목록 반환."""
        logs_dir = tmp_path / "logs"

        # 여러 로그 생성
        for i in range(3):
            run_log = create_run_log(f"JOB-{i}")
            save_run_log(run_log, logs_dir)

        result = list_run_logs(logs_dir)

        assert len(result) == 3
        assert all(p.name.startswith("run_") for p in result)

    def test_sorted_by_mtime_descending(self, tmp_path: Path):
        """최신순 정렬."""
        import time

        logs_dir = tmp_path / "logs"

        # 시간차를 두고 생성
        run_log1 = create_run_log("JOB-001")
        save_run_log(run_log1, logs_dir)
        time.sleep(0.1)

        run_log2 = create_run_log("JOB-002")
        save_run_log(run_log2, logs_dir)

        result = list_run_logs(logs_dir)

        # 최신 파일이 먼저
        assert run_log2.run_id in result[0].name
        assert run_log1.run_id in result[1].name

    def test_ignores_non_run_files(self, tmp_path: Path):
        """run_*.json이 아닌 파일 무시."""
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()

        # 다른 파일 생성
        (logs_dir / "other.json").write_text("{}")
        (logs_dir / "run_log.txt").write_text("not json")

        run_log = create_run_log("JOB-001")
        save_run_log(run_log, logs_dir)

        result = list_run_logs(logs_dir)

        # run_*.json만 포함
        assert len(result) == 1
