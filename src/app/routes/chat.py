"""
Chat Routes: 대화형 문서 생성 (메인 기능).

spec-v2.md Section 4.3.1:
- GET /chat → 채팅 화면 (HTMX)
- GET /api/chat/stream → SSE 스트림
- POST /api/chat/message → 메시지 전송
- POST /api/chat/upload → 파일 첨부

## 테스트 전용 파라미터 원칙 (_debug 등)

`_debug` 같은 테스트 전용 파라미터는 **내부 함수 인자로만** 노출한다.
FastAPI 라우트에서 Query/Form 파라미터로 절대 받지 말 것.

이유:
- 외부에서 켜면 응답 스키마가 달라져 캐싱/비교/골든테스트가 꼬임
- API 계약 문서에 디버그 필드가 섞이면 클라이언트가 의존하게 됨
- 보안 리뷰에서 "왜 디버그가 응답에?" 지적 대상
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
        f"세션 매핑 경합 실패: session_id={session_id}. 파일이 존재하지만 읽기 실패."
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
# Validation Error HTML Generation
# =============================================================================


def build_validation_error_html(
    validation: "ValidationResult",
    *,
    measurement_issues: dict[str, list[str]] | None = None,
) -> str:
    """
    검증 오류/경고를 카드 형태 HTML로 생성.

    Args:
        validation: ValidationResult 객체
        measurement_issues: 측정값 관련 이슈 {
            "empty_measured": ["row 0", "row 2"],  # 빈 측정값
            "nan_inf": ["row 1"],  # NaN/Inf 값
        }

    Returns:
        HTML string (여러 항목을 카드 형태로 렌더)
        빈 문자열 반환 시 문제 없음

    리스크 방어:
    - getattr로 ValidationResult 스키마 변화에 안전
    - override 실패는 별도 섹션으로 분리 (입력 검증과 구분)
    - result 필드 중복 방지 (missing_required에 있으면 invalid_values에서 제외)
    """
    validation_items: list[str] = []
    override_items: list[str] = []

    # 스키마 변화에 안전한 접근 (getattr + 빈 배열 폴백)
    missing_required: list[str] = getattr(validation, "missing_required", []) or []
    invalid_values: list[dict[str, Any]] = (
        getattr(validation, "invalid_values", []) or []
    )
    invalid_override_fields: list[str] = (
        getattr(validation, "invalid_override_fields", []) or []
    )
    invalid_override_reasons: dict[str, str] = (
        getattr(validation, "invalid_override_reasons", {}) or {}
    )

    # 1) 필수 필드 누락 (에러, 🔴) - 에러 코드 포함
    # 에러 코드는 domain/errors.py ErrorCodes와 일치
    if missing_required:
        fields_str = ", ".join(escape_html(f) for f in missing_required)
        # 다음 액션 힌트 추가
        hint = _get_missing_field_hint(missing_required)
        validation_items.append(
            f'<div class="error-item">'
            f'<span class="error-code">[MISSING_REQUIRED_FIELD]</span> '
            f"🔴 필수 필드 누락: {fields_str}"
            f"{hint}</div>"
        )

    # 2) 유효하지 않은 값 (에러, 🔴)
    # result 중복 방지: missing_required에 있으면 invalid_values에서 제외
    for invalid in invalid_values:
        field_name = str(invalid.get("field", "unknown"))
        # result가 missing_required에 이미 있으면 스킵 (중복 방지)
        if field_name == "result" and "result" in missing_required:
            continue

        value = escape_html(str(invalid.get("value", "")))
        error_msg = escape_html(str(invalid.get("error", "")))
        validation_items.append(
            f'<div class="error-item">'
            f'<span class="error-code">[RESULT_INVALID_VALUE]</span> '
            f'🔴 유효하지 않은 값: {escape_html(field_name)}="{value}" ({error_msg})</div>'
        )

    # 3) 측정값 관련 이슈 (measurement_issues 파라미터로 전달)
    if measurement_issues:
        has_more = measurement_issues.get("has_more", False)

        # 빈 측정값 (에러, 🔴) - INVALID_DATA (빈값/무효값)
        empty_measured = measurement_issues.get("empty_measured", [])
        for identifier in empty_measured:
            validation_items.append(
                f'<div class="error-item">'
                f'<span class="error-code">[INVALID_DATA]</span> '
                f"🔴 빈 측정값: {escape_html(identifier)}</div>"
            )

        # NaN/Inf 값 (에러, 🔴) - INVALID_DATA (NaN/Inf)
        nan_inf = measurement_issues.get("nan_inf", [])
        for identifier in nan_inf:
            validation_items.append(
                f'<div class="error-item">'
                f'<span class="error-code">[INVALID_DATA]</span> '
                f"🔴 NaN/Inf 포함: {escape_html(identifier)}</div>"
            )

        # "외 다수" 표시 (조기 종료 시)
        if has_more:
            validation_items.append(
                f'<div class="error-item overflow-notice">'
                f'<span class="error-code">[INVALID_DATA]</span> '
                f"🔴 외 다수의 측정 이슈가 있습니다</div>"
            )

    # 4) Override 검증 실패 (별도 섹션 - 시스템 처리 오류)
    # 입력 검증과 분리하여 사용자 혼란 방지
    # OVERRIDE_NOT_ALLOWED: domain/errors.py ErrorCodes와 일치
    for field_name in invalid_override_fields:
        reason = invalid_override_reasons.get(field_name, "")
        override_items.append(
            f'<div class="override-error-item">'
            f'<span class="error-code">[OVERRIDE_NOT_ALLOWED]</span> '
            f"⚙️ Override 처리 실패: {escape_html(field_name)} - {escape_html(reason)}</div>"
        )

    # 아이템이 없으면 빈 문자열 반환
    if not validation_items and not override_items:
        return ""

    # 컨테이너로 감싸서 반환 (입력 검증 / 처리 오류 분리)
    html_parts: list[str] = []

    if validation_items:
        html_parts.append(
            '<div class="validation-errors">\n' + "\n".join(validation_items) + "\n</div>"
        )

    if override_items:
        html_parts.append(
            '<div class="override-errors">\n'
            '<div class="override-errors-header">⚙️ 시스템 처리 오류</div>\n'
            + "\n".join(override_items)
            + "\n</div>"
        )

    return "\n".join(html_parts)


def _get_missing_field_hint(missing_fields: list[str]) -> str:
    """필수 필드 누락 시 다음 액션 힌트 생성."""
    hints: list[str] = []

    field_hints = {
        "wo_no": "예: WO-2412-007",
        "line": "예: L1, L2",
        "result": "예: PASS, FAIL, OK, NG",
        "part_no": "예: P-12345",
        "lot": "예: LOT-001",
    }

    for field in missing_fields:
        if field in field_hints:
            hints.append(f"{field}: {field_hints[field]}")

    if hints:
        return '<br><small class="hint">💡 ' + " | ".join(hints) + "</small>"
    return ""


# 측정 이슈 표시 상한 (성능 + UX)
MAX_MEASUREMENT_ISSUES_DISPLAY = 10

# 빈값/무효값으로 처리할 토큰들 (대소문자 무시)
EMPTY_VALUE_TOKENS = frozenset({
    "n/a", "na", "none", "-", "—", "--", "null", "nil", "미측정", "측정불가",
    ".", "..", "...", "x", "xx", "xxx", "ㅡ", "ㅡㅡ",
})


def _is_empty_or_placeholder(value: str) -> bool:
    """값이 빈값 또는 플레이스홀더인지 확인."""
    normalized = value.strip().lower()
    return normalized in EMPTY_VALUE_TOKENS


def _normalize_number_string(value: str) -> str | None:
    """
    다양한 로컬 포맷을 표준 숫자 문자열로 변환 시도.

    지원:
    - "1,234.56" → "1234.56" (영미권)
    - "1.234,56" → "1234.56" (유럽권)
    - "1 234.56" → "1234.56" (공백 천단위)

    Returns:
        정규화된 문자열 또는 None (변환 불가)
    """
    s = value.strip()
    if not s:
        return None

    # 공백 제거
    s = s.replace(" ", "")

    # 천단위 구분자 패턴 감지
    # Case 1: 1,234.56 (쉼표 천단위, 점 소수점)
    if "," in s and "." in s:
        if s.rfind(",") < s.rfind("."):
            # 1,234.56 형식
            s = s.replace(",", "")
        else:
            # 1.234,56 형식 (유럽)
            s = s.replace(".", "").replace(",", ".")
    elif "," in s and "." not in s:
        # 쉼표만 있음: 1,234 (천단위) 또는 1,5 (유럽 소수점)
        # 쉼표 뒤 3자리면 천단위로 간주
        parts = s.split(",")
        if len(parts) == 2 and len(parts[1]) == 3:
            s = s.replace(",", "")
        else:
            # 유럽식 소수점으로 간주
            s = s.replace(",", ".")

    return s


def analyze_measurement_issues(
    measurements: list[dict[str, Any]] | None,
    *,
    stop_after_limit: bool = True,
    _debug: bool = False,
) -> dict[str, list[str]]:
    """
    측정 데이터에서 빈 값/NaN/Inf 이슈 분석.

    Args:
        measurements: 측정 데이터 리스트
        stop_after_limit: True면 10개 찾으면 스캔 중단 (성능 우선)
                         False면 끝까지 스캔하여 정확한 overflow count 반환
        _debug: 테스트 전용. True면 _debug_iterations 필드 추가.
                프로덕션 경로에서는 절대 True로 호출하지 말 것.

    Returns:
        {
            "empty_measured": ["직경 (SPEC: 3.0±0.1) - 2번째 줄", ...],
            "nan_inf": ["길이 (SPEC: 10.0) - 3번째 줄", ...],
            "has_more": True,  # stop_after_limit=True일 때 10개 초과 여부
            "_debug_iterations": 10,  # _debug=True일 때만 포함
        }

    리스크 방어:
    - 항목 식별자에 characteristic/spec_name/item 등 다양한 키 우선 검색
    - SPEC 값도 함께 표시하여 현장에서 어떤 측정인지 명확히 식별
    - "몇 번째 줄" 형태로 한글 표기
    - 로컬 숫자 포맷 지원 (1,234.56, 1.234,56 등)
    - N/A, —, 측정불가 등 플레이스홀더는 빈값으로 처리
    - 성능: stop_after_limit=True(기본)면 10개 찾으면 즉시 종료
    """
    import math

    result: dict[str, Any] = {
        "empty_measured": [],
        "nan_inf": [],
        "has_more": False,  # 10개 초과 여부 (stop_after_limit=True일 때)
    }

    if not measurements:
        return result

    total_issues = 0  # 조기 종료 판단용
    iterations = 0  # _debug=True일 때만 사용

    for i, row in enumerate(measurements):
        iterations += 1
        # 항목 식별자 (다양한 키 우선순위로 검색)
        item_name = (
            row.get("characteristic")
            or row.get("CHARACTERISTIC")
            or row.get("spec_name")
            or row.get("SPEC_NAME")
            or row.get("ITEM")
            or row.get("item")
            or row.get("name")
            or row.get("NAME")
            or None
        )

        # SPEC/규격 값 (추가 컨텍스트)
        spec_value = (
            row.get("SPEC")
            or row.get("spec")
            or row.get("specification")
            or row.get("nominal")
            or row.get("NOMINAL")
            or None
        )

        # 식별자 구성: "항목명 (SPEC: 값) - N번째 줄" 또는 "N번째 줄"
        row_label = f"{i + 1}번째 줄"  # 1-indexed, 한글

        if item_name:
            item_str = escape_html(str(item_name))
            if spec_value:
                spec_str = escape_html(str(spec_value))
                identifier = f"{item_str} (SPEC: {spec_str}) - {row_label}"
            else:
                identifier = f"{item_str} - {row_label}"
        else:
            identifier = row_label

        # MEASURED 값 확인 (다양한 키)
        measured = (
            row.get("MEASURED")
            or row.get("measured")
            or row.get("actual")
            or row.get("ACTUAL")
            or row.get("value")
            or row.get("VALUE")
        )

        # 빈 값 체크 (None, 빈 문자열, 플레이스홀더)
        if measured is None:
            if len(result["empty_measured"]) < MAX_MEASUREMENT_ISSUES_DISPLAY:
                result["empty_measured"].append(identifier)
            total_issues += 1
            # 조기 종료: 10개 찾으면 스캔 중단
            if stop_after_limit and total_issues >= MAX_MEASUREMENT_ISSUES_DISPLAY:
                result["has_more"] = True
                break
            continue

        measured_str = str(measured).strip()
        if not measured_str or _is_empty_or_placeholder(measured_str):
            if len(result["empty_measured"]) < MAX_MEASUREMENT_ISSUES_DISPLAY:
                result["empty_measured"].append(identifier)
            total_issues += 1
            if stop_after_limit and total_issues >= MAX_MEASUREMENT_ISSUES_DISPLAY:
                result["has_more"] = True
                break
            continue

        # 숫자 정규화 시도 (로컬 포맷 지원)
        normalized = _normalize_number_string(measured_str)
        if normalized is None:
            # 정규화 실패 → 문자열 측정값으로 간주 (에러 아님)
            continue

        # NaN/Inf 체크
        try:
            value = float(normalized)
            if math.isnan(value) or math.isinf(value):
                if len(result["nan_inf"]) < MAX_MEASUREMENT_ISSUES_DISPLAY:
                    result["nan_inf"].append(identifier)
                total_issues += 1
                if stop_after_limit and total_issues >= MAX_MEASUREMENT_ISSUES_DISPLAY:
                    result["has_more"] = True
                    break
        except (ValueError, TypeError):
            # 변환 실패 → 문자열 측정값으로 간주 (에러 아님)
            pass

    # stop_after_limit=False일 때도 10개 초과하면 has_more 설정
    if total_issues > MAX_MEASUREMENT_ISSUES_DISPLAY:
        result["has_more"] = True

    # 테스트 전용: _debug=True일 때만 반복 횟수 포함
    if _debug:
        result["_debug_iterations"] = iterations

    return result


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

        # 측정값 이슈 분석
        measurement_issues = analyze_measurement_issues(extraction_result.measurements)

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

        # 검증 오류 카드 HTML 생성 (에러/경고가 있을 때만)
        validation_error_html = build_validation_error_html(
            validation, measurement_issues=measurement_issues
        )
        if validation_error_html:
            assistant_response += "<br>" + validation_error_html

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
    # 지원되지 않는 이미지 확장자 (경고 표시 대상)
    unsupported_image_extensions = {".gif", ".bmp", ".tiff", ".tif", ".webp", ".heic"}
    ocr_extensions = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".pdf"}
    template_extensions = {".docx", ".dotx", ".odt"}  # 템플릿 후보 파일

    slot_key: str | None = None
    raw_path: str | None = None
    unsupported_extension = False

    # UI에 표시할 HTML 메시지 조각들
    html_parts: list[str] = []

    # 지원되지 않는 이미지 확장자: 저장하지 않고 즉시 거절
    # 저장하면 "왜 분석 안 됐지?" 디버깅 비용이 늘어남
    if file_ext in unsupported_image_extensions:
        unsupported_extension = True
        user_content = f"[파일 첨부 시도: {filename}]"
        # 저장하지 않음 - 메시지만 기록
        intake.add_message(
            role="user",
            content=user_content,
            # attachments 제외 - 저장 안 함
        )
        html_parts.append(build_user_message_html(user_content))

        # 경고 메시지 (⚠️ 주황색 카드) + 다음 액션 힌트
        warning_msg = (
            f'<div class="warning-item">'
            f'<span class="error-code">[UNSUPPORTED_EXT]</span> '
            f"⚠️ 지원하지 않는 확장자: {safe_filename}<br>"
            f"파일이 저장되지 않았습니다.<br>"
            f'<small class="hint">💡 jpg/jpeg/png로 변환 후 다시 업로드해주세요.</small>'
            f"</div>"
        )
        html_parts.append(build_assistant_message_html(warning_msg))

    # 사진 슬롯 매핑 처리 (지원되는 확장자만)
    elif file_ext in photo_extensions:
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

    # 파일이 실제로 저장되었는지 여부
    # 지원 안 되는 확장자는 저장하지 않음 (디버깅 비용 절감)
    file_stored = not unsupported_extension and (raw_path is not None or file_ext not in photo_extensions)

    return {
        "success": not unsupported_extension,  # 지원 안 되는 확장자면 success=False
        "stored": file_stored,  # 파일이 실제로 저장되었는지 명확한 상태
        "filename": filename,
        "size": len(file_bytes),
        "session_id": session_id,
        "job_id": job_id,
        "message": (
            "지원하지 않는 파일 형식입니다. 파일이 저장되지 않았습니다."
            if unsupported_extension
            else "파일이 업로드되었습니다."
        ),
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
        # 지원되지 않는 확장자 플래그
        "unsupported_extension": unsupported_extension,
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
