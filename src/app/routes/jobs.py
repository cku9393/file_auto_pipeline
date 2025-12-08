"""
Jobs Routes: 작업 조회 및 다운로드.

spec-v2.md Section 4.2:
- GET /jobs → 작업 목록
- GET /api/jobs → 작업 목록 API
- GET /api/jobs/<job_id> → 작업 상세
- GET /api/jobs/<job_id>/download/<file> → 파일 다운로드
- GET /api/jobs/<job_id>/download → ZIP 다운로드
"""

import json
import zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse

from src.domain.constants import JOB_DELIVERABLES_DIR, JOB_JSON_FILENAME, get_mime_type

# Routers
router = APIRouter()  # HTML pages
api_router = APIRouter()  # API endpoints


def get_jobs_root(request: Request) -> Path:
    """Request에서 jobs_root 경로 가져오기."""
    return request.app.state.jobs_root


# =============================================================================
# Page Routes (HTML)
# =============================================================================

@router.get("", response_class=HTMLResponse)
async def jobs_page(request: Request) -> HTMLResponse:
    """작업 목록 화면."""
    return HTMLResponse(content="""
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <title>작업 목록</title>
    <script src="https://unpkg.com/htmx.org@1.9.10"></script>
    <link rel="stylesheet" href="/static/css/style.css">
</head>
<body>
    <div class="container">
        <header>
            <h1>📋 작업 목록</h1>
            <a href="/generate" class="button">+ 새 작업</a>
        </header>

        <div id="job-list"
             hx-get="/api/jobs"
             hx-trigger="load"
             hx-swap="innerHTML">
            로딩 중...
        </div>
    </div>
</body>
</html>
    """)


@router.get("/{job_id}", response_class=HTMLResponse)
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
            <a href="/jobs" class="back-link">← 목록으로</a>
            <h1>📁 {job_id}</h1>
        </header>

        <div id="job-detail"
             hx-get="/api/jobs/{job_id}"
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

@api_router.get("")
async def list_jobs(
    request: Request,
    limit: int = 50,
    offset: int = 0,
) -> HTMLResponse:
    """
    작업 목록 (HTML 조각).

    HTMX용 부분 렌더링.
    """
    jobs_root = get_jobs_root(request)

    if not jobs_root.exists():
        return HTMLResponse(content="<p class='empty'>작업이 없습니다.</p>")

    # Job 폴더 스캔
    jobs: list[dict[str, Any]] = []
    for job_dir in sorted(jobs_root.iterdir(), reverse=True):
        if not job_dir.is_dir() or job_dir.name.startswith("."):
            continue

        job_id = job_dir.name
        job_json_path = job_dir / JOB_JSON_FILENAME

        # job.json에서 메타데이터 읽기
        meta: dict[str, Any] = {"job_id": job_id}
        if job_json_path.exists():
            try:
                data = json.loads(job_json_path.read_text(encoding="utf-8"))
                meta.update(data)
            except (json.JSONDecodeError, OSError):
                pass

        # deliverables 확인
        deliverables_dir = job_dir / JOB_DELIVERABLES_DIR
        if deliverables_dir.exists():
            meta["has_deliverables"] = any(deliverables_dir.iterdir())
        else:
            meta["has_deliverables"] = False

        jobs.append(meta)

    # 페이지네이션
    total = len(jobs)
    jobs = jobs[offset:offset + limit]

    if not jobs:
        return HTMLResponse(content="<p class='empty'>작업이 없습니다.</p>")

    html = f"<p class='count'>총 {total}개 작업</p>"
    html += "<ul class='job-list'>"
    for job in jobs:
        created = job.get("created_at", "")[:10] if job.get("created_at") else "-"
        wo_no = job.get("wo_no", "-")
        has_files = "✅" if job.get("has_deliverables") else "⏳"

        html += f"""
        <li>
            <a href="/jobs/{job['job_id']}">
                <strong>{job['job_id']}</strong>
                <span class="wo-no">WO: {wo_no}</span>
                <span class="created">{created}</span>
                <span class="status">{has_files}</span>
            </a>
        </li>
        """
    html += "</ul>"

    return HTMLResponse(content=html)


@api_router.get("/{job_id}")
async def get_job(
    request: Request,
    job_id: str,
) -> HTMLResponse:
    """작업 상세 (HTML 조각)."""
    jobs_root = get_jobs_root(request)
    job_dir = jobs_root / job_id

    if not job_dir.exists():
        raise HTTPException(status_code=404, detail={"code": "JOB_NOT_FOUND", "message": f"Job '{job_id}' not found"})

    # job.json 읽기
    job_json_path = job_dir / JOB_JSON_FILENAME
    meta: dict[str, Any] = {"job_id": job_id}
    if job_json_path.exists():
        try:
            data = json.loads(job_json_path.read_text(encoding="utf-8"))
            meta.update(data)
        except (json.JSONDecodeError, OSError):
            pass

    # deliverables 파일 목록
    deliverables: list[dict[str, Any]] = []
    deliverables_dir = job_dir / JOB_DELIVERABLES_DIR
    if deliverables_dir.exists():
        for f in sorted(deliverables_dir.iterdir()):
            if f.is_file():
                stat = f.stat()
                deliverables.append({
                    "name": f.name,
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                })

    # HTML 렌더링
    html = "<div class='job-info'>"
    html += f"<dl><dt>Job ID</dt><dd><code>{meta['job_id']}</code></dd></dl>"

    if meta.get("wo_no"):
        html += f"<dl><dt>Work Order</dt><dd>{meta['wo_no']}</dd></dl>"
    if meta.get("line"):
        html += f"<dl><dt>Line</dt><dd>{meta['line']}</dd></dl>"
    if meta.get("created_at"):
        html += f"<dl><dt>Created</dt><dd>{meta['created_at'][:19]}</dd></dl>"

    html += "</div>"

    # 파일 목록
    html += "<div class='deliverables'>"
    html += "<h3>생성된 파일</h3>"

    if deliverables:
        html += "<ul class='file-list'>"
        for f in deliverables:
            size_kb = f["size"] / 1024
            icon = "📄" if f["name"].endswith(".docx") else "📊" if f["name"].endswith(".xlsx") else "📁"
            html += f"""
            <li>
                {icon} <span class="filename">{f['name']}</span>
                <span class="size">{size_kb:.1f} KB</span>
                <a href="/api/jobs/{job_id}/download/{f['name']}" class="button small">다운로드</a>
            </li>
            """
        html += "</ul>"

        # ZIP 다운로드 버튼
        html += f"""
        <div class="zip-download">
            <a href="/api/jobs/{job_id}/download" class="button primary">📁 전체 다운로드 (ZIP)</a>
        </div>
        """
    else:
        html += "<p class='empty'>생성된 파일이 없습니다.</p>"

    html += "</div>"

    return HTMLResponse(content=html)


@api_router.get("/{job_id}/download/{filename}")
async def download_file(
    request: Request,
    job_id: str,
    filename: str,
) -> FileResponse:
    """개별 파일 다운로드."""
    jobs_root = get_jobs_root(request)
    job_dir = jobs_root / job_id

    if not job_dir.exists():
        raise HTTPException(status_code=404, detail={"code": "JOB_NOT_FOUND", "message": f"Job '{job_id}' not found"})

    file_path = job_dir / JOB_DELIVERABLES_DIR / filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail={"code": "FILE_NOT_FOUND", "message": f"File '{filename}' not found"})

    # 경로 순회 공격 방지 (symlink 포함)
    # resolve()는 symlink를 따라가므로, 실제 경로가 job_dir 내부인지 확인
    try:
        resolved = file_path.resolve(strict=True)
        resolved.relative_to(job_dir.resolve())
    except (ValueError, OSError):
        raise HTTPException(status_code=400, detail={"code": "INVALID_PATH", "message": "Invalid file path"})

    # symlink 자체를 명시적으로 차단
    if file_path.is_symlink():
        raise HTTPException(status_code=400, detail={"code": "SYMLINK_NOT_ALLOWED", "message": "Symbolic links are not allowed"})

    # MIME 타입 결정
    media_type = get_mime_type(filename)

    return FileResponse(
        path=file_path,
        filename=filename,
        media_type=media_type,
    )


@api_router.get("/{job_id}/download")
async def download_zip(
    request: Request,
    job_id: str,
) -> StreamingResponse:
    """전체 파일 ZIP 다운로드."""
    jobs_root = get_jobs_root(request)
    job_dir = jobs_root / job_id

    if not job_dir.exists():
        raise HTTPException(status_code=404, detail={"code": "JOB_NOT_FOUND", "message": f"Job '{job_id}' not found"})

    deliverables_dir = job_dir / JOB_DELIVERABLES_DIR
    if not deliverables_dir.exists():
        raise HTTPException(status_code=404, detail={"code": "NO_FILES", "message": "No deliverables to download"})

    # ZIP 파일 생성 (메모리에서)
    # 보안: deliverables만 포함, symlink 제외
    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in deliverables_dir.iterdir():
            # symlink 제외, 일반 파일만 포함
            if f.is_file() and not f.is_symlink():
                # 경로 검증: resolve된 경로가 deliverables_dir 내부인지 확인
                try:
                    f.resolve(strict=True).relative_to(deliverables_dir.resolve())
                    zf.write(f, arcname=f.name)
                except (ValueError, OSError):
                    continue  # 의심스러운 파일은 건너뜀

    zip_buffer.seek(0)

    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{job_id}.zip"',
        },
    )
