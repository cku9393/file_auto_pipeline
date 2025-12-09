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
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from src.domain.errors import ErrorCodes, PolicyRejectError
from src.domain.schemas import (
    MoveResult,
    PhotoSlot,
    SlotMatchConfidence,
    SlotMatchResult,
)

if TYPE_CHECKING:
    from src.domain.schemas import PhotoProcessingLog

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
            override_requires_reason=slot.get("override_requires_reason", True),
            description=slot.get("description", ""),
            verify_keywords=slot.get("verify_keywords"),
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


# =============================================================================
# Photo Service (웹 플로우 통합용)
# =============================================================================

@dataclass
class PhotoValidationResult:
    """사진 검증 결과."""
    valid: bool
    missing_required: list[str] = field(default_factory=list)
    overridable: list[str] = field(default_factory=list)
    mapped_slots: dict[str, Path] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    processing_logs: list["PhotoProcessingLog"] = field(default_factory=list)


class PhotoService:
    """
    사진 처리 서비스.

    웹 플로우 전체를 관리:
    - 업로드 → raw/ 저장 → 슬롯 매핑
    - generate 시 → derived 생성 + 아카이브 + 검증
    """

    def __init__(self, job_dir: Path, definition_path: Path):
        """
        Args:
            job_dir: Job 폴더 경로
            definition_path: definition.yaml 경로
        """
        self.job_dir = job_dir
        self.definition_path = definition_path
        self.photos_dir = job_dir / "photos"
        self.raw_dir = self.photos_dir / "raw"
        self.derived_dir = self.photos_dir / "derived"
        self.trash_dir = self.photos_dir / "_trash"

    def get_slots(self) -> list[PhotoSlot]:
        """definition.yaml에서 슬롯 목록 로드."""
        return load_photo_slots(self.definition_path)

    def save_upload(self, filename: str, file_bytes: bytes) -> Path:
        """
        업로드된 사진을 raw/에 저장.

        Args:
            filename: 원본 파일명
            file_bytes: 파일 바이트

        Returns:
            저장된 파일 경로
        """
        self.raw_dir.mkdir(parents=True, exist_ok=True)

        # 파일명 충돌 방지
        target = self.raw_dir / filename
        counter = 1
        while target.exists():
            stem = Path(filename).stem
            suffix = Path(filename).suffix
            target = self.raw_dir / f"{stem}_{counter}{suffix}"
            counter += 1

        target.write_bytes(file_bytes)
        return target

    def match_slot_for_file(self, filename: str) -> PhotoSlot | None:
        """
        파일명에 맞는 슬롯 찾기 (하위 호환용).

        Args:
            filename: 파일명 (예: 01_overview.jpg)

        Returns:
            매칭된 슬롯 또는 None
        """
        result = self.match_slot_for_file_with_confidence(filename)
        return result.slot if result.is_reliable else None

    def match_slot_for_file_with_confidence(
        self,
        filename: str,
        ocr_text: str | None = None,
    ) -> SlotMatchResult:
        """
        파일명에 맞는 슬롯 찾기 (confidence 포함).

        매칭 우선순위:
        1. basename 정확히 일치 → HIGH
        2. basename prefix 일치 → MEDIUM
        3. 슬롯 key prefix 일치 → LOW (사용자 확인 필요)
        4. 여러 슬롯 매칭 가능 → AMBIGUOUS

        Args:
            filename: 파일명 (예: 01_overview.jpg)
            ocr_text: OCR 추출 텍스트 (핵심 슬롯 검증용)

        Returns:
            SlotMatchResult (slot, confidence, warning 등)
        """
        slots = self.get_slots()
        file_stem = Path(filename).stem.lower()
        file_ext = Path(filename).suffix.lower()

        allowed_extensions = get_allowed_extensions(self.definition_path)
        if file_ext not in [ext.lower() for ext in allowed_extensions]:
            return SlotMatchResult(
                slot=None,
                confidence=SlotMatchConfidence.LOW,
                warning=f"허용되지 않은 확장자: {file_ext}",
            )

        # 매칭 후보 수집
        exact_matches: list[tuple[PhotoSlot, str]] = []  # (slot, matched_by)
        prefix_matches: list[tuple[PhotoSlot, str]] = []
        key_matches: list[tuple[PhotoSlot, str]] = []

        for slot in slots:
            basename_lower = slot.basename.lower()
            key_lower = slot.key.lower()

            # 1. basename 정확히 일치 (가장 신뢰도 높음)
            if file_stem == basename_lower:
                exact_matches.append((slot, "basename_exact"))
            # 2. basename prefix 일치
            elif file_stem.startswith(basename_lower):
                prefix_matches.append((slot, "basename_prefix"))
            # 3. key prefix 일치 (신뢰도 낮음)
            elif file_stem.startswith(key_lower):
                key_matches.append((slot, "key_prefix"))

        # 결과 결정
        all_matches = exact_matches + prefix_matches + key_matches

        if not all_matches:
            return SlotMatchResult(
                slot=None,
                confidence=SlotMatchConfidence.LOW,
                warning=f"매칭되는 슬롯 없음: {filename}",
            )

        # 여러 개 매칭 → AMBIGUOUS
        if len(all_matches) > 1:
            slot_keys = [m[0].key for m in all_matches]
            return SlotMatchResult(
                slot=all_matches[0][0],  # 첫 번째 반환하되 경고
                confidence=SlotMatchConfidence.AMBIGUOUS,
                matched_by=all_matches[0][1],
                warning=f"여러 슬롯 매칭 가능: {slot_keys}. 사용자 확인 필요.",
                alternative_slots=slot_keys[1:],
            )

        # 단일 매칭
        matched_slot, matched_by = all_matches[0]

        # 신뢰도 결정
        if matched_by == "basename_exact":
            confidence = SlotMatchConfidence.HIGH
        elif matched_by == "basename_prefix":
            confidence = SlotMatchConfidence.MEDIUM
        else:  # key_prefix
            confidence = SlotMatchConfidence.LOW

        # OCR 키워드 검증 (핵심 슬롯에서 confidence 상승 가능)
        ocr_verified = False
        if ocr_text and matched_slot.verify_keywords:
            ocr_lower = ocr_text.lower()
            for keyword in matched_slot.verify_keywords:
                if keyword.lower() in ocr_lower:
                    ocr_verified = True
                    if confidence == SlotMatchConfidence.MEDIUM:
                        confidence = SlotMatchConfidence.HIGH
                    break

        # 핵심 슬롯(required + !override_allowed)인데 LOW면 경고
        warning = None
        if matched_slot.required and not matched_slot.override_allowed:
            if confidence == SlotMatchConfidence.LOW:
                warning = f"핵심 슬롯 '{matched_slot.key}'이 낮은 신뢰도로 매칭됨. 파일명 확인 필요."
            elif confidence == SlotMatchConfidence.MEDIUM and not ocr_verified:
                warning = f"핵심 슬롯 '{matched_slot.key}' 매칭. OCR 검증 권장."

        return SlotMatchResult(
            slot=matched_slot,
            confidence=confidence,
            matched_by=matched_by,
            warning=warning,
            ocr_verified=ocr_verified,
        )

    def validate_and_process(
        self,
        overrides: dict[str, str] | None = None,
        run_id: str | None = None,
    ) -> PhotoValidationResult:
        """
        사진 슬롯 검증 및 처리.

        Args:
            overrides: {slot_key: reason} override 사유
            run_id: Run ID (아카이브 폴더명용)

        Returns:
            PhotoValidationResult
        """
        from datetime import datetime

        from src.domain.schemas import PhotoProcessingLog

        result = PhotoValidationResult(valid=True)
        overrides = overrides or {}
        now = datetime.now()
        timestamp = now.isoformat()
        archive_folder = now.strftime("%Y%m%d_%H%M%S")
        if run_id:
            archive_folder = f"{archive_folder}_{run_id[:8]}"

        slots = self.get_slots()

        for slot in slots:
            # 슬롯에 매칭되는 파일 선택
            try:
                selected_path, warning = select_photo_for_slot(
                    slot=slot,
                    raw_dir=self.raw_dir,
                    definition_path=self.definition_path,
                )
            except PolicyRejectError as e:
                # required + override_allowed=false → 즉시 실패
                result.valid = False
                result.missing_required.append(slot.key)
                result.processing_logs.append(PhotoProcessingLog(
                    slot_id=slot.key,
                    action="missing",
                    warning=str(e),
                    timestamp=timestamp,
                ))
                continue

            if warning:
                result.warnings.append(warning)

            if selected_path:
                # 매핑 성공 → derived로 복사
                # 먼저 기존 derived 아카이브
                existing_derived = self._find_existing_derived(slot.key)
                archived_path = None

                if existing_derived:
                    trash_run_dir = self.trash_dir / archive_folder
                    archive_result = safe_move(existing_derived, trash_run_dir)
                    if archive_result.success:
                        archived_path = str(archive_result.dst) if archive_result.dst else None

                # 새 derived 생성
                derived_path = copy_to_derived(
                    src=selected_path,
                    derived_dir=self.derived_dir,
                    slot=slot,
                )

                result.mapped_slots[slot.key] = derived_path
                result.processing_logs.append(PhotoProcessingLog(
                    slot_id=slot.key,
                    action="mapped",
                    raw_path=str(selected_path),
                    derived_path=str(derived_path),
                    archived_path=archived_path,
                    warning=warning,
                    timestamp=timestamp,
                ))

            else:
                # 파일 없음
                if slot.required:
                    if slot.override_allowed and slot.key in overrides:
                        # Override 적용
                        result.processing_logs.append(PhotoProcessingLog(
                            slot_id=slot.key,
                            action="override",
                            override_reason=overrides[slot.key],
                            timestamp=timestamp,
                        ))
                    elif slot.override_allowed:
                        # Override 가능하지만 사유 없음
                        result.valid = False
                        result.overridable.append(slot.key)
                        result.processing_logs.append(PhotoProcessingLog(
                            slot_id=slot.key,
                            action="missing_overridable",
                            timestamp=timestamp,
                        ))
                    else:
                        # Override 불가
                        result.valid = False
                        result.missing_required.append(slot.key)
                        result.processing_logs.append(PhotoProcessingLog(
                            slot_id=slot.key,
                            action="missing",
                            timestamp=timestamp,
                        ))
                else:
                    # 선택 슬롯 누락 → 경고만
                    result.processing_logs.append(PhotoProcessingLog(
                        slot_id=slot.key,
                        action="skipped",
                        timestamp=timestamp,
                    ))

        return result

    def _find_existing_derived(self, slot_key: str) -> Path | None:
        """기존 derived 파일 찾기."""
        if not self.derived_dir.exists():
            return None

        for ext in [".jpg", ".jpeg", ".png"]:
            path = self.derived_dir / f"{slot_key}{ext}"
            if path.exists():
                return path

        return None

    def get_slot_mapping_status(self) -> dict[str, dict]:
        """
        현재 슬롯 매핑 상태 조회.

        Returns:
            {slot_key: {required, has_raw, has_derived, raw_path, derived_path}}
        """
        slots = self.get_slots()
        status = {}

        for slot in slots:
            # raw에서 찾기
            raw_path = None
            try:
                raw_path, _ = select_photo_for_slot(
                    slot=slot,
                    raw_dir=self.raw_dir,
                    definition_path=self.definition_path,
                )
            except PolicyRejectError:
                pass

            # derived에서 찾기
            derived_path = self._find_existing_derived(slot.key)

            status[slot.key] = {
                "required": slot.required,
                "override_allowed": slot.override_allowed,
                "has_raw": raw_path is not None,
                "has_derived": derived_path is not None,
                "raw_path": str(raw_path) if raw_path else None,
                "derived_path": str(derived_path) if derived_path else None,
            }

        return status
