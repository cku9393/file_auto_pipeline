"""
SSOT (Single Source of Truth) 관리: job.json

AGENTS.md 규칙:
- job.json = Job ID의 유일한 진실 원천
- job_id 수정 금지, run_id만 새로 발급
- 락 관리: 컨텍스트 매니저
- 원자적 쓰기: temp → rename + fsync
- Mismatch 검증: wo_no, line 불일치 시 reject

파일시스템 안정성 (best-effort):
- 락 해제 실패 시 warning 로그 남김
- fsync로 가능한 환경에서 내구성 강화 (파일 + 디렉토리)
- fsync 실패 시 경고 남기고 계속 진행
- stale lock 감지: PID/hostname 메타 + TTL 기반 정리
"""

import json
import logging
import os
import socket
import tempfile
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.domain.constants import JOB_JSON_FILENAME
from src.domain.errors import ErrorCodes, PolicyRejectError

logger = logging.getLogger(__name__)

# Stale lock threshold (seconds) - 1 hour
STALE_LOCK_THRESHOLD_SECONDS = 3600

# Lock metadata filename
LOCK_META_FILENAME = "lock.meta"

# =============================================================================
# Lock Management
# =============================================================================


def _get_current_hostname() -> str:
    """현재 호스트명 반환 (실패 시 'unknown')."""
    try:
        return socket.gethostname()
    except OSError:
        return "unknown"


def _write_lock_meta(lock_dir: Path) -> None:
    """
    락 메타정보 파일 생성.

    메타 내용: PID, hostname, created_at
    """
    meta_path = lock_dir / LOCK_META_FILENAME
    meta = {
        "pid": os.getpid(),
        "hostname": _get_current_hostname(),
        "created_at": datetime.now(UTC).isoformat(),
    }
    try:
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
    except OSError as e:
        logger.warning(f"Failed to write lock meta {meta_path}: {e}")


def _read_lock_meta(lock_dir: Path) -> dict | None:
    """
    락 메타정보 읽기.

    Returns:
        메타 dict 또는 None (파일 없거나 파싱 실패)
    """
    meta_path = lock_dir / LOCK_META_FILENAME
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _is_process_alive(pid: int) -> bool:
    """
    PID가 살아있는지 확인 (동일 호스트에서만 유효).

    Args:
        pid: 프로세스 ID

    Returns:
        True if alive, False otherwise
    """
    try:
        os.kill(pid, 0)  # signal 0 = 존재 확인만
        return True
    except OSError:
        return False


def _is_stale_lock(
    lock_dir: Path, threshold_seconds: float = STALE_LOCK_THRESHOLD_SECONDS
) -> bool:
    """
    락 디렉토리가 stale(오래된) 상태인지 확인.

    판단 기준:
    1. 메타 파일이 있고 동일 호스트면: PID 생존 여부로 판단
    2. 메타 파일이 있고 다른 호스트면: TTL 기반으로만 판단 (보수적)
    3. 메타 파일이 없으면: 디렉토리 mtime 기준 TTL

    Args:
        lock_dir: 락 디렉토리 경로
        threshold_seconds: stale로 간주할 시간 (기본 1시간)

    Returns:
        True if stale (자동 정리 가능), False otherwise
    """
    meta = _read_lock_meta(lock_dir)

    if meta:
        lock_hostname = meta.get("hostname", "unknown")
        lock_pid = meta.get("pid")
        current_hostname = _get_current_hostname()

        # 동일 호스트: PID 확인
        if lock_hostname == current_hostname and lock_pid:
            if not _is_process_alive(lock_pid):
                return True  # 프로세스 죽음 → stale
            return False  # 프로세스 살아있음 → not stale

        # 다른 호스트: TTL 기반 (보수적)
        # created_at 파싱 시도
        try:
            created_str = meta.get("created_at", "")
            created_at = datetime.fromisoformat(created_str)
            age_seconds = (datetime.now(UTC) - created_at).total_seconds()
            return age_seconds > threshold_seconds
        except (ValueError, TypeError):
            pass  # 파싱 실패 시 아래로

    # 메타 없거나 파싱 실패: 디렉토리 mtime 기준
    try:
        stat = lock_dir.stat()
        age_seconds = time.time() - stat.st_mtime
        return age_seconds > threshold_seconds
    except OSError:
        return False


def _try_cleanup_stale_lock(lock_dir: Path) -> bool:
    """
    Stale lock 정리 시도.

    Args:
        lock_dir: 락 디렉토리 경로

    Returns:
        True if cleaned up, False otherwise
    """
    if not _is_stale_lock(lock_dir):
        return False

    meta = _read_lock_meta(lock_dir)
    meta_info = ""
    if meta:
        meta_info = f" (owner: pid={meta.get('pid')}, host={meta.get('hostname')})"

    try:
        # 메타 파일 먼저 삭제
        meta_path = lock_dir / LOCK_META_FILENAME
        if meta_path.exists():
            meta_path.unlink()

        # 디렉토리 삭제
        os.rmdir(lock_dir)
        logger.warning(
            f"Cleaned up stale lock: {lock_dir}{meta_info}. "
            f"Lock exceeded TTL of {STALE_LOCK_THRESHOLD_SECONDS} seconds."
        )
        return True
    except OSError:
        # 디렉토리에 다른 파일이 있거나 삭제 실패
        return False


def _cleanup_lock_dir(lock_dir: Path) -> None:
    """
    락 디렉토리와 메타 파일 정리.

    Args:
        lock_dir: 락 디렉토리 경로
    """
    # 메타 파일 먼저 삭제
    meta_path = lock_dir / LOCK_META_FILENAME
    if meta_path.exists():
        try:
            meta_path.unlink()
        except OSError:
            pass  # 무시하고 계속

    # 디렉토리 삭제
    os.rmdir(lock_dir)


@contextmanager
def job_lock(job_dir: Path, config: dict) -> Generator[Path, None, None]:
    """
    job.json 접근을 위한 디렉터리 락.

    사용법:
        with job_lock(job_dir, config):
            # job.json 읽기/쓰기

    동작:
    - 락 획득: os.mkdir() 원자적 생성 + 메타 파일(PID, hostname) 기록
    - 락 해제: 정상/예외 모두 메타 삭제 + rmdir() 호출
    - timeout: config 기반 재시도
    - stale lock: PID 생존 확인(동일 호스트) 또는 TTL 기반(다른 호스트) 정리
    - 해제 실패: warning 로그 남김

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
    for attempt in range(max_retries):
        try:
            os.mkdir(lock_dir)
            acquired = True
            _write_lock_meta(lock_dir)  # 메타 파일 기록
            break
        except FileExistsError:
            # 첫 번째 시도에서 stale lock 정리 시도
            if attempt == 0 and _try_cleanup_stale_lock(lock_dir):
                # 정리 성공, 다시 시도
                try:
                    os.mkdir(lock_dir)
                    acquired = True
                    _write_lock_meta(lock_dir)
                    break
                except FileExistsError:
                    pass  # 다른 프로세스가 먼저 획득
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
        if acquired:
            try:
                _cleanup_lock_dir(lock_dir)
            except OSError as e:
                # 락 해제 실패 - warning 로그 남김
                logger.warning(
                    f"Lock release failed for {job_dir}: {e}. "
                    f"Manual cleanup may be required: rm -rf {lock_dir}"
                )


# =============================================================================
# Atomic Write
# =============================================================================


def _fsync_dir(dir_path: Path) -> None:
    """
    디렉토리 fsync (가능한 환경에서).

    rename 후 디렉토리 엔트리까지 내구성을 강화하려면 필요.
    Linux에서 주로 유효하며, 일부 OS/파일시스템에서는 지원되지 않을 수 있음.

    Args:
        dir_path: fsync할 디렉토리 경로
    """
    try:
        dir_fd = os.open(str(dir_path), os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except (OSError, AttributeError) as e:
        # O_DIRECTORY 미지원, 권한 문제 등
        logger.warning(
            f"Directory fsync failed for {dir_path}: {e}. "
            f"Rename durability may not be guaranteed."
        )


def atomic_write_json(path: Path, data: dict) -> None:
    """
    원자적 JSON 쓰기.

    동작:
    - 중간 상태 없음: temp → rename
    - 가능한 환경에서 내구성 강화: 파일 fsync + 디렉토리 fsync
    - fsync 실패 시 경고 남기고 계속 진행
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
            f.flush()  # Python 버퍼 → OS 버퍼
            try:
                os.fsync(f.fileno())  # OS 버퍼 → 디스크 (파일 내용)
            except OSError as e:
                logger.warning(
                    f"File fsync failed for {path}: {e}. "
                    f"Data may not be durable on power loss."
                )
            temp_path = Path(f.name)

        os.rename(temp_path, path)  # 원자적

        # 디렉토리 fsync (rename 엔트리 내구성)
        _fsync_dir(dir_path)

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
    job_json_path = job_dir / JOB_JSON_FILENAME

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
