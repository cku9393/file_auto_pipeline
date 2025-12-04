"""
사진 처리: raw→derived, safe_move, archive

AGENTS.md 규칙:
- safe_move: 원인 보존, dst 충돌 해결, 원자성, fsync 경고
- prefer_order: 중복 파일 시 우선순위대로 선택
- required 슬롯 누락 시 reject
"""

import logging
import os
import shutil
from datetime import datetime
from pathlib import Path

import yaml

from src.domain.errors import ErrorCodes, PolicyRejectError
from src.domain.schemas import MoveResult, PhotoSlot

logger = logging.getLogger(__name__)


# =============================================================================
# Safe Move (Archive)
# =============================================================================

def safe_move(src: Path, dst_dir: Path) -> MoveResult:
    """
    안전한 파일 이동 (아카이브용).

    보장:
    - 원인 보존: 실패 시 operation/errno/message 기록
    - dst 충돌 해결: 동일 파일명 존재 시 suffix 추가
    - 원자성: 이동 완료 전 원본 삭제 없음
    - fsync 경고: fsync 실패 시 warn (데이터는 보존)

    Args:
        src: 원본 파일 경로
        dst_dir: 대상 디렉터리

    Returns:
        MoveResult
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst_name = f"{src.stem}_{timestamp}{src.suffix}"
    dst = dst_dir / dst_name

    # dst 충돌 해결
    counter = 1
    while dst.exists():
        dst_name = f"{src.stem}_{timestamp}_{counter}{src.suffix}"
        dst = dst_dir / dst_name
        counter += 1

    # 이동 시도 (원인 보존)
    try:
        dst_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dst))  # 먼저 복사 (원자성)
    except OSError as e:
        return MoveResult(
            success=False,
            src=src,
            operation="copy",
            errno_code=e.errno,
            error_message=str(e),
        )

    # fsync 시도 (경고만, 실패해도 계속)
    fsync_warning = False
    try:
        fd = os.open(str(dst), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError as e:
        fsync_warning = True
        logger.warning(
            "fsync failed for %s: %s (data preserved)",
            dst, e
        )

    # 원본 삭제 (복사 성공 후에만)
    try:
        src.unlink()
    except OSError as e:
        return MoveResult(
            success=False,
            src=src,
            dst=dst,
            operation="unlink_source",
            errno_code=e.errno,
            error_message=str(e),
        )

    return MoveResult(
        success=True,
        src=src,
        dst=dst,
        fsync_warning=fsync_warning,
    )


# =============================================================================
# Photo Slot Selection
# =============================================================================

def load_photo_slots(definition_path: Path) -> list[PhotoSlot]:
    """
    definition.yaml에서 사진 슬롯 정의 로드.

    Args:
        definition_path: definition.yaml 경로

    Returns:
        PhotoSlot 목록
    """
    with open(definition_path, encoding="utf-8") as f:
        definition = yaml.safe_load(f)

    photos_config = definition.get("photos", {})
    slots_config = photos_config.get("slots", [])

    return [
        PhotoSlot(
            key=slot["key"],
            basename=slot["basename"],
            required=slot.get("required", False),
            override_allowed=slot.get("override_allowed", True),
        )
        for slot in slots_config
    ]


def get_allowed_extensions(definition_path: Path) -> list[str]:
    """허용된 확장자 목록."""
    with open(definition_path, encoding="utf-8") as f:
        definition = yaml.safe_load(f)

    extensions: list[str] = definition.get("photos", {}).get(
        "allowed_extensions", [".jpg", ".jpeg", ".png"]
    )
    return extensions


def get_prefer_order(definition_path: Path) -> list[str]:
    """중복 시 우선순위."""
    with open(definition_path, encoding="utf-8") as f:
        definition = yaml.safe_load(f)

    order: list[str] = definition.get("photos", {}).get(
        "prefer_order", [".jpg", ".jpeg", ".png"]
    )
    return order


def select_photo_for_slot(
    slot: PhotoSlot,
    raw_dir: Path,
    definition_path: Path,
) -> tuple[Path | None, str | None]:
    """
    슬롯에 맞는 사진 파일 선택.

    Args:
        slot: 사진 슬롯
        raw_dir: photos/raw/ 디렉터리
        definition_path: definition.yaml 경로

    Returns:
        (선택된 파일 경로, 경고 메시지 or None)

    Raises:
        PolicyRejectError: required 슬롯인데 파일 없고 override 불가
    """
    allowed_extensions = get_allowed_extensions(definition_path)
    prefer_order = get_prefer_order(definition_path)

    # 슬롯에 매칭되는 파일 찾기
    candidates = []
    for ext in allowed_extensions:
        candidate = raw_dir / f"{slot.basename}{ext}"
        if candidate.exists():
            candidates.append(candidate)

    # 후보가 없는 경우
    if not candidates:
        if slot.required and not slot.override_allowed:
            raise PolicyRejectError(
                ErrorCodes.PHOTO_REQUIRED_MISSING,
                slot=slot.key,
                basename=slot.basename,
            )
        return None, None

    # 중복인 경우 prefer_order로 선택
    if len(candidates) > 1:
        # prefer_order에 따라 정렬
        def sort_key(p: Path) -> int:
            ext = p.suffix.lower()
            if ext in prefer_order:
                return prefer_order.index(ext)
            return len(prefer_order)

        candidates.sort(key=sort_key)
        selected = candidates[0]

        warning = (
            f"Multiple files for slot '{slot.key}': "
            f"{[c.name for c in candidates]}, selected '{selected.name}'"
        )
        return selected, warning

    return candidates[0], None


def archive_old_derived(
    derived_dir: Path,
    trash_dir: Path,
) -> list[MoveResult]:
    """
    기존 derived 파일을 _trash로 아카이브.

    Args:
        derived_dir: photos/derived/ 디렉터리
        trash_dir: photos/derived/_trash/ 디렉터리

    Returns:
        MoveResult 목록
    """
    results: list[MoveResult] = []

    if not derived_dir.exists():
        return results

    for file_path in derived_dir.iterdir():
        # _trash 폴더 자체는 건너뛰기
        if file_path.name == "_trash":
            continue
        if file_path.is_file():
            result = safe_move(file_path, trash_dir)
            results.append(result)

    return results


def copy_to_derived(
    src: Path,
    derived_dir: Path,
    slot: PhotoSlot,
) -> Path:
    """
    raw → derived로 복사.

    Args:
        src: 원본 파일 (raw)
        derived_dir: photos/derived/ 디렉터리
        slot: 사진 슬롯

    Returns:
        복사된 파일 경로
    """
    derived_dir.mkdir(parents=True, exist_ok=True)

    # 슬롯 키로 이름 지정 (예: overview.jpg)
    dst = derived_dir / f"{slot.key}{src.suffix}"
    shutil.copy2(str(src), str(dst))

    return dst
