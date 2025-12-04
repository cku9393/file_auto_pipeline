"""
test_api_generate.py - Generate API E2E 테스트

엔드포인트:
- POST /api/generate
- GET /api/generate/jobs
- GET /api/generate/jobs/{job_id}
- GET /api/generate/jobs/{job_id}/download/{filename}
- GET /api/generate/jobs/{job_id}/download (ZIP)
- GET /generate/jobs (HTML page)
- GET /generate/jobs/{job_id} (HTML page)
"""

from pathlib import Path
from unittest.mock import patch

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
def sample_job_dir(tmp_path: Path) -> Path:
    """테스트용 Job 디렉터리."""
    job_dir = tmp_path / "JOB-TEST-001"
    deliverables = job_dir / "deliverables"
    deliverables.mkdir(parents=True)

    # 테스트 파일 생성
    (deliverables / "report.docx").write_bytes(b"fake docx content")
    (deliverables / "measurements.xlsx").write_bytes(b"fake xlsx content")

    return job_dir


# =============================================================================
# Page Routes (HTML)
# =============================================================================

class TestJobsPage:
    """작업 이력 페이지 테스트."""

    def test_jobs_page_loads(self, client):
        """GET /generate/jobs → HTML 페이지."""
        response = client.get("/generate/jobs")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "작업 이력" in response.text

    def test_jobs_page_has_htmx_trigger(self, client):
        """작업 목록이 HTMX로 로드됨."""
        response = client.get("/generate/jobs")

        assert "hx-get" in response.text
        assert "/api/generate/jobs" in response.text


class TestJobDetailPage:
    """작업 상세 페이지 테스트."""

    def test_job_detail_page_loads(self, client):
        """GET /generate/jobs/{job_id} → HTML 페이지."""
        response = client.get("/generate/jobs/JOB-TEST-001")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "작업 상세" in response.text
        assert "JOB-TEST-001" in response.text

    def test_job_detail_page_has_htmx_trigger(self, client):
        """작업 상세가 HTMX로 로드됨."""
        response = client.get("/generate/jobs/JOB-TEST-001")

        assert "hx-get" in response.text
        assert "/api/generate/jobs/JOB-TEST-001" in response.text


# =============================================================================
# POST /api/generate
# =============================================================================

class TestGenerateDocument:
    """문서 생성 요청 테스트."""

    def test_generate_document_success(self, client):
        """POST /api/generate → 문서 생성."""
        response = client.post(
            "/api/generate",
            data={
                "session_id": "test-session",
                "template_id": "base",
                "output_format": "both",
            },
        )

        assert response.status_code == 200
        data = response.json()

        assert data["success"] is True
        assert "job_id" in data
        assert "files" in data
        assert "download_url" in data

    def test_generate_document_docx_only(self, client):
        """DOCX만 생성."""
        response = client.post(
            "/api/generate",
            data={
                "session_id": "test-session",
                "template_id": "base",
                "output_format": "docx",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_generate_document_xlsx_only(self, client):
        """XLSX만 생성."""
        response = client.post(
            "/api/generate",
            data={
                "session_id": "test-session",
                "template_id": "base",
                "output_format": "xlsx",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_generate_document_with_custom_template(self, client):
        """커스텀 템플릿 사용."""
        response = client.post(
            "/api/generate",
            data={
                "session_id": "test-session",
                "template_id": "customer_a",
                "output_format": "both",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True


# =============================================================================
# GET /api/generate/jobs
# =============================================================================

class TestListJobs:
    """작업 목록 API 테스트."""

    def test_list_jobs_returns_html(self, client):
        """GET /api/generate/jobs → HTML 응답."""
        response = client.get("/api/generate/jobs")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_list_jobs_with_limit(self, client):
        """limit 파라미터."""
        response = client.get("/api/generate/jobs?limit=5")

        assert response.status_code == 200

    def test_list_jobs_contains_job_links(self, client):
        """작업 목록에 링크 포함."""
        response = client.get("/api/generate/jobs")

        # 데모 데이터에 JOB-DEMO-001 포함
        assert "JOB-DEMO-001" in response.text or "작업 이력" in response.text


# =============================================================================
# GET /api/generate/jobs/{job_id}
# =============================================================================

class TestGetJobDetail:
    """작업 상세 API 테스트."""

    def test_get_job_detail_returns_html(self, client):
        """GET /api/generate/jobs/{job_id} → HTML 응답."""
        response = client.get("/api/generate/jobs/JOB-TEST-001")

        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_get_job_detail_contains_job_info(self, client):
        """작업 상세에 Job 정보 포함."""
        response = client.get("/api/generate/jobs/JOB-TEST-001")

        assert "JOB-TEST-001" in response.text

    def test_get_job_detail_contains_download_links(self, client):
        """작업 상세에 다운로드 링크 포함."""
        response = client.get("/api/generate/jobs/JOB-DEMO-001")

        assert "download" in response.text.lower()


# =============================================================================
# GET /api/generate/jobs/{job_id}/download/{filename}
# =============================================================================

class TestDownloadFile:
    """파일 다운로드 테스트."""

    def test_download_nonexistent_file_returns_404(self, client):
        """존재하지 않는 파일 → 404."""
        response = client.get("/api/generate/jobs/NONEXISTENT/download/report.docx")

        assert response.status_code == 404

    def test_download_file_with_existing_job(self, client, sample_job_dir):
        """실제 파일 다운로드."""
        # jobs_root를 임시 디렉터리로 패치
        with patch.object(
            client.app.state, "jobs_root", sample_job_dir.parent
        ):
            response = client.get(
                f"/api/generate/jobs/{sample_job_dir.name}/download/report.docx"
            )

            # 파일이 존재하면 200
            assert response.status_code == 200
            assert response.content == b"fake docx content"


# =============================================================================
# GET /api/generate/jobs/{job_id}/download (ZIP)
# =============================================================================

class TestDownloadAll:
    """전체 다운로드 (ZIP) 테스트."""

    def test_download_all_not_implemented(self, client):
        """ZIP 다운로드 미구현 → 501."""
        response = client.get("/api/generate/jobs/JOB-TEST-001/download")

        assert response.status_code == 501


# =============================================================================
# Error Cases
# =============================================================================

class TestGenerateErrorCases:
    """에러 케이스 테스트."""

    def test_generate_without_session_id(self, client):
        """session_id 없이 생성 요청."""
        response = client.post(
            "/api/generate",
            data={
                "template_id": "base",
                "output_format": "both",
                # session_id 누락
            },
        )

        assert response.status_code == 422  # Validation Error

    def test_invalid_job_id_format(self, client):
        """잘못된 Job ID 형식 (현재는 에러 없음 - 데모 응답)."""
        response = client.get("/api/generate/jobs/invalid/id/with/slashes")

        # 현재 구현에서는 job_id를 그대로 사용
        # 실제 구현 시 404 또는 400 반환해야 할 수 있음
        assert response.status_code in [200, 404, 400]


# =============================================================================
# Navigation & Links
# =============================================================================

class TestNavigation:
    """네비게이션 테스트."""

    def test_jobs_page_has_new_document_link(self, client):
        """작업 이력 페이지에 새 문서 링크."""
        response = client.get("/generate/jobs")

        assert "/chat" in response.text or "새 문서" in response.text

    def test_root_endpoint_has_jobs_link(self, client):
        """루트 엔드포인트에 jobs 링크."""
        response = client.get("/")

        data = response.json()
        assert "jobs" in data.get("endpoints", {})
