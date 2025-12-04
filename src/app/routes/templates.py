"""
Templates Routes: 템플릿 관리.

spec-v2.md Section 4.1:
- GET /templates → 템플릿 관리 화면
- GET /register → 템플릿 등록 화면
- API: CRUD
"""

from typing import Any

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse

# Routers
router = APIRouter()  # HTML pages
api_router = APIRouter()  # API endpoints


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
    # TODO: TemplateManager 연동
    templates = [
        {"template_id": "base", "display_name": "기본 템플릿", "status": "ready"},
    ]

    html = "<ul class='template-list'>"
    for t in templates:
        html += f"""
        <li>
            <strong>{t['display_name']}</strong>
            <span class="badge">{t['status']}</span>
            <code>{t['template_id']}</code>
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
    # TODO: TemplateManager + TemplateScaffolder 연동

    return {
        "success": True,
        "template_id": template_id,
        "message": f"템플릿 '{display_name}'이(가) 생성되었습니다.",
        "requires_review": True,
    }


@api_router.get("/{template_id}")
async def get_template(
    request: Request,
    template_id: str,
) -> dict[str, Any]:
    """템플릿 상세 조회."""
    # TODO: TemplateManager 연동

    return {
        "template_id": template_id,
        "display_name": "기본 템플릿",
        "doc_type": "inspection",
        "status": "ready",
    }


@api_router.patch("/{template_id}")
async def update_template_status(
    request: Request,
    template_id: str,
    status: str = Form(...),
) -> dict[str, Any]:
    """템플릿 상태 변경."""
    # TODO: TemplateManager 연동

    return {
        "success": True,
        "template_id": template_id,
        "status": status,
    }


@api_router.delete("/{template_id}")
async def delete_template(
    request: Request,
    template_id: str,
    force: bool = False,
) -> dict[str, Any]:
    """템플릿 삭제."""
    # TODO: TemplateManager 연동

    return {
        "success": True,
        "template_id": template_id,
        "message": f"템플릿 '{template_id}'이(가) 삭제되었습니다.",
    }
