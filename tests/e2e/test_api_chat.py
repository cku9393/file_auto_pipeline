"""
test_api_chat.py - Chat API E2E 테스트

엔드포인트:
- POST /api/chat/message
- POST /api/chat/upload
- POST /api/chat/extract
- POST /api/chat/override
- GET /api/chat/stream (SSE)
"""

import pytest
from fastapi.testclient import TestClient

from src.app.main import app

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def client():
    """FastAPI TestClient."""
    with TestClient(app) as client:
        yield client


# =============================================================================
# Health Check
# =============================================================================


class TestHealthCheck:
    """헬스 체크 테스트."""

    def test_health_endpoint(self, client):
        """GET /health."""
        response = client.get("/health")

        assert response.status_code == 200
        assert response.text == "ok"  # PlainTextResponse returns plain text


# =============================================================================
# Chat Page
# =============================================================================


class TestChatPage:
    """채팅 페이지 테스트."""

    def test_chat_page_loads(self, client):
        """GET /chat → HTML 페이지."""
        response = client.get("/chat")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "문서 생성" in response.text


# =============================================================================
# POST /api/chat/message
# =============================================================================


class TestSendMessage:
    """메시지 전송 테스트."""

    def test_send_message_returns_html(self, client):
        """POST /api/chat/message → HTML 응답."""
        response = client.post(
            "/api/chat/message",
            data={
                "content": "작업번호 WO-001입니다",
                "session_id": "",
            },
        )

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_send_message_contains_user_input(self, client):
        """사용자 입력이 응답에 포함."""
        response = client.post(
            "/api/chat/message",
            data={
                "content": "WO-001, L1, PASS",
                "session_id": "",
            },
        )

        assert "WO-001" in response.text

    def test_send_message_with_session_id(self, client):
        """세션 ID 전달."""
        response = client.post(
            "/api/chat/message",
            data={
                "content": "Hello",
                "session_id": "test-session-123",
            },
        )

        assert response.status_code == 200


# =============================================================================
# POST /api/chat/upload
# =============================================================================


class TestUploadFile:
    """파일 업로드 테스트."""

    def test_upload_file(self, client):
        """POST /api/chat/upload."""
        response = client.post(
            "/api/chat/upload",
            files={"file": ("test.jpg", b"fake image data", "image/jpeg")},
            data={"session_id": ""},
        )

        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True
        assert data["filename"] == "test.jpg"
        assert data["size"] == len(b"fake image data")

    def test_upload_returns_session_id(self, client):
        """업로드 시 세션 ID 반환."""
        response = client.post(
            "/api/chat/upload",
            files={"file": ("doc.pdf", b"pdf content", "application/pdf")},
            data={"session_id": ""},
        )

        data = response.json()
        assert "session_id" in data
        assert data["session_id"] is not None


# =============================================================================
# POST /api/chat/extract
# =============================================================================


class TestExtractFields:
    """필드 추출 테스트."""

    @pytest.mark.skip(reason="Requires external API authentication not available in CI")
    def test_extract_fields(self, client):
        """POST /api/chat/extract."""
        response = client.post(
            "/api/chat/extract",
            data={"session_id": "test-session"},
        )

        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True
        assert "fields" in data
        assert "measurements" in data
        assert "missing_fields" in data


# =============================================================================
# POST /api/chat/override
# =============================================================================


class TestApplyOverride:
    """Override 적용 테스트."""

    def test_apply_override(self, client):
        """POST /api/chat/override."""
        response = client.post(
            "/api/chat/override",
            data={
                "session_id": "test-session",
                "field": "inspector",
                "reason": "사진에서 확인 불가",
            },
        )

        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True
        assert data["field"] == "inspector"
        assert data["reason"] == "사진에서 확인 불가"


# =============================================================================
# GET /api/chat/stream (SSE)
# =============================================================================


class TestChatStream:
    """SSE 스트림 테스트."""

    @pytest.mark.skip(
        reason="SSE 스트림 테스트는 TestClient에서 제한적 - httpx 비동기 테스트 필요"
    )
    def test_stream_returns_event_stream(self, client):
        """GET /api/chat/stream → SSE."""
        # Note: TestClient에서 SSE 테스트는 제한적
        # 실제 SSE 연결 테스트는 httpx나 별도 도구 필요
        # TestClient.stream()은 SSE 연결을 종료하지 않아 무한 대기
        with client.stream("GET", "/api/chat/stream") as response:
            assert response.status_code == 200
            assert "text/event-stream" in response.headers.get("content-type", "")


# =============================================================================
# Error Cases
# =============================================================================


class TestChatErrorCases:
    """에러 케이스 테스트."""

    def test_message_without_content(self, client):
        """content 없이 메시지 전송."""
        response = client.post(
            "/api/chat/message",
            data={"session_id": "test"},
            # content 누락
        )

        assert response.status_code == 422  # Validation Error

    def test_message_with_empty_content(self, client):
        """content가 빈 문자열일 때 422 (FastAPI는 빈 Form 필드를 missing으로 처리)."""
        response = client.post(
            "/api/chat/message",
            data={"content": "", "session_id": "test"},
        )

        # FastAPI의 Form(...)은 빈 문자열을 missing으로 취급하여 422 반환
        assert response.status_code == 422

    def test_message_with_whitespace_content(self, client):
        """content가 공백만 있을 때 친절한 안내 메시지 반환."""
        response = client.post(
            "/api/chat/message",
            data={"content": "   ", "session_id": "test"},
        )

        # 공백만 있는 경우 200 + 친절한 안내 메시지
        assert response.status_code == 200
        assert "메시지를 입력해주세요" in response.text

    def test_upload_without_file(self, client):
        """파일 없이 업로드."""
        response = client.post(
            "/api/chat/upload",
            data={"session_id": "test"},
            # file 누락
        )

        assert response.status_code == 422

    def test_extract_without_session(self, client):
        """세션 없이 추출."""
        response = client.post(
            "/api/chat/extract",
            data={},  # session_id 누락
        )

        assert response.status_code == 422

    def test_override_without_field(self, client):
        """필드 없이 override."""
        response = client.post(
            "/api/chat/override",
            data={
                "session_id": "test",
                "reason": "사유",
                # field 누락
            },
        )

        assert response.status_code == 422

    def test_override_without_reason(self, client):
        """사유 없이 override."""
        response = client.post(
            "/api/chat/override",
            data={
                "session_id": "test",
                "field": "inspector",
                # reason 누락
            },
        )

        assert response.status_code == 422


# =============================================================================
# Validation Error Card E2E (CI 안전망)
# =============================================================================


class TestValidationErrorCardE2E:
    """
    검증 오류 카드 E2E 테스트.

    목적: CSS/템플릿 깨짐을 CI에서 잡는 최소 안전망.
    - 필수 필드 누락 시 validation-errors 컨테이너 + error-item 존재 확인
    - 에러 코드가 도메인과 일치하는지 확인
    """

    @pytest.mark.skip(reason="Requires external API - run locally with API key")
    def test_missing_required_shows_error_card(self, client):
        """
        필수 필드 누락 입력 → 빨간 카드 DOM 존재 + 텍스트 포함.

        Note: 외부 LLM API 호출이 필요하므로 CI에서는 skip.
        로컬 테스트: pytest tests/e2e/test_api_chat.py -k "error_card" --run-external
        """
        response = client.post(
            "/api/chat/message",
            data={
                # 필수 필드(wo_no, line, result) 의도적 누락
                "content": "이것은 불완전한 입력입니다",
                "session_id": "",
            },
        )

        assert response.status_code == 200
        html = response.text

        # 1) validation-errors 컨테이너 존재
        assert "validation-errors" in html

        # 2) error-item 클래스 존재
        assert "error-item" in html

        # 3) 에러 코드 존재 (domain/errors.py와 일치)
        assert "[MISSING_REQUIRED_FIELD]" in html

        # 4) 필수 필드 누락 메시지
        assert "필수 필드 누락" in html

    def test_validation_error_html_structure_unit(self, client):
        """
        E2E 환경에서 validation error HTML 구조 검증 (API 호출 없이).

        route 함수를 직접 호출하여 HTML 구조 검증.
        외부 API 의존 없이 CI에서 실행 가능.
        """
        from src.app.routes.chat import build_validation_error_html
        from src.app.services.validate import ValidationResult

        # 필수 필드 누락 시나리오
        validation = ValidationResult(
            valid=False,
            missing_required=["wo_no", "line", "result"],
        )

        html = build_validation_error_html(validation)

        # 1) validation-errors 컨테이너 존재
        assert 'class="validation-errors"' in html

        # 2) error-item 클래스 존재
        assert 'class="error-item"' in html

        # 3) 에러 코드 존재 (domain/errors.py와 일치)
        assert "[MISSING_REQUIRED_FIELD]" in html

        # 4) 필수 필드명 포함
        assert "wo_no" in html
        assert "line" in html
        assert "result" in html

        # 5) 🔴 아이콘 존재
        assert "🔴" in html
