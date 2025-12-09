"""
템플릿 관리자: CRUD + source/ 불변 가드.

ADR-0002 핵심 규칙:
- source/ 불변: 덮어쓰기 시 에러 (chmod 0o444)
- template_id 네이밍: {customer}_{doctype}, 최대 50자
- 중복 template_id 생성 시 에러 (fail-fast)
- 상태: draft → ready → archived
"""

import json
import re
import shutil
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from filelock import FileLock, Timeout

# =============================================================================
# Exceptions
# =============================================================================

class TemplateError(Exception):
    """템플릿 관련 에러."""

    def __init__(self, code: str, message: str, **context: Any) -> None:
        self.code = code
        self.message = message
        self.context = context
        super().__init__(f"[{code}] {message}")


# =============================================================================
# Constants
# =============================================================================

class TemplateStatus(str, Enum):
    """템플릿 상태."""
    DRAFT = "draft"      # 작성 중, 렌더 불가
    READY = "ready"      # 사용 가능, 렌더 가능
    ARCHIVED = "archived"  # 폐기됨, 렌더 불가


# template_id 네이밍 규칙
TEMPLATE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_]*[a-z0-9]$")
TEMPLATE_ID_MAX_LENGTH = 50
FORBIDDEN_CHARS = set('/\\:*?"<>| ')


# =============================================================================
# Validation
# =============================================================================

def validate_template_id(template_id: str) -> None:
    """
    template_id 유효성 검증.

    규칙:
    - 소문자 + 숫자 + 언더스코어만 허용
    - 시작/끝은 소문자 또는 숫자
    - 최대 50자
    - 금지 문자: / \\ : * ? " < > | 공백

    Args:
        template_id: 검증할 ID

    Raises:
        TemplateError: INVALID_TEMPLATE_ID
    """
    if not template_id:
        raise TemplateError(
            "INVALID_TEMPLATE_ID",
            "template_id cannot be empty",
        )

    if len(template_id) > TEMPLATE_ID_MAX_LENGTH:
        raise TemplateError(
            "INVALID_TEMPLATE_ID",
            f"template_id exceeds {TEMPLATE_ID_MAX_LENGTH} characters",
            length=len(template_id),
        )

    # 금지 문자 체크
    found_forbidden = set(template_id) & FORBIDDEN_CHARS
    if found_forbidden:
        raise TemplateError(
            "INVALID_TEMPLATE_ID",
            f"template_id contains forbidden characters: {found_forbidden}",
            forbidden=list(found_forbidden),
        )

    # 패턴 체크
    if not TEMPLATE_ID_PATTERN.match(template_id):
        raise TemplateError(
            "INVALID_TEMPLATE_ID",
            "template_id must be lowercase alphanumeric with underscores, "
            "start/end with alphanumeric",
            pattern=TEMPLATE_ID_PATTERN.pattern,
        )


def get_template_path(
    templates_root: Path,
    template_id: str,
    category: str = "custom",
) -> Path:
    """
    템플릿 폴더 경로 반환.

    Args:
        templates_root: templates/ 루트 경로
        template_id: 템플릿 ID
        category: "base" 또는 "custom"

    Returns:
        템플릿 폴더 경로
    """
    return templates_root / category / template_id


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class TemplateMeta:
    """템플릿 메타데이터 (meta.json)."""
    template_id: str
    doc_type: str
    display_name: str
    description: str = ""

    status: TemplateStatus = TemplateStatus.DRAFT
    version: str = "1.0"

    created_at: str = ""
    created_by: str = ""
    updated_at: str = ""

    derived_from: str | None = None  # source 파일명
    creation_level: str = "manual"  # manual, auto, semi-auto
    reviewed_by: str | None = None
    reviewed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "doc_type": self.doc_type,
            "display_name": self.display_name,
            "description": self.description,
            "status": self.status.value if isinstance(self.status, TemplateStatus) else self.status,
            "version": self.version,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "updated_at": self.updated_at,
            "derived_from": self.derived_from,
            "creation_level": self.creation_level,
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TemplateMeta":
        status = data.get("status", "draft")
        if isinstance(status, str):
            status = TemplateStatus(status)

        return cls(
            template_id=data["template_id"],
            doc_type=data["doc_type"],
            display_name=data["display_name"],
            description=data.get("description", ""),
            status=status,
            version=data.get("version", "1.0"),
            created_at=data.get("created_at", ""),
            created_by=data.get("created_by", ""),
            updated_at=data.get("updated_at", ""),
            derived_from=data.get("derived_from"),
            creation_level=data.get("creation_level", "manual"),
            reviewed_by=data.get("reviewed_by"),
            reviewed_at=data.get("reviewed_at"),
        )


# =============================================================================
# Template Manager
# =============================================================================

class TemplateManager:
    """
    템플릿 CRUD 관리자.

    구조:
    templates/custom/<template_id>/
    ├── source/          # 원본 (불변, 감사용)
    ├── compiled/        # 렌더용 (placeholder 포함)
    ├── meta.json        # 메타데이터
    └── manifest.yaml    # 매핑 정보
    """

    # 락 timeout (초)
    LOCK_TIMEOUT = 10.0

    def __init__(self, templates_root: Path):
        """
        Args:
            templates_root: templates/ 루트 경로
        """
        self.templates_root = templates_root
        self.custom_dir = templates_root / "custom"
        self.base_dir = templates_root / "base"
        self._locks_dir = templates_root / ".locks"

    @contextmanager
    def _template_lock(self, template_id: str) -> Generator[None, None, None]:
        """
        템플릿별 락 획득.

        동시성 보호: 같은 템플릿에 대한 동시 수정 방지.

        Args:
            template_id: 락을 획득할 템플릿 ID

        Yields:
            None

        Raises:
            TemplateError: TEMPLATE_LOCK_TIMEOUT
        """
        self._locks_dir.mkdir(parents=True, exist_ok=True)
        lock_file = self._locks_dir / f"{template_id}.lock"
        lock = FileLock(lock_file, timeout=self.LOCK_TIMEOUT)

        try:
            lock.acquire()
            yield
        except Timeout:
            raise TemplateError(
                "TEMPLATE_LOCK_TIMEOUT",
                f"Failed to acquire lock for template '{template_id}'",
                template_id=template_id,
                timeout=self.LOCK_TIMEOUT,
            )
        finally:
            lock.release()

    # =========================================================================
    # Create
    # =========================================================================

    def create(
        self,
        template_id: str,
        doc_type: str,
        display_name: str,
        created_by: str,
        description: str = "",
    ) -> Path:
        """
        새 템플릿 폴더 생성.

        Args:
            template_id: 템플릿 ID
            doc_type: 문서 타입 (inspection, report 등)
            display_name: 표시 이름
            created_by: 생성자
            description: 설명

        Returns:
            생성된 템플릿 폴더 경로

        Raises:
            TemplateError: INVALID_TEMPLATE_ID, TEMPLATE_EXISTS
        """
        # ID 검증
        validate_template_id(template_id)

        # 동시성 보호: 전체 생성 과정을 락으로 보호
        with self._template_lock(template_id):
            # 중복 체크 (fail-fast)
            template_path = self.custom_dir / template_id
            if template_path.exists():
                raise TemplateError(
                    "TEMPLATE_EXISTS",
                    f"Template '{template_id}' already exists",
                    template_id=template_id,
                )

            # 폴더 구조 생성
            (template_path / "source").mkdir(parents=True)
            (template_path / "compiled").mkdir()

            # 메타데이터 생성
            now = datetime.now(UTC).isoformat()
            meta = TemplateMeta(
                template_id=template_id,
                doc_type=doc_type,
                display_name=display_name,
                description=description,
                status=TemplateStatus.DRAFT,
                created_at=now,
                created_by=created_by,
                updated_at=now,
            )
            self._save_meta(template_path, meta)

            # 빈 manifest 생성
            self._save_manifest(template_path, self._default_manifest(template_id, doc_type))

            return template_path

    # =========================================================================
    # Source Management (불변 가드)
    # =========================================================================

    def save_source(
        self,
        template_id: str,
        file_bytes: bytes,
        filename: str,
    ) -> Path:
        """
        source/ 폴더에 원본 파일 저장.

        ADR-0002: source/ 불변 가드
        - 이미 존재하면 에러
        - 저장 후 chmod 0o444 (읽기 전용)

        Args:
            template_id: 템플릿 ID
            file_bytes: 파일 내용
            filename: 파일명

        Returns:
            저장된 파일 경로

        Raises:
            TemplateError: TEMPLATE_NOT_FOUND, SOURCE_IMMUTABLE
        """
        # 동시성 보호
        with self._template_lock(template_id):
            template_path = self._get_template_path(template_id)
            source_dir = template_path / "source"
            target = source_dir / filename

            # 불변 가드: 이미 존재하면 에러
            if target.exists():
                raise TemplateError(
                    "SOURCE_IMMUTABLE",
                    f"source/{filename} already exists. Cannot overwrite.",
                    template_id=template_id,
                    filename=filename,
                )

            # 저장
            target.write_bytes(file_bytes)

            # readonly 설정 (Unix)
            try:
                target.chmod(0o444)  # r--r--r--
            except OSError:
                pass  # Windows에서는 무시

            # 메타데이터 업데이트
            meta = self.get_meta(template_id)
            meta.derived_from = filename
            meta.updated_at = datetime.now(UTC).isoformat()
            self._save_meta(template_path, meta)

            return target

    def save_compiled(
        self,
        template_id: str,
        file_bytes: bytes,
        filename: str,
    ) -> Path:
        """
        compiled/ 폴더에 렌더용 템플릿 저장.

        compiled/는 덮어쓰기 허용.

        Args:
            template_id: 템플릿 ID
            file_bytes: 파일 내용
            filename: 파일명

        Returns:
            저장된 파일 경로
        """
        template_path = self._get_template_path(template_id)
        compiled_dir = template_path / "compiled"
        target = compiled_dir / filename

        target.write_bytes(file_bytes)

        # 메타데이터 업데이트
        meta = self.get_meta(template_id)
        meta.updated_at = datetime.now(UTC).isoformat()
        self._save_meta(template_path, meta)

        return target

    # =========================================================================
    # Read
    # =========================================================================

    def get_meta(self, template_id: str) -> TemplateMeta:
        """
        템플릿 메타데이터 조회.

        Args:
            template_id: 템플릿 ID

        Returns:
            TemplateMeta

        Raises:
            TemplateError: TEMPLATE_NOT_FOUND
        """
        template_path = self._get_template_path(template_id)
        meta_path = template_path / "meta.json"

        if not meta_path.exists():
            raise TemplateError(
                "TEMPLATE_NOT_FOUND",
                f"meta.json not found for '{template_id}'",
                template_id=template_id,
            )

        data = json.loads(meta_path.read_text(encoding="utf-8"))
        return TemplateMeta.from_dict(data)

    def get_manifest(self, template_id: str) -> dict[str, Any]:
        """
        템플릿 manifest 조회.

        Args:
            template_id: 템플릿 ID

        Returns:
            manifest 내용
        """
        template_path = self._get_template_path(template_id)
        manifest_path = template_path / "manifest.yaml"

        if not manifest_path.exists():
            return self._default_manifest(template_id, "unknown")

        with open(manifest_path, encoding="utf-8") as f:
            data: dict[str, Any] = yaml.safe_load(f)
            return data

    def list_templates(
        self,
        category: str = "custom",
        status: TemplateStatus | None = None,
    ) -> list[TemplateMeta]:
        """
        템플릿 목록 조회.

        Args:
            category: "base", "custom", 또는 "all"
            status: 필터링할 상태 (None이면 전체)

        Returns:
            TemplateMeta 목록
        """
        results = []

        dirs_to_scan = []
        if category in ("base", "all"):
            dirs_to_scan.append(self.base_dir)
        if category in ("custom", "all"):
            dirs_to_scan.append(self.custom_dir)

        for scan_dir in dirs_to_scan:
            if not scan_dir.exists():
                continue

            for template_dir in scan_dir.iterdir():
                if not template_dir.is_dir():
                    continue
                if template_dir.name.startswith("."):
                    continue

                meta_path = template_dir / "meta.json"
                if not meta_path.exists():
                    # manifest.yaml만 있는 base 템플릿 처리
                    manifest_path = template_dir / "manifest.yaml"
                    if manifest_path.exists():
                        with open(manifest_path, encoding="utf-8") as f:
                            manifest = yaml.safe_load(f)
                        meta = TemplateMeta(
                            template_id=manifest.get("template_id", template_dir.name),
                            doc_type=manifest.get("doc_type", "unknown"),
                            display_name=manifest.get("display_name", template_dir.name),
                            status=TemplateStatus.READY,
                        )
                        if status is None or meta.status == status:
                            results.append(meta)
                    continue

                try:
                    data = json.loads(meta_path.read_text(encoding="utf-8"))
                    meta = TemplateMeta.from_dict(data)
                    if status is None or meta.status == status:
                        results.append(meta)
                except (json.JSONDecodeError, KeyError):
                    continue

        return results

    # =========================================================================
    # Update
    # =========================================================================

    def update_status(
        self,
        template_id: str,
        new_status: TemplateStatus,
        reviewed_by: str | None = None,
    ) -> TemplateMeta:
        """
        템플릿 상태 변경.

        Args:
            template_id: 템플릿 ID
            new_status: 새 상태
            reviewed_by: 검토자 (ready로 변경 시)

        Returns:
            업데이트된 TemplateMeta
        """
        # 동시성 보호
        with self._template_lock(template_id):
            template_path = self._get_template_path(template_id)
            meta = self.get_meta(template_id)

            now = datetime.now(UTC).isoformat()
            meta.status = new_status
            meta.updated_at = now

            if new_status == TemplateStatus.READY and reviewed_by:
                meta.reviewed_by = reviewed_by
                meta.reviewed_at = now

            self._save_meta(template_path, meta)
            return meta

    def update_manifest(
        self,
        template_id: str,
        manifest: dict[str, Any],
    ) -> Path:
        """
        manifest.yaml 업데이트.

        Args:
            template_id: 템플릿 ID
            manifest: 새 manifest 내용

        Returns:
            manifest.yaml 경로
        """
        template_path = self._get_template_path(template_id)
        manifest_path = self._save_manifest(template_path, manifest)

        # 메타데이터 업데이트
        meta = self.get_meta(template_id)
        meta.updated_at = datetime.now(UTC).isoformat()
        self._save_meta(template_path, meta)

        return manifest_path

    # =========================================================================
    # Delete
    # =========================================================================

    def delete(self, template_id: str, force: bool = False) -> None:
        """
        템플릿 삭제.

        기본: archived 상태만 삭제 가능
        force=True: 강제 삭제

        Args:
            template_id: 템플릿 ID
            force: 강제 삭제 여부

        Raises:
            TemplateError: TEMPLATE_NOT_FOUND, DELETE_NOT_ALLOWED
        """
        # 동시성 보호
        with self._template_lock(template_id):
            template_path = self._get_template_path(template_id)

            if not force:
                meta = self.get_meta(template_id)
                if meta.status != TemplateStatus.ARCHIVED:
                    raise TemplateError(
                        "DELETE_NOT_ALLOWED",
                        f"Template '{template_id}' is not archived. Use force=True or archive first.",
                        template_id=template_id,
                        status=meta.status.value,
                    )

            # source/ 파일 readonly 해제 후 삭제
            source_dir = template_path / "source"
            if source_dir.exists():
                for f in source_dir.iterdir():
                    try:
                        f.chmod(0o644)
                    except OSError:
                        pass

            shutil.rmtree(template_path)

    # =========================================================================
    # Internal Helpers
    # =========================================================================

    def _get_template_path(self, template_id: str) -> Path:
        """템플릿 경로 반환 (존재 확인)."""
        # custom 먼저 확인
        path = self.custom_dir / template_id
        if path.exists():
            return path

        # base 확인
        path = self.base_dir / template_id
        if path.exists():
            return path

        raise TemplateError(
            "TEMPLATE_NOT_FOUND",
            f"Template '{template_id}' not found",
            template_id=template_id,
        )

    def _save_meta(self, template_path: Path, meta: TemplateMeta) -> Path:
        """meta.json 저장."""
        meta_path = template_path / "meta.json"
        meta_path.write_text(
            json.dumps(meta.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return meta_path

    def _save_manifest(self, template_path: Path, manifest: dict[str, Any]) -> Path:
        """manifest.yaml 저장."""
        manifest_path = template_path / "manifest.yaml"
        with open(manifest_path, "w", encoding="utf-8") as f:
            yaml.dump(manifest, f, default_flow_style=False, allow_unicode=True)
        return manifest_path

    def _default_manifest(self, template_id: str, doc_type: str) -> dict[str, Any]:
        """기본 manifest 생성."""
        return {
            "template_id": template_id,
            "doc_type": doc_type,
            "docx_placeholders": [],
            "xlsx_mappings": {
                "named_ranges": {},
                "cell_addresses": {},
                "measurements": {
                    "sheet": "Sheet1",
                    "start_row": 5,
                    "columns": {},
                },
                "conflict_policy": "fail",
            },
        }
