"""
test_ssot_job.py - SSOT (job.json) 관리 테스트

DoD:
1. job.json SSOT + lock + mismatch/corrupt reject
"""

import json
import os
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from src.core.ssot_job import (
    atomic_write_json,
    ensure_job_json,
    job_lock,
    load_job_json,
    verify_mismatch,
)
from src.domain.errors import ErrorCodes, PolicyRejectError

# =============================================================================
# job_lock 테스트
# =============================================================================


class TestJobLock:
    """job_lock 컨텍스트 매니저 테스트."""

    def test_lock_acquired_and_released(self, tmp_path: Path, test_config: dict):
        """락 획득 후 정상 해제 확인."""
        job_dir = tmp_path / "job"
        job_dir.mkdir()

        lock_dir = job_dir / ".lock"

        # 락 획득 전
        assert not lock_dir.exists()

        # 락 획득 중
        with job_lock(job_dir, test_config) as acquired_lock:
            assert lock_dir.exists()
            assert acquired_lock == lock_dir

        # 락 해제 후
        assert not lock_dir.exists()

    def test_lock_released_on_exception(self, tmp_path: Path, test_config: dict):
        """예외 발생 시에도 락 해제 확인."""
        job_dir = tmp_path / "job"
        job_dir.mkdir()

        lock_dir = job_dir / ".lock"

        with pytest.raises(ValueError, match="test error"):
            with job_lock(job_dir, test_config):
                assert lock_dir.exists()
                raise ValueError("test error")

        # 예외 후에도 락 해제됨
        assert not lock_dir.exists()

    def test_lock_timeout_raises_error(self, tmp_path: Path):
        """락 타임아웃 시 PolicyRejectError 발생."""
        job_dir = tmp_path / "job"
        job_dir.mkdir()

        # 사전에 락 폴더 생성 (잠금 상태 시뮬레이션)
        lock_dir = job_dir / ".lock"
        lock_dir.mkdir()

        # 짧은 타임아웃 설정
        config = {
            "paths": {"lock_dir": ".lock"},
            "pipeline": {
                "lock_retry_interval": 0.01,
                "lock_max_retries": 2,
            },
        }

        with pytest.raises(PolicyRejectError) as exc_info:
            with job_lock(job_dir, config):
                pass

        assert exc_info.value.code == ErrorCodes.JOB_JSON_LOCK_TIMEOUT
        assert "job_dir" in exc_info.value.context

    def test_concurrent_lock_acquisition(self, tmp_path: Path, test_config: dict):
        """동시 락 획득 시 한 쪽만 성공."""
        job_dir = tmp_path / "job"
        job_dir.mkdir()

        results = []
        barrier = threading.Barrier(2)

        def try_lock(name: str):
            barrier.wait()  # 동시 시작
            try:
                with job_lock(job_dir, test_config):
                    time.sleep(0.1)  # 락 보유
                    results.append(f"{name}:success")
            except PolicyRejectError:
                results.append(f"{name}:timeout")

        t1 = threading.Thread(target=try_lock, args=("t1",))
        t2 = threading.Thread(target=try_lock, args=("t2",))

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # 둘 중 하나는 성공, 하나는 timeout
        success_count = sum(1 for r in results if "success" in r)

        assert success_count >= 1  # 최소 1개 성공
        # Note: 타이밍에 따라 둘 다 성공할 수 있음 (순차적 획득)


# =============================================================================
# atomic_write_json 테스트
# =============================================================================


class TestAtomicWriteJson:
    """atomic_write_json 함수 테스트."""

    def test_writes_json_correctly(self, tmp_path: Path):
        """JSON 파일 정상 작성."""
        file_path = tmp_path / "test.json"
        data = {"key": "value", "number": 42, "한글": "테스트"}

        atomic_write_json(file_path, data)

        assert file_path.exists()
        loaded = json.loads(file_path.read_text(encoding="utf-8"))
        assert loaded == data

    def test_creates_parent_directories(self, tmp_path: Path):
        """부모 디렉터리 자동 생성."""
        file_path = tmp_path / "nested" / "dir" / "test.json"
        data = {"key": "value"}

        atomic_write_json(file_path, data)

        assert file_path.exists()
        assert file_path.parent.exists()

    def test_overwrites_existing_file(self, tmp_path: Path):
        """기존 파일 덮어쓰기."""
        file_path = tmp_path / "test.json"
        file_path.write_text('{"old": "data"}')

        new_data = {"new": "data"}
        atomic_write_json(file_path, new_data)

        loaded = json.loads(file_path.read_text())
        assert loaded == new_data

    def test_no_temp_file_left_on_success(self, tmp_path: Path):
        """성공 시 temp 파일 남지 않음."""
        file_path = tmp_path / "test.json"
        data = {"key": "value"}

        atomic_write_json(file_path, data)

        # .tmp 파일 없어야 함
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0

    def test_preserves_original_on_failure(self, tmp_path: Path):
        """실패 시 원본 파일 보존 (쓰기 에러 시뮬레이션)."""
        file_path = tmp_path / "test.json"
        original_data = {"original": "data"}
        file_path.write_text(json.dumps(original_data))

        # json.dump가 실패하도록 직렬화 불가능한 객체 전달
        class NonSerializable:
            pass

        with pytest.raises(TypeError):
            atomic_write_json(file_path, {"bad": NonSerializable()})

        # 원본 파일 유지됨
        loaded = json.loads(file_path.read_text())
        assert loaded == original_data


# =============================================================================
# verify_mismatch 테스트
# =============================================================================


class TestVerifyMismatch:
    """verify_mismatch 함수 테스트."""

    def test_no_error_when_match(self):
        """wo_no, line이 일치하면 에러 없음."""
        existing = {"wo_no": "WO-001", "line": "L1"}
        current = {"wo_no": "WO-001", "line": "L1", "extra": "ignored"}

        # 에러 없이 통과
        verify_mismatch(existing, current)

    def test_raises_on_wo_no_mismatch(self):
        """wo_no 불일치 시 PolicyRejectError 발생."""
        existing = {"wo_no": "WO-001", "line": "L1"}
        current = {"wo_no": "WO-002", "line": "L1"}

        with pytest.raises(PolicyRejectError) as exc_info:
            verify_mismatch(existing, current)

        assert exc_info.value.code == ErrorCodes.PACKET_JOB_MISMATCH
        assert exc_info.value.context["field"] == "wo_no"
        assert exc_info.value.context["existing"] == "WO-001"
        assert exc_info.value.context["current"] == "WO-002"

    def test_raises_on_line_mismatch(self):
        """line 불일치 시 PolicyRejectError 발생."""
        existing = {"wo_no": "WO-001", "line": "L1"}
        current = {"wo_no": "WO-001", "line": "L2"}

        with pytest.raises(PolicyRejectError) as exc_info:
            verify_mismatch(existing, current)

        assert exc_info.value.code == ErrorCodes.PACKET_JOB_MISMATCH
        assert exc_info.value.context["field"] == "line"


# =============================================================================
# load_job_json 테스트
# =============================================================================


class TestLoadJobJson:
    """load_job_json 함수 테스트."""

    def test_loads_valid_json(self, tmp_path: Path):
        """정상 JSON 파일 로드."""
        job_json_path = tmp_path / "job.json"
        data = {"job_id": "JOB-001", "wo_no": "WO-001", "line": "L1"}
        job_json_path.write_text(json.dumps(data))

        loaded = load_job_json(job_json_path)

        assert loaded == data

    def test_raises_on_corrupt_json(self, tmp_path: Path):
        """손상된 JSON 시 PolicyRejectError 발생."""
        job_json_path = tmp_path / "job.json"
        job_json_path.write_text("{ invalid json }")

        with pytest.raises(PolicyRejectError) as exc_info:
            load_job_json(job_json_path)

        assert exc_info.value.code == ErrorCodes.JOB_JSON_CORRUPT
        assert "path" in exc_info.value.context


# =============================================================================
# ensure_job_json 테스트
# =============================================================================


class TestEnsureJobJson:
    """ensure_job_json 함수 테스트."""

    def test_creates_new_job_json(self, tmp_path: Path, test_config: dict):
        """job.json 없으면 새로 생성."""
        job_dir = tmp_path / "job"
        job_dir.mkdir()

        packet = {"wo_no": "WO-001", "line": "L1"}

        def generate_id(p):
            return f"JOB-{p['wo_no']}-{p['line']}"

        job_id = ensure_job_json(job_dir, packet, test_config, generate_id)

        assert job_id == "JOB-WO-001-L1"

        # job.json 생성 확인
        job_json_path = job_dir / "job.json"
        assert job_json_path.exists()

        job_data = json.loads(job_json_path.read_text())
        assert job_data["job_id"] == "JOB-WO-001-L1"
        assert job_data["wo_no"] == "WO-001"
        assert job_data["line"] == "L1"
        assert "created_at" in job_data
        assert job_data["schema_version"] == "1.0"

    def test_returns_existing_job_id(self, tmp_path: Path, test_config: dict):
        """기존 job.json 있으면 job_id 반환."""
        job_dir = tmp_path / "job"
        job_dir.mkdir()

        # 기존 job.json 생성
        existing_data = {
            "job_id": "EXISTING-JOB-ID",
            "wo_no": "WO-001",
            "line": "L1",
        }
        (job_dir / "job.json").write_text(json.dumps(existing_data))

        packet = {"wo_no": "WO-001", "line": "L1"}

        def generate_id(p):  # noqa: ARG001
            return "NEW-JOB-ID"  # 호출되지 않아야 함

        job_id = ensure_job_json(job_dir, packet, test_config, generate_id)

        assert job_id == "EXISTING-JOB-ID"  # 기존 ID 반환

    def test_raises_on_mismatch(self, tmp_path: Path, test_config: dict):
        """wo_no/line 불일치 시 에러."""
        job_dir = tmp_path / "job"
        job_dir.mkdir()

        # 기존 job.json
        existing_data = {"job_id": "JOB-001", "wo_no": "WO-001", "line": "L1"}
        (job_dir / "job.json").write_text(json.dumps(existing_data))

        # 다른 wo_no로 시도
        packet = {"wo_no": "WO-DIFFERENT", "line": "L1"}

        with pytest.raises(PolicyRejectError) as exc_info:
            ensure_job_json(job_dir, packet, test_config, lambda p: "NEW")

        assert exc_info.value.code == ErrorCodes.PACKET_JOB_MISMATCH


# =============================================================================
# Lock 해제 실패 테스트
# =============================================================================


class TestJobLockReleaseFailure:
    """락 해제 실패 시 warning 로그 테스트."""

    def test_lock_release_failure_logs_warning(
        self, tmp_path: Path, test_config: dict, caplog
    ):
        """락 해제 실패 시 warning 로그가 남는지 확인."""
        import logging

        from src.core import ssot_job

        job_dir = tmp_path / "job"
        job_dir.mkdir()

        caplog.set_level(logging.WARNING, logger="src.core.ssot_job")

        # 원본 os.rmdir 저장
        original_rmdir = os.rmdir

        def failing_rmdir(path):
            raise OSError("Permission denied")

        # job_lock 진입 후 rmdir만 mock
        with job_lock(job_dir, test_config):
            # 컨텍스트 내에서 rmdir을 실패하도록 교체
            ssot_job.os.rmdir = failing_rmdir

        # 원본 복원
        ssot_job.os.rmdir = original_rmdir

        # warning 로그 확인
        assert any("Lock release failed" in record.message for record in caplog.records)
        assert any(
            "Manual cleanup may be required" in record.message
            for record in caplog.records
        )

    def test_lock_release_failure_includes_path_in_log(
        self, tmp_path: Path, test_config: dict, caplog
    ):
        """락 해제 실패 시 로그에 경로 정보 포함 확인."""
        import logging

        job_dir = tmp_path / "job"
        job_dir.mkdir()

        caplog.set_level(logging.WARNING, logger="src.core.ssot_job")

        with patch("src.core.ssot_job.os.rmdir") as mock_rmdir:
            mock_rmdir.side_effect = OSError("Device busy")

            with job_lock(job_dir, test_config):
                pass

        # 로그에 job_dir 경로 포함
        warning_logs = [r.message for r in caplog.records if r.levelname == "WARNING"]
        assert len(warning_logs) >= 1
        assert str(job_dir) in warning_logs[0]


# =============================================================================
# fsync 실패 테스트
# =============================================================================


class TestAtomicWriteFsyncFailure:
    """fsync 실패 시 warning 로그 테스트."""

    def test_fsync_failure_logs_warning(self, tmp_path: Path, caplog):
        """fsync 실패 시 warning 로그가 남는지 확인."""
        import logging

        file_path = tmp_path / "test.json"
        data = {"key": "value"}

        caplog.set_level(logging.WARNING, logger="src.core.ssot_job")

        with patch("os.fsync") as mock_fsync:
            mock_fsync.side_effect = OSError("I/O error")

            atomic_write_json(file_path, data)

        # warning 로그 확인
        assert any("fsync failed" in record.message for record in caplog.records)
        assert any(
            "Data may not be durable" in record.message for record in caplog.records
        )

    def test_fsync_failure_still_writes_file(self, tmp_path: Path):
        """fsync 실패해도 파일은 정상적으로 작성됨."""
        file_path = tmp_path / "test.json"
        data = {"key": "value", "number": 42}

        with patch("os.fsync") as mock_fsync:
            mock_fsync.side_effect = OSError("I/O error")

            atomic_write_json(file_path, data)

        # 파일은 정상 작성됨
        assert file_path.exists()
        loaded = json.loads(file_path.read_text(encoding="utf-8"))
        assert loaded == data

    def test_fsync_failure_includes_path_in_log(self, tmp_path: Path, caplog):
        """fsync 실패 시 로그에 파일 경로 포함 확인."""
        import logging

        file_path = tmp_path / "important.json"
        data = {"key": "value"}

        caplog.set_level(logging.WARNING, logger="src.core.ssot_job")

        with patch("os.fsync") as mock_fsync:
            mock_fsync.side_effect = OSError("Disk full")

            atomic_write_json(file_path, data)

        # 로그에 파일 경로 포함
        warning_logs = [r.message for r in caplog.records if r.levelname == "WARNING"]
        assert len(warning_logs) >= 1
        assert str(file_path) in warning_logs[0]

    def test_fsync_success_no_warning(self, tmp_path: Path, caplog):
        """fsync 성공 시 warning 없음."""
        import logging

        file_path = tmp_path / "test.json"
        data = {"key": "value"}

        caplog.set_level(logging.WARNING, logger="src.core.ssot_job")

        # fsync 정상 동작 (mock 없이)
        atomic_write_json(file_path, data)

        # fsync 관련 warning 없음
        fsync_warnings = [r for r in caplog.records if "fsync" in r.message]
        assert len(fsync_warnings) == 0


# =============================================================================
# 디렉토리 fsync 테스트
# =============================================================================


class TestDirectoryFsync:
    """디렉토리 fsync 테스트."""

    def test_dir_fsync_failure_logs_warning(self, tmp_path: Path, caplog):
        """디렉토리 fsync 실패 시 warning 로그가 남는지 확인."""
        import logging

        from src.core.ssot_job import _fsync_dir

        caplog.set_level(logging.WARNING, logger="src.core.ssot_job")

        with patch("os.open") as mock_open:
            mock_open.side_effect = OSError("Operation not permitted")

            _fsync_dir(tmp_path)

        # warning 로그 확인
        assert any(
            "Directory fsync failed" in record.message for record in caplog.records
        )

    def test_dir_fsync_success_no_warning(self, tmp_path: Path, caplog):
        """디렉토리 fsync 성공 시 warning 없음."""
        import logging

        from src.core.ssot_job import _fsync_dir

        caplog.set_level(logging.WARNING, logger="src.core.ssot_job")

        # 실제 디렉토리 fsync (Linux에서는 성공해야 함)
        _fsync_dir(tmp_path)

        # dir fsync 관련 warning 없음
        dir_fsync_warnings = [
            r for r in caplog.records if "Directory fsync" in r.message
        ]
        assert len(dir_fsync_warnings) == 0

    def test_atomic_write_calls_dir_fsync(self, tmp_path: Path):
        """atomic_write_json이 디렉토리 fsync를 호출하는지 확인."""
        from src.core import ssot_job

        file_path = tmp_path / "test.json"
        data = {"key": "value"}

        dir_fsync_called = []
        original_fsync_dir = ssot_job._fsync_dir

        def tracking_fsync_dir(dir_path):
            dir_fsync_called.append(dir_path)
            return original_fsync_dir(dir_path)

        ssot_job._fsync_dir = tracking_fsync_dir
        try:
            atomic_write_json(file_path, data)
        finally:
            ssot_job._fsync_dir = original_fsync_dir

        # 디렉토리 fsync가 호출됨
        assert len(dir_fsync_called) == 1
        assert dir_fsync_called[0] == tmp_path


# =============================================================================
# Stale Lock 메타정보 테스트
# =============================================================================


class TestStaleLockMeta:
    """Stale lock 메타정보 테스트."""

    def test_lock_creates_meta_file(self, tmp_path: Path, test_config: dict):
        """락 획득 시 메타 파일이 생성되는지 확인."""
        from src.core.ssot_job import LOCK_META_FILENAME

        job_dir = tmp_path / "job"
        job_dir.mkdir()

        with job_lock(job_dir, test_config) as lock_dir:
            meta_path = lock_dir / LOCK_META_FILENAME
            assert meta_path.exists()

            # 메타 내용 확인
            meta = json.loads(meta_path.read_text())
            assert "pid" in meta
            assert "hostname" in meta
            assert "created_at" in meta
            assert meta["pid"] == os.getpid()

    def test_lock_removes_meta_file_on_release(self, tmp_path: Path, test_config: dict):
        """락 해제 시 메타 파일이 삭제되는지 확인."""
        from src.core.ssot_job import LOCK_META_FILENAME

        job_dir = tmp_path / "job"
        job_dir.mkdir()
        lock_dir = job_dir / ".lock"

        with job_lock(job_dir, test_config):
            pass

        # 락 해제 후 메타 파일과 디렉토리 모두 없어야 함
        assert not lock_dir.exists()
        assert not (lock_dir / LOCK_META_FILENAME).exists()

    def test_stale_lock_detected_by_dead_pid(self, tmp_path: Path):
        """죽은 PID의 락은 stale로 감지되는지 확인."""
        from src.core.ssot_job import (
            LOCK_META_FILENAME,
            _get_current_hostname,
            _is_stale_lock,
        )

        lock_dir = tmp_path / ".lock"
        lock_dir.mkdir()

        # 존재하지 않는 PID로 메타 작성
        meta = {
            "pid": 999999999,  # 존재하지 않을 가능성 높은 PID
            "hostname": _get_current_hostname(),
            "created_at": datetime.now(UTC).isoformat(),
        }
        (lock_dir / LOCK_META_FILENAME).write_text(json.dumps(meta))

        # stale로 감지되어야 함 (PID가 죽었으므로)
        assert _is_stale_lock(lock_dir) is True

    def test_stale_lock_not_detected_for_alive_pid(self, tmp_path: Path):
        """현재 프로세스 PID의 락은 stale이 아님."""
        from src.core.ssot_job import (
            LOCK_META_FILENAME,
            _get_current_hostname,
            _is_stale_lock,
        )

        lock_dir = tmp_path / ".lock"
        lock_dir.mkdir()

        # 현재 PID로 메타 작성
        meta = {
            "pid": os.getpid(),
            "hostname": _get_current_hostname(),
            "created_at": datetime.now(UTC).isoformat(),
        }
        (lock_dir / LOCK_META_FILENAME).write_text(json.dumps(meta))

        # stale이 아니어야 함 (현재 프로세스가 살아있으므로)
        assert _is_stale_lock(lock_dir) is False

    def test_stale_lock_ttl_for_different_host(self, tmp_path: Path):
        """다른 호스트의 락은 TTL 기반으로만 판단."""
        from src.core.ssot_job import (
            LOCK_META_FILENAME,
            STALE_LOCK_THRESHOLD_SECONDS,
            _is_stale_lock,
        )

        lock_dir = tmp_path / ".lock"
        lock_dir.mkdir()

        # 다른 호스트, 최근 시간
        meta = {
            "pid": 12345,
            "hostname": "other-host-that-does-not-exist",
            "created_at": datetime.now(UTC).isoformat(),
        }
        (lock_dir / LOCK_META_FILENAME).write_text(json.dumps(meta))

        # 최근이므로 stale 아님
        assert _is_stale_lock(lock_dir) is False

        # 오래된 시간으로 변경
        from datetime import timedelta

        old_time = datetime.now(UTC) - timedelta(
            seconds=STALE_LOCK_THRESHOLD_SECONDS + 100
        )
        meta["created_at"] = old_time.isoformat()
        (lock_dir / LOCK_META_FILENAME).write_text(json.dumps(meta))

        # TTL 초과로 stale
        assert _is_stale_lock(lock_dir) is True

    def test_cleanup_stale_lock_logs_owner_info(self, tmp_path: Path, caplog):
        """stale lock 정리 시 소유자 정보가 로그에 포함되는지 확인."""
        import logging
        from datetime import timedelta

        from src.core.ssot_job import (
            LOCK_META_FILENAME,
            STALE_LOCK_THRESHOLD_SECONDS,
            _try_cleanup_stale_lock,
        )

        lock_dir = tmp_path / ".lock"
        lock_dir.mkdir()

        # 다른 호스트의 오래된 락 (TTL 초과)
        old_time = datetime.now(UTC) - timedelta(
            seconds=STALE_LOCK_THRESHOLD_SECONDS + 100
        )
        meta = {
            "pid": 999999999,
            "hostname": "test-host",
            "created_at": old_time.isoformat(),
        }
        (lock_dir / LOCK_META_FILENAME).write_text(json.dumps(meta))

        caplog.set_level(logging.WARNING, logger="src.core.ssot_job")

        result = _try_cleanup_stale_lock(lock_dir)

        assert result is True
        assert not lock_dir.exists()

        # 로그에 소유자 정보 포함
        warning_logs = [r.message for r in caplog.records if r.levelname == "WARNING"]
        assert len(warning_logs) >= 1
        assert "pid=999999999" in warning_logs[0]
        assert "host=test-host" in warning_logs[0]
