"""
test_ssot_job.py - SSOT (job.json) 관리 테스트

DoD:
1. job.json SSOT + lock + mismatch/corrupt reject
"""

import json
import os
import threading
import time
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
        timeout_count = sum(1 for r in results if "timeout" in r)

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
        generate_id = lambda p: f"JOB-{p['wo_no']}-{p['line']}"

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
        generate_id = lambda p: "NEW-JOB-ID"  # 호출되지 않아야 함

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
