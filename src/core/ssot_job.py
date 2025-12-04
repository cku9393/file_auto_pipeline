"""
SSOT (Single Source of Truth) 관리: job.json

AGENTS.md 규칙:
- job.json = Job ID의 유일한 진실 원천
- job_id 수정 금지, run_id만 새로 발급
- 락 관리: 컨텍스트 매니저
- 원자적 쓰기: temp → rename
- Mismatch 검증: wo_no, line 불일치 시 reject
"""

import json
import os
import tempfile
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.domain.errors import ErrorCodes, PolicyRejectError

# =============================================================================
# Lock Management
# =============================================================================

@contextmanager
def job_lock(job_dir: Path, config: dict) -> Generator[Path, None, None]:
    """
    job.json 접근을 위한 디렉터리 락.

    사용법:
        with job_lock(job_dir, config):
            # job.json 읽기/쓰기

    보장:
    - 락 획득: os.mkdir() 원자적 생성
    - 락 해제: 정상/예외 모두 rmdir() 호출
    - timeout: config 기반 재시도

    Args:
        job_dir: Job 폴더 경로
        config: 설정 (paths.lock_dir, pipeline.lock_retry_interval, lock_max_retries)

    Yields:
        lock_dir: 락 디렉터리 경로

    Raises:
        PolicyRejectError: JOB_JSON_LOCK_TIMEOUT
    """
    lock_dir_name = config.get("paths", {}).get("lock_dir", ".lock")
    interval = config.get("pipeline", {}).get("lock_retry_interval", 0.5)
    max_retries = config.get("pipeline", {}).get("lock_max_retries", 10)

    lock_dir = job_dir / lock_dir_name

    # 락 획득 시도
    acquired = False
    for _attempt in range(max_retries):
        try:
            os.mkdir(lock_dir)
            acquired = True
            break
        except FileExistsError:
            time.sleep(interval)

    if not acquired:
        raise PolicyRejectError(
            ErrorCodes.JOB_JSON_LOCK_TIMEOUT,
            job_dir=str(job_dir),
            attempts=max_retries,
            total_wait=max_retries * interval,
        )

    try:
        yield lock_dir
    finally:
        # 락 해제 (정상/예외 모두)
        try:
            os.rmdir(lock_dir)
        except OSError:
            pass  # 이미 삭제됨 or 다른 문제 - 무시


# =============================================================================
# Atomic Write
# =============================================================================

def atomic_write_json(path: Path, data: dict) -> None:
    """
    원자적 JSON 쓰기.

    보장:
    - 중간 상태 없음: temp → rename
    - 실패 시 cleanup: temp 파일 삭제
    - 기존 파일 보존: rename 실패 시 원본 유지

    Args:
        path: 저장할 파일 경로
        data: JSON 직렬화할 데이터
    """
    dir_path = path.parent
    dir_path.mkdir(parents=True, exist_ok=True)

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=dir_path,
            suffix=".tmp",
            delete=False,
            encoding="utf-8",
        ) as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            temp_path = Path(f.name)

        os.rename(temp_path, path)  # 원자적

    except Exception:
        # 실패 시 temp 파일 정리
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        raise


# =============================================================================
# Mismatch Verification
# =============================================================================

def verify_mismatch(existing: dict, current: dict) -> None:
    """
    기존 job.json과 현재 packet의 핵심 필드 일치 확인.

    AGENTS.md: wo_no, line이 다르면 PACKET_JOB_MISMATCH

    Args:
        existing: 기존 job.json 데이터
        current: 현재 packet 데이터

    Raises:
        PolicyRejectError: PACKET_JOB_MISMATCH
    """
    for key in ["wo_no", "line"]:
        if existing.get(key) != current.get(key):
            raise PolicyRejectError(
                ErrorCodes.PACKET_JOB_MISMATCH,
                field=key,
                existing=existing.get(key),
                current=current.get(key),
            )


# =============================================================================
# Job JSON Operations
# =============================================================================

def load_job_json(job_json_path: Path) -> dict[str, Any]:
    """
    job.json 로드.

    Args:
        job_json_path: job.json 파일 경로

    Returns:
        job.json 데이터

    Raises:
        PolicyRejectError: JOB_JSON_CORRUPT (JSON 파싱 실패)
    """
    try:
        data: dict[str, Any] = json.loads(job_json_path.read_text(encoding="utf-8"))
        return data
    except json.JSONDecodeError as e:
        raise PolicyRejectError(
            ErrorCodes.JOB_JSON_CORRUPT,
            path=str(job_json_path),
            error=str(e),
        ) from e


def ensure_job_json(
    job_dir: Path,
    packet: dict,
    config: dict,
    generate_job_id_func: Callable[[dict], str],
) -> str:
    """
    job.json 존재 확인 및 생성/검증.

    - 존재하면: mismatch 검증 후 기존 job_id 반환
    - 없으면: 새로 생성

    Args:
        job_dir: Job 폴더 경로
        packet: 현재 packet 데이터 (wo_no, line 포함)
        config: 설정
        generate_job_id_func: job_id 생성 함수

    Returns:
        job_id

    Raises:
        PolicyRejectError: PACKET_JOB_MISMATCH, JOB_JSON_LOCK_TIMEOUT
    """
    job_json_path = job_dir / "job.json"

    with job_lock(job_dir, config):
        if job_json_path.exists():
            existing = load_job_json(job_json_path)
            verify_mismatch(existing, packet)
            job_id: str = existing["job_id"]
            return job_id
        else:
            job_id = generate_job_id_func(packet)
            now = datetime.now(UTC).isoformat()

            job_data = {
                "job_id": job_id,
                "job_id_version": 1,
                "schema_version": "1.0",
                "created_at": now,
                "wo_no": packet["wo_no"],
                "line": packet["line"],
            }

            atomic_write_json(job_json_path, job_data)
            return job_id
