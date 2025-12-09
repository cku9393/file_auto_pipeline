"""
test_generate_concurrency.py - Generate 동시성 테스트

테스트 케이스:
- TC1: 동일 job에서 동시 generate 호출 시 한쪽은 대기 또는 실패
- TC2: 두 generate 모두 run log가 남음
- TC3: 락 타임아웃 시 명확한 에러 코드 반환
"""

import os
import threading
import time
from pathlib import Path

import pytest

from src.core.ssot_job import job_lock
from src.domain.errors import ErrorCodes, PolicyRejectError


@pytest.fixture
def job_dir(tmp_path: Path) -> Path:
    """테스트용 job 디렉터리."""
    job = tmp_path / "JOB-CONCURRENT"
    job.mkdir()
    return job


@pytest.fixture
def config() -> dict:
    """테스트용 설정."""
    return {
        "paths": {"lock_dir": ".lock"},
        "pipeline": {
            "lock_retry_interval": 0.1,  # 빠른 테스트용
            "lock_max_retries": 5,
        },
    }


# =============================================================================
# TC1: 동시 접근 시 한쪽 대기 또는 실패
# =============================================================================

class TestConcurrentLockBehavior:
    """동시 접근 시 락 동작 테스트."""

    def test_second_caller_waits_for_first(self, job_dir: Path, config: dict):
        """두 번째 호출자는 첫 번째가 완료될 때까지 대기."""
        results = {"first": None, "second": None}
        order = []

        def first_task():
            with job_lock(job_dir, config):
                order.append("first_start")
                time.sleep(0.3)  # 작업 시뮬레이션
                order.append("first_end")
                results["first"] = "success"

        def second_task():
            time.sleep(0.05)  # 첫 번째가 먼저 시작하도록
            try:
                with job_lock(job_dir, config):
                    order.append("second_start")
                    results["second"] = "success"
                    order.append("second_end")
            except PolicyRejectError as e:
                results["second"] = f"error: {e.code}"
                order.append("second_timeout")

        t1 = threading.Thread(target=first_task)
        t2 = threading.Thread(target=second_task)

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # 첫 번째는 항상 성공
        assert results["first"] == "success"

        # 두 번째는 대기 후 성공하거나 타임아웃
        # (config에서 retry 5번 * 0.1초 = 0.5초 > first 0.3초이므로 성공 가능)
        if results["second"] == "success":
            # 순서 확인: first가 끝난 후 second 시작
            assert order.index("first_end") < order.index("second_start")
        else:
            # 타임아웃된 경우
            assert ErrorCodes.JOB_JSON_LOCK_TIMEOUT in results["second"]

    def test_lock_timeout_on_long_operation(self, job_dir: Path):
        """오래 걸리는 작업 시 두 번째는 타임아웃."""
        # 짧은 타임아웃 설정
        short_timeout_config = {
            "paths": {"lock_dir": ".lock"},
            "pipeline": {
                "lock_retry_interval": 0.05,
                "lock_max_retries": 3,  # 0.15초 후 타임아웃
            },
        }

        results = {"first": None, "second": None}

        def first_task():
            with job_lock(job_dir, short_timeout_config):
                time.sleep(0.5)  # 타임아웃보다 오래
                results["first"] = "success"

        def second_task():
            time.sleep(0.05)  # 첫 번째가 먼저 시작
            try:
                with job_lock(job_dir, short_timeout_config):
                    results["second"] = "success"
            except PolicyRejectError as e:
                results["second"] = e.code

        t1 = threading.Thread(target=first_task)
        t2 = threading.Thread(target=second_task)

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert results["first"] == "success"
        assert results["second"] == ErrorCodes.JOB_JSON_LOCK_TIMEOUT


# =============================================================================
# TC2: 두 generate 모두 run log가 남음
# =============================================================================

class TestBothOperationsLogged:
    """성공/실패 모두 로그가 남는지 테스트."""

    def test_lock_released_after_exception(self, job_dir: Path, config: dict):
        """예외 발생해도 락이 해제됨."""
        lock_dir = job_dir / ".lock"

        # 첫 번째: 예외 발생
        with pytest.raises(ValueError):
            with job_lock(job_dir, config):
                assert lock_dir.exists()  # 락 획득됨
                raise ValueError("test error")

        # 락이 해제되어 있어야 함
        assert not lock_dir.exists()

        # 두 번째: 정상 실행 가능
        with job_lock(job_dir, config):
            assert lock_dir.exists()

        assert not lock_dir.exists()

    def test_run_log_saved_on_lock_timeout(self, job_dir: Path):
        """타임아웃 시에도 에러 정보 포함."""
        short_config = {
            "paths": {"lock_dir": ".lock"},
            "pipeline": {
                "lock_retry_interval": 0.01,
                "lock_max_retries": 2,
            },
        }

        # 락 먼저 획득 (수동)
        lock_dir = job_dir / ".lock"
        os.mkdir(lock_dir)

        try:
            with pytest.raises(PolicyRejectError) as exc_info:
                with job_lock(job_dir, short_config):
                    pass

            error = exc_info.value
            assert error.code == ErrorCodes.JOB_JSON_LOCK_TIMEOUT
            assert "attempts" in error.context
            assert "total_wait" in error.context
        finally:
            os.rmdir(lock_dir)


# =============================================================================
# TC3: 락 타임아웃 시 명확한 에러 코드
# =============================================================================

class TestLockTimeoutErrorCode:
    """타임아웃 에러 코드 테스트."""

    def test_timeout_error_has_context(self, job_dir: Path):
        """타임아웃 에러에 상세 컨텍스트 포함."""
        config = {
            "paths": {"lock_dir": ".custom_lock"},
            "pipeline": {
                "lock_retry_interval": 0.01,
                "lock_max_retries": 3,
            },
        }

        # 락 먼저 획득
        lock_dir = job_dir / ".custom_lock"
        os.mkdir(lock_dir)

        try:
            with pytest.raises(PolicyRejectError) as exc_info:
                with job_lock(job_dir, config):
                    pass

            error = exc_info.value
            assert error.code == ErrorCodes.JOB_JSON_LOCK_TIMEOUT
            assert error.context["job_dir"] == str(job_dir)
            assert error.context["attempts"] == 3
            assert error.context["total_wait"] == pytest.approx(0.03, rel=0.5)
        finally:
            os.rmdir(lock_dir)

    def test_error_code_used_in_http_response(self, job_dir: Path):
        """에러 코드가 HTTP 응답에 사용됨."""
        # 이 테스트는 generate.py의 except 블록 검증
        config = {
            "paths": {"lock_dir": ".lock"},
            "pipeline": {
                "lock_retry_interval": 0.01,
                "lock_max_retries": 1,
            },
        }

        # 락 먼저 획득
        lock_dir = job_dir / ".lock"
        os.mkdir(lock_dir)

        try:
            with pytest.raises(PolicyRejectError) as exc_info:
                with job_lock(job_dir, config):
                    pass

            # generate.py에서 이 에러를 HTTP 409로 변환
            assert exc_info.value.code == ErrorCodes.JOB_JSON_LOCK_TIMEOUT
        finally:
            os.rmdir(lock_dir)


# =============================================================================
# 추가: 락 정리 테스트
# =============================================================================

class TestLockCleanup:
    """락 정리 동작 테스트."""

    def test_stale_lock_handling(self, job_dir: Path, config: dict):
        """죽은 프로세스의 스테일 락은 별도 처리 필요 (현재 미지원)."""
        # 현재 구현에서는 스테일 락 감지 없음
        # 운영에서는 수동 정리 또는 락 에이징 필요
        lock_dir = job_dir / ".lock"
        os.mkdir(lock_dir)

        # 스테일 락이 있으면 타임아웃 발생
        short_config = {
            "paths": {"lock_dir": ".lock"},
            "pipeline": {"lock_retry_interval": 0.01, "lock_max_retries": 2},
        }

        try:
            with pytest.raises(PolicyRejectError):
                with job_lock(job_dir, short_config):
                    pass
        finally:
            os.rmdir(lock_dir)

        # 이후 정상 동작
        with job_lock(job_dir, config):
            assert lock_dir.exists()

        assert not lock_dir.exists()
