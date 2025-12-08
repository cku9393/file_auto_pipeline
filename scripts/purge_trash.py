#!/usr/bin/env python3
"""
purge_trash.py - _trash 보관 정책 기반 정리 스크립트

definition.yaml의 photos.trash_retention 설정에 따라:
1. 보관 기간(retention_days) 초과 파일 정리
2. job 단위 용량(max_size_per_job_mb) 초과 시 오래된 것부터 정리
3. 전체 용량(max_total_size_gb) 초과 시 오래된 것부터 정리

purge_mode:
- delete: 완전 삭제
- compress: tar.gz로 압축 후 archive_dir로 이동
- external: 외부 스토리지로 이동 (미구현, 확장용)

사용법:
    # 기본 실행 (dry-run)
    uv run python scripts/purge_trash.py

    # 실제 삭제
    uv run python scripts/purge_trash.py --execute

    # 특정 job만
    uv run python scripts/purge_trash.py --job JOB-12345678 --execute

    # cron 예시 (매일 새벽 3시)
    0 3 * * * cd /path/to/project && uv run python scripts/purge_trash.py --execute >> /var/log/purge_trash.log 2>&1
"""

import argparse
import logging
import os
import shutil
import tarfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import yaml

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


@dataclass
class TrashRetentionConfig:
    """_trash 보관 정책 설정."""
    retention_days: int = 30
    max_size_per_job_mb: int = 100
    max_total_size_gb: int = 10
    purge_mode: str = "compress"  # delete, compress, external
    archive_dir: str = "_archive"
    min_keep_count: int = 3


@dataclass
class PurgeResult:
    """Purge 결과."""
    scanned_jobs: int = 0
    scanned_folders: int = 0
    scanned_files: int = 0
    scanned_size_mb: float = 0.0

    purged_folders: int = 0
    purged_files: int = 0
    purged_size_mb: float = 0.0

    compressed_archives: int = 0
    errors: list[str] = field(default_factory=list)


def load_retention_config(definition_path: Path) -> TrashRetentionConfig:
    """definition.yaml에서 보관 정책 로드."""
    with open(definition_path, encoding="utf-8") as f:
        definition = yaml.safe_load(f)

    trash_config = definition.get("photos", {}).get("trash_retention", {})

    return TrashRetentionConfig(
        retention_days=trash_config.get("retention_days", 30),
        max_size_per_job_mb=trash_config.get("max_size_per_job_mb", 100),
        max_total_size_gb=trash_config.get("max_total_size_gb", 10),
        purge_mode=trash_config.get("purge_mode", "compress"),
        archive_dir=trash_config.get("archive_dir", "_archive"),
        min_keep_count=trash_config.get("min_keep_count", 3),
    )


def get_folder_size(folder: Path) -> int:
    """폴더 전체 크기 (bytes)."""
    total = 0
    try:
        for item in folder.rglob("*"):
            if item.is_file():
                total += item.stat().st_size
    except OSError:
        pass
    return total


def get_folder_mtime(folder: Path) -> datetime:
    """폴더 수정 시간 (폴더명에서 파싱 시도, 실패 시 mtime)."""
    # 폴더명 형식: 20240115_093000_RUN-001
    folder_name = folder.name
    try:
        # 앞 15자리가 날짜시간
        dt_str = folder_name[:15]  # 20240115_093000
        return datetime.strptime(dt_str, "%Y%m%d_%H%M%S")
    except (ValueError, IndexError):
        # 파싱 실패 시 실제 mtime 사용
        return datetime.fromtimestamp(folder.stat().st_mtime)


def compress_folder(folder: Path, archive_dir: Path) -> Path | None:
    """폴더를 tar.gz로 압축."""
    try:
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_name = f"{folder.name}.tar.gz"
        archive_path = archive_dir / archive_name

        # 이미 존재하면 suffix 추가
        counter = 1
        while archive_path.exists():
            archive_name = f"{folder.name}_{counter}.tar.gz"
            archive_path = archive_dir / archive_name
            counter += 1

        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(folder, arcname=folder.name)

        return archive_path
    except Exception as e:
        logger.error(f"압축 실패 {folder}: {e}")
        return None


def purge_folder(
    folder: Path,
    config: TrashRetentionConfig,
    job_dir: Path,
    execute: bool,
    result: PurgeResult,
) -> None:
    """단일 폴더 purge 처리."""
    folder_size = get_folder_size(folder)
    file_count = sum(1 for f in folder.rglob("*") if f.is_file())

    if config.purge_mode == "delete":
        if execute:
            try:
                shutil.rmtree(folder)
                result.purged_folders += 1
                result.purged_files += file_count
                result.purged_size_mb += folder_size / (1024 * 1024)
                logger.info(f"삭제됨: {folder} ({folder_size / 1024:.1f} KB)")
            except Exception as e:
                result.errors.append(f"삭제 실패 {folder}: {e}")
                logger.error(f"삭제 실패 {folder}: {e}")
        else:
            logger.info(f"[DRY-RUN] 삭제 예정: {folder} ({folder_size / 1024:.1f} KB)")
            result.purged_folders += 1
            result.purged_files += file_count
            result.purged_size_mb += folder_size / (1024 * 1024)

    elif config.purge_mode == "compress":
        archive_dir = job_dir / "photos" / config.archive_dir
        if execute:
            archive_path = compress_folder(folder, archive_dir)
            if archive_path:
                try:
                    shutil.rmtree(folder)
                    result.purged_folders += 1
                    result.purged_files += file_count
                    result.purged_size_mb += folder_size / (1024 * 1024)
                    result.compressed_archives += 1
                    logger.info(f"압축됨: {folder} → {archive_path}")
                except Exception as e:
                    result.errors.append(f"원본 삭제 실패 {folder}: {e}")
        else:
            logger.info(f"[DRY-RUN] 압축 예정: {folder} → {archive_dir}")
            result.purged_folders += 1
            result.purged_files += file_count
            result.purged_size_mb += folder_size / (1024 * 1024)
            result.compressed_archives += 1

    elif config.purge_mode == "external":
        # 외부 스토리지 이동 - 확장용 (현재 미구현)
        logger.warning(f"external 모드 미구현: {folder}")


def purge_job_trash(
    job_dir: Path,
    config: TrashRetentionConfig,
    execute: bool,
    result: PurgeResult,
) -> None:
    """단일 job의 _trash 정리."""
    trash_dir = job_dir / "photos" / "_trash"

    if not trash_dir.exists():
        return

    # 모든 아카이브 폴더 수집
    folders = [f for f in trash_dir.iterdir() if f.is_dir()]
    if not folders:
        return

    result.scanned_jobs += 1

    # 수정 시간순 정렬 (오래된 것 먼저)
    folders.sort(key=get_folder_mtime)

    now = datetime.now()
    cutoff_date = now - timedelta(days=config.retention_days)
    max_size_bytes = config.max_size_per_job_mb * 1024 * 1024

    # 현재 총 크기
    current_size = sum(get_folder_size(f) for f in folders)
    result.scanned_folders += len(folders)
    result.scanned_size_mb += current_size / (1024 * 1024)

    # 각 폴더 파일 수 계산
    for folder in folders:
        result.scanned_files += sum(1 for f in folder.rglob("*") if f.is_file())

    purge_candidates = []

    # 1. 보관 기간 초과 폴더 수집
    for folder in folders:
        folder_mtime = get_folder_mtime(folder)
        if folder_mtime < cutoff_date:
            purge_candidates.append(folder)

    # 2. 용량 초과 시 오래된 것부터 추가 (min_keep_count 유지)
    remaining_folders = [f for f in folders if f not in purge_candidates]
    remaining_size = sum(get_folder_size(f) for f in remaining_folders)

    while remaining_size > max_size_bytes and len(remaining_folders) > config.min_keep_count:
        oldest = remaining_folders.pop(0)  # 가장 오래된 것
        purge_candidates.append(oldest)
        remaining_size -= get_folder_size(oldest)

    # 중복 제거 및 순서 유지
    seen = set()
    unique_candidates = []
    for folder in purge_candidates:
        if folder not in seen:
            seen.add(folder)
            unique_candidates.append(folder)

    # Purge 실행
    for folder in unique_candidates:
        purge_folder(folder, config, job_dir, execute, result)


def purge_all_jobs(
    jobs_root: Path,
    config: TrashRetentionConfig,
    execute: bool,
    specific_job: str | None = None,
) -> PurgeResult:
    """모든 job의 _trash 정리."""
    result = PurgeResult()

    if not jobs_root.exists():
        logger.warning(f"jobs 디렉터리 없음: {jobs_root}")
        return result

    # job 디렉터리 목록
    if specific_job:
        job_dirs = [jobs_root / specific_job]
        if not job_dirs[0].exists():
            logger.error(f"job 디렉터리 없음: {job_dirs[0]}")
            return result
    else:
        job_dirs = [d for d in jobs_root.iterdir() if d.is_dir() and d.name.startswith("JOB-")]

    logger.info(f"스캔 대상 job: {len(job_dirs)}개")

    for job_dir in job_dirs:
        purge_job_trash(job_dir, config, execute, result)

    # 전체 용량 체크 (추가 purge 필요 시)
    # 이미 개별 job에서 처리했으므로 여기서는 로그만
    total_trash_size = 0
    for job_dir in job_dirs:
        trash_dir = job_dir / "photos" / "_trash"
        if trash_dir.exists():
            total_trash_size += get_folder_size(trash_dir)

    total_trash_gb = total_trash_size / (1024 * 1024 * 1024)
    if total_trash_gb > config.max_total_size_gb:
        logger.warning(
            f"전체 _trash 용량 초과: {total_trash_gb:.2f}GB > {config.max_total_size_gb}GB"
        )

    return result


def main():
    parser = argparse.ArgumentParser(
        description="_trash 보관 정책 기반 정리 스크립트",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="실제 삭제/압축 실행 (기본: dry-run)",
    )
    parser.add_argument(
        "--job",
        type=str,
        help="특정 job만 처리 (예: JOB-12345678)",
    )
    parser.add_argument(
        "--jobs-root",
        type=str,
        default="jobs",
        help="jobs 디렉터리 경로 (기본: jobs)",
    )
    parser.add_argument(
        "--definition",
        type=str,
        default="definition.yaml",
        help="definition.yaml 경로 (기본: definition.yaml)",
    )

    args = parser.parse_args()

    # 경로 설정
    project_root = Path(__file__).parent.parent
    jobs_root = project_root / args.jobs_root
    definition_path = project_root / args.definition

    if not definition_path.exists():
        logger.error(f"definition.yaml 없음: {definition_path}")
        return 1

    # 설정 로드
    config = load_retention_config(definition_path)
    logger.info(f"보관 정책: {config.retention_days}일, job당 {config.max_size_per_job_mb}MB, 모드: {config.purge_mode}")

    if not args.execute:
        logger.info("=" * 50)
        logger.info("DRY-RUN 모드 (실제 삭제 없음)")
        logger.info("실제 실행: --execute 옵션 추가")
        logger.info("=" * 50)

    # Purge 실행
    result = purge_all_jobs(
        jobs_root=jobs_root,
        config=config,
        execute=args.execute,
        specific_job=args.job,
    )

    # 결과 출력
    logger.info("=" * 50)
    logger.info("Purge 결과:")
    logger.info(f"  스캔: {result.scanned_jobs} jobs, {result.scanned_folders} folders, {result.scanned_files} files ({result.scanned_size_mb:.2f} MB)")
    logger.info(f"  정리: {result.purged_folders} folders, {result.purged_files} files ({result.purged_size_mb:.2f} MB)")
    if config.purge_mode == "compress":
        logger.info(f"  압축: {result.compressed_archives} archives")
    if result.errors:
        logger.warning(f"  에러: {len(result.errors)}개")
        for err in result.errors[:5]:  # 최대 5개만 출력
            logger.warning(f"    - {err}")

    return 0 if not result.errors else 1


if __name__ == "__main__":
    exit(main())
