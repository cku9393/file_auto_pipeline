"""
Generate Routes: 문서 생성 요청.

spec-v2.md Section 4.2:
- POST /api/generate → 최종 문서 생성 요청
- GET /jobs → 작업 이력
- GET /jobs/<job_id> → 작업 상세

AGENTS.md 규칙:
- SSOT: job.json 항상 확인/생성
- Run Log: 항상 저장 (성공/실패/거절 모두)
- Hashing: packet_hash, packet_full_hash 계산
- Photos: raw → derived 처리, _trash 아카이브
"""

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse

from src.core.hashing import compute_packet_full_hash, compute_packet_hash
from src.core.logging import (
    complete_run_log,
    create_run_log,
    emit_override,
    emit_warning,
    save_run_log,
)
from src.core.photos import PhotoService
from src.core.ssot_job import job_lock, load_job_json
from src.domain.constants import (
    JOB_DELIVERABLES_DIR,
    JOB_JSON_FILENAME,
    OUTPUT_DOCX_FILENAME,
    OUTPUT_XLSX_FILENAME,
)
from src.domain.errors import ErrorCodes, PolicyRejectError

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
    photo_overrides: str | None = Form(None),  # JSON: {slot_key: reason}
) -> dict[str, Any]:
    """
    최종 문서 생성 요청.

    SSOT + RunLog + Hashing + Photos 통합 적용:
    - job.json 강제 생성/검증 (ensure_job_json)
    - photos: raw → derived 처리, _trash 아카이브
    - RunLog 항상 저장 (finally 블록에서 보장)
    - packet_hash, packet_full_hash 계산 및 기록

    Args:
        session_id: Intake 세션 ID
        template_id: 사용할 템플릿
        output_format: 출력 형식 (docx, xlsx, both)
        photo_overrides: 사진 슬롯 override 사유 (JSON)

    Returns:
        생성 결과 (job_id, files, download_url, run_id, photo_processing)
    """
    import json as json_module

    from src.app.services.intake import IntakeService
    from src.app.services.validate import ValidationService, validate_override_reason
    from src.render.excel import ExcelRenderer
    from src.render.word import DocxRenderer

    # === 0. 초기 설정 ===
    jobs_root: Path = request.app.state.jobs_root
    definition_path: Path = request.app.state.definition_path
    config: dict = request.app.state.config

    # Import session mapping from chat.py
    from src.app.routes.chat import _session_to_job

    if session_id not in _session_to_job:
        raise HTTPException(status_code=404, detail="Session not found")

    job_id = _session_to_job[session_id]
    job_dir = jobs_root / job_id
    logs_dir = job_dir / "logs"

    # Photo overrides 파싱
    parsed_photo_overrides: dict[str, str] = {}
    if photo_overrides:
        try:
            parsed_photo_overrides = json_module.loads(photo_overrides)
        except json_module.JSONDecodeError:
            raise HTTPException(
                status_code=400,
                detail="photo_overrides must be valid JSON",
            ) from None

    # === 1. RunLog 생성 (시작 시점) ===
    run_log = create_run_log(job_id)

    # 결과 추적용 변수
    success = False
    packet_hash_value: str | None = None
    packet_full_hash_value: str | None = None
    error_code: str | None = None
    error_context: dict[str, Any] | None = None
    files: list[dict[str, Any]] = []

    # === 동시성 보호: job_lock 적용 ===
    # 같은 job에서 generate가 동시에 호출되면 한쪽이 대기하거나 실패
    try:
        with job_lock(job_dir, config):
            # === 2. IntakeService에서 데이터 로드 ===
            intake = IntakeService(job_dir)
            session = intake.load_session()

            # Check if extraction was done
            if not session.extraction_result:
                error_code = "EXTRACTION_NOT_DONE"
                error_context = {"session_id": session_id}
                raise HTTPException(
                    status_code=400,
                    detail="추출이 완료되지 않았습니다. /api/chat/extract를 먼저 호출하세요.",
                )

            # Combine fields and measurements into data dict
            data = {
                **session.extraction_result.fields,
                "measurements": session.extraction_result.measurements,
            }

            # === 3. SSOT: job.json 강제 생성/검증 ===
            # Note: ensure_job_json도 내부적으로 job_lock을 사용하므로
            # 여기서는 락 없이 직접 처리
            job_json_path = job_dir / JOB_JSON_FILENAME
            packet_for_ssot = {
                "wo_no": data.get("wo_no", "UNKNOWN"),
                "line": data.get("line", "UNKNOWN"),
            }

            if job_json_path.exists():
                existing = load_job_json(job_json_path)
                # mismatch 검증
                for key in ["wo_no", "line"]:
                    if existing.get(key) != packet_for_ssot.get(key):
                        error_code = ErrorCodes.PACKET_JOB_MISMATCH
                        error_context = {
                            "field": key,
                            "existing": existing.get(key),
                            "current": packet_for_ssot.get(key),
                        }
                        raise HTTPException(
                            status_code=409,
                            detail=f"SSOT 검증 실패: {key} 불일치",
                        )
                verified_job_id = existing["job_id"]
                if verified_job_id != job_id:
                    emit_warning(
                        run_log=run_log,
                        code="JOB_ID_MISMATCH_WARNING",
                        action_id="generate_document",
                        field_or_slot="job_id",
                        message=f"job.json의 job_id({verified_job_id})와 세션의 job_id({job_id})가 다름",
                        original_value=job_id,
                        resolved_value=verified_job_id,
                    )

            # === 4. Photos 파이프라인: raw → derived, 아카이브, 검증 ===
            photo_service = PhotoService(job_dir, definition_path)

            # Override 사유 품질 검증
            validated_photo_overrides: dict[str, str] = {}
            for slot_key, reason in parsed_photo_overrides.items():
                parsed, error = validate_override_reason(slot_key, reason)
                if error:
                    error_code = ErrorCodes.INVALID_OVERRIDE_REASON
                    error_context = {"slot": slot_key, "error": error.message}
                    raise HTTPException(
                        status_code=400,
                        detail=f"사진 슬롯 '{slot_key}' override 사유 검증 실패: {error.message}",
                    )
                if parsed:
                    validated_photo_overrides[slot_key] = f"{parsed.code.value}: {parsed.detail}"

            # 사진 검증 및 처리
            photo_result = photo_service.validate_and_process(
                overrides=validated_photo_overrides,
                run_id=run_log.run_id,
            )

            # 사진 처리 로그를 RunLog에 기록
            run_log.photo_processing = photo_result.processing_logs

            # 사진 경고를 RunLog에 기록
            for warning_msg in photo_result.warnings:
                emit_warning(
                    run_log=run_log,
                    code=ErrorCodes.PHOTO_DUPLICATE_AUTO_SELECTED,
                    action_id="photo_processing",
                    field_or_slot=warning_msg.split("'")[1] if "'" in warning_msg else "unknown",
                    message=warning_msg,
                )

            # Override 적용된 슬롯 기록
            for log_entry in photo_result.processing_logs:
                if log_entry.action == "override" and log_entry.override_reason:
                    # override reason 파싱
                    parsed, _ = validate_override_reason(log_entry.slot_id, log_entry.override_reason)
                    if parsed:
                        emit_override(
                            run_log=run_log,
                            field_or_slot=log_entry.slot_id,
                            override_type="photo",
                            reason_code=parsed.code.value,
                            reason_detail=parsed.detail,
                            user="api",
                        )

            if not photo_result.valid:
                if photo_result.missing_required:
                    error_code = ErrorCodes.PHOTO_REQUIRED_MISSING
                    error_context = {"missing_slots": photo_result.missing_required}
                    raise HTTPException(
                        status_code=400,
                        detail=f"필수 사진 누락: {photo_result.missing_required}",
                    )
                elif photo_result.overridable:
                    error_code = "PHOTO_OVERRIDE_REQUIRED"
                    error_context = {"overridable_slots": photo_result.overridable}
                    raise HTTPException(
                        status_code=400,
                        detail=f"사진 슬롯 override 필요: {photo_result.overridable}. photo_overrides 파라미터로 사유 제공 필요.",
                    )

            # === 5. Hashing: packet_hash, packet_full_hash 계산 ===
            packet_hash_value = compute_packet_hash(data, config, definition_path)
            packet_full_hash_value = compute_packet_full_hash(data)

            # === 6. ValidationService로 최종 검증 ===
            validation_service = ValidationService(definition_path)
            validation_result = validation_service.validate(
                fields=session.extraction_result.fields,
                measurements=session.extraction_result.measurements,
            )

            if not validation_result.valid:
                error_code = "VALIDATION_FAILED"
                error_context = {"missing_required": validation_result.missing_required}
                raise HTTPException(
                    status_code=400,
                    detail=f"검증 실패: {validation_result.missing_required}",
                )

            # === 7. 템플릿 경로 설정 ===
            templates_root = Path(__file__).parent.parent.parent.parent / "templates"
            template_dir = templates_root / template_id

            if not template_dir.exists():
                error_code = ErrorCodes.TEMPLATE_NOT_FOUND
                error_context = {"template_id": template_id}
                raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")

            docx_template = template_dir / "report_template.docx"
            xlsx_template = template_dir / "measurements_template.xlsx"

            # === 8. Render (DOCX, XLSX) ===
            deliverables_dir = job_dir / JOB_DELIVERABLES_DIR
            deliverables_dir.mkdir(parents=True, exist_ok=True)

            # Generate DOCX
            if output_format in ("docx", "both"):
                if not docx_template.exists():
                    error_code = ErrorCodes.TEMPLATE_NOT_FOUND
                    error_context = {"template": str(docx_template)}
                    raise HTTPException(
                        status_code=404,
                        detail=f"DOCX template not found: {docx_template}",
                    )

                docx_output = deliverables_dir / OUTPUT_DOCX_FILENAME
                docx_renderer = DocxRenderer(docx_template)

                docx_renderer.render(
                    data=data,
                    output_path=docx_output,
                )

                files.append({
                    "name": OUTPUT_DOCX_FILENAME,
                    "size": docx_output.stat().st_size,
                    "path": str(docx_output.relative_to(jobs_root)),
                })

            # Generate XLSX
            if output_format in ("xlsx", "both"):
                if not xlsx_template.exists():
                    error_code = ErrorCodes.TEMPLATE_NOT_FOUND
                    error_context = {"template": str(xlsx_template)}
                    raise HTTPException(
                        status_code=404,
                        detail=f"XLSX template not found: {xlsx_template}",
                    )

                # Load manifest.yaml
                import yaml

                manifest_path = template_dir / "manifest.yaml"
                if not manifest_path.exists():
                    error_code = ErrorCodes.TEMPLATE_NOT_FOUND
                    error_context = {"manifest": str(manifest_path)}
                    raise HTTPException(
                        status_code=404,
                        detail=f"Manifest not found: {manifest_path}",
                    )

                with open(manifest_path) as f:
                    manifest = yaml.safe_load(f)

                xlsx_output = deliverables_dir / OUTPUT_XLSX_FILENAME
                xlsx_renderer = ExcelRenderer(xlsx_template, manifest)

                xlsx_renderer.render(
                    data=data,
                    output_path=xlsx_output,
                )

                files.append({
                    "name": OUTPUT_XLSX_FILENAME,
                    "size": xlsx_output.stat().st_size,
                    "path": str(xlsx_output.relative_to(jobs_root)),
                })

            # 성공!
            success = True

            # === 9. 결과 반환 ===
            return {
                "success": True,
                "job_id": job_id,
                "run_id": run_log.run_id,
                "files": files,
                "download_url": f"/api/generate/jobs/{job_id}/download",
                "message": "문서가 생성되었습니다!",
                "packet_hash": packet_hash_value,
                "packet_full_hash": packet_full_hash_value,
                "photo_processing": [p.to_dict() for p in run_log.photo_processing],
            }

    except PolicyRejectError as e:
        # job_lock 타임아웃 등 PolicyRejectError
        if e.code == ErrorCodes.JOB_JSON_LOCK_TIMEOUT:
            error_code = ErrorCodes.JOB_JSON_LOCK_TIMEOUT
            error_context = e.context
            raise HTTPException(
                status_code=409,
                detail="동시 접근 충돌: 다른 generate 작업이 진행 중입니다. 잠시 후 다시 시도하세요.",
            ) from e
        error_code = e.code
        error_context = e.context
        raise HTTPException(status_code=409, detail=str(e)) from e

    except HTTPException:
        # HTTPException은 그대로 전파 (이미 error_code/context 설정됨)
        raise

    except Exception as e:
        # 예상치 못한 에러
        if not error_code:
            error_code = ErrorCodes.RENDER_FAILED
            error_context = {"error": str(e)}
        raise HTTPException(
            status_code=500,
            detail=f"문서 생성 중 오류 발생: {e}",
        ) from e

    finally:
        # === 10. RunLog 항상 저장 (성공/실패/예외 모두) ===
        complete_run_log(
            run_log=run_log,
            success=success,
            packet_hash=packet_hash_value,
            packet_full_hash=packet_full_hash_value,
            error_code=error_code,
            error_context=error_context,
        )
        save_run_log(run_log, logs_dir)


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
    file_path = jobs_root / job_id / JOB_DELIVERABLES_DIR / filename

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
