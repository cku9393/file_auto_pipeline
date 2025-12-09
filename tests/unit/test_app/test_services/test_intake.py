"""
test_intake.py - Intake 서비스 테스트

ADR-0003 불변성 규칙 검증:
- messages 원문은 절대 수정 금지
- 후처리 결과는 append 이벤트로만 추가
- 원문 덮어쓰기 시도 시 에러
- model_used 필수
"""

import json
from pathlib import Path

import pytest

from src.app.providers.base import ExtractionResult, OCRResult
from src.app.services.intake import IntakeService
from src.domain.errors import ErrorCodes, PolicyRejectError

# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def job_dir(tmp_path: Path) -> Path:
    """테스트용 job 디렉터리."""
    job_path = tmp_path / "jobs" / "test_job"
    job_path.mkdir(parents=True)
    return job_path


@pytest.fixture
def intake_service(job_dir: Path) -> IntakeService:
    """IntakeService 인스턴스."""
    return IntakeService(job_dir)


@pytest.fixture
def session_with_messages(intake_service: IntakeService):
    """메시지가 있는 세션."""
    intake_service.create_session()
    intake_service.add_message("user", "WO-001, L1, PASS")
    intake_service.add_message("assistant", "작업번호: WO-001로 확인했습니다.")
    return intake_service


# =============================================================================
# 세션 생성/로드 테스트
# =============================================================================

class TestSessionCreation:
    """세션 생성 테스트."""

    def test_create_session(self, intake_service: IntakeService):
        """세션 생성."""
        session = intake_service.create_session()

        assert session.schema_version == "1.0"
        assert session.session_id is not None
        assert session.created_at is not None
        assert session.immutable is True

    def test_creates_directory_structure(self, intake_service: IntakeService, job_dir: Path):
        """디렉터리 구조 생성."""
        intake_service.create_session()

        assert (job_dir / "inputs").exists()
        assert (job_dir / "inputs" / "uploads").exists()
        assert (job_dir / "inputs" / "intake_session.json").exists()

    def test_load_existing_session(self, intake_service: IntakeService):
        """기존 세션 로드."""
        original = intake_service.create_session()

        loaded = intake_service.load_session()

        assert loaded.session_id == original.session_id
        assert loaded.schema_version == original.schema_version

    def test_load_creates_if_not_exists(self, intake_service: IntakeService):
        """세션 없으면 생성."""
        session = intake_service.load_session()

        assert session.session_id is not None

    def test_corrupt_session_raises_error(self, intake_service: IntakeService):
        """손상된 세션 → 에러."""
        # 손상된 JSON 생성
        intake_service.inputs_dir.mkdir(parents=True, exist_ok=True)
        intake_service.session_path.write_text("not valid json", encoding="utf-8")

        with pytest.raises(PolicyRejectError) as exc_info:
            intake_service.load_session()

        assert exc_info.value.code == ErrorCodes.INTAKE_SESSION_CORRUPT

    def test_missing_schema_version_raises_error(self, intake_service: IntakeService):
        """schema_version 누락 → 에러."""
        intake_service.inputs_dir.mkdir(parents=True, exist_ok=True)
        intake_service.session_path.write_text(
            '{"session_id": "test"}',
            encoding="utf-8",
        )

        with pytest.raises(PolicyRejectError) as exc_info:
            intake_service.load_session()

        assert exc_info.value.code == ErrorCodes.INTAKE_SESSION_CORRUPT
        assert "schema_version" in str(exc_info.value)


# =============================================================================
# 메시지 추가 테스트 (Append-Only)
# =============================================================================

class TestAddMessage:
    """메시지 추가 테스트."""

    def test_add_user_message(self, intake_service: IntakeService):
        """사용자 메시지 추가."""
        intake_service.create_session()

        message = intake_service.add_message("user", "WO-001, L1")

        assert message.role == "user"
        assert message.content == "WO-001, L1"
        assert message.timestamp is not None

    def test_add_assistant_message(self, intake_service: IntakeService):
        """어시스턴트 메시지 추가."""
        intake_service.create_session()

        message = intake_service.add_message("assistant", "확인했습니다.")

        assert message.role == "assistant"

    def test_messages_are_appended(self, intake_service: IntakeService):
        """메시지는 append만 가능."""
        intake_service.create_session()
        intake_service.add_message("user", "Message 1")
        intake_service.add_message("user", "Message 2")

        session = intake_service.load_session()

        assert len(session.messages) == 2
        assert session.messages[0].content == "Message 1"
        assert session.messages[1].content == "Message 2"

    def test_message_with_attachment(
        self,
        intake_service: IntakeService,
        job_dir: Path,
    ):
        """첨부 파일 포함 메시지."""
        intake_service.create_session()

        message = intake_service.add_message(
            "user",
            "사진 첨부합니다",
            attachments=[("photo.jpg", b"fake image data")],
        )

        assert len(message.attachments) == 1
        assert message.attachments[0].filename == "photo.jpg"
        assert message.attachments[0].size == len(b"fake image data")

        # 파일 실제 저장 확인
        upload_path = job_dir / message.attachments[0].path
        assert upload_path.exists()

    def test_attachment_filename_collision(self, intake_service: IntakeService):
        """첨부 파일명 충돌 해결."""
        intake_service.create_session()

        intake_service.add_message(
            "user", "First",
            attachments=[("file.jpg", b"data1")],
        )
        message = intake_service.add_message(
            "user", "Second",
            attachments=[("file.jpg", b"data2")],
        )

        # 두 번째 파일은 다른 이름으로 저장
        assert "file_1.jpg" in message.attachments[0].path


# =============================================================================
# OCR 결과 추가 테스트
# =============================================================================

class TestAddOCRResult:
    """OCR 결과 추가 테스트."""

    def test_add_ocr_result(self, intake_service: IntakeService):
        """OCR 결과 추가."""
        intake_service.create_session()

        ocr_result = OCRResult(
            success=True,
            text="WO-001\nLine: L1",
            confidence=0.95,
            model_requested="gemini-3-pro",
            model_used="gemini-3-pro",
        )

        intake_service.add_ocr_result("photo.jpg", ocr_result)

        session = intake_service.load_session()
        assert "photo.jpg" in session.ocr_results
        assert session.ocr_results["photo.jpg"].text == "WO-001\nLine: L1"

    def test_model_used_required(self, intake_service: IntakeService):
        """ADR-0003: model_used 필수."""
        intake_service.create_session()

        ocr_result = OCRResult(
            success=True,
            text="Some text",
            model_requested="gemini-3-pro",
            model_used=None,  # 필수인데 None
        )

        with pytest.raises(PolicyRejectError) as exc_info:
            intake_service.add_ocr_result("photo.jpg", ocr_result)

        assert "model_used" in str(exc_info.value)

    def test_ocr_result_with_fallback(self, intake_service: IntakeService):
        """Fallback 발생 시 기록."""
        intake_service.create_session()

        ocr_result = OCRResult(
            success=True,
            text="Fallback text",
            model_requested="gemini-3-pro",
            model_used="gemini-2.5-flash",
            fallback_triggered=True,
        )

        intake_service.add_ocr_result("photo.jpg", ocr_result)

        session = intake_service.load_session()
        assert session.ocr_results["photo.jpg"].fallback_triggered is True
        assert session.ocr_results["photo.jpg"].model_used == "gemini-2.5-flash"


# =============================================================================
# Extraction 결과 추가 테스트 (불변성)
# =============================================================================

class TestAddExtractionResult:
    """Extraction 결과 추가 테스트."""

    def test_add_extraction_result(self, intake_service: IntakeService):
        """Extraction 결과 추가."""
        intake_service.create_session()

        result = ExtractionResult(
            success=True,
            fields={"wo_no": "WO-001", "line": "L1"},
            model_requested="claude-opus-4-5-20251101",
            model_used="claude-opus-4-5-20251101",
        )

        intake_service.add_extraction_result(result)

        session = intake_service.load_session()
        assert session.extraction_result is not None
        assert session.extraction_result.fields["wo_no"] == "WO-001"

    def test_model_used_required(self, intake_service: IntakeService):
        """ADR-0003: model_used 필수."""
        intake_service.create_session()

        result = ExtractionResult(
            success=True,
            fields={"wo_no": "WO-001"},
            model_used=None,  # 필수인데 None
        )

        with pytest.raises(PolicyRejectError) as exc_info:
            intake_service.add_extraction_result(result)

        assert "model_used" in str(exc_info.value)

    def test_overwrite_raises_error(self, intake_service: IntakeService):
        """ADR-0003: extraction_result 덮어쓰기 → 에러."""
        intake_service.create_session()

        result1 = ExtractionResult(
            success=True,
            fields={"wo_no": "WO-001"},
            model_used="claude-opus-4-5-20251101",
        )
        intake_service.add_extraction_result(result1)

        result2 = ExtractionResult(
            success=True,
            fields={"wo_no": "WO-002"},  # 다른 값으로 덮어쓰기 시도
            model_used="claude-opus-4-5-20251101",
        )

        with pytest.raises(PolicyRejectError) as exc_info:
            intake_service.add_extraction_result(result2)

        assert exc_info.value.code == ErrorCodes.INTAKE_IMMUTABLE_VIOLATION
        assert "overwrite" in str(exc_info.value).lower()


# =============================================================================
# 사용자 수정 테스트
# =============================================================================

class TestAddUserCorrection:
    """사용자 수정 기록 테스트."""

    def test_add_correction(self, intake_service: IntakeService):
        """수정 기록 추가."""
        intake_service.create_session()

        intake_service.add_user_correction(
            field="wo_no",
            original="WO-001",
            corrected="WO-001A",
            user="operator1",
        )

        session = intake_service.load_session()
        assert len(session.user_corrections) == 1
        assert session.user_corrections[0].field == "wo_no"
        assert session.user_corrections[0].original == "WO-001"
        assert session.user_corrections[0].corrected == "WO-001A"
        assert session.user_corrections[0].corrected_by == "operator1"

    def test_multiple_corrections(self, intake_service: IntakeService):
        """여러 수정 기록 (append)."""
        intake_service.create_session()

        intake_service.add_user_correction("wo_no", "WO-001", "WO-001A")
        intake_service.add_user_correction("line", "L1", "L2")

        session = intake_service.load_session()
        assert len(session.user_corrections) == 2

    def test_same_field_multiple_corrections(self, intake_service: IntakeService):
        """같은 필드 여러 번 수정 (히스토리 유지)."""
        intake_service.create_session()

        intake_service.add_user_correction("wo_no", "WO-001", "WO-001A")
        intake_service.add_user_correction("wo_no", "WO-001A", "WO-001B")

        session = intake_service.load_session()
        assert len(session.user_corrections) == 2
        # 마지막 수정이 최신
        assert session.user_corrections[-1].corrected == "WO-001B"


# =============================================================================
# 최종 필드 계산 테스트
# =============================================================================

class TestGetFinalFields:
    """get_final_fields 테스트."""

    def test_returns_empty_if_no_extraction(self, intake_service: IntakeService):
        """추출 결과 없으면 빈 dict."""
        intake_service.create_session()

        fields = intake_service.get_final_fields()

        assert fields == {}

    def test_returns_extraction_fields(self, intake_service: IntakeService):
        """추출 결과 반환."""
        intake_service.create_session()
        intake_service.add_extraction_result(ExtractionResult(
            success=True,
            fields={"wo_no": "WO-001", "line": "L1"},
            model_used="claude-opus-4-5-20251101",
        ))

        fields = intake_service.get_final_fields()

        assert fields["wo_no"] == "WO-001"
        assert fields["line"] == "L1"

    def test_applies_user_corrections(self, intake_service: IntakeService):
        """사용자 수정 적용."""
        intake_service.create_session()
        intake_service.add_extraction_result(ExtractionResult(
            success=True,
            fields={"wo_no": "WO-001", "line": "L1"},
            model_used="claude-opus-4-5-20251101",
        ))
        intake_service.add_user_correction("wo_no", "WO-001", "WO-001A")

        fields = intake_service.get_final_fields()

        assert fields["wo_no"] == "WO-001A"  # 수정됨
        assert fields["line"] == "L1"  # 원본 유지

    def test_latest_correction_wins(self, intake_service: IntakeService):
        """최신 수정이 적용됨."""
        intake_service.create_session()
        intake_service.add_extraction_result(ExtractionResult(
            success=True,
            fields={"wo_no": "WO-001"},
            model_used="claude-opus-4-5-20251101",
        ))
        intake_service.add_user_correction("wo_no", "WO-001", "WO-001A")
        intake_service.add_user_correction("wo_no", "WO-001A", "WO-001B")

        fields = intake_service.get_final_fields()

        assert fields["wo_no"] == "WO-001B"


# =============================================================================
# 직렬화/역직렬화 테스트
# =============================================================================

class TestSerialization:
    """세션 직렬화 테스트."""

    def test_session_persisted_as_json(self, intake_service: IntakeService):
        """세션이 JSON으로 저장됨."""
        intake_service.create_session()
        intake_service.add_message("user", "Hello")

        # 파일 직접 읽기
        data = json.loads(intake_service.session_path.read_text(encoding="utf-8"))

        assert data["schema_version"] == "1.0"
        assert len(data["messages"]) == 1
        assert data["messages"][0]["content"] == "Hello"

    def test_full_roundtrip(self, intake_service: IntakeService):
        """전체 라운드트립 테스트."""
        intake_service.create_session()
        intake_service.add_message("user", "입력", attachments=[("f.txt", b"data")])
        intake_service.add_ocr_result("img.jpg", OCRResult(
            success=True, text="OCR text", model_used="gemini"
        ))
        intake_service.add_extraction_result(ExtractionResult(
            success=True,
            fields={"wo_no": "WO-001"},
            model_used="claude",
        ))
        intake_service.add_user_correction("wo_no", "WO-001", "WO-002")

        # 새 서비스로 로드
        new_service = IntakeService(intake_service.job_dir)
        session = new_service.load_session()

        assert len(session.messages) == 1
        assert "img.jpg" in session.ocr_results
        assert session.extraction_result.fields["wo_no"] == "WO-001"
        assert len(session.user_corrections) == 1

    def test_immutable_flag_persisted(self, intake_service: IntakeService):
        """immutable 플래그 저장됨."""
        intake_service.create_session()

        data = json.loads(intake_service.session_path.read_text(encoding="utf-8"))

        assert data["immutable"] is True
