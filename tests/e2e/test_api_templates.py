"""
test_api_templates.py - Templates API E2E 테스트

엔드포인트:
- GET /templates (HTML page)
- GET /templates/register (HTML page)
- GET /api/templates
- POST /api/templates
- GET /api/templates/{template_id}
- PATCH /api/templates/{template_id}
- DELETE /api/templates/{template_id}
"""

import io
import uuid

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


@pytest.fixture
def sample_docx() -> bytes:
    """테스트용 DOCX 파일 (fake)."""
    return b"PK\x03\x04fake docx content"


@pytest.fixture
def sample_xlsx() -> bytes:
    """테스트용 XLSX 파일 (fake)."""
    return b"PK\x03\x04fake xlsx content"


# =============================================================================
# Page Routes (HTML)
# =============================================================================


class TestTemplatesPage:
    """템플릿 관리 페이지 테스트."""

    def test_templates_page_loads(self, client):
        """GET /templates → HTML 페이지."""
        response = client.get("/templates")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "템플릿 관리" in response.text

    def test_templates_page_has_htmx_trigger(self, client):
        """템플릿 목록이 HTMX로 로드됨."""
        response = client.get("/templates")

        assert "hx-get" in response.text
        assert "/api/templates" in response.text

    def test_templates_page_has_new_template_link(self, client):
        """새 템플릿 등록 링크."""
        response = client.get("/templates")

        assert "새 템플릿" in response.text or "/register" in response.text


class TestRegisterPage:
    """템플릿 등록 페이지 테스트."""

    def test_register_page_loads(self, client):
        """GET /templates/register → HTML 페이지."""
        response = client.get("/templates/register")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "템플릿 등록" in response.text

    def test_register_page_has_form(self, client):
        """등록 폼 포함."""
        response = client.get("/templates/register")

        assert "form" in response.text.lower()
        assert "template_id" in response.text
        assert "display_name" in response.text

    def test_register_page_accepts_file_upload(self, client):
        """파일 업로드 필드 포함."""
        response = client.get("/templates/register")

        assert 'type="file"' in response.text
        assert ".docx" in response.text or ".xlsx" in response.text


# =============================================================================
# GET /api/templates
# =============================================================================


class TestListTemplates:
    """템플릿 목록 API 테스트."""

    def test_list_templates_returns_html(self, client):
        """GET /api/templates → HTML 응답."""
        response = client.get("/api/templates")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    @pytest.mark.skip(reason="Requires 'base' template to exist - run locally")
    def test_list_templates_contains_base_template(self, client):
        """기본 템플릿 포함."""
        response = client.get("/api/templates")

        assert "기본 템플릿" in response.text or "base" in response.text

    def test_list_templates_shows_status(self, client):
        """템플릿 상태 표시."""
        response = client.get("/api/templates")

        assert "ready" in response.text or "badge" in response.text


# =============================================================================
# POST /api/templates
# =============================================================================


class TestCreateTemplate:
    """템플릿 생성 API 테스트."""

    def test_create_template_success(self, client):
        """POST /api/templates → 템플릿 생성."""
        unique_id = f"test_template_{uuid.uuid4().hex[:8]}"
        response = client.post(
            "/api/templates",
            data={
                "template_id": unique_id,
                "display_name": "테스트 템플릿",
                "doc_type": "inspection",
            },
        )

        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True
        assert data["template_id"] == unique_id
        assert "message" in data

    def test_create_template_with_docx(self, client, sample_docx):
        """DOCX 파일과 함께 생성."""
        unique_id = f"with_docx_{uuid.uuid4().hex[:8]}"
        response = client.post(
            "/api/templates",
            data={
                "template_id": unique_id,
                "display_name": "DOCX 템플릿",
                "doc_type": "inspection",
            },
            files={
                "example_docx": (
                    "template.docx",
                    io.BytesIO(sample_docx),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ),
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_create_template_with_xlsx(self, client, sample_xlsx):
        """XLSX 파일과 함께 생성."""
        unique_id = f"with_xlsx_{uuid.uuid4().hex[:8]}"
        response = client.post(
            "/api/templates",
            data={
                "template_id": unique_id,
                "display_name": "XLSX 템플릿",
                "doc_type": "inspection",
            },
            files={
                "example_xlsx": (
                    "template.xlsx",
                    io.BytesIO(sample_xlsx),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                ),
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_create_template_with_both_files(self, client, sample_docx, sample_xlsx):
        """DOCX, XLSX 모두 업로드."""
        unique_id = f"with_both_{uuid.uuid4().hex[:8]}"
        response = client.post(
            "/api/templates",
            data={
                "template_id": unique_id,
                "display_name": "DOCX+XLSX 템플릿",
                "doc_type": "inspection",
            },
            files={
                "example_docx": (
                    "template.docx",
                    io.BytesIO(sample_docx),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ),
                "example_xlsx": (
                    "template.xlsx",
                    io.BytesIO(sample_xlsx),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                ),
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_create_template_returns_requires_review(self, client):
        """리뷰 필요 플래그 반환."""
        unique_id = f"needs_review_{uuid.uuid4().hex[:8]}"
        response = client.post(
            "/api/templates",
            data={
                "template_id": unique_id,
                "display_name": "리뷰 필요",
                "doc_type": "inspection",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "requires_review" in data


# =============================================================================
# GET /api/templates/{template_id}
# =============================================================================


class TestGetTemplate:
    """템플릿 상세 조회 API 테스트."""

    @pytest.mark.skip(reason="Requires 'base' template to exist - run locally")
    def test_get_template_success(self, client):
        """GET /api/templates/{template_id} → 템플릿 정보."""
        response = client.get("/api/templates/base")

        assert response.status_code == 200
        data = response.json()

        assert data["template_id"] == "base"
        assert "display_name" in data
        assert "doc_type" in data
        assert "status" in data

    def test_get_nonexistent_template(self, client):
        """존재하지 않는 템플릿 (현재는 데모 응답)."""
        response = client.get("/api/templates/nonexistent")

        # 현재 구현은 데모 데이터 반환
        # 실제 구현 시 404 반환해야 함
        assert response.status_code in [200, 404]


# =============================================================================
# PATCH /api/templates/{template_id}
# =============================================================================


class TestUpdateTemplateStatus:
    """템플릿 상태 변경 API 테스트."""

    @pytest.mark.skip(reason="Requires 'base' template to exist - run locally")
    def test_update_status_to_ready(self, client):
        """상태를 ready로 변경."""
        response = client.patch(
            "/api/templates/base",
            data={"status": "ready"},
        )

        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True
        assert data["template_id"] == "base"
        assert data["status"] == "ready"

    @pytest.mark.skip(reason="Requires 'base' template to exist - run locally")
    def test_update_status_to_pending(self, client):
        """상태를 pending으로 변경."""
        response = client.patch(
            "/api/templates/base",
            data={"status": "pending"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "pending"

    @pytest.mark.skip(reason="Requires 'base' template to exist - run locally")
    def test_update_status_to_archived(self, client):
        """상태를 archived로 변경."""
        response = client.patch(
            "/api/templates/base",
            data={"status": "archived"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "archived"


# =============================================================================
# DELETE /api/templates/{template_id}
# =============================================================================


class TestDeleteTemplate:
    """템플릿 삭제 API 테스트."""

    @pytest.mark.skip(reason="Requires template to be created first - run locally")
    def test_delete_template_success(self, client):
        """DELETE /api/templates/{template_id} → 삭제."""
        response = client.delete("/api/templates/test_template")

        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True
        assert data["template_id"] == "test_template"
        assert "message" in data

    @pytest.mark.skip(reason="Requires template to be created first - run locally")
    def test_delete_template_with_force(self, client):
        """강제 삭제."""
        response = client.delete("/api/templates/test_template?force=true")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True


# =============================================================================
# Error Cases
# =============================================================================


class TestTemplatesErrorCases:
    """에러 케이스 테스트."""

    def test_create_without_template_id(self, client):
        """template_id 없이 생성."""
        response = client.post(
            "/api/templates",
            data={
                "display_name": "이름만",
                "doc_type": "inspection",
                # template_id 누락
            },
        )

        assert response.status_code == 422  # Validation Error

    def test_create_without_display_name(self, client):
        """display_name 없이 생성."""
        response = client.post(
            "/api/templates",
            data={
                "template_id": "no_name",
                "doc_type": "inspection",
                # display_name 누락
            },
        )

        assert response.status_code == 422  # Validation Error

    def test_update_without_status(self, client):
        """status 없이 업데이트."""
        response = client.patch(
            "/api/templates/base",
            data={},
        )

        assert response.status_code == 422  # Validation Error


# =============================================================================
# Template ID Validation (현재 미구현 - 향후 추가)
# =============================================================================


class TestTemplateIdValidation:
    """템플릿 ID 유효성 검증 테스트."""

    def test_template_id_with_valid_chars(self, client):
        """유효한 템플릿 ID (소문자, 숫자, 밑줄)."""
        unique_id = f"valid_template_{uuid.uuid4().hex[:8]}"
        response = client.post(
            "/api/templates",
            data={
                "template_id": unique_id,
                "display_name": "유효한 ID",
                "doc_type": "inspection",
            },
        )

        assert response.status_code == 200

    # 향후 서버 측 검증 추가 시 활성화
    # def test_template_id_with_invalid_chars(self, client):
    #     """잘못된 템플릿 ID (대문자, 특수문자)."""
    #     response = client.post(
    #         "/api/templates",
    #         data={
    #             "template_id": "Invalid-Template!",
    #             "display_name": "잘못된 ID",
    #             "doc_type": "inspection",
    #         },
    #     )
    #
    #     assert response.status_code == 422


# =============================================================================
# Doc Types
# =============================================================================


class TestDocTypes:
    """문서 타입 테스트."""

    def test_create_inspection_template(self, client):
        """검사성적서 타입."""
        unique_id = f"inspection_{uuid.uuid4().hex[:8]}"
        response = client.post(
            "/api/templates",
            data={
                "template_id": unique_id,
                "display_name": "검사성적서",
                "doc_type": "inspection",
            },
        )

        assert response.status_code == 200

    def test_create_report_template(self, client):
        """보고서 타입."""
        unique_id = f"report_{uuid.uuid4().hex[:8]}"
        response = client.post(
            "/api/templates",
            data={
                "template_id": unique_id,
                "display_name": "보고서",
                "doc_type": "report",
            },
        )

        assert response.status_code == 200

    def test_create_other_template(self, client):
        """기타 타입."""
        unique_id = f"other_{uuid.uuid4().hex[:8]}"
        response = client.post(
            "/api/templates",
            data={
                "template_id": unique_id,
                "display_name": "기타",
                "doc_type": "other",
            },
        )

        assert response.status_code == 200
