"""
test_purge_trash.py - purge_trash.py 스크립트 테스트

테스트 케이스:
- TC1: retention_days 초과 폴더 purge
- TC2: max_size_per_job_mb 초과 시 오래된 것부터 purge
- TC3: min_keep_count 유지
- TC4: compress 모드 동작
- TC5: dry-run 모드 (실제 삭제 없음)
"""

import sys
import tarfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

# scripts 모듈 임포트를 위한 경로 추가
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "scripts"))

from purge_trash import (
    PurgeResult,
    TrashRetentionConfig,
    compress_folder,
    get_folder_mtime,
    get_folder_size,
    purge_job_trash,
)


@pytest.fixture
def trash_dir(tmp_path: Path) -> Path:
    """테스트용 _trash 디렉터리."""
    job_dir = tmp_path / "JOB-TEST"
    trash = job_dir / "photos" / "_trash"
    trash.mkdir(parents=True)
    return trash


@pytest.fixture
def job_dir(trash_dir: Path) -> Path:
    """테스트용 job 디렉터리."""
    return trash_dir.parent.parent


def create_archive_folder(trash_dir: Path, name: str, size_kb: int = 10) -> Path:
    """테스트용 아카이브 폴더 생성."""
    folder = trash_dir / name
    folder.mkdir(parents=True, exist_ok=True)

    # 지정 크기의 파일 생성
    test_file = folder / "test.jpg"
    test_file.write_bytes(b"x" * (size_kb * 1024))

    return folder


# =============================================================================
# TC1: retention_days 초과 폴더 purge
# =============================================================================

class TestRetentionDaysPurge:
    """보관 기간 초과 폴더 정리 테스트."""

    def test_old_folders_purged(self, job_dir: Path, trash_dir: Path):
        """30일 이상 된 폴더는 삭제됨."""
        # 오래된 폴더 (35일 전)
        old_date = datetime.now() - timedelta(days=35)
        old_name = old_date.strftime("%Y%m%d_%H%M%S_RUN-OLD")
        old_folder = create_archive_folder(trash_dir, old_name)

        # 최근 폴더 (5일 전)
        new_date = datetime.now() - timedelta(days=5)
        new_name = new_date.strftime("%Y%m%d_%H%M%S_RUN-NEW")
        new_folder = create_archive_folder(trash_dir, new_name)

        config = TrashRetentionConfig(
            retention_days=30,
            purge_mode="delete",
        )

        result = PurgeResult()
        purge_job_trash(job_dir, config, execute=True, result=result)

        # 오래된 폴더만 삭제됨
        assert not old_folder.exists()
        assert new_folder.exists()
        assert result.purged_folders == 1

    def test_all_within_retention_kept(self, job_dir: Path, trash_dir: Path):
        """보관 기간 내 폴더는 모두 유지됨."""
        # 최근 폴더들
        for i in range(3):
            date = datetime.now() - timedelta(days=i + 1)
            name = date.strftime("%Y%m%d_%H%M%S") + f"_RUN-{i:03d}"
            create_archive_folder(trash_dir, name)

        config = TrashRetentionConfig(
            retention_days=30,
            purge_mode="delete",
        )

        result = PurgeResult()
        purge_job_trash(job_dir, config, execute=True, result=result)

        # 모두 유지
        assert result.purged_folders == 0
        assert len(list(trash_dir.iterdir())) == 3


# =============================================================================
# TC2: max_size_per_job_mb 초과 시 오래된 것부터 purge
# =============================================================================

class TestMaxSizePurge:
    """용량 초과 시 오래된 것부터 정리 테스트."""

    def test_oldest_purged_when_over_limit(self, job_dir: Path, trash_dir: Path):
        """용량 초과 시 오래된 것부터 삭제됨."""
        # 폴더 3개 생성 (각 50KB, 총 150KB)
        folders = []
        for i in range(3):
            date = datetime.now() - timedelta(days=i + 1)
            name = date.strftime("%Y%m%d_%H%M%S") + f"_RUN-{i:03d}"
            folder = create_archive_folder(trash_dir, name, size_kb=50)
            folders.append(folder)

        # 가장 오래된 폴더
        oldest_folder = folders[-1]

        config = TrashRetentionConfig(
            retention_days=365,  # 기간은 충분히
            max_size_per_job_mb=0.1,  # 100KB 제한 (150KB 중 50KB 삭제 필요)
            min_keep_count=1,
            purge_mode="delete",
        )

        result = PurgeResult()
        purge_job_trash(job_dir, config, execute=True, result=result)

        # 가장 오래된 폴더 삭제됨
        assert not oldest_folder.exists()
        assert result.purged_folders >= 1


# =============================================================================
# TC3: min_keep_count 유지
# =============================================================================

class TestMinKeepCount:
    """최소 보관 개수 유지 테스트."""

    def test_min_count_preserved(self, job_dir: Path, trash_dir: Path):
        """용량 초과해도 min_keep_count는 유지됨."""
        # 폴더 5개 생성 (각 100KB, 총 500KB)
        folders = []
        for i in range(5):
            date = datetime.now() - timedelta(days=i + 1)
            name = date.strftime("%Y%m%d_%H%M%S") + f"_RUN-{i:03d}"
            folder = create_archive_folder(trash_dir, name, size_kb=100)
            folders.append(folder)

        config = TrashRetentionConfig(
            retention_days=365,
            max_size_per_job_mb=0.05,  # 50KB 제한 (거의 모든 폴더 초과)
            min_keep_count=3,  # 최소 3개 유지
            purge_mode="delete",
        )

        result = PurgeResult()
        purge_job_trash(job_dir, config, execute=True, result=result)

        # 최소 3개 유지
        remaining = list(trash_dir.iterdir())
        assert len(remaining) >= 3


# =============================================================================
# TC4: compress 모드 동작
# =============================================================================

class TestCompressMode:
    """압축 모드 테스트."""

    def test_folder_compressed_to_archive(self, job_dir: Path, trash_dir: Path):
        """폴더가 tar.gz로 압축됨."""
        # 오래된 폴더
        old_date = datetime.now() - timedelta(days=35)
        old_name = old_date.strftime("%Y%m%d_%H%M%S_RUN-OLD")
        old_folder = create_archive_folder(trash_dir, old_name)

        config = TrashRetentionConfig(
            retention_days=30,
            purge_mode="compress",
            archive_dir="_archive",
        )

        result = PurgeResult()
        purge_job_trash(job_dir, config, execute=True, result=result)

        # 원본 폴더 삭제됨
        assert not old_folder.exists()

        # archive 디렉터리에 tar.gz 생성됨
        archive_dir = job_dir / "photos" / "_archive"
        assert archive_dir.exists()

        archives = list(archive_dir.glob("*.tar.gz"))
        assert len(archives) == 1
        assert result.compressed_archives == 1

    def test_compressed_archive_is_valid(self, job_dir: Path, trash_dir: Path):
        """압축 파일이 유효한 tar.gz임."""
        old_date = datetime.now() - timedelta(days=35)
        old_name = old_date.strftime("%Y%m%d_%H%M%S_RUN-OLD")
        old_folder = create_archive_folder(trash_dir, old_name, size_kb=10)

        config = TrashRetentionConfig(
            retention_days=30,
            purge_mode="compress",
            archive_dir="_archive",
        )

        result = PurgeResult()
        purge_job_trash(job_dir, config, execute=True, result=result)

        # tar.gz 유효성 검증
        archive_dir = job_dir / "photos" / "_archive"
        archive_file = list(archive_dir.glob("*.tar.gz"))[0]

        with tarfile.open(archive_file, "r:gz") as tar:
            names = tar.getnames()
            assert any("test.jpg" in name for name in names)


# =============================================================================
# TC5: dry-run 모드
# =============================================================================

class TestDryRunMode:
    """Dry-run 모드 테스트."""

    def test_dry_run_no_deletion(self, job_dir: Path, trash_dir: Path):
        """execute=False면 실제 삭제 없음."""
        old_date = datetime.now() - timedelta(days=35)
        old_name = old_date.strftime("%Y%m%d_%H%M%S_RUN-OLD")
        old_folder = create_archive_folder(trash_dir, old_name)

        config = TrashRetentionConfig(
            retention_days=30,
            purge_mode="delete",
        )

        result = PurgeResult()
        purge_job_trash(job_dir, config, execute=False, result=result)

        # 폴더 여전히 존재
        assert old_folder.exists()

        # 하지만 결과에는 purge 예정으로 기록
        assert result.purged_folders == 1


# =============================================================================
# Helper 함수 테스트
# =============================================================================

class TestHelperFunctions:
    """유틸리티 함수 테스트."""

    def test_get_folder_size(self, tmp_path: Path):
        """폴더 크기 계산."""
        folder = tmp_path / "test_folder"
        folder.mkdir()

        (folder / "file1.txt").write_bytes(b"x" * 1000)
        (folder / "file2.txt").write_bytes(b"y" * 500)

        size = get_folder_size(folder)
        assert size == 1500

    def test_get_folder_mtime_from_name(self, tmp_path: Path):
        """폴더명에서 날짜 파싱."""
        folder = tmp_path / "20240115_093000_RUN-001"
        folder.mkdir()

        mtime = get_folder_mtime(folder)
        assert mtime.year == 2024
        assert mtime.month == 1
        assert mtime.day == 15
        assert mtime.hour == 9
        assert mtime.minute == 30

    def test_compress_folder_creates_archive(self, tmp_path: Path):
        """폴더 압축 함수."""
        source = tmp_path / "source_folder"
        source.mkdir()
        (source / "test.txt").write_text("hello")

        archive_dir = tmp_path / "archives"
        archive_path = compress_folder(source, archive_dir)

        assert archive_path is not None
        assert archive_path.exists()
        assert archive_path.suffix == ".gz"
