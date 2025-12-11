"""
Chat Routes: 대화형 문서 생성 (메인 기능).

spec-v2.md Section 4.3.1:
- GET /chat → 채팅 화면 (HTMX)
- GET /api/chat/stream → SSE 스트림
- POST /api/chat/message → 메시지 전송
- POST /api/chat/upload → 파일 첨부
"""

import asyncio
import html as html_escape_module
import json
import time
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from src.app.services.intake import IntakeService
from src.core.ssot_job import atomic_write_json_exclusive
from src.templates.manager import TemplateManager

# Jinja2 템플릿 설정
_templates_dir = Path(__file__).parent.parent / "templates"
jinja_templates = (
    Jinja2Templates(directory=_templates_dir) if _templates_dir.exists() else None
)

# Routers
router = APIRouter()  # HTML pages
api_router = APIRouter()  # API endpoints

# Session storage (in-memory cache - disk is source of truth)
_session_to_job: dict[str, str] = {}

# Default timeout for extraction (seconds)
DEFAULT_EXTRACTION_TIMEOUT = 60.0


# =============================================================================
# Session-Job Mapping Persistence
# =============================================================================


def _get_sessions_dir(jobs_root: Path) -> Path:
    """세션 매핑 저장 디렉토리."""
    sessions_dir = jobs_root / "_sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    return sessions_dir


def _load_session_mapping(jobs_root: Path, session_id: str) -> str | None:
    """
    디스크에서 세션-잡 매핑 로드.

    Returns:
        job_id if found, None otherwise
    """
    session_file = _get_sessions_dir(jobs_root) / f"{session_id}.json"
    if session_file.exists():
        try:
            data = json.loads(session_file.read_text(encoding="utf-8"))
            job_id = data.get("job_id")
            return str(job_id) if job_id is not None else None
        except (json.JSONDecodeError, OSError):
            return None
    return None


def _save_session_mapping(jobs_root: Path, session_id: str, job_id: str) -> str:
    """
    세션-잡 매핑을 디스크에 원자적으로 저장 (TOCTOU-safe).

    O_EXCL 패턴으로 경합 윈도우를 제거:
    - 파일이 없으면: 새로 생성하고 job_id 반환
    - 파일이 있으면: 기존 job_id를 읽어서 반환 (덮어쓰지 않음)

    경합 시나리오:
    1. Thread A: O_EXCL 성공 → 파일 쓰기 시작
    2. Thread B: O_EXCL 실패 → 파일 읽기 시도
    3. Thread B: 파일이 아직 쓰기 중 → 재시도

    Args:
        jobs_root: jobs 루트 디렉토리
        session_id: 세션 ID
        job_id: 새로 생성할 Job ID (이미 존재하면 무시됨)

    Returns:
        실제 사용할 job_id (새로 생성됐거나 기존 값)
    """
    session_file = _get_sessions_dir(jobs_root) / f"{session_id}.json"

    now = datetime.now(UTC).isoformat()
    data = {
        "session_id": session_id,
        "job_id": job_id,
        "created_at": now,
        "updated_at": now,
    }

    # O_EXCL: 원자적으로 "존재 확인 + 생성"
    if atomic_write_json_exclusive(session_file, data):
        # 새로 생성됨 → 전달받은 job_id 사용
        return job_id

    # 이미 존재 → 기존 job_id 읽어서 반환 (재시도 로직으로 쓰기 완료 대기)
    # 경합 시 다른 스레드가 파일 쓰기를 완료할 때까지 짧게 대기
    max_retries = 10
    retry_delay = 0.01  # 10ms

    for _attempt in range(max_retries):
        existing_job_id = _load_session_mapping(jobs_root, session_id)
        if existing_job_id:
            return existing_job_id
        # 파일이 존재하지만 아직 쓰기가 완료되지 않음 → 잠시 대기 후 재시도
        time.sleep(retry_delay)

    # 최대 재시도 후에도 실패 (매우 드문 경우)
    # 마지막으로 한 번 더 시도
    existing_job_id = _load_session_mapping(jobs_root, session_id)
    if existing_job_id:
        return existing_job_id

    # 정말 실패 시 에러 발생 (데이터 무결성 보장)
    raise RuntimeError(
        f"세션 매핑 경합 실패: session_id={session_id}. "
        f"파일이 존재하지만 읽기 실패."
    )


def get_or_create_intake(request: Request, session_id: str) -> IntakeService:
    """
    세션 ID에 대응하는 IntakeService 반환.

    새 세션이면 job 폴더 생성, 기존이면 로드.
    디스크가 source of truth, 메모리는 캐시.

    TOCTOU-safe: O_EXCL 패턴으로 경합 시에도 동일 job_id 보장.
    """
    jobs_root: Path = request.app.state.jobs_root
    job_id: str  # 최종적으로 항상 str이 됨

    # 1. 메모리 캐시 확인
    if session_id in _session_to_job:
        job_id = _session_to_job[session_id]
    else:
        # 2. 디스크에서 로드 시도
        loaded_job_id = _load_session_mapping(jobs_root, session_id)

        if loaded_job_id is None:
            # 3. 새 Job ID 생성 시도 (TOCTOU-safe)
            candidate_job_id = f"JOB-{uuid.uuid4().hex[:8].upper()}"
            # _save_session_mapping이 실제 사용할 job_id를 반환
            # (경합 시 기존 job_id, 아니면 candidate_job_id)
            job_id = _save_session_mapping(jobs_root, session_id, candidate_job_id)
        else:
            job_id = loaded_job_id

        # 캐시 업데이트
        _session_to_job[session_id] = job_id

    job_dir = jobs_root / job_id
    return IntakeService(job_dir)


def get_job_id_for_session(request: Request, session_id: str) -> str:
    """세션 ID에 대응하는 Job ID 반환."""
    jobs_root: Path = request.app.state.jobs_root

    # 메모리 캐시 우선
    if session_id in _session_to_job:
        return _session_to_job[session_id]

    # 디스크에서 로드
    job_id = _load_session_mapping(jobs_root, session_id)
    if job_id:
        _session_to_job[session_id] = job_id
        return job_id

    return "unknown"


# =============================================================================
# HTML Generation Helpers
# =============================================================================


def escape_html(text: str) -> str:
    """HTML 이스케이프."""
    return html_escape_module.escape(text)


def build_user_message_html(content: str) -> str:
    """사용자 메시지 HTML 생성."""
    return f'<div class="message user">{escape_html(content)}</div>'


def build_assistant_message_html(content: str, job_id: str | None = None) -> str:
    """
    어시스턴트 메시지 HTML 생성.

    Args:
        content: 메시지 내용 (HTML 허용 - 이미 escape된 것으로 가정하거나 safe HTML)
        job_id: Job ID (있으면 표시)
    """
    job_info = ""
    if job_id:
        job_info = f'<br><small class="job-info">📁 Job: {escape_html(job_id)}</small>'

    return f"""<div class="message assistant">
        {content}{job_info}
    </div>"""


def build_oob_session_input(session_id: str) -> str:
    """HTMX OOB session_id hidden input 생성."""
    return f'''<input type="hidden" name="session_id" id="session-id"
           value="{escape_html(session_id)}" hx-swap-oob="true">'''


# =============================================================================
# Page Routes (HTML)
# =============================================================================


@router.get("/chat", response_class=HTMLResponse)
async def chat_page(request: Request) -> HTMLResponse:
    """
    채팅 화면.

    Jinja2 템플릿으로 렌더링.
    템플릿 목록은 HTMX로 동적 로딩 (/api/chat/templates/options).
    """
    # 세션 ID 생성 (새 세션)
    session_id = str(uuid.uuid4())

    # Jinja2 템플릿 사용
    if jinja_templates:
        return jinja_templates.TemplateResponse(
            "chat.html",
            {
                "request": request,
                "session_id": session_id,
            },
        )

    # Fallback: Jinja2 템플릿이 없는 경우 기본 HTML
    return HTMLResponse(
        content=f"""
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>문서 생성 - 채팅</title>
    <script src="https://unpkg.com/htmx.org@1.9.10"></script>
    <link rel="stylesheet" href="/static/css/style.css">
</head>
<body>
    <div class="chat-container">
        <header>
            <h1>📄 문서 생성</h1>
            <select id="template-select"
                    hx-get="/api/chat/templates/options"
                    hx-trigger="load"
                    hx-swap="innerHTML">
                <option value="base">로딩 중...</option>
            </select>
        </header>
        <div id="chat-messages" class="messages">
            <div class="message assistant">
                안녕하세요! 문서 생성을 도와드릴게요.
            </div>
        </div>
        <input type="hidden" id="session-id" name="session_id" value="{session_id}">
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
    content: str = Form(...),  # 필수 필드: 없으면 422 (빈 문자열은 허용, 내부에서 처리)
    session_id: str | None = Form(None),
) -> HTMLResponse:
    """
    채팅 메시지 전송 + 동기 분석(추출/검증) 수행.

    Returns:
        새 메시지 HTML (HTMX swap용) + session_id OOB 업데이트
    """
    from src.app.services.extract import ExtractionService
    from src.app.services.validate import ValidationService

    # 1) 세션 ID 생성/유지
    if not session_id:
        session_id = str(uuid.uuid4())

    # 빈 content 방어: 422 대신 친절한 메시지 반환
    if not content or not content.strip():
        oob_session = build_oob_session_input(session_id)
        return HTMLResponse(
            content=(
                '<div class="message assistant">'
                "메시지를 입력해주세요. 📝"
                "</div>" + oob_session
            )
        )

    # IntakeService 연동
    intake = get_or_create_intake(request, session_id)

    # 사용자 메시지 저장
    intake.add_message(role="user", content=content)

    # Job ID 표시
    job_id = get_job_id_for_session(request, session_id)

    # 2) 분석(추출+검증)을 여기서 실제로 수행
    assistant_response: str
    try:
        session = intake.load_session()

        # 모든 사용자 메시지 수집
        user_messages = [m.content for m in session.messages if m.role == "user"]
        user_input = "\n".join(user_messages)

        # OCR 결과 수집
        ocr_texts = [
            r.text for r in session.ocr_results.values() if r.success and r.text
        ]
        has_ocr = bool(ocr_texts)

        # 입력이 너무 빈약하면 LLM 호출 없이 안내 메시지 반환
        # (비용 절약 + 불필요한 에러 방지)
        total_input_length = len(user_input) + sum(len(t) for t in ocr_texts)
        if total_input_length < 20 and not has_ocr:
            assistant_response = (
                "문서 생성에 필요한 정보를 입력해주세요 📋<br><br>"
                "<b>필수 정보:</b><br>"
                "• WO 번호 (작업지시 번호)<br>"
                "• 라인 (L1, L2 등)<br>"
                "• 판정 결과 (PASS/FAIL)<br><br>"
                "<b>선택 정보:</b><br>"
                "• 측정값, 비고, 사진 등<br><br>"
                "예: <i>WO-2024-001, L1라인, 합격, 측정값 3.5mm</i>"
            )
            intake.add_message(role="assistant", content=assistant_response)
            user_html = build_user_message_html(content)
            assistant_html = build_assistant_message_html(assistant_response, job_id)
            oob_session = build_oob_session_input(session_id)
            return HTMLResponse(content=user_html + assistant_html + oob_session)

        # OCR 텍스트 결합
        ocr_text = "\n".join(ocr_texts) if ocr_texts else None

        # 서비스 초기화
        config = request.app.state.config
        definition_path: Path = request.app.state.definition_path
        prompts_dir = Path(__file__).parent.parent.parent.parent / "prompts"

        extraction_service = ExtractionService(
            config=config,
            definition_path=definition_path,
            prompts_dir=prompts_dir,
        )

        # 타임아웃 설정
        timeout = config.get("ai", {}).get(
            "extraction_timeout", DEFAULT_EXTRACTION_TIMEOUT
        )

        # 추출 실행 (타임아웃 적용)
        try:
            extraction_result = await asyncio.wait_for(
                extraction_service.extract(
                    user_input=user_input,
                    ocr_text=ocr_text,
                ),
                timeout=timeout,
            )
        except TimeoutError:
            assistant_response = (
                "분석 시간 초과 ⏱️<br>"
                "외부 AI 서비스 응답이 지연되고 있습니다.<br>"
                "잠시 후 다시 시도해주세요."
            )
            intake.add_message(role="assistant", content=assistant_response)
            user_html = build_user_message_html(content)
            assistant_html = build_assistant_message_html(assistant_response, job_id)
            oob_session = build_oob_session_input(session_id)
            return HTMLResponse(content=user_html + assistant_html + oob_session)

        intake.add_extraction_result(extraction_result)

        # result 필드 노멀라이저 적용 (LLM이 긴 문장 넣은 경우 전처리)
        from src.app.services.validate import normalize_result_field

        normalize_result_field(extraction_result.fields)

        # 검증 실행
        validation_service = ValidationService(definition_path)
        validation = validation_service.validate(
            fields=extraction_result.fields,
            measurements=extraction_result.measurements,
        )

        # 결과에 따른 응답 생성
        if validation.valid:
            assistant_response = (
                "분석 완료 ✅<br>"
                f"- 추출된 필드: {len(extraction_result.fields)}개<br>"
                f"- 누락 필수값: 없음<br>"
                f"- 경고: {len(validation.warnings)}개"
            )
        else:
            missing = (
                ", ".join(validation.missing_required)
                if validation.missing_required
                else "없음"
            )
            assistant_response = (
                "분석 결과 ⚠️<br>"
                f"- 추출된 필드: {len(extraction_result.fields)}개<br>"
                f"- 누락 필수값: {escape_html(missing)}<br>"
                "누락값을 채워주시거나 override 해주세요."
            )

    except TimeoutError:
        # 이미 위에서 처리됨 - 안전장치
        assistant_response = (
            "분석 시간 초과 ⏱️<br>외부 AI 서비스 응답이 지연되고 있습니다."
        )
    except Exception as e:
        # 에러 유형별 사용자 친화적 메시지
        error_msg = str(e)
        if "api_key" in error_msg.lower() or "authentication" in error_msg.lower():
            assistant_response = (
                "분석 실패 ❌<br>"
                "API 인증 문제가 발생했습니다.<br>"
                "관리자에게 문의해주세요."
            )
        elif "rate" in error_msg.lower() or "limit" in error_msg.lower():
            assistant_response = (
                "분석 실패 ❌<br>"
                "API 호출 한도에 도달했습니다.<br>"
                "잠시 후 다시 시도해주세요."
            )
        else:
            # 보안: raw 에러 전체 노출 금지
            assistant_response = (
                f"분석 실패 ❌<br>오류가 발생했습니다: {escape_html(error_msg[:100])}"
            )

    # 어시스턴트 응답 저장
    intake.add_message(role="assistant", content=assistant_response)

    # HTML 생성
    user_html = build_user_message_html(content)
    assistant_html = build_assistant_message_html(assistant_response, job_id)
    oob_session = build_oob_session_input(session_id)

    return HTMLResponse(content=user_html + assistant_html + oob_session)


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
        업로드 결과 (filename, size, path, slot_mapped, ocr_result, messages_html)
    """
    from src.app.services.ocr import OCRService
    from src.core.photos import PhotoService

    # 세션 ID 검증
    if not session_id:
        session_id = str(uuid.uuid4())

    # 파일 읽기
    file_bytes = await file.read()
    filename = file.filename or "unknown"
    safe_filename = escape_html(filename)

    # IntakeService 연동
    intake = get_or_create_intake(request, session_id)

    # Job ID
    job_id = get_job_id_for_session(request, session_id)
    jobs_root: Path = request.app.state.jobs_root
    job_dir = jobs_root / job_id
    definition_path: Path = request.app.state.definition_path

    # 이미지 파일인지 확인
    file_ext = Path(filename).suffix.lower()
    photo_extensions = {".jpg", ".jpeg", ".png"}
    ocr_extensions = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".pdf"}
    template_extensions = {".docx", ".dotx", ".odt"}  # 템플릿 후보 파일

    slot_key: str | None = None
    raw_path: str | None = None

    # UI에 표시할 HTML 메시지 조각들
    html_parts: list[str] = []

    # 사진 슬롯 매핑 처리
    if file_ext in photo_extensions:
        photo_service = PhotoService(job_dir, definition_path)

        # 파일명으로 슬롯 매칭 시도
        matched_slot = photo_service.match_slot_for_file(filename)

        # raw/에 저장
        saved_path = photo_service.save_upload(filename, file_bytes)
        raw_path = str(saved_path)

        # 사용자 메시지: [사진 첨부: ...]
        user_content = f"[사진 첨부: {filename}]"
        intake.add_message(
            role="user",
            content=user_content,
            attachments=[(filename, file_bytes)],
        )
        html_parts.append(build_user_message_html(user_content))

        if matched_slot:
            # 슬롯 매핑 기록
            intake.add_photo_mapping(
                slot_key=matched_slot.key,
                filename=filename,
                raw_path=str(saved_path.relative_to(job_dir)),
            )
            slot_key = matched_slot.key

            # 어시스턴트 메시지
            slot_msg = (
                f"📷 사진이 '{escape_html(matched_slot.key)}' 슬롯에 매핑되었습니다."
            )
            intake.add_message(role="assistant", content=slot_msg)
            html_parts.append(build_assistant_message_html(slot_msg))
        else:
            # 슬롯 미매칭 - 일반 사진으로 저장됨
            slot_msg = f"📷 사진이 저장되었습니다. (슬롯 미매칭: {safe_filename})"
            intake.add_message(role="assistant", content=slot_msg)
            html_parts.append(build_assistant_message_html(slot_msg))

    else:
        # 비-사진 파일
        user_content = f"[파일 첨부: {filename}]"
        intake.add_message(
            role="user",
            content=user_content,
            attachments=[(filename, file_bytes)],
        )
        html_parts.append(build_user_message_html(user_content))

    # OCR 처리 (이미지/PDF)
    ocr_result = None
    ocr_detail_msg: str | None = None

    if file_ext in ocr_extensions:
        try:
            config = request.app.state.config

            # OCR 타임아웃 적용
            ocr_timeout = config.get("ai", {}).get("ocr_timeout", 30.0)
            ocr_service = OCRService(config)

            try:
                ocr_result = await asyncio.wait_for(
                    ocr_service.extract_from_bytes(file_bytes, file_ext),
                    timeout=ocr_timeout,
                )
            except TimeoutError:
                ocr_detail_msg = (
                    f"OCR 시간 초과 ⏱️<br>"
                    f"파일 '{safe_filename}'의 텍스트 추출이 지연되고 있습니다."
                )
                intake.add_message(role="assistant", content=ocr_detail_msg)
                html_parts.append(build_assistant_message_html(ocr_detail_msg))
            else:
                # OCR 결과를 intake_session.json에 저장
                intake.add_ocr_result(filename, ocr_result)

                # 사용자에게 OCR 결과 메시지 전달
                ocr_detail_msg = ocr_service.get_user_message(ocr_result)
                intake.add_message(role="assistant", content=ocr_detail_msg)
                html_parts.append(build_assistant_message_html(ocr_detail_msg))

        except Exception as e:
            # OCR 실패 시에도 파일은 저장되도록
            error_msg = escape_html(str(e)[:100])
            ocr_detail_msg = f"OCR 처리 중 오류가 발생했습니다: {error_msg}"
            intake.add_message(role="assistant", content=ocr_detail_msg)
            html_parts.append(build_assistant_message_html(ocr_detail_msg))

    # Job ID 표시 (완료 메시지 추가)
    if html_parts:
        complete_msg = f"📁 Job: {escape_html(job_id)} - 업로드 완료"
        html_parts.append(
            f'<div class="message assistant upload-complete">'
            f'<small class="job-info">{complete_msg}</small></div>'
        )

    # 템플릿 후보 파일(.docx 등)이면 "템플릿으로 등록" 버튼 노출
    can_register_as_template = file_ext in template_extensions
    suggested_template_id: str | None = None
    suggested_display_name: str | None = None

    if can_register_as_template:
        # 파일명에서 템플릿 ID 후보 생성 (확장자 제거, 소문자화, 특수문자→언더스코어)
        import re

        stem = Path(filename).stem
        suggested_template_id = re.sub(r"[^a-z0-9]+", "_", stem.lower()).strip("_")
        suggested_display_name = stem

        # 템플릿 등록 버튼 HTML (HTMX로 모달 열기)
        template_btn_html = f"""
        <div class="message assistant template-register-prompt">
            <p>📝 이 파일을 템플릿으로 등록할 수 있습니다.</p>
            <button type="button"
                    class="btn btn-primary"
                    onclick="openTemplateRegisterModal('{escape_html(session_id)}', '{safe_filename}', '{escape_html(suggested_template_id)}', '{escape_html(suggested_display_name)}')">
                📋 템플릿으로 등록
            </button>
        </div>
        """
        html_parts.append(template_btn_html)

    # 전체 HTML 조립
    messages_html = "\n".join(html_parts)

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
        "ocr_text_preview": (
            ocr_result.text[:200] + "..."
            if ocr_result and ocr_result.text and len(ocr_result.text) > 200
            else (ocr_result.text if ocr_result else None)
        ),
        "messages_html": messages_html,
        # 템플릿 등록 가능 여부
        "can_register_as_template": can_register_as_template,
        "suggested_template_id": suggested_template_id
        if can_register_as_template
        else None,
        "suggested_display_name": suggested_display_name
        if can_register_as_template
        else None,
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

        # result 필드 노멀라이저 적용
        from src.app.services.validate import normalize_result_field

        normalize_result_field(extraction_result.fields)

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


@api_router.get("/templates/options", response_class=HTMLResponse)
async def get_template_options(request: Request) -> HTMLResponse:
    """
    템플릿 목록을 <option> HTML로 반환.

    HTMX hx-trigger="load"로 동적 로딩하여 사용.
    """
    from src.templates.manager import TemplateStatus

    templates_root: Path = request.app.state.templates_root
    template_manager = TemplateManager(templates_root)

    # READY 상태 템플릿만 조회 (draft, archived 제외)
    template_list = template_manager.list_templates(
        category="all",
        status=TemplateStatus.READY,
    )

    # <option> HTML 생성
    options = ['<option value="base">기본 템플릿</option>']
    for tmpl in template_list:
        tid = escape_html(tmpl.template_id)
        name = escape_html(tmpl.display_name)
        options.append(f'<option value="{tid}">{name}</option>')

    return HTMLResponse(content="\n".join(options))
