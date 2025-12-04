"""
Generate Routes: 문서 생성 요청.

spec-v2.md Section 4.2:
- POST /api/generate → 최종 문서 생성 요청
- GET /jobs → 작업 이력
- GET /jobs/<job_id> → 작업 상세
"""

from typing import Any

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse

# Routers
router = APIRouter()  # HTML pages
api_router = APIRouter()  # API endpoints


# =============================================================================
# Page Routes (HTML)
# =============================================================================

@router.get("/jobs", response_class=HTMLResponse)
async def jobs_page(request: Request) -> HTMLResponse:
    """작업 이력 화면."""
    return HTMLResponse(content="""
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <title>작업 이력</title>
    <script src="https://unpkg.com/htmx.org@1.9.10"></script>
    <link rel="stylesheet" href="/static/css/style.css">
</head>
<body>
    <div class="container">
        <header>
            <h1>📁 작업 이력</h1>
            <a href="/chat" class="button">+ 새 문서</a>
        </header>

        <div id="job-list"
             hx-get="/api/generate/jobs"
             hx-trigger="load"
             hx-swap="innerHTML">
            로딩 중...
        </div>
    </div>
</body>
</html>
    """)


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_detail_page(request: Request, job_id: str) -> HTMLResponse:
    """작업 상세 화면."""
    return HTMLResponse(content=f"""
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <title>작업 상세 - {job_id}</title>
    <script src="https://unpkg.com/htmx.org@1.9.10"></script>
    <link rel="stylesheet" href="/static/css/style.css">
</head>
<body>
    <div class="container">
        <header>
            <h1>📄 작업 상세</h1>
            <code>{job_id}</code>
        </header>

        <div id="job-detail"
             hx-get="/api/generate/jobs/{job_id}"
             hx-trigger="load"
             hx-swap="innerHTML">
            로딩 중...
        </div>
    </div>
</body>
</html>
    """)


# =============================================================================
# API Routes
# =============================================================================

@api_router.post("")
async def generate_document(
    request: Request,
    session_id: str = Form(...),
    template_id: str = Form("base"),
    output_format: str = Form("both"),  # docx, xlsx, both
) -> dict[str, Any]:
    """
    최종 문서 생성 요청.

    Args:
        session_id: Intake 세션 ID
        template_id: 사용할 템플릿
        output_format: 출력 형식 (docx, xlsx, both)

    Returns:
        생성 결과 (job_id, files, download_url)
    """
    from pathlib import Path

    from src.app.services.intake import IntakeService
    from src.app.services.validate import ValidationService
    from src.render.excel import ExcelRenderer
    from src.render.word import DocxRenderer

    # 1. IntakeService에서 최종 필드 가져오기
    jobs_root: Path = request.app.state.jobs_root

    # Import session mapping from chat.py
    from src.app.routes.chat import _session_to_job

    if session_id not in _session_to_job:
        raise HTTPException(status_code=404, detail="Session not found")

    job_id = _session_to_job[session_id]
    job_dir = jobs_root / job_id

    intake = IntakeService(job_dir)
    session = intake.load_session()

    # Check if extraction was done
    if not session.extraction_result:
        raise HTTPException(
            status_code=400,
            detail="추출이 완료되지 않았습니다. /api/chat/extract를 먼저 호출하세요.",
        )

    # 2. ValidationService로 최종 검증
    definition_path = request.app.state.definition_path
    validation_service = ValidationService(definition_path)
    validation_result = validation_service.validate(
        fields=session.extraction_result.fields,
        measurements=session.extraction_result.measurements,
    )

    if not validation_result.valid:
        raise HTTPException(
            status_code=400,
            detail=f"검증 실패: {validation_result.missing_required}",
        )

    # 3. 템플릿 경로 설정
    templates_root = Path(__file__).parent.parent.parent.parent / "templates"
    template_dir = templates_root / template_id

    if not template_dir.exists():
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")

    docx_template = template_dir / "report_template.docx"
    xlsx_template = template_dir / "measurements_template.xlsx"

    # 4. Render (DOCX, XLSX)
    deliverables_dir = job_dir / "deliverables"
    deliverables_dir.mkdir(parents=True, exist_ok=True)

    files = []

    # Generate DOCX
    if output_format in ("docx", "both"):
        if not docx_template.exists():
            raise HTTPException(
                status_code=404,
                detail=f"DOCX template not found: {docx_template}",
            )

        docx_output = deliverables_dir / "report.docx"
        docx_renderer = DocxRenderer(docx_template)

        # Combine fields and measurements into data dict
        data = {
            **session.extraction_result.fields,
            "measurements": session.extraction_result.measurements,
        }

        docx_renderer.render(
            data=data,
            output_path=docx_output,
        )

        files.append({
            "name": "report.docx",
            "size": docx_output.stat().st_size,
            "path": str(docx_output.relative_to(jobs_root)),
        })

    # Generate XLSX
    if output_format in ("xlsx", "both"):
        if not xlsx_template.exists():
            raise HTTPException(
                status_code=404,
                detail=f"XLSX template not found: {xlsx_template}",
            )

        # Load manifest.yaml
        import yaml

        manifest_path = template_dir / "manifest.yaml"
        if not manifest_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Manifest not found: {manifest_path}",
            )

        with open(manifest_path) as f:
            manifest = yaml.safe_load(f)

        xlsx_output = deliverables_dir / "measurements.xlsx"
        xlsx_renderer = ExcelRenderer(xlsx_template, manifest)

        # Combine fields and measurements into data dict
        data = {
            **session.extraction_result.fields,
            "measurements": session.extraction_result.measurements,
        }

        xlsx_renderer.render(
            data=data,
            output_path=xlsx_output,
        )

        files.append({
            "name": "measurements.xlsx",
            "size": xlsx_output.stat().st_size,
            "path": str(xlsx_output.relative_to(jobs_root)),
        })

    # 5. 결과 반환
    return {
        "success": True,
        "job_id": job_id,
        "files": files,
        "download_url": f"/api/generate/jobs/{job_id}/download",
        "message": "문서가 생성되었습니다!",
    }


@api_router.get("/jobs")
async def list_jobs(
    request: Request,
    limit: int = 20,
) -> HTMLResponse:
    """
    작업 목록 (HTML 조각).

    HTMX용 부분 렌더링.
    """
    # TODO: jobs/ 폴더 스캔

    jobs = [
        {"job_id": "JOB-DEMO-001", "created_at": "2024-01-15", "status": "success"},
    ]

    html = "<ul class='job-list'>"
    for job in jobs:
        html += f"""
        <li>
            <a href="/jobs/{job['job_id']}">{job['job_id']}</a>
            <span class="badge">{job['status']}</span>
            <small>{job['created_at']}</small>
        </li>
        """
    html += "</ul>"

    if not jobs:
        html = "<p>작업 이력이 없습니다.</p>"

    return HTMLResponse(content=html)


@api_router.get("/jobs/{job_id}")
async def get_job_detail(
    request: Request,
    job_id: str,
) -> HTMLResponse:
    """
    작업 상세 (HTML 조각).
    """
    # TODO: job.json, run logs 로드

    html = f"""
    <div class="job-info">
        <h2>{job_id}</h2>
        <p>상태: <span class="badge">success</span></p>

        <h3>생성된 파일</h3>
        <ul>
            <li>
                <a href="/api/generate/jobs/{job_id}/download/report.docx">
                    📄 report.docx
                </a>
            </li>
            <li>
                <a href="/api/generate/jobs/{job_id}/download/measurements.xlsx">
                    📊 measurements.xlsx
                </a>
            </li>
        </ul>

        <a href="/api/generate/jobs/{job_id}/download" class="button">
            📁 전체 다운로드 (ZIP)
        </a>
    </div>
    """

    return HTMLResponse(content=html)


@api_router.get("/jobs/{job_id}/download/{filename}")
async def download_file(
    request: Request,
    job_id: str,
    filename: str,
) -> FileResponse:
    """
    개별 파일 다운로드.
    """
    # TODO: 실제 파일 경로 조회
    jobs_root = request.app.state.jobs_root
    file_path = jobs_root / job_id / "deliverables" / filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        path=file_path,
        filename=filename,
        media_type="application/octet-stream",
    )


@api_router.get("/jobs/{job_id}/download")
async def download_all(
    request: Request,
    job_id: str,
) -> FileResponse:
    """
    전체 파일 다운로드 (ZIP).
    """
    # TODO: ZIP 생성 및 반환
    raise HTTPException(status_code=501, detail="Not implemented yet")
