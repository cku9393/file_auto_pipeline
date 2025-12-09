"""
Domain Constants: 파이프라인 전역 상수.

파일명 정책, 경로 상수 등 시스템 전반에서 사용되는 값들.
spec-v2.md 기준으로 정의됨.
"""

# =============================================================================
# Output Filenames (출력 파일명 정책)
# =============================================================================
# spec-v2.md Section 2.1 참조:
# - report.docx: 문서 형식 출력 (검사성적서 등)
# - measurements.xlsx: 표 형식 출력 (측정 데이터)

OUTPUT_DOCX_FILENAME = "report.docx"
OUTPUT_XLSX_FILENAME = "measurements.xlsx"

# =============================================================================
# Job Directory Structure (작업 디렉토리 구조)
# =============================================================================
# spec-v2.md Section 2.1 참조:
# jobs/<job_id>/
# ├── inputs/
# │   ├── packet.xlsx
# │   └── photos/raw/
# ├── photos/derived/
# ├── logs/
# └── deliverables/

JOB_INPUTS_DIR = "inputs"
JOB_PHOTOS_DIR = "photos"
JOB_PHOTOS_RAW_DIR = "photos/raw"
JOB_PHOTOS_DERIVED_DIR = "photos/derived"
JOB_PHOTOS_TRASH_DIR = "photos/derived/_trash"
JOB_LOGS_DIR = "logs"
JOB_DELIVERABLES_DIR = "deliverables"
JOB_JSON_FILENAME = "job.json"

# =============================================================================
# Template Directory Structure (템플릿 디렉토리 구조)
# =============================================================================
# ADR-0002 참조:
# templates/<category>/<template_id>/
# ├── source/      # 원본 (불변)
# ├── compiled/    # 렌더용
# ├── meta.json
# └── manifest.yaml

TEMPLATE_SOURCE_DIR = "source"
TEMPLATE_COMPILED_DIR = "compiled"
TEMPLATE_META_FILENAME = "meta.json"
TEMPLATE_MANIFEST_FILENAME = "manifest.yaml"

# =============================================================================
# Photo Slots (사진 슬롯 정책)
# =============================================================================
# definition.yaml 참조:
# 파일명 패턴: {번호}_{슬롯키}.{확장자}
# 예: 01_overview.jpg, 02_label_serial.png

PHOTO_ALLOWED_EXTENSIONS = (".jpg", ".jpeg", ".png")
PHOTO_MAX_SIZE_MB = 10

# 기본 슬롯 (definition.yaml에서 오버라이드 가능)
DEFAULT_PHOTO_SLOTS = {
    "overview": {"basename": "01_overview", "required": True},
    "label_serial": {"basename": "02_label_serial", "required": True},
    "defect": {"basename": "03_defect", "required": False},
}

# =============================================================================
# Hash & ID Prefixes
# =============================================================================

JOB_ID_PREFIX = "JOB-"
RUN_ID_PREFIX = "RUN-"

# =============================================================================
# MIME Types
# =============================================================================

MIME_TYPES = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".json": "application/json",
    ".yaml": "application/x-yaml",
    ".zip": "application/zip",
}


def get_mime_type(filename: str) -> str:
    """
    파일명에서 MIME 타입 추출.

    Args:
        filename: 파일명 (확장자 포함)

    Returns:
        MIME 타입 문자열 (알 수 없으면 octet-stream)
    """
    import os

    ext = os.path.splitext(filename)[1].lower()
    return MIME_TYPES.get(ext, "application/octet-stream")
