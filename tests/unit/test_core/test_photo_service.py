"""
test_photo_service.py - PhotoService 통합 테스트

DoD:
- TC1: 정상 매핑 (upload → slot 매핑 → derived 생성)
- TC2: derived 교체 + 아카이브
- TC3: 필수 슬롯 누락 - fail-fast
- TC4: 필수 슬롯 누락 - override 허용
- TC5: 중복 사진 prefer_order 선택
- TC6: run log에 photo_processing 기록
"""

from pathlib import Path

import pytest

from src.core.photos import PhotoService
from src.domain.schemas import PhotoProcessingLog, SlotMatchConfidence


@pytest.fixture
def job_dir(tmp_path: Path) -> Path:
    """임시 job 디렉터리."""
    job = tmp_path / "JOB-TEST"
    job.mkdir()
    return job


@pytest.fixture
def definition_path(tmp_path: Path) -> Path:
    """테스트용 definition.yaml."""
    definition = tmp_path / "definition.yaml"
    definition.write_text("""
photos:
  allowed_extensions:
    - ".jpg"
    - ".jpeg"
    - ".png"
  prefer_order:
    - ".jpg"
    - ".jpeg"
    - ".png"
  slots:
    - key: overview
      basename: "01_overview"
      required: true
      override_allowed: false
      description: "제품 전체 사진"
    - key: label_serial
      basename: "02_label_serial"
      required: true
      override_allowed: false
      description: "라벨/시리얼 사진"
      verify_keywords:
        - "S/N"
        - "Serial"
        - "Model"
    - key: measurement_setup
      basename: "03_measurement_setup"
      required: true
      override_allowed: true
      override_requires_reason: true
      description: "측정 장비 사진"
    - key: defect
      basename: "04_defect"
      required: false
      override_allowed: true
      override_requires_reason: false
      description: "결함 사진 (선택)"
""")
    return definition


# =============================================================================
# TC1: 정상 매핑
# =============================================================================


class TestPhotoUploadMapsToSlot:
    """TC1: 이미지 업로드 → slot 자동 매핑 → derived 생성."""

    def test_upload_saves_to_raw(self, job_dir: Path, definition_path: Path):
        """업로드 시 raw/에 저장됨."""
        service = PhotoService(job_dir, definition_path)

        file_bytes = b"fake image data"
        saved = service.save_upload("01_overview.jpg", file_bytes)

        assert saved.exists()
        assert saved.parent.name == "raw"
        assert saved.read_bytes() == file_bytes

    def test_match_slot_for_file(self, job_dir: Path, definition_path: Path):
        """파일명에서 슬롯 매칭."""
        service = PhotoService(job_dir, definition_path)

        slot = service.match_slot_for_file("01_overview.jpg")
        assert slot is not None
        assert slot.key == "overview"

        slot = service.match_slot_for_file("02_label_serial.png")
        assert slot is not None
        assert slot.key == "label_serial"

    def test_no_match_for_unknown_file(self, job_dir: Path, definition_path: Path):
        """알 수 없는 파일명은 None 반환."""
        service = PhotoService(job_dir, definition_path)

        slot = service.match_slot_for_file("unknown_photo.jpg")
        assert slot is None

    def test_validate_creates_derived(self, job_dir: Path, definition_path: Path):
        """validate_and_process 후 derived/ 생성됨."""
        service = PhotoService(job_dir, definition_path)

        # 필수 사진 모두 저장
        service.save_upload("01_overview.jpg", b"overview data")
        service.save_upload("02_label_serial.jpg", b"label data")
        service.save_upload("03_measurement_setup.jpg", b"setup data")

        result = service.validate_and_process()

        assert result.valid
        assert "overview" in result.mapped_slots
        assert "label_serial" in result.mapped_slots

        # derived 파일 존재 확인
        derived_dir = job_dir / "photos" / "derived"
        assert (derived_dir / "overview.jpg").exists()
        assert (derived_dir / "label_serial.jpg").exists()


# =============================================================================
# TC2: derived 교체 + 아카이브
# =============================================================================


class TestPhotoReplacesExistingDerived:
    """TC2: 기존 derived 있는 상태에서 새 사진 업로드."""

    def test_existing_derived_archived(self, job_dir: Path, definition_path: Path):
        """기존 derived → _trash/ 이동."""
        service = PhotoService(job_dir, definition_path)

        # 초기 사진 설정
        raw_dir = job_dir / "photos" / "raw"
        raw_dir.mkdir(parents=True)
        (raw_dir / "01_overview.jpg").write_bytes(b"original")
        (raw_dir / "02_label_serial.jpg").write_bytes(b"label")

        derived_dir = job_dir / "photos" / "derived"
        derived_dir.mkdir(parents=True)
        (derived_dir / "overview.jpg").write_bytes(b"old derived")

        # 첫 번째 처리 (overview 교체 발생)
        result = service.validate_and_process(run_id="RUN-001")

        # _trash에 이전 파일 있어야 함
        trash_dir = job_dir / "photos" / "_trash"
        assert trash_dir.exists()

        # archive된 로그 확인
        archived_logs = [log for log in result.processing_logs if log.archived_path]
        assert len(archived_logs) >= 1
        assert archived_logs[0].slot_id == "overview"

    def test_new_derived_created(self, job_dir: Path, definition_path: Path):
        """새 파일 → derived/ 생성."""
        service = PhotoService(job_dir, definition_path)

        # 필수 사진 저장
        service.save_upload("01_overview.jpg", b"new photo")
        service.save_upload("02_label_serial.jpg", b"label")

        service.validate_and_process()

        # derived에 새 파일 존재
        derived = job_dir / "photos" / "derived" / "overview.jpg"
        assert derived.exists()
        assert derived.read_bytes() == b"new photo"


# =============================================================================
# TC3: 필수 슬롯 누락 - fail-fast
# =============================================================================


class TestMissingRequiredPhotoRejects:
    """TC3: required=true, override_allowed=false 슬롯 누락."""

    def test_missing_required_not_overridable_fails(
        self, job_dir: Path, definition_path: Path
    ):
        """필수 + override 불가 → 즉시 실패."""
        service = PhotoService(job_dir, definition_path)

        # overview와 label_serial 누락
        result = service.validate_and_process()

        assert not result.valid
        assert "overview" in result.missing_required
        assert "label_serial" in result.missing_required

    def test_processing_log_contains_missing_action(
        self, job_dir: Path, definition_path: Path
    ):
        """누락 시 action='missing' 로그."""
        service = PhotoService(job_dir, definition_path)

        result = service.validate_and_process()

        missing_logs = [
            log for log in result.processing_logs if log.action == "missing"
        ]
        assert len(missing_logs) >= 2  # overview, label_serial


# =============================================================================
# TC4: 필수 슬롯 누락 - override 허용
# =============================================================================


class TestMissingPhotoWithValidOverride:
    """TC4: required=true, override_allowed=true 슬롯 누락 + 유효한 override."""

    def test_override_allows_missing_required(
        self, job_dir: Path, definition_path: Path
    ):
        """override 제공 시 통과."""
        service = PhotoService(job_dir, definition_path)

        # 필수 사진 중 override 불가 슬롯만 저장
        service.save_upload("01_overview.jpg", b"overview")
        service.save_upload("02_label_serial.jpg", b"label")
        # measurement_setup은 누락, override로 처리

        result = service.validate_and_process(
            overrides={
                "measurement_setup": "DEVICE_FAILURE: 측정 장비 고장으로 촬영 불가능 상태입니다"
            }
        )

        assert result.valid

    def test_override_logged_in_processing(self, job_dir: Path, definition_path: Path):
        """override 시 action='override' 로그."""
        service = PhotoService(job_dir, definition_path)

        service.save_upload("01_overview.jpg", b"overview")
        service.save_upload("02_label_serial.jpg", b"label")

        result = service.validate_and_process(
            overrides={
                "measurement_setup": "MISSING_PHOTO: 현장 사정으로 사진 촬영 불가"
            }
        )

        override_logs = [
            log for log in result.processing_logs if log.action == "override"
        ]
        assert len(override_logs) == 1
        assert override_logs[0].slot_id == "measurement_setup"
        assert override_logs[0].override_reason is not None

    def test_missing_override_reason_marks_overridable(
        self, job_dir: Path, definition_path: Path
    ):
        """override 가능하지만 사유 없으면 overridable 목록에 추가."""
        service = PhotoService(job_dir, definition_path)

        service.save_upload("01_overview.jpg", b"overview")
        service.save_upload("02_label_serial.jpg", b"label")
        # measurement_setup 누락, override 미제공

        result = service.validate_and_process()

        assert not result.valid
        assert "measurement_setup" in result.overridable


# =============================================================================
# TC5: 중복 사진 처리
# =============================================================================


class TestDuplicatePhotosSelectsByPreferOrder:
    """TC5: 동일 슬롯에 여러 사진 매칭 시 prefer_order 기준 선택."""

    def test_selects_jpg_over_png(self, job_dir: Path, definition_path: Path):
        """prefer_order: jpg > jpeg > png."""
        service = PhotoService(job_dir, definition_path)

        # 같은 슬롯에 여러 확장자
        service.save_upload("01_overview.jpg", b"jpg version")
        service.save_upload("01_overview.png", b"png version")
        service.save_upload("02_label_serial.jpg", b"label")

        service.validate_and_process()

        # jpg가 선택되어야 함
        derived = job_dir / "photos" / "derived" / "overview.jpg"
        assert derived.exists()
        assert derived.read_bytes() == b"jpg version"

    def test_warning_logged_for_duplicate(self, job_dir: Path, definition_path: Path):
        """중복 시 warning 기록."""
        service = PhotoService(job_dir, definition_path)

        service.save_upload("01_overview.jpg", b"jpg version")
        service.save_upload("01_overview.png", b"png version")
        service.save_upload("02_label_serial.jpg", b"label")

        result = service.validate_and_process()

        assert len(result.warnings) > 0
        assert "Multiple files" in result.warnings[0]


# =============================================================================
# TC6: run log에 photo_processing 기록
# =============================================================================


class TestRunLogIncludesPhotoProcessing:
    """TC6: generate 완료 후 run log에 photo_processing 배열."""

    def test_processing_logs_returned(self, job_dir: Path, definition_path: Path):
        """processing_logs 배열 반환."""
        service = PhotoService(job_dir, definition_path)

        service.save_upload("01_overview.jpg", b"overview")
        service.save_upload("02_label_serial.jpg", b"label")

        result = service.validate_and_process()

        assert len(result.processing_logs) > 0

        # 각 로그 항목 구조 확인
        for log in result.processing_logs:
            assert log.slot_id is not None
            assert log.action is not None
            assert log.timestamp is not None

    def test_processing_log_contains_paths(self, job_dir: Path, definition_path: Path):
        """로그에 raw_path, derived_path 포함."""
        service = PhotoService(job_dir, definition_path)

        service.save_upload("01_overview.jpg", b"overview")
        service.save_upload("02_label_serial.jpg", b"label")

        result = service.validate_and_process()

        mapped_logs = [log for log in result.processing_logs if log.action == "mapped"]
        assert len(mapped_logs) >= 2

        for log in mapped_logs:
            assert log.raw_path is not None
            assert log.derived_path is not None

    def test_photo_processing_log_to_dict(self):
        """PhotoProcessingLog.to_dict() 동작."""
        log = PhotoProcessingLog(
            slot_id="overview",
            action="mapped",
            raw_path="/photos/raw/01_overview.jpg",
            derived_path="/photos/derived/overview.jpg",
            timestamp="2024-01-15T09:30:00",
        )

        d = log.to_dict()

        assert d["slot_id"] == "overview"
        assert d["action"] == "mapped"
        assert d["raw_path"] == "/photos/raw/01_overview.jpg"
        assert d["derived_path"] == "/photos/derived/overview.jpg"


# =============================================================================
# 추가 테스트: 슬롯 매핑 상태 조회
# =============================================================================


class TestGetSlotMappingStatus:
    """슬롯 매핑 상태 조회."""

    def test_returns_all_slots(self, job_dir: Path, definition_path: Path):
        """모든 슬롯 상태 반환."""
        service = PhotoService(job_dir, definition_path)

        status = service.get_slot_mapping_status()

        assert "overview" in status
        assert "label_serial" in status
        assert "measurement_setup" in status
        assert "defect" in status

    def test_shows_raw_and_derived_status(self, job_dir: Path, definition_path: Path):
        """raw/derived 존재 여부 표시."""
        service = PhotoService(job_dir, definition_path)

        # raw에만 저장
        service.save_upload("01_overview.jpg", b"overview")

        status = service.get_slot_mapping_status()

        assert status["overview"]["has_raw"] is True
        assert status["overview"]["has_derived"] is False

    def test_shows_required_and_override_allowed(
        self, job_dir: Path, definition_path: Path
    ):
        """required, override_allowed 정보 포함."""
        service = PhotoService(job_dir, definition_path)

        status = service.get_slot_mapping_status()

        # overview: required=true, override_allowed=false
        assert status["overview"]["required"] is True
        assert status["overview"]["override_allowed"] is False

        # defect: required=false, override_allowed=true
        assert status["defect"]["required"] is False
        assert status["defect"]["override_allowed"] is True


# =============================================================================
# TC7: 슬롯 매칭 Confidence 테스트
# =============================================================================


class TestSlotMatchingConfidence:
    """슬롯 매칭 신뢰도 테스트."""

    def test_exact_basename_match_is_high(self, job_dir: Path, definition_path: Path):
        """정확한 basename 매칭 → HIGH confidence."""
        service = PhotoService(job_dir, definition_path)

        result = service.match_slot_for_file_with_confidence("01_overview.jpg")

        assert result.slot is not None
        assert result.slot.key == "overview"
        assert result.confidence == SlotMatchConfidence.HIGH
        assert result.matched_by == "basename_exact"
        assert result.is_reliable is True

    def test_basename_prefix_match_is_medium(
        self, job_dir: Path, definition_path: Path
    ):
        """basename prefix 매칭 → MEDIUM confidence."""
        service = PhotoService(job_dir, definition_path)

        # 01_overview_v2.jpg → 01_overview로 시작
        result = service.match_slot_for_file_with_confidence("01_overview_v2.jpg")

        assert result.slot is not None
        assert result.slot.key == "overview"
        assert result.confidence == SlotMatchConfidence.MEDIUM
        assert result.matched_by == "basename_prefix"
        assert result.is_reliable is True

    def test_key_prefix_match_is_low(self, job_dir: Path, definition_path: Path):
        """key prefix만 매칭 → LOW confidence (사용자 확인 필요)."""
        service = PhotoService(job_dir, definition_path)

        # overview_photo.jpg → overview key로 시작
        result = service.match_slot_for_file_with_confidence("overview_photo.jpg")

        assert result.slot is not None
        assert result.slot.key == "overview"
        assert result.confidence == SlotMatchConfidence.LOW
        assert result.matched_by == "key_prefix"
        assert result.needs_user_confirmation is True

    def test_no_match_returns_low_with_warning(
        self, job_dir: Path, definition_path: Path
    ):
        """매칭 없음 → LOW + 경고."""
        service = PhotoService(job_dir, definition_path)

        result = service.match_slot_for_file_with_confidence("random_photo.jpg")

        assert result.slot is None
        assert result.confidence == SlotMatchConfidence.LOW
        assert result.warning is not None
        assert "매칭되는 슬롯 없음" in result.warning

    def test_critical_slot_low_match_has_warning(
        self, job_dir: Path, definition_path: Path
    ):
        """핵심 슬롯이 LOW로 매칭되면 경고 발생."""
        service = PhotoService(job_dir, definition_path)

        # overview_xxx.jpg → overview key로 시작 (LOW)
        result = service.match_slot_for_file_with_confidence("overview_xxx.jpg")

        assert result.slot.key == "overview"
        assert result.confidence == SlotMatchConfidence.LOW
        assert result.warning is not None
        assert "핵심 슬롯" in result.warning

    def test_ocr_verification_upgrades_confidence(
        self, job_dir: Path, definition_path: Path
    ):
        """OCR 키워드 발견 시 신뢰도 상승."""
        service = PhotoService(job_dir, definition_path)

        # MEDIUM 매칭 + OCR 검증 → HIGH
        result = service.match_slot_for_file_with_confidence(
            "02_label_serial_v1.jpg",
            ocr_text="Model: XYZ-123\nS/N: ABC456789",
        )

        assert result.slot.key == "label_serial"
        assert result.confidence == SlotMatchConfidence.HIGH
        assert result.ocr_verified is True

    def test_backward_compatible_match_slot(self, job_dir: Path, definition_path: Path):
        """기존 match_slot_for_file는 reliable한 경우만 반환."""
        service = PhotoService(job_dir, definition_path)

        # HIGH/MEDIUM → 슬롯 반환
        slot = service.match_slot_for_file("01_overview.jpg")
        assert slot is not None
        assert slot.key == "overview"

        # LOW → None 반환
        slot = service.match_slot_for_file("overview_xxx.jpg")
        assert slot is None

    def test_invalid_extension_returns_low(self, job_dir: Path, definition_path: Path):
        """허용되지 않은 확장자 → LOW + 경고."""
        service = PhotoService(job_dir, definition_path)

        result = service.match_slot_for_file_with_confidence("01_overview.gif")

        assert result.slot is None
        assert result.confidence == SlotMatchConfidence.LOW
        assert "허용되지 않은 확장자" in result.warning
