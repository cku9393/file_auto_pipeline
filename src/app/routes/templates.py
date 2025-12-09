"""
Templates Routes: 템플릿 관리.

spec-v2.md Section 4.1:
- GET /templates → 템플릿 관리 화면
- GET /register → 템플릿 등록 화면
- API: CRUD
"""

from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse

from src.templates.manager import TemplateError, TemplateManager, TemplateStatus

# Routers
router = APIRouter()  # HTML pages
api_router = APIRouter()  # API endpoints

# Template Manager 인스턴스
# 프로젝트 루트의 templates/ 디렉터리 사용
TEMPLATES_ROOT = Path(__file__).parent.parent.parent.parent / "templates"
template_manager = TemplateManager(TEMPLATES_ROOT)


# =============================================================================
# Page Routes (HTML)
# =============================================================================

@router.get("", response_class=HTMLResponse)
async def templates_page(request: Request) -> HTMLResponse:
    """템플릿 관리 화면."""
    return HTMLResponse(content="""
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <title>템플릿 관리</title>
    <script src="https://unpkg.com/htmx.org@1.9.10"></script>
    <link rel="stylesheet" href="/static/css/style.css">
</head>
<body>
    <div class="container">
        <header>
            <h1>📋 템플릿 관리</h1>
            <a href="/register" class="button">+ 새 템플릿</a>
        </header>

        <div id="template-list"
             hx-get="/api/templates"
             hx-trigger="load"
             hx-swap="innerHTML">
            로딩 중...
        </div>
    </div>
</body>
</html>
    """)


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request) -> HTMLResponse:
    """템플릿 등록 화면."""
    return HTMLResponse(content="""
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <title>템플릿 등록</title>
    <script src="https://unpkg.com/htmx.org@1.9.10"></script>
    <link rel="stylesheet" href="/static/css/style.css">
</head>
<body>
    <div class="container">
        <header>
            <h1>📄 템플릿 등록</h1>
        </header>

        <form hx-post="/api/templates"
              hx-encoding="multipart/form-data"
              hx-target="#result">

            <div class="form-group">
                <label>템플릿 ID</label>
                <input type="text" name="template_id"
                       placeholder="customer_a_inspection"
                       pattern="[a-z0-9_]+" required>
                <small>소문자, 숫자, 밑줄만 허용</small>
            </div>

            <div class="form-group">
                <label>표시 이름</label>
                <input type="text" name="display_name"
                       placeholder="고객사A 검사성적서" required>
            </div>

            <div class="form-group">
                <label>문서 타입</label>
                <select name="doc_type">
                    <option value="inspection">검사성적서</option>
                    <option value="report">보고서</option>
                    <option value="other">기타</option>
                </select>
            </div>

            <div class="form-group">
                <label>예시 Word 파일</label>
                <input type="file" name="example_docx" accept=".docx">
            </div>

            <div class="form-group">
                <label>예시 Excel 파일</label>
                <input type="file" name="example_xlsx" accept=".xlsx">
            </div>

            <button type="submit">분석 및 등록</button>
        </form>

        <div id="result"></div>
    </div>
</body>
</html>
    """)


# =============================================================================
# API Routes
# =============================================================================

@api_router.get("")
async def list_templates(
    request: Request,
    status: str | None = None,
) -> HTMLResponse:
    """
    템플릿 목록 (HTML 조각).

    HTMX용 부분 렌더링.
    """
    # 상태 필터링
    status_filter = None
    if status:
        try:
            status_filter = TemplateStatus(status)
        except ValueError:
            pass  # 잘못된 상태값은 무시

    # TemplateManager에서 목록 조회 (base + custom 전체)
    templates = template_manager.list_templates(category="all", status=status_filter)

    if not templates:
        return HTMLResponse(content="<p class='empty'>등록된 템플릿이 없습니다.</p>")

    html = "<ul class='template-list'>"
    for meta in templates:
        status_value = meta.status.value if isinstance(meta.status, TemplateStatus) else meta.status
        html += f"""
        <li>
            <strong>{meta.display_name}</strong>
            <span class="badge badge-{status_value}">{status_value}</span>
            <code>{meta.template_id}</code>
        </li>
        """
    html += "</ul>"

    return HTMLResponse(content=html)


@api_router.post("")
async def create_template(
    request: Request,
    template_id: str = Form(...),
    display_name: str = Form(...),
    doc_type: str = Form("inspection"),
    example_docx: UploadFile | None = File(None),
    example_xlsx: UploadFile | None = File(None),
) -> dict[str, Any]:
    """
    템플릿 등록.

    1. 폴더 생성
    2. source/ 에 예시 파일 저장
    3. 스캐폴딩 실행
    4. 결과 반환
    """
    try:
        # 1. 템플릿 폴더 생성
        template_manager.create(
            template_id=template_id,
            doc_type=doc_type,
            display_name=display_name,
            created_by="web_user",  # TODO: 실제 사용자 정보 연동
            description="",
        )

        # 2. source/에 예시 파일 저장 (불변 가드 적용)
        if example_docx and example_docx.filename:
            file_bytes = await example_docx.read()
            template_manager.save_source(template_id, file_bytes, example_docx.filename)

        if example_xlsx and example_xlsx.filename:
            file_bytes = await example_xlsx.read()
            template_manager.save_source(template_id, file_bytes, example_xlsx.filename)

        # 3. 스캐폴딩은 별도 프로세스로 진행 (수동 또는 자동)
        # TODO: TemplateScaffolder 연동 (ADR-0003 AI 파싱 레이어)

        return {
            "success": True,
            "template_id": template_id,
            "message": f"템플릿 '{display_name}'이(가) 생성되었습니다.",
            "status": "draft",
            "requires_review": True,
        }
    except TemplateError as e:
        raise HTTPException(status_code=400, detail={"code": e.code, "message": e.message}) from e


@api_router.get("/{template_id}")
async def get_template(
    request: Request,
    template_id: str,
) -> dict[str, Any]:
    """템플릿 상세 조회."""
    try:
        meta = template_manager.get_meta(template_id)
        return meta.to_dict()
    except TemplateError as e:
        raise HTTPException(status_code=404, detail={"code": e.code, "message": e.message}) from e


@api_router.patch("/{template_id}")
async def update_template_status(
    request: Request,
    template_id: str,
    status: str = Form(...),
    reviewed_by: str | None = Form(None),
) -> dict[str, Any]:
    """템플릿 상태 변경."""
    try:
        new_status = TemplateStatus(status)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_STATUS", "message": f"Invalid status: {status}"}
        ) from None

    try:
        meta = template_manager.update_status(template_id, new_status, reviewed_by)
        return {
            "success": True,
            "template_id": template_id,
            "status": meta.status.value,
            "updated_at": meta.updated_at,
        }
    except TemplateError as e:
        raise HTTPException(status_code=404, detail={"code": e.code, "message": e.message}) from e


@api_router.delete("/{template_id}")
async def delete_template(
    request: Request,
    template_id: str,
    force: bool = False,
) -> dict[str, Any]:
    """템플릿 삭제."""
    try:
        template_manager.delete(template_id, force=force)
        return {
            "success": True,
            "template_id": template_id,
            "message": f"템플릿 '{template_id}'이(가) 삭제되었습니다.",
        }
    except TemplateError as e:
        status_code = 404 if e.code == "TEMPLATE_NOT_FOUND" else 400
        raise HTTPException(status_code=status_code, detail={"code": e.code, "message": e.message}) from e
