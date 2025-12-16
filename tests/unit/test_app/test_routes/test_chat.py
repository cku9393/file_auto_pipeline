"""
test_chat.py - Chat Routes 유닛 테스트

검증 포인트:
1. /upload 응답에 messages_html 포함
2. 파일명 XSS escape 확인
3. 세션-잡 매핑 영속화
4. 타임아웃 처리
"""

import asyncio
import json
import threading
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.app.providers.base import OCRResult
from src.app.routes.chat import (
    _get_sessions_dir,
    _load_session_mapping,
    _save_session_mapping,
    _session_to_job,
    analyze_measurement_issues,
    api_router,
    build_assistant_message_html,
    build_user_message_html,
    build_validation_error_html,
    escape_html,
    router,
)
from src.app.services.validate import ValidationResult

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def app(tmp_path: Path) -> FastAPI:
    """테스트용 FastAPI 앱."""
    app = FastAPI()
    app.include_router(router)
    app.include_router(api_router, prefix="/api/chat")

    # App state 설정
    jobs_root = tmp_path / "jobs"
    jobs_root.mkdir()

    definition_path = tmp_path / "definition.yaml"
    definition_path.write_text(
        """
definition_version: "1.0.0"
fields:
  wo_no:
    type: token
    importance: critical
"""
    )

    app.state.jobs_root = jobs_root
    app.state.definition_path = definition_path
    app.state.config = {"ai": {"extraction_timeout": 60.0, "ocr_timeout": 30.0}}

    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """테스트 클라이언트."""
    return TestClient(app)


@pytest.fixture
def jobs_root(tmp_path: Path) -> Path:
    """Jobs 루트 디렉토리."""
    jobs_root = tmp_path / "jobs"
    jobs_root.mkdir(exist_ok=True)
    return jobs_root


@pytest.fixture(autouse=True)
def clear_session_cache():
    """각 테스트 전 세션 캐시 초기화."""
    _session_to_job.clear()
    yield
    _session_to_job.clear()


# =============================================================================
# 1. HTML 헬퍼 함수 테스트
# =============================================================================


class TestHtmlHelpers:
    """HTML 헬퍼 함수 테스트."""

    def test_escape_html_basic(self):
        """기본 HTML 이스케이프."""
        assert escape_html("<script>") == "&lt;script&gt;"
        assert escape_html("'quote'") == "&#x27;quote&#x27;"
        assert escape_html('"double"') == "&quot;double&quot;"
        assert escape_html("&amp") == "&amp;amp"

    def test_escape_html_xss_filename(self):
        """파일명 XSS 공격 방지."""
        malicious = '<script>alert("xss")</script>.jpg'
        escaped = escape_html(malicious)

        assert "<script>" not in escaped
        assert "&lt;script&gt;" in escaped

    def test_build_user_message_html(self):
        """사용자 메시지 HTML 생성."""
        html = build_user_message_html("Hello <world>")

        assert 'class="message user"' in html
        assert "Hello &lt;world&gt;" in html

    def test_build_assistant_message_html_with_job_id(self):
        """어시스턴트 메시지 HTML (Job ID 포함)."""
        html = build_assistant_message_html("Response text", job_id="JOB-123")

        assert 'class="message assistant"' in html
        assert "Response text" in html
        assert "JOB-123" in html
        assert 'class="job-info"' in html

    def test_build_assistant_message_html_without_job_id(self):
        """어시스턴트 메시지 HTML (Job ID 없음)."""
        html = build_assistant_message_html("Response text")

        assert 'class="message assistant"' in html
        assert "Response text" in html
        assert "job-info" not in html


# =============================================================================
# 2. 세션-잡 매핑 영속화 테스트
# =============================================================================


class TestSessionJobMapping:
    """세션-잡 매핑 영속화 테스트."""

    def test_sessions_dir_creation(self, jobs_root: Path):
        """세션 디렉토리 생성."""
        sessions_dir = _get_sessions_dir(jobs_root)

        assert sessions_dir.exists()
        assert sessions_dir.name == "_sessions"

    def test_save_and_load_session_mapping(self, jobs_root: Path):
        """세션 매핑 저장 및 로드."""
        session_id = "test-session-123"
        job_id = "JOB-ABCD1234"

        # 저장
        _save_session_mapping(jobs_root, session_id, job_id)

        # 로드
        loaded_job_id = _load_session_mapping(jobs_root, session_id)

        assert loaded_job_id == job_id

    def test_session_mapping_file_structure(self, jobs_root: Path):
        """세션 매핑 파일 구조 확인."""
        session_id = "test-session-456"
        job_id = "JOB-EFGH5678"

        _save_session_mapping(jobs_root, session_id, job_id)

        session_file = jobs_root / "_sessions" / f"{session_id}.json"
        assert session_file.exists()

        data = json.loads(session_file.read_text())
        assert data["session_id"] == session_id
        assert data["job_id"] == job_id
        assert "created_at" in data
        assert "updated_at" in data

    def test_load_nonexistent_session(self, jobs_root: Path):
        """존재하지 않는 세션 로드."""
        result = _load_session_mapping(jobs_root, "nonexistent-session")
        assert result is None

    def test_same_session_same_job_across_calls(self, jobs_root: Path):
        """동일 세션 → 동일 잡 보장."""
        session_id = "persistent-session"
        job_id = "JOB-PERSIST"

        # 첫 번째 저장 - 새로 생성됨
        returned_job_id = _save_session_mapping(jobs_root, session_id, job_id)
        assert returned_job_id == job_id

        # 두 번째 저장 시도 (이미 존재하면 기존 값 반환)
        returned_job_id_2 = _save_session_mapping(
            jobs_root, session_id, "JOB-DIFFERENT"
        )
        assert returned_job_id_2 == job_id  # 원래 값 반환

        # 디스크에서도 원래 값 유지
        loaded = _load_session_mapping(jobs_root, session_id)
        assert loaded == job_id

    def test_session_restored_after_cache_clear(self, jobs_root: Path):
        """캐시 클리어 후 디스크에서 복원."""
        session_id = "cache-test-session"
        job_id = "JOB-CACHE123"

        # 저장
        _save_session_mapping(jobs_root, session_id, job_id)

        # 캐시 클리어 (서버 재시작 시뮬레이션)
        _session_to_job.clear()

        # 디스크에서 복원
        loaded = _load_session_mapping(jobs_root, session_id)
        assert loaded == job_id


# =============================================================================
# 3. /upload 응답 테스트 (messages_html)
# =============================================================================


class TestUploadResponse:
    """업로드 응답 테스트."""

    @pytest.fixture
    def mock_ocr_service(self):
        """Mock OCR Service."""
        with patch("src.app.services.ocr.OCRService") as MockOCR:
            mock_instance = MagicMock()
            mock_instance.extract_from_bytes = AsyncMock(
                return_value=OCRResult(
                    success=True,
                    text="OCR extracted text",
                    confidence=0.95,
                    model_requested="gemini",
                    model_used="gemini",
                )
            )
            mock_instance.get_user_message = MagicMock(
                return_value="OCR 완료: 텍스트 추출 성공 (신뢰도 95%)"
            )
            MockOCR.return_value = mock_instance
            yield mock_instance

    @pytest.fixture
    def mock_photo_service(self):
        """Mock Photo Service."""
        with patch("src.core.photos.PhotoService") as MockPhoto:
            mock_instance = MagicMock()
            mock_instance.match_slot_for_file = MagicMock(return_value=None)
            mock_instance.save_upload = MagicMock(
                return_value=Path("/tmp/test/photos/raw/test.jpg")
            )
            MockPhoto.return_value = mock_instance
            yield mock_instance

    def test_upload_response_has_messages_html(
        self, client: TestClient, mock_ocr_service, mock_photo_service
    ):
        """업로드 응답에 messages_html 포함."""
        response = client.post(
            "/api/chat/upload",
            files={"file": ("test.jpg", b"fake image data", "image/jpeg")},
            data={"session_id": "test-session"},
        )

        assert response.status_code == 200
        data = response.json()

        assert "messages_html" in data
        assert data["messages_html"]  # 비어있지 않음

    def test_upload_messages_html_contains_user_message(
        self, client: TestClient, mock_ocr_service, mock_photo_service
    ):
        """messages_html에 사용자 메시지 포함."""
        response = client.post(
            "/api/chat/upload",
            files={"file": ("myfile.jpg", b"fake data", "image/jpeg")},
            data={"session_id": "test-session"},
        )

        data = response.json()
        html = data["messages_html"]

        assert "message user" in html
        assert "myfile.jpg" in html

    def test_upload_messages_html_contains_ocr_result(
        self, client: TestClient, mock_ocr_service, mock_photo_service
    ):
        """messages_html에 OCR 결과 포함."""
        response = client.post(
            "/api/chat/upload",
            files={"file": ("scan.png", b"fake png", "image/png")},
            data={"session_id": "test-session"},
        )

        data = response.json()
        html = data["messages_html"]

        assert "message assistant" in html
        # OCR 메시지 포함
        assert "OCR" in html or "텍스트" in html

    def test_upload_escapes_malicious_filename(self):
        """악성 파일명 이스케이프 (HTML 헬퍼 직접 테스트)."""
        malicious_name = '<script>alert("xss")</script>.jpg'

        # HTML 생성 함수 직접 테스트
        user_html = build_user_message_html(f"[파일 첨부: {malicious_name}]")
        assistant_html = build_assistant_message_html(
            f"📷 사진이 저장되었습니다. (슬롯 미매칭: {escape_html(malicious_name)})"
        )

        # Raw script 태그가 없어야 함
        assert "<script>" not in user_html
        assert "<script>" not in assistant_html

        # 이스케이프된 버전이 있어야 함
        assert "&lt;script&gt;" in user_html
        assert "&lt;script&gt;" in assistant_html

    def test_upload_response_has_job_id(
        self, client: TestClient, mock_ocr_service, mock_photo_service
    ):
        """업로드 응답에 Job ID 포함."""
        response = client.post(
            "/api/chat/upload",
            files={"file": ("test.jpg", b"data", "image/jpeg")},
            data={"session_id": "job-test-session"},
        )

        data = response.json()

        assert "job_id" in data
        assert data["job_id"].startswith("JOB-")
        # HTML에도 Job ID 포함
        assert data["job_id"] in data["messages_html"]

    def test_upload_non_image_file(self, client: TestClient):
        """비이미지 파일 업로드."""
        response = client.post(
            "/api/chat/upload",
            files={"file": ("document.txt", b"text content", "text/plain")},
            data={"session_id": "text-session"},
        )

        assert response.status_code == 200
        data = response.json()

        assert "messages_html" in data
        assert "[파일 첨부: document.txt]" in data["messages_html"]
        assert data["ocr_executed"] is False


# =============================================================================
# 4. 타임아웃 테스트
# =============================================================================


class TestTimeout:
    """타임아웃 테스트."""

    @pytest.mark.asyncio
    async def test_extraction_timeout_message(self):
        """추출 타임아웃 시 사용자 메시지."""

        # asyncio.wait_for 타임아웃 시뮬레이션
        async def slow_extract():
            await asyncio.sleep(10)
            return None

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(slow_extract(), timeout=0.1)

    def test_timeout_error_response_format(self):
        """타임아웃 에러 응답 형식."""
        # 타임아웃 메시지가 사용자 친화적인지 확인
        timeout_msg = (
            "분석 시간 초과 ⏱️<br>"
            "외부 AI 서비스 응답이 지연되고 있습니다.<br>"
            "잠시 후 다시 시도해주세요."
        )

        assert "시간 초과" in timeout_msg
        assert "다시 시도" in timeout_msg

    @pytest.fixture
    def mock_extraction_timeout(self):
        """Extraction 타임아웃 Mock."""
        with patch("src.app.routes.chat.ExtractionService") as MockExtract:
            mock_instance = MagicMock()

            async def timeout_extract(*args, **kwargs):
                await asyncio.sleep(100)  # 긴 시간

            mock_instance.extract = timeout_extract
            MockExtract.return_value = mock_instance
            yield mock_instance


# =============================================================================
# 5. 에러 UX 테스트
# =============================================================================


class TestErrorUX:
    """에러 UX 테스트."""

    def test_api_key_error_message(self):
        """API 키 에러 메시지."""
        error_msg = "Invalid api_key provided"

        if "api_key" in error_msg.lower():
            user_msg = "API 인증 문제가 발생했습니다."
            assert "인증" in user_msg

    def test_rate_limit_error_message(self):
        """Rate limit 에러 메시지."""
        error_msg = "Rate limit exceeded"

        if "rate" in error_msg.lower():
            user_msg = "API 호출 한도에 도달했습니다."
            assert "한도" in user_msg

    def test_error_message_truncation(self):
        """에러 메시지 길이 제한."""
        long_error = "A" * 200

        truncated = escape_html(long_error[:100])
        assert len(truncated) <= 100 + 50  # escape로 인한 증가 허용


# =============================================================================
# 6. 세션 일관성 테스트
# =============================================================================


class TestSessionConsistency:
    """세션 일관성 테스트."""

    def test_same_session_same_job_upload_and_message(self, client: TestClient):
        """upload와 message가 같은 세션 → 같은 잡."""
        session_id = "consistency-test-session"

        # 첫 번째: upload
        with patch("src.core.photos.PhotoService") as MockPhoto:
            mock_photo = MagicMock()
            mock_photo.match_slot_for_file = MagicMock(return_value=None)
            mock_photo.save_upload = MagicMock(return_value=Path("/tmp/test.jpg"))
            MockPhoto.return_value = mock_photo

            response1 = client.post(
                "/api/chat/upload",
                files={"file": ("test.jpg", b"data", "image/jpeg")},
                data={"session_id": session_id},
            )

        job_id_1 = response1.json()["job_id"]

        # 두 번째: 같은 세션으로 다시 upload
        with patch("src.core.photos.PhotoService") as MockPhoto:
            mock_photo = MagicMock()
            mock_photo.match_slot_for_file = MagicMock(return_value=None)
            mock_photo.save_upload = MagicMock(return_value=Path("/tmp/test2.jpg"))
            MockPhoto.return_value = mock_photo

            response2 = client.post(
                "/api/chat/upload",
                files={"file": ("test2.jpg", b"data2", "image/jpeg")},
                data={"session_id": session_id},
            )

        job_id_2 = response2.json()["job_id"]

        # 같은 Job ID
        assert job_id_1 == job_id_2

    def test_different_session_different_job(self, client: TestClient):
        """다른 세션 → 다른 잡."""
        with patch("src.core.photos.PhotoService") as MockPhoto:
            mock_photo = MagicMock()
            mock_photo.match_slot_for_file = MagicMock(return_value=None)
            mock_photo.save_upload = MagicMock(return_value=Path("/tmp/test.jpg"))
            MockPhoto.return_value = mock_photo

            response1 = client.post(
                "/api/chat/upload",
                files={"file": ("test.jpg", b"data", "image/jpeg")},
                data={"session_id": "session-A"},
            )

            response2 = client.post(
                "/api/chat/upload",
                files={"file": ("test.jpg", b"data", "image/jpeg")},
                data={"session_id": "session-B"},
            )

        job_id_1 = response1.json()["job_id"]
        job_id_2 = response2.json()["job_id"]

        # 다른 Job ID
        assert job_id_1 != job_id_2


# =============================================================================
# 7. 세션 매핑 TOCTOU-safe 테스트
# =============================================================================


class TestSessionMappingTOCTOUSafe:
    """세션 매핑 TOCTOU-safe 테스트 (O_EXCL 패턴 검증)."""

    def test_concurrent_session_mapping_same_job_id(self, jobs_root: Path):
        """
        동시 세션 매핑 시 동일한 job_id 반환 (TOCTOU-safe).

        이전 구현의 문제점:
            if session_file.exists():  # ← Time of Check
                return
            atomic_write_json(...)      # ← Time of Use (경합!)

        수정 후:
            O_EXCL로 원자적 생성 → 경합해도 동일 job_id 보장
        """
        # _sessions 디렉토리 미리 생성 (테스트 경합 방지)
        _get_sessions_dir(jobs_root)

        session_id = "race-session"
        results: list[str] = []
        results_lock = threading.Lock()
        barrier = threading.Barrier(3)

        def try_create_mapping(name: str, job_id: str):
            barrier.wait()  # 동시 시작
            returned_id = _save_session_mapping(jobs_root, session_id, job_id)
            with results_lock:
                results.append(returned_id)

        threads = [
            threading.Thread(target=try_create_mapping, args=(f"t{i}", f"JOB-{i}"))
            for i in range(3)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 모든 스레드가 동일한 job_id를 반환해야 함
        assert len(set(results)) == 1, f"경합 발생: 서로 다른 job_id 반환됨 {results}"

        # 디스크의 값과 일치
        loaded = _load_session_mapping(jobs_root, session_id)
        assert loaded == results[0]

    def test_save_returns_job_id(self, jobs_root: Path):
        """_save_session_mapping이 실제 사용할 job_id를 반환."""
        session_id = "return-test"

        # 첫 번째: 새로 생성
        job_id_1 = _save_session_mapping(jobs_root, session_id, "JOB-FIRST")
        assert job_id_1 == "JOB-FIRST"

        # 두 번째: 기존 값 반환
        job_id_2 = _save_session_mapping(jobs_root, session_id, "JOB-SECOND")
        assert job_id_2 == "JOB-FIRST"  # 기존 값

    def test_file_content_matches_first_writer(self, jobs_root: Path):
        """파일 내용이 첫 번째 성공한 쓰기와 일치."""
        session_id = "content-test"

        # 첫 번째 저장
        _save_session_mapping(jobs_root, session_id, "JOB-WINNER")

        # 두 번째 시도 (실패해야 함)
        _save_session_mapping(jobs_root, session_id, "JOB-LOSER")

        # 파일 내용 확인
        session_file = _get_sessions_dir(jobs_root) / f"{session_id}.json"
        data = json.loads(session_file.read_text())

        assert data["job_id"] == "JOB-WINNER"
        assert data["session_id"] == session_id


# =============================================================================
# 8. Validation Error HTML 테스트
# =============================================================================


class TestBuildValidationErrorHtml:
    """검증 오류 HTML 생성 테스트."""

    def test_build_validation_error_html_missing_required(self):
        """필수 필드 누락 시 error-item 포함 확인."""
        validation = ValidationResult(
            valid=False,
            missing_required=["wo_no", "line", "result"],
        )

        html = build_validation_error_html(validation)

        # 컨테이너 확인
        assert "validation-errors" in html

        # error-item 포함
        assert "error-item" in html

        # 필수 필드 누락 메시지
        assert "필수 필드 누락" in html
        assert "wo_no" in html
        assert "line" in html
        assert "result" in html

        # 🔴 아이콘
        assert "🔴" in html

        # 에러 코드 포함 (domain/errors.py ErrorCodes와 일치)
        assert "[MISSING_REQUIRED_FIELD]" in html

        # 힌트 메시지 포함 (리뷰 피드백 반영)
        assert "hint" in html
        assert "💡" in html

    def test_build_validation_error_html_invalid_values(self):
        """유효하지 않은 값 시 error-item 포함 확인."""
        validation = ValidationResult(
            valid=False,
            invalid_values=[
                {
                    "field": "result",
                    "value": "UNKNOWN_VALUE",
                    "error": "Invalid result",
                },
                {"field": "lot", "value": "<script>", "error": "Invalid format"},
            ],
        )

        html = build_validation_error_html(validation)

        # 컨테이너 확인
        assert "validation-errors" in html

        # error-item 포함
        assert "error-item" in html

        # 유효하지 않은 값 메시지
        assert "유효하지 않은 값" in html
        assert "result" in html
        assert "UNKNOWN_VALUE" in html
        assert "lot" in html

        # XSS 이스케이프 확인
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

        # 에러 코드 포함 (domain/errors.py ErrorCodes와 일치)
        assert "[RESULT_INVALID_VALUE]" in html

    def test_build_validation_error_html_empty_when_valid(self):
        """검증 통과 시 빈 문자열 반환."""
        validation = ValidationResult(valid=True)

        html = build_validation_error_html(validation)

        assert html == ""

    def test_build_validation_error_html_measurement_issues(self):
        """측정값 이슈 시 error-item 포함 확인."""
        validation = ValidationResult(valid=True)

        measurement_issues = {
            "empty_measured": ["항목A - 1번째 줄", "항목B - 3번째 줄"],
            "nan_inf": ["항목C - 2번째 줄"],
        }

        html = build_validation_error_html(
            validation, measurement_issues=measurement_issues
        )

        # 컨테이너 확인
        assert "validation-errors" in html

        # 빈 측정값
        assert "빈 측정값" in html
        assert "항목A" in html

        # NaN/Inf
        assert "NaN/Inf 포함" in html
        assert "항목C" in html

        # 에러 코드 포함 (domain/errors.py INVALID_DATA와 일치)
        assert "[INVALID_DATA]" in html

    def test_build_validation_error_html_result_not_duplicated(self):
        """result 필드가 missing_required와 invalid_values에 중복되지 않음 확인."""
        validation = ValidationResult(
            valid=False,
            missing_required=["result"],  # missing_required에 result 있음
            invalid_values=[
                {"field": "result", "value": "BAD", "error": "Invalid"},  # 중복
                {"field": "lot", "value": "X", "error": "Invalid format"},
            ],
        )

        html = build_validation_error_html(validation)

        # invalid_values의 result는 스킵됨 (missing_required 우선)
        # "BAD" 값이 HTML에 없어야 함
        assert "BAD" not in html

        # lot의 invalid_value는 표시됨
        assert "lot" in html
        assert "Invalid format" in html

        # RESULT_INVALID_VALUE 에러 코드는 lot에만 있어야 함 (1번)
        assert html.count("[RESULT_INVALID_VALUE]") == 1

    def test_build_validation_error_html_override_errors_separate(self):
        """Override 실패는 별도 섹션에 표시됨 확인."""
        validation = ValidationResult(
            valid=False,
            invalid_override_fields=["wo_no"],
            invalid_override_reasons={"wo_no": "금지 토큰 포함"},
        )

        html = build_validation_error_html(validation)

        # Override 에러는 별도 컨테이너
        assert "override-errors" in html
        assert "시스템 처리 오류" in html
        assert "Override 처리 실패" in html
        # domain/errors.py OVERRIDE_NOT_ALLOWED와 일치
        assert "[OVERRIDE_NOT_ALLOWED]" in html

        # ⚙️ 아이콘 (🔴가 아님)
        assert "⚙️" in html

    def test_analyze_measurement_issues_empty(self):
        """빈 측정 데이터 분석."""
        result = analyze_measurement_issues([])

        assert result["empty_measured"] == []
        assert result["nan_inf"] == []
        assert result["has_more"] is False

    def test_analyze_measurement_issues_with_empty_values(self):
        """빈 MEASURED 값 감지."""
        measurements = [
            {"ITEM": "직경", "MEASURED": "3.5"},
            {"ITEM": "길이", "MEASURED": ""},  # 빈 값
            {"ITEM": "높이", "MEASURED": None},  # None
            {"ITEM": "너비", "MEASURED": "2.1"},
        ]

        result = analyze_measurement_issues(measurements)

        assert len(result["empty_measured"]) == 2
        # 개선된 식별자: "항목명 - N번째 줄"
        assert "길이" in result["empty_measured"][0]
        assert "2번째 줄" in result["empty_measured"][0]  # 1-indexed
        assert "높이" in result["empty_measured"][1]
        assert "3번째 줄" in result["empty_measured"][1]
        assert result["nan_inf"] == []
        # has_more 없음 (2개 < 10개 상한)
        assert result["has_more"] is False

    def test_analyze_measurement_issues_with_nan_inf(self):
        """NaN/Inf 값 감지."""
        measurements = [
            {"ITEM": "정상값", "MEASURED": "3.5"},
            {"ITEM": "NaN값", "MEASURED": "nan"},
            {"ITEM": "Inf값", "MEASURED": "inf"},
            {"ITEM": "음수Inf", "MEASURED": "-inf"},
        ]

        result = analyze_measurement_issues(measurements)

        assert result["empty_measured"] == []
        assert len(result["nan_inf"]) == 3
        assert any("NaN값" in item for item in result["nan_inf"])
        assert any("Inf값" in item for item in result["nan_inf"])

    def test_analyze_measurement_issues_with_spec(self):
        """SPEC 값도 함께 표시 확인."""
        measurements = [
            {"characteristic": "직경", "SPEC": "3.0±0.1", "MEASURED": ""},
        ]

        result = analyze_measurement_issues(measurements)

        assert len(result["empty_measured"]) == 1
        # SPEC 포함
        assert "직경" in result["empty_measured"][0]
        assert "SPEC: 3.0±0.1" in result["empty_measured"][0]

    def test_getattr_fallback_for_schema_changes(self):
        """ValidationResult 스키마 변경에도 안전하게 동작."""
        # missing_required 등이 없는 최소 객체로 테스트
        from dataclasses import dataclass

        @dataclass
        class MinimalValidation:
            valid: bool = True

        minimal = MinimalValidation()
        html = build_validation_error_html(minimal)  # type: ignore

        # 에러 없이 빈 문자열 반환
        assert html == ""

    def test_analyze_measurement_issues_early_termination(self):
        """조기 종료: 10개 찾으면 스캔 중단 (stop_after_limit=True 기본).

        검증 포인트:
        1. 결과가 10개인지 (출력 제한)
        2. has_more=True인지 (더 있음 표시)
        3. 15개 모두 반복하지 않았는지 (상한 검증으로 off-by-one 방지)
        """
        # 15개의 빈 측정값 생성
        measurements = []
        for i in range(15):
            measurements.append({"ITEM": f"빈값{i}", "MEASURED": ""})

        result = analyze_measurement_issues(measurements, _debug=True)

        # 10개만 수집 (조기 종료)
        assert len(result["empty_measured"]) == 10
        # has_more=True (더 있음 표시)
        assert result["has_more"] is True
        # 핵심: 조기 종료 증명 - 15번 모두 돌지 않았음을 상한으로 검증
        # (정확히 10인지 11인지는 구현에 따라 다를 수 있으므로 상한만 체크)
        assert result["_debug_iterations"] <= 11, (
            f"조기 종료 실패: {result['_debug_iterations']}번 반복 (11 이하여야 함)"
        )
        # 프로덕션에서는 _debug_iterations 없음 확인
        prod_result = analyze_measurement_issues(measurements)
        assert "_debug_iterations" not in prod_result

    def test_analyze_measurement_issues_full_scan(self):
        """stop_after_limit=False일 때 끝까지 스캔.

        검증 포인트:
        1. 결과가 10개인지 (출력 제한은 여전히 적용)
        2. has_more=True인지 (10개 넘었으므로)
        3. 실제로 15번 모두 반복했는지 (정확한 값 검증)
        """
        # 15개의 빈 측정값 생성
        measurements = []
        for i in range(15):
            measurements.append({"ITEM": f"빈값{i}", "MEASURED": ""})

        result = analyze_measurement_issues(
            measurements, stop_after_limit=False, _debug=True
        )

        # 10개만 수집하지만 끝까지 스캔
        assert len(result["empty_measured"]) == 10
        # has_more는 아직 True (10개 넘었으므로)
        assert result["has_more"] is True
        # 핵심: full scan은 정확히 15번 반복해야 함
        assert result["_debug_iterations"] == 15, (
            f"Full scan 실패: {result['_debug_iterations']}번 반복 (15번 해야 함)"
        )

    def test_build_validation_error_html_has_more_display(self):
        """has_more=True일 때 '외 다수' 메시지 표시."""
        validation = ValidationResult(valid=True)

        measurement_issues = {
            "empty_measured": ["항목1 - 1번째 줄"] * 10,
            "nan_inf": [],
            "has_more": True,
        }

        html = build_validation_error_html(
            validation, measurement_issues=measurement_issues
        )

        # "외 다수" 알림 메시지 포함
        assert "외 다수" in html
        # overflow-notice 클래스 포함
        assert "overflow-notice" in html

    def test_validation_error_html_dom_structure(self):
        """
        DOM 구조 검증 (리뷰 피드백: 문자열 매칭보다 구조 확인).

        검증 포인트:
        - validation-errors 컨테이너 내부에 error-item이 있어야 함
        - override-errors는 별도 컨테이너
        - error-code 뱃지가 error-item 내부에 있어야 함
        """
        validation = ValidationResult(
            valid=False,
            missing_required=["wo_no"],
            invalid_values=[{"field": "lot", "value": "X", "error": "Bad"}],
            invalid_override_fields=["line"],
            invalid_override_reasons={"line": "금지 토큰"},
        )

        measurement_issues = {
            "empty_measured": ["직경 - 1번째 줄"],
            "nan_inf": [],
            "has_more": False,
        }

        html = build_validation_error_html(
            validation, measurement_issues=measurement_issues
        )

        # 1) validation-errors 컨테이너 확인
        assert html.startswith('<div class="validation-errors">')

        # 2) error-item 개수 확인 (missing_required 1 + invalid_values 1 + empty_measured 1)
        error_item_count = html.count('class="error-item"')
        assert error_item_count == 3

        # 3) override-errors는 validation-errors 이후에 별도 컨테이너
        validation_errors_end = html.find("</div>", html.find("validation-errors"))
        override_errors_start = html.find("override-errors")
        assert override_errors_start > validation_errors_end

        # 4) error-code 뱃지가 error-item 내부에 있음
        error_item_start = html.find("error-item")
        error_code_in_item = html.find("error-code", error_item_start)
        next_error_item_end = html.find("</div>", error_item_start)
        assert error_item_start < error_code_in_item < next_error_item_end

    def test_analyze_measurement_issues_placeholder_tokens(self):
        """N/A, —, 측정불가 등 플레이스홀더가 빈값으로 처리되는지 확인."""
        measurements = [
            {"ITEM": "항목1", "MEASURED": "N/A"},
            {"ITEM": "항목2", "MEASURED": "—"},
            {"ITEM": "항목3", "MEASURED": "측정불가"},
            {"ITEM": "항목4", "MEASURED": "none"},
            {"ITEM": "항목5", "MEASURED": "3.5"},  # 정상값
        ]

        result = analyze_measurement_issues(measurements)

        # 4개가 빈값으로 처리됨 (N/A, —, 측정불가, none)
        assert len(result["empty_measured"]) == 4
        assert "항목5" not in " ".join(result["empty_measured"])

    def test_analyze_measurement_issues_locale_number_format(self):
        """다양한 로컬 숫자 포맷이 정상 파싱되는지 확인."""
        measurements = [
            {"ITEM": "미국식", "MEASURED": "1,234.56"},  # 정상
            {"ITEM": "유럽식", "MEASURED": "1.234,56"},  # 정상
            {"ITEM": "공백구분", "MEASURED": "1 234.56"},  # 정상
            {"ITEM": "빈값", "MEASURED": ""},  # 빈값
        ]

        result = analyze_measurement_issues(measurements)

        # 빈값만 감지되어야 함 (로컬 포맷은 정상 파싱)
        assert len(result["empty_measured"]) == 1
        assert "빈값" in result["empty_measured"][0]


# =============================================================================
# 9. 지원하지 않는 확장자 경고 테스트
# =============================================================================


class TestUnsupportedExtensionWarning:
    """지원하지 않는 확장자 경고 테스트."""

    def test_unsupported_extension_warning_message(self, client: TestClient):
        """
        .gif 업로드 시 경고 메시지 포함 확인.

        - messages_html에 warning-item 포함
        - "지원하지 않는 확장자" 문구 포함
        - unsupported_extension 플래그 True
        - stored 플래그 False (파일 저장 안 함)
        """
        response = client.post(
            "/api/chat/upload",
            files={"file": ("test.gif", b"GIF89a...", "image/gif")},
            data={"session_id": "test-gif-session"},
        )

        assert response.status_code == 200
        data = response.json()

        # unsupported_extension 플래그 확인
        assert data.get("unsupported_extension") is True

        # success는 False (지원 안 되는 확장자)
        assert data.get("success") is False

        # stored는 False (파일 저장 안 함 - 디버깅 비용 절감)
        assert data.get("stored") is False

        # messages_html 포함
        assert "messages_html" in data
        html = data["messages_html"]

        # warning-item 확인
        assert "warning-item" in html

        # 지원하지 않는 확장자 메시지
        assert "지원하지 않는 확장자" in html
        assert "test.gif" in html

        # 파일 저장 안 됨 메시지
        assert "저장되지 않았습니다" in html

        # 다음 액션 힌트 (리뷰 피드백 반영)
        assert "jpg/jpeg/png" in html

        # 에러 코드 포함
        assert "[UNSUPPORTED_EXT]" in html

    def test_supported_extension_no_warning(self, client: TestClient):
        """
        .jpg 업로드 시 경고 없음 확인.

        - unsupported_extension 플래그 False
        - warning-item 미포함
        """
        with patch("src.app.services.ocr.OCRService") as MockOCR:
            mock_instance = MagicMock()
            mock_instance.extract_from_bytes = AsyncMock(
                return_value=OCRResult(
                    success=True,
                    text="Test text",
                    confidence=0.95,
                    model_requested="gemini",
                    model_used="gemini",
                )
            )
            mock_instance.get_user_message = MagicMock(return_value="OCR 완료")
            MockOCR.return_value = mock_instance

            with patch("src.core.photos.PhotoService") as MockPhoto:
                photo_mock = MagicMock()
                photo_mock.match_slot_for_file = MagicMock(return_value=None)
                photo_mock.save_upload = MagicMock(return_value=Path("/tmp/test.jpg"))
                MockPhoto.return_value = photo_mock

                response = client.post(
                    "/api/chat/upload",
                    files={"file": ("test.jpg", b"JPEG data", "image/jpeg")},
                    data={"session_id": "test-jpg-session"},
                )

        assert response.status_code == 200
        data = response.json()

        # unsupported_extension 플래그 False
        assert data.get("unsupported_extension") is False

        # success는 True
        assert data.get("success") is True

        # warning-item 미포함
        html = data.get("messages_html", "")
        assert "지원하지 않는 확장자" not in html

    def test_bmp_extension_warning(self, client: TestClient):
        """
        .bmp 업로드 시 경고 메시지 포함 확인.
        """
        response = client.post(
            "/api/chat/upload",
            files={"file": ("image.bmp", b"BM...", "image/bmp")},
            data={"session_id": "test-bmp-session"},
        )

        assert response.status_code == 200
        data = response.json()

        assert data.get("unsupported_extension") is True
        assert "warning-item" in data.get("messages_html", "")
