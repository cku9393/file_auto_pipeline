"""
test_photos.py - 사진 처리 테스트

DoD:
- safe_move: 원인 보존, dst 충돌 해결, 원자성
- fsync 경고 (실패해도 데이터 보존)
- select_photo_for_slot: prefer_order, required 슬롯 reject
"""

import logging
import os
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from src.core.photos import (
    archive_old_derived,
    copy_to_derived,
    get_allowed_extensions,
    get_prefer_order,
    load_photo_slots,
    safe_move,
    select_photo_for_slot,
)
from src.domain.errors import ErrorCodes, PolicyRejectError
from src.domain.schemas import MoveResult, PhotoSlot


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def sample_photo_definition(tmp_path: Path) -> Path:
    """테스트용 definition.yaml (photos 섹션)."""
    definition = {
        "definition_version": "1.0.0",
        "photos": {
            "allowed_extensions": [".jpg", ".jpeg", ".png"],
            "prefer_order": [".jpg", ".jpeg", ".png"],
            "slots": [
                {
                    "key": "overview",
                    "basename": "01_overview",
                    "required": True,
                    "override_allowed": False,
                },
                {
                    "key": "label_serial",
                    "basename": "02_label_serial",
                    "required": True,
                    "override_allowed": True,
                },
                {
                    "key": "detail",
                    "basename": "03_detail",
                    "required": False,
                    "override_allowed": True,
                },
            ],
        },
    }

    definition_path = tmp_path / "definition.yaml"
    with open(definition_path, "w", encoding="utf-8") as f:
        yaml.dump(definition, f, allow_unicode=True)

    return definition_path


@pytest.fixture
def raw_photo_dir(tmp_path: Path) -> Path:
    """테스트용 photos/raw 디렉터리."""
    raw_dir = tmp_path / "photos" / "raw"
    raw_dir.mkdir(parents=True)
    return raw_dir


@pytest.fixture
def derived_photo_dir(tmp_path: Path) -> Path:
    """테스트용 photos/derived 디렉터리."""
    derived_dir = tmp_path / "photos" / "derived"
    derived_dir.mkdir(parents=True)
    return derived_dir


# =============================================================================
# safe_move 테스트
# =============================================================================

class TestSafeMove:
    """safe_move 함수 테스트."""

    def test_successful_move(self, tmp_path: Path):
        """정상 이동 성공."""
        src = tmp_path / "source.jpg"
        src.write_bytes(b"photo content")
        dst_dir = tmp_path / "archive"

        result = safe_move(src, dst_dir)

        assert result.success is True
        assert result.dst is not None
        assert result.dst.exists()
        assert not src.exists()  # 원본 삭제됨
        assert result.dst.read_bytes() == b"photo content"

    def test_creates_destination_directory(self, tmp_path: Path):
        """대상 디렉터리 자동 생성."""
        src = tmp_path / "source.jpg"
        src.write_bytes(b"content")
        dst_dir = tmp_path / "nested" / "archive"  # 존재하지 않음

        result = safe_move(src, dst_dir)

        assert result.success is True
        assert dst_dir.exists()

    def test_timestamp_in_filename(self, tmp_path: Path):
        """파일명에 타임스탬프 포함."""
        src = tmp_path / "photo.jpg"
        src.write_bytes(b"content")
        dst_dir = tmp_path / "archive"

        result = safe_move(src, dst_dir)

        # 포맷: photo_YYYYMMDD_HHMMSS.jpg
        assert "photo_" in result.dst.stem
        assert result.dst.suffix == ".jpg"

    def test_collision_resolution(self, tmp_path: Path):
        """dst 충돌 시 suffix 추가."""
        src1 = tmp_path / "source1" / "photo.jpg"
        src2 = tmp_path / "source2" / "photo.jpg"
        src1.parent.mkdir(parents=True)
        src2.parent.mkdir(parents=True)
        src1.write_bytes(b"content 1")
        src2.write_bytes(b"content 2")
        dst_dir = tmp_path / "archive"
        dst_dir.mkdir()

        # 같은 파일명으로 2번 이동
        result1 = safe_move(src1, dst_dir)

        # 두번째 파일 생성
        src3 = tmp_path / "source3" / "photo.jpg"
        src3.parent.mkdir(parents=True)
        src3.write_bytes(b"content 3")
        result2 = safe_move(src3, dst_dir)

        assert result1.success is True
        assert result2.success is True
        # 이름이 달라야 함
        assert result1.dst != result2.dst

    def test_preserves_original_on_copy_failure(self, tmp_path: Path):
        """복사 실패 시 원본 보존."""
        src = tmp_path / "source.jpg"
        src.write_bytes(b"content")

        # 존재하지 않는 경로 (권한 없음 시뮬레이션)
        dst_dir = Path("/nonexistent/path")

        result = safe_move(src, dst_dir)

        assert result.success is False
        assert result.operation == "copy"
        assert result.errno_code is not None
        assert src.exists()  # 원본 보존

    def test_fsync_warning_logged(self, tmp_path: Path, caplog):
        """fsync 실패 시 경고 로그."""
        src = tmp_path / "source.jpg"
        src.write_bytes(b"content")
        dst_dir = tmp_path / "archive"

        # fsync 실패 시뮬레이션
        with patch("os.fsync", side_effect=OSError("mock fsync error")):
            with caplog.at_level(logging.WARNING):
                result = safe_move(src, dst_dir)

        assert result.success is True
        assert result.fsync_warning is True
        assert "fsync" in caplog.text.lower()

    def test_error_context_preserved(self, tmp_path: Path):
        """실패 시 원인 정보 보존."""
        src = tmp_path / "source.jpg"
        src.write_bytes(b"content")

        dst_dir = Path("/nonexistent/path")

        result = safe_move(src, dst_dir)

        assert result.success is False
        assert result.operation is not None
        assert result.errno_code is not None
        assert result.error_message is not None


# =============================================================================
# load_photo_slots 테스트
# =============================================================================

class TestLoadPhotoSlots:
    """load_photo_slots 함수 테스트."""

    def test_loads_all_slots(self, sample_photo_definition: Path):
        """모든 슬롯 로드."""
        slots = load_photo_slots(sample_photo_definition)

        assert len(slots) == 3
        assert slots[0].key == "overview"
        assert slots[1].key == "label_serial"
        assert slots[2].key == "detail"

    def test_slot_properties(self, sample_photo_definition: Path):
        """슬롯 속성 확인."""
        slots = load_photo_slots(sample_photo_definition)

        overview = slots[0]
        assert overview.key == "overview"
        assert overview.basename == "01_overview"
        assert overview.required is True
        assert overview.override_allowed is False

        detail = slots[2]
        assert detail.required is False
        assert detail.override_allowed is True


# =============================================================================
# get_allowed_extensions / get_prefer_order 테스트
# =============================================================================

class TestPhotoConfig:
    """사진 설정 함수 테스트."""

    def test_allowed_extensions(self, sample_photo_definition: Path):
        """허용 확장자 로드."""
        extensions = get_allowed_extensions(sample_photo_definition)

        assert ".jpg" in extensions
        assert ".png" in extensions

    def test_prefer_order(self, sample_photo_definition: Path):
        """우선순위 로드."""
        order = get_prefer_order(sample_photo_definition)

        assert order == [".jpg", ".jpeg", ".png"]


# =============================================================================
# select_photo_for_slot 테스트
# =============================================================================

class TestSelectPhotoForSlot:
    """select_photo_for_slot 함수 테스트."""

    def test_selects_matching_file(
        self, raw_photo_dir: Path, sample_photo_definition: Path
    ):
        """매칭 파일 선택."""
        # 01_overview.jpg 생성
        (raw_photo_dir / "01_overview.jpg").write_bytes(b"photo")

        slot = PhotoSlot(
            key="overview",
            basename="01_overview",
            required=True,
            override_allowed=False,
        )

        selected, warning = select_photo_for_slot(
            slot, raw_photo_dir, sample_photo_definition
        )

        assert selected is not None
        assert selected.name == "01_overview.jpg"
        assert warning is None

    def test_no_file_optional_slot(
        self, raw_photo_dir: Path, sample_photo_definition: Path
    ):
        """optional 슬롯: 파일 없어도 OK."""
        slot = PhotoSlot(
            key="detail",
            basename="03_detail",
            required=False,
            override_allowed=True,
        )

        selected, warning = select_photo_for_slot(
            slot, raw_photo_dir, sample_photo_definition
        )

        assert selected is None
        assert warning is None

    def test_no_file_required_with_override(
        self, raw_photo_dir: Path, sample_photo_definition: Path
    ):
        """required + override_allowed: 파일 없어도 OK (override 가능)."""
        slot = PhotoSlot(
            key="label_serial",
            basename="02_label_serial",
            required=True,
            override_allowed=True,
        )

        selected, warning = select_photo_for_slot(
            slot, raw_photo_dir, sample_photo_definition
        )

        assert selected is None  # 파일 없지만 에러 아님

    def test_no_file_required_no_override_raises(
        self, raw_photo_dir: Path, sample_photo_definition: Path
    ):
        """required + no override: 파일 없으면 reject."""
        slot = PhotoSlot(
            key="overview",
            basename="01_overview",
            required=True,
            override_allowed=False,
        )

        with pytest.raises(PolicyRejectError) as exc_info:
            select_photo_for_slot(slot, raw_photo_dir, sample_photo_definition)

        assert exc_info.value.code == ErrorCodes.PHOTO_REQUIRED_MISSING
        assert exc_info.value.context["slot"] == "overview"

    def test_prefer_order_selection(
        self, raw_photo_dir: Path, sample_photo_definition: Path
    ):
        """중복 파일 시 prefer_order로 선택."""
        # jpg, png 둘 다 존재
        (raw_photo_dir / "01_overview.jpg").write_bytes(b"jpg")
        (raw_photo_dir / "01_overview.png").write_bytes(b"png")

        slot = PhotoSlot(
            key="overview",
            basename="01_overview",
            required=True,
            override_allowed=False,
        )

        selected, warning = select_photo_for_slot(
            slot, raw_photo_dir, sample_photo_definition
        )

        # jpg 우선 (.jpg가 prefer_order 첫번째)
        assert selected.suffix == ".jpg"
        assert warning is not None
        assert "Multiple files" in warning

    def test_warning_on_duplicate(
        self, raw_photo_dir: Path, sample_photo_definition: Path
    ):
        """중복 파일 시 경고 메시지."""
        (raw_photo_dir / "01_overview.jpg").write_bytes(b"jpg")
        (raw_photo_dir / "01_overview.png").write_bytes(b"png")

        slot = PhotoSlot(
            key="overview",
            basename="01_overview",
            required=True,
            override_allowed=False,
        )

        selected, warning = select_photo_for_slot(
            slot, raw_photo_dir, sample_photo_definition
        )

        assert warning is not None
        assert "01_overview" in warning


# =============================================================================
# archive_old_derived 테스트
# =============================================================================

class TestArchiveOldDerived:
    """archive_old_derived 함수 테스트."""

    def test_moves_files_to_trash(self, derived_photo_dir: Path, tmp_path: Path):
        """기존 파일을 _trash로 이동."""
        # derived에 파일 생성
        (derived_photo_dir / "old_photo.jpg").write_bytes(b"old")
        trash_dir = derived_photo_dir / "_trash"

        results = archive_old_derived(derived_photo_dir, trash_dir)

        assert len(results) == 1
        assert results[0].success is True
        assert trash_dir.exists()
        assert not (derived_photo_dir / "old_photo.jpg").exists()

    def test_skips_trash_folder(self, derived_photo_dir: Path, tmp_path: Path):
        """_trash 폴더 자체는 건너뜀."""
        trash_dir = derived_photo_dir / "_trash"
        trash_dir.mkdir()
        (trash_dir / "old_archived.jpg").write_bytes(b"old archived")

        results = archive_old_derived(derived_photo_dir, trash_dir)

        # _trash는 이동 대상 아님
        assert len(results) == 0

    def test_empty_derived_returns_empty_list(self, tmp_path: Path):
        """derived가 비어있으면 빈 리스트."""
        derived_dir = tmp_path / "empty_derived"
        derived_dir.mkdir()
        trash_dir = derived_dir / "_trash"

        results = archive_old_derived(derived_dir, trash_dir)

        assert results == []

    def test_nonexistent_derived_returns_empty_list(self, tmp_path: Path):
        """derived가 없으면 빈 리스트."""
        derived_dir = tmp_path / "nonexistent"
        trash_dir = tmp_path / "_trash"

        results = archive_old_derived(derived_dir, trash_dir)

        assert results == []


# =============================================================================
# copy_to_derived 테스트
# =============================================================================

class TestCopyToDerived:
    """copy_to_derived 함수 테스트."""

    def test_copies_with_slot_key_name(
        self, raw_photo_dir: Path, derived_photo_dir: Path
    ):
        """슬롯 키 이름으로 복사."""
        src = raw_photo_dir / "01_overview.jpg"
        src.write_bytes(b"photo content")

        slot = PhotoSlot(
            key="overview",
            basename="01_overview",
            required=True,
            override_allowed=False,
        )

        dst = copy_to_derived(src, derived_photo_dir, slot)

        assert dst.exists()
        assert dst.name == "overview.jpg"  # 슬롯 키 이름으로
        assert dst.read_bytes() == b"photo content"

    def test_creates_derived_directory(self, raw_photo_dir: Path, tmp_path: Path):
        """derived 디렉터리 자동 생성."""
        src = raw_photo_dir / "01_overview.jpg"
        src.write_bytes(b"content")
        derived_dir = tmp_path / "new_derived"  # 존재하지 않음

        slot = PhotoSlot(
            key="overview",
            basename="01_overview",
            required=True,
            override_allowed=False,
        )

        dst = copy_to_derived(src, derived_dir, slot)

        assert derived_dir.exists()
        assert dst.exists()
