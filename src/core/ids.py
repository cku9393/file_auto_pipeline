"""
ID 생성: job_id, run_id

AGENTS.md 규칙:
- job_id 수정 금지
- run_id만 새로 발급
"""

import hashlib
import uuid
from datetime import UTC, datetime


def generate_job_id(packet: dict) -> str:
    """
    Job ID 생성.

    결정론적: 동일 packet → 동일 job_id
    포맷: JOB-{wo_no}-{line}-{hash[:8]}

    Args:
        packet: wo_no, line 포함된 packet 데이터

    Returns:
        job_id 문자열
    """
    wo_no = packet.get("wo_no", "")
    line = packet.get("line", "")

    # 결정론적 해시 (wo_no + line 기반)
    hash_input = f"{wo_no}:{line}"
    hash_value = hashlib.sha256(hash_input.encode()).hexdigest()[:8]

    # 안전한 문자로 변환 (파일명으로 사용 가능하도록)
    safe_wo_no = _sanitize_for_id(wo_no)
    safe_line = _sanitize_for_id(line)

    return f"JOB-{safe_wo_no}-{safe_line}-{hash_value}"


def generate_run_id() -> str:
    """
    Run ID 생성.

    고유성 보장: UUID v4
    포맷: RUN-{timestamp}-{uuid[:8]}

    Returns:
        run_id 문자열
    """
    now = datetime.now(UTC)
    timestamp = now.strftime("%Y%m%d%H%M%S")
    unique = uuid.uuid4().hex[:8]

    return f"RUN-{timestamp}-{unique}"


def _sanitize_for_id(value: str) -> str:
    """
    ID에 사용할 수 있도록 문자열 정리.

    - 공백 → 밑줄
    - 특수문자/비ASCII 제거
    - 최대 20자
    """
    # 허용 문자: ASCII 알파벳, 숫자만 (파일명 안전)
    sanitized = ""
    for c in value:
        if c.isascii() and c.isalnum():
            sanitized += c
        elif c in " _-":
            sanitized += "_"
        # 그 외 문자는 무시 (한글 등 비ASCII 포함)

    # 연속 밑줄 정리
    while "__" in sanitized:
        sanitized = sanitized.replace("__", "_")

    # 앞뒤 밑줄 제거
    sanitized = sanitized.strip("_")

    # 최대 길이 제한
    return sanitized[:20] if sanitized else "UNKNOWN"
