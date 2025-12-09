"""
Chat Routes: 대화형 문서 생성 (메인 기능).

spec-v2.md Section 4.3.1:
- GET /chat → 채팅 화면 (HTMX)
- GET /api/chat/stream → SSE 스트림
- POST /api/chat/message → 메시지 전송
- POST /api/chat/upload → 파일 첨부
"""

import asyncio
import json
import uuid
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse

from src.app.services.intake import IntakeService

# Routers
router = APIRouter()  # HTML pages
api_router = APIRouter()  # API endpoints

# Session storage (in-memory session_id -> job_id mapping)
# In production, this should use Redis or database
_session_to_job: dict[str, str] = {}


def get_or_create_intake(request: Request, session_id: str) -> IntakeService:
    """
    세션 ID에 대응하는 IntakeService 반환.

    새 세션이면 job 폴더 생성, 기존이면 로드.
    """
    jobs_root: Path = request.app.state.jobs_root

    # 기존 매핑 확인
    if session_id in _session_to_job:
        job_id = _session_to_job[session_id]
    else:
        # 새 Job ID 생성
        job_id = f"JOB-{uuid.uuid4().hex[:8].upper()}"
        _session_to_job[session_id] = job_id

    job_dir = jobs_root / job_id
    return IntakeService(job_dir)


# =============================================================================
# Page Routes (HTML)
# =============================================================================


@router.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request) -> HTMLResponse:
    """
    채팅 화면.

    TODO: Jinja2 템플릿으로 렌더링
    """
    return HTMLResponse(
        content="""
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>문서 생성 - 채팅</title>
    <script src="https://unpkg.com/htmx.org@1.9.10"></script>
    <script src="https://unpkg.com/htmx.org/dist/ext/sse.js"></script>
    <link rel="stylesheet" href="/static/css/style.css">
</head>
<body>
    <div class="chat-container">
        <header>
            <h1>📄 문서 생성</h1>
            <select id="template-select">
                <option value="base">기본 템플릿</option>
            </select>
        </header>

        <div id="chat-messages" class="messages">
            <div class="message assistant">
                안녕하세요! 문서 생성을 도와드릴게요.<br>
                작업 정보를 자유롭게 입력해주세요.<br>
                (엑셀, 사진, PDF 등 파일도 첨부 가능합니다)
            </div>
        </div>

        <form id="chat-form"
              hx-post="/api/chat/message"
              hx-target="#chat-messages"
              hx-swap="beforeend"
              hx-trigger="submit">
            <input type="hidden" name="session_id" id="session-id" value="">
            <div class="input-area">
                <textarea name="content"
                          placeholder="메시지 입력..."
                          rows="2"></textarea>
                <input type="file" id="file-input" multiple hidden>
                <button type="button" onclick="document.getElementById('file-input').click()">📎</button>
                <button type="submit">전송</button>
            </div>
            <div id="file-list" class="file-list"></div>
        </form>
    </div>

    <script src="/static/js/app.js"></script>
</body>
</html>
    """
    )


# =============================================================================
# API Routes
# =============================================================================


@api_router.get("/stream")
async def chat_stream(
    request: Request,
    session_id: str | None = None,
) -> StreamingResponse:
    """
    SSE 스트림 (실시간 응답).

    HTMX hx-sse 연동용.
    """

    async def event_generator() -> AsyncGenerator[str, None]:
        """SSE 이벤트 생성기."""
        # 연결 유지
        while True:
            # 클라이언트 연결 확인
            if await request.is_disconnected():
                break

            # Heartbeat
            yield f"event: heartbeat\ndata: {json.dumps({'time': 'now'})}\n\n"
            await asyncio.sleep(30)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@api_router.post("/message")
async def send_message(
    request: Request,
    content: str = Form(...),
    session_id: str | None = Form(None),
) -> HTMLResponse:
    """
    채팅 메시지 전송.

    Returns:
        새 메시지 HTML (HTMX swap용)
    """
    import html as html_escape

    # 세션 ID 생성/검증
    if not session_id:
        session_id = str(uuid.uuid4())

    # IntakeService 연동
    intake = get_or_create_intake(request, session_id)

    # 사용자 메시지 저장
    intake.add_message(role="user", content=content)

    # 어시스턴트 응답 생성 (TODO: 실제 LLM 연동)
    assistant_response = "메시지를 받았습니다. 분석 중..."

    # 어시스턴트 응답 저장
    intake.add_message(role="assistant", content=assistant_response)

    # Job ID 표시
    job_id = _session_to_job.get(session_id, "unknown")

    # HTML 이스케이프 처리
    safe_content = html_escape.escape(content)

    user_html = f"""
    <div class="message user">{safe_content}</div>
    """

    assistant_html = f"""
    <div class="message assistant">
        {assistant_response}<br>
        <small class="job-info">📁 Job: {job_id}</small>
    </div>
    """

    return HTMLResponse(content=user_html + assistant_html)


@api_router.post("/upload")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    session_id: str | None = Form(None),
) -> dict[str, Any]:
    """
    파일 첨부.

    이미지 파일인 경우:
    1. photos/raw/에 저장
    2. 슬롯 자동 매핑
    3. OCR 자동 실행

    Returns:
        업로드 결과 (filename, size, path, slot_mapped, ocr_result)
    """
    from src.app.services.ocr import OCRService
    from src.core.photos import PhotoService

    # 세션 ID 검증
    if not session_id:
        session_id = str(uuid.uuid4())

    # 파일 읽기
    file_bytes = await file.read()
    filename = file.filename or "unknown"

    # IntakeService 연동
    intake = get_or_create_intake(request, session_id)

    # Job ID
    job_id = _session_to_job.get(session_id, "unknown")
    jobs_root: Path = request.app.state.jobs_root
    job_dir = jobs_root / job_id
    definition_path: Path = request.app.state.definition_path

    # 이미지 파일인지 확인
    file_ext = Path(filename).suffix.lower()
    photo_extensions = {".jpg", ".jpeg", ".png"}
    ocr_extensions = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".pdf"}

    slot_key: str | None = None
    raw_path: str | None = None

    # 사진 슬롯 매핑 처리
    if file_ext in photo_extensions:
        photo_service = PhotoService(job_dir, definition_path)

        # 파일명으로 슬롯 매칭 시도
        matched_slot = photo_service.match_slot_for_file(filename)

        # raw/에 저장
        saved_path = photo_service.save_upload(filename, file_bytes)
        raw_path = str(saved_path)

        if matched_slot:
            # 슬롯 매핑 기록
            intake.add_photo_mapping(
                slot_key=matched_slot.key,
                filename=filename,
                raw_path=str(saved_path.relative_to(job_dir)),
            )
            slot_key = matched_slot.key

            # 어시스턴트 메시지
            intake.add_message(
                role="assistant",
                content=f"📷 사진이 '{matched_slot.key}' 슬롯에 매핑되었습니다.",
            )
        else:
            # 슬롯 미매칭 - 일반 사진으로 저장됨
            intake.add_message(
                role="assistant",
                content=f"📷 사진이 저장되었습니다. (슬롯 미매칭: {filename})",
            )

        # 파일 첨부 메시지
        intake.add_message(
            role="user",
            content=f"[사진 첨부: {filename}]",
            attachments=[(filename, file_bytes)],
        )
    else:
        # 비-사진 파일은 기존 로직 유지
        intake.add_message(
            role="user",
            content=f"[파일 첨부: {filename}]",
            attachments=[(filename, file_bytes)],
        )

    # OCR 처리 (이미지/PDF)
    ocr_result = None
    if file_ext in ocr_extensions:
        try:
            config = request.app.state.config
            ocr_service = OCRService(config)
            ocr_result = await ocr_service.extract_from_bytes(file_bytes, file_ext)

            # OCR 결과를 intake_session.json에 저장
            intake.add_ocr_result(filename, ocr_result)

            # 사용자에게 OCR 결과 메시지 전달
            user_message = ocr_service.get_user_message(ocr_result)
            intake.add_message(
                role="assistant",
                content=user_message,
            )

        except Exception as e:
            # OCR 실패 시에도 파일은 저장되도록
            intake.add_message(
                role="assistant",
                content=f"OCR 처리 중 오류가 발생했습니다: {str(e)}",
            )

    return {
        "success": True,
        "filename": filename,
        "size": len(file_bytes),
        "session_id": session_id,
        "job_id": job_id,
        "message": "파일이 업로드되었습니다.",
        "slot_mapped": slot_key,
        "raw_path": raw_path,
        "ocr_executed": ocr_result is not None,
        "ocr_success": ocr_result.success if ocr_result else None,
    }


@api_router.post("/extract")
async def extract_fields(
    request: Request,
    session_id: str = Form(...),
) -> dict[str, Any]:
    """
    필드 추출 요청.

    전체 흐름: 입력 수집 → OCR → 추출 → 검증

    Returns:
        추출 결과 (fields, measurements, missing, warnings, validation)
    """
    from src.app.services.extract import ExtractionService
    from src.app.services.validate import ValidationService

    # IntakeService 연동
    intake = get_or_create_intake(request, session_id)
    session = intake.load_session()

    # 모든 메시지 수집
    user_messages = [m.content for m in session.messages if m.role == "user"]
    user_input = "\n".join(user_messages)

    # OCR 결과 수집
    ocr_texts = [
        result.text
        for result in session.ocr_results.values()
        if result.success and result.text
    ]
    ocr_text = "\n".join(ocr_texts) if ocr_texts else None

    # ExtractionService 실행
    try:
        config = request.app.state.config
        definition_path = request.app.state.definition_path
        prompts_dir = Path(__file__).parent.parent.parent.parent / "prompts"

        extraction_service = ExtractionService(
            config=config,
            definition_path=definition_path,
            prompts_dir=prompts_dir,
        )

        extraction_result = await extraction_service.extract(
            user_input=user_input,
            ocr_text=ocr_text,
        )

        # 추출 결과 저장
        intake.add_extraction_result(extraction_result)

        # ValidationService 실행
        validation_service = ValidationService(definition_path)
        validation_result = validation_service.validate(
            fields=extraction_result.fields,
            measurements=extraction_result.measurements,
        )

        return {
            "success": True,
            "fields": extraction_result.fields,
            "measurements": extraction_result.measurements,
            "missing_fields": extraction_result.missing_fields,
            "warnings": extraction_result.warnings,
            "confidence": extraction_result.confidence,
            "model_used": extraction_result.model_used,
            "validation": {
                "valid": validation_result.valid,
                "missing_required": validation_result.missing_required,
                "invalid_values": validation_result.invalid_values,
                "overridable": validation_result.overridable,
            },
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "fields": {},
            "measurements": [],
            "missing_fields": [],
            "warnings": [f"Extraction failed: {e}"],
        }


@api_router.post("/override")
async def apply_override(
    request: Request,
    session_id: str = Form(...),
    field: str = Form(...),
    reason: str = Form(...),
) -> dict[str, Any]:
    """
    Override 적용.

    Args:
        field: 필드명 또는 사진 슬롯
        reason: Override 사유

    Returns:
        적용 결과
    """
    # TODO: ValidationService 연동

    return {
        "success": True,
        "field": field,
        "reason": reason,
        "message": f"'{field}' 필드가 생략되었습니다.",
    }
