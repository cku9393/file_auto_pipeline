"""
test_manager.py - 템플릿 관리자 테스트

ADR-0002 검증:
- source/ 불변: 덮어쓰기 시 에러, chmod 0o444
- template_id 네이밍: {customer}_{doctype}, 최대 50자
- 중복 template_id 생성 시 에러 (fail-fast)
- 상태: draft → ready → archived
"""

import json
import os
import stat
from pathlib import Path

import pytest
import yaml

from src.templates.manager import (
    TemplateError,
    TemplateManager,
    TemplateMeta,
    TemplateStatus,
    validate_template_id,
    get_template_path,
    TEMPLATE_ID_PATTERN,
    TEMPLATE_ID_MAX_LENGTH,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def templates_root(tmp_path: Path) -> Path:
    """테스트용 templates/ 루트."""
    root = tmp_path / "templates"
    (root / "base").mkdir(parents=True)
    (root / "custom").mkdir(parents=True)
    return root


@pytest.fixture
def manager(templates_root: Path) -> TemplateManager:
    """TemplateManager 인스턴스."""
    return TemplateManager(templates_root)


@pytest.fixture
def sample_template(manager: TemplateManager) -> str:
    """샘플 템플릿 생성 후 ID 반환."""
    template_id = "customer_a_inspection"
    manager.create(
        template_id=template_id,
        doc_type="inspection",
        display_name="고객사A 검사성적서",
        created_by="test_user",
        description="테스트용 템플릿",
    )
    return template_id


# =============================================================================
# validate_template_id 테스트
# =============================================================================

class TestValidateTemplateId:
    """template_id 유효성 검증 테스트."""

    def test_valid_ids(self):
        """유효한 ID들."""
        valid_ids = [
            "customer_a",
            "customer_a_inspection",
            "customer_a_inspection_v2",
            "ab",  # 최소 2자
            "a1b2c3",
            "test123",
        ]

        for tid in valid_ids:
            validate_template_id(tid)  # 에러 없어야 함

    def test_empty_id(self):
        """빈 ID → 에러."""
        with pytest.raises(TemplateError) as exc_info:
            validate_template_id("")

        assert exc_info.value.code == "INVALID_TEMPLATE_ID"
        assert "empty" in exc_info.value.message.lower()

    def test_too_long_id(self):
        """50자 초과 → 에러."""
        long_id = "a" * 51

        with pytest.raises(TemplateError) as exc_info:
            validate_template_id(long_id)

        assert exc_info.value.code == "INVALID_TEMPLATE_ID"
        assert "50" in exc_info.value.message

    def test_max_length_id(self):
        """50자는 허용."""
        max_id = "a" * 48 + "b1"  # 50자
        validate_template_id(max_id)  # 에러 없어야 함

    def test_forbidden_characters(self):
        """금지 문자 → 에러."""
        forbidden_ids = [
            "customer/a",     # /
            "customer\\a",    # \
            "customer:a",     # :
            "customer*a",     # *
            "customer?a",     # ?
            'customer"a',     # "
            "customer<a",     # <
            "customer>a",     # >
            "customer|a",     # |
            "customer a",     # 공백
        ]

        for tid in forbidden_ids:
            with pytest.raises(TemplateError) as exc_info:
                validate_template_id(tid)

            assert exc_info.value.code == "INVALID_TEMPLATE_ID"
            assert "forbidden" in exc_info.value.message.lower()

    def test_uppercase_not_allowed(self):
        """대문자 → 에러."""
        with pytest.raises(TemplateError) as exc_info:
            validate_template_id("Customer_A")

        assert exc_info.value.code == "INVALID_TEMPLATE_ID"

    def test_start_with_underscore_not_allowed(self):
        """밑줄로 시작 → 에러."""
        with pytest.raises(TemplateError) as exc_info:
            validate_template_id("_customer")

        assert exc_info.value.code == "INVALID_TEMPLATE_ID"

    def test_end_with_underscore_not_allowed(self):
        """밑줄로 끝 → 에러."""
        with pytest.raises(TemplateError) as exc_info:
            validate_template_id("customer_")

        assert exc_info.value.code == "INVALID_TEMPLATE_ID"

    def test_single_char_not_allowed(self):
        """단일 문자 → 에러 (패턴이 시작+끝 알파뉴메릭 요구)."""
        with pytest.raises(TemplateError) as exc_info:
            validate_template_id("a")

        assert exc_info.value.code == "INVALID_TEMPLATE_ID"


# =============================================================================
# TemplateManager.create 테스트
# =============================================================================

class TestTemplateManagerCreate:
    """TemplateManager.create 테스트."""

    def test_creates_folder_structure(
        self,
        manager: TemplateManager,
        templates_root: Path,
    ):
        """폴더 구조 생성."""
        template_id = "test_template"

        path = manager.create(
            template_id=template_id,
            doc_type="inspection",
            display_name="테스트 템플릿",
            created_by="test_user",
        )

        assert path.exists()
        assert (path / "source").is_dir()
        assert (path / "compiled").is_dir()
        assert (path / "meta.json").exists()
        assert (path / "manifest.yaml").exists()

    def test_creates_meta_json(
        self,
        manager: TemplateManager,
    ):
        """meta.json 생성."""
        template_id = "test_meta"

        manager.create(
            template_id=template_id,
            doc_type="inspection",
            display_name="테스트",
            created_by="user1",
            description="설명입니다",
        )

        meta = manager.get_meta(template_id)

        assert meta.template_id == template_id
        assert meta.doc_type == "inspection"
        assert meta.display_name == "테스트"
        assert meta.created_by == "user1"
        assert meta.description == "설명입니다"
        assert meta.status == TemplateStatus.DRAFT

    def test_duplicate_id_raises_error(
        self,
        manager: TemplateManager,
    ):
        """
        ADR-0002: 중복 template_id 생성 시 에러 (fail-fast).
        """
        template_id = "duplicate_test"

        # 첫 번째 생성
        manager.create(
            template_id=template_id,
            doc_type="inspection",
            display_name="첫 번째",
            created_by="user1",
        )

        # 두 번째 생성 시도 → 에러
        with pytest.raises(TemplateError) as exc_info:
            manager.create(
                template_id=template_id,
                doc_type="report",
                display_name="두 번째",
                created_by="user2",
            )

        assert exc_info.value.code == "TEMPLATE_EXISTS"
        assert template_id in exc_info.value.message

    def test_invalid_id_raises_error(
        self,
        manager: TemplateManager,
    ):
        """잘못된 ID → 에러."""
        with pytest.raises(TemplateError) as exc_info:
            manager.create(
                template_id="Invalid ID",  # 공백, 대문자
                doc_type="inspection",
                display_name="테스트",
                created_by="user1",
            )

        assert exc_info.value.code == "INVALID_TEMPLATE_ID"


# =============================================================================
# TemplateManager.save_source 테스트 (source/ 불변 가드)
# =============================================================================

class TestTemplateManagerSaveSource:
    """
    save_source 테스트.

    ADR-0002: source/ 불변 가드
    - 이미 존재하면 에러
    - 저장 후 chmod 0o444
    """

    def test_saves_file(
        self,
        manager: TemplateManager,
        sample_template: str,
    ):
        """파일 저장."""
        file_bytes = b"example docx content"
        filename = "example.docx"

        path = manager.save_source(sample_template, file_bytes, filename)

        assert path.exists()
        assert path.read_bytes() == file_bytes

    def test_updates_derived_from(
        self,
        manager: TemplateManager,
        sample_template: str,
    ):
        """meta.derived_from 업데이트."""
        manager.save_source(sample_template, b"content", "source.docx")

        meta = manager.get_meta(sample_template)

        assert meta.derived_from == "source.docx"

    def test_sets_readonly_permission(
        self,
        manager: TemplateManager,
        sample_template: str,
    ):
        """
        ADR-0002: chmod 0o444 (읽기 전용).
        """
        path = manager.save_source(sample_template, b"content", "file.docx")

        # Unix 권한 확인
        mode = path.stat().st_mode
        # 0o444 = S_IRUSR | S_IRGRP | S_IROTH
        expected = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH

        assert (mode & 0o777) == expected

    def test_overwrite_raises_error(
        self,
        manager: TemplateManager,
        sample_template: str,
    ):
        """
        ADR-0002: source/ 덮어쓰기 시 에러.
        """
        filename = "example.docx"

        # 첫 번째 저장
        manager.save_source(sample_template, b"original", filename)

        # 두 번째 저장 시도 → 에러
        with pytest.raises(TemplateError) as exc_info:
            manager.save_source(sample_template, b"new content", filename)

        assert exc_info.value.code == "SOURCE_IMMUTABLE"
        assert "already exists" in exc_info.value.message

    def test_different_filename_allowed(
        self,
        manager: TemplateManager,
        sample_template: str,
    ):
        """다른 파일명은 허용."""
        manager.save_source(sample_template, b"docx", "example.docx")
        manager.save_source(sample_template, b"xlsx", "example.xlsx")  # 에러 없음

        # 둘 다 존재
        template_path = manager._get_template_path(sample_template)
        assert (template_path / "source" / "example.docx").exists()
        assert (template_path / "source" / "example.xlsx").exists()


# =============================================================================
# TemplateManager.save_compiled 테스트
# =============================================================================

class TestTemplateManagerSaveCompiled:
    """save_compiled 테스트 (compiled/는 덮어쓰기 허용)."""

    def test_saves_file(
        self,
        manager: TemplateManager,
        sample_template: str,
    ):
        """파일 저장."""
        path = manager.save_compiled(sample_template, b"template", "report.docx")

        assert path.exists()
        assert path.read_bytes() == b"template"

    def test_overwrite_allowed(
        self,
        manager: TemplateManager,
        sample_template: str,
    ):
        """compiled/는 덮어쓰기 허용."""
        filename = "report.docx"

        manager.save_compiled(sample_template, b"version 1", filename)
        manager.save_compiled(sample_template, b"version 2", filename)  # 에러 없음

        template_path = manager._get_template_path(sample_template)
        content = (template_path / "compiled" / filename).read_bytes()

        assert content == b"version 2"


# =============================================================================
# TemplateManager.update_status 테스트
# =============================================================================

class TestTemplateManagerUpdateStatus:
    """update_status 테스트."""

    def test_draft_to_ready(
        self,
        manager: TemplateManager,
        sample_template: str,
    ):
        """draft → ready 전환."""
        meta = manager.update_status(
            sample_template,
            TemplateStatus.READY,
            reviewed_by="reviewer1",
        )

        assert meta.status == TemplateStatus.READY
        assert meta.reviewed_by == "reviewer1"
        assert meta.reviewed_at is not None

    def test_ready_to_archived(
        self,
        manager: TemplateManager,
        sample_template: str,
    ):
        """ready → archived 전환."""
        manager.update_status(sample_template, TemplateStatus.READY)
        meta = manager.update_status(sample_template, TemplateStatus.ARCHIVED)

        assert meta.status == TemplateStatus.ARCHIVED


# =============================================================================
# TemplateManager.list_templates 테스트
# =============================================================================

class TestTemplateManagerListTemplates:
    """list_templates 테스트."""

    def test_lists_custom_templates(
        self,
        manager: TemplateManager,
    ):
        """custom 템플릿 목록."""
        manager.create("template_a", "inspection", "Template A", "user1")
        manager.create("template_b", "report", "Template B", "user1")

        templates = manager.list_templates(category="custom")

        assert len(templates) == 2
        ids = {t.template_id for t in templates}
        assert "template_a" in ids
        assert "template_b" in ids

    def test_filter_by_status(
        self,
        manager: TemplateManager,
    ):
        """상태로 필터링."""
        manager.create("draft_1", "inspection", "Draft 1", "user1")
        manager.create("draft_2", "inspection", "Draft 2", "user1")
        manager.update_status("draft_2", TemplateStatus.READY)

        drafts = manager.list_templates(status=TemplateStatus.DRAFT)
        ready = manager.list_templates(status=TemplateStatus.READY)

        assert len(drafts) == 1
        assert drafts[0].template_id == "draft_1"
        assert len(ready) == 1
        assert ready[0].template_id == "draft_2"


# =============================================================================
# TemplateManager.delete 테스트
# =============================================================================

class TestTemplateManagerDelete:
    """delete 테스트."""

    def test_delete_archived_template(
        self,
        manager: TemplateManager,
        sample_template: str,
    ):
        """archived 템플릿 삭제."""
        manager.update_status(sample_template, TemplateStatus.ARCHIVED)

        manager.delete(sample_template)

        with pytest.raises(TemplateError) as exc_info:
            manager.get_meta(sample_template)

        assert exc_info.value.code == "TEMPLATE_NOT_FOUND"

    def test_delete_non_archived_raises_error(
        self,
        manager: TemplateManager,
        sample_template: str,
    ):
        """archived가 아닌 템플릿 삭제 시 에러."""
        with pytest.raises(TemplateError) as exc_info:
            manager.delete(sample_template)

        assert exc_info.value.code == "DELETE_NOT_ALLOWED"

    def test_force_delete(
        self,
        manager: TemplateManager,
        sample_template: str,
    ):
        """force=True로 강제 삭제."""
        manager.delete(sample_template, force=True)

        with pytest.raises(TemplateError):
            manager.get_meta(sample_template)

    def test_delete_removes_readonly_source(
        self,
        manager: TemplateManager,
        sample_template: str,
    ):
        """readonly source/ 파일도 삭제."""
        manager.save_source(sample_template, b"content", "file.docx")
        manager.update_status(sample_template, TemplateStatus.ARCHIVED)

        manager.delete(sample_template)  # 에러 없이 삭제


# =============================================================================
# TemplateMeta 테스트
# =============================================================================

class TestTemplateMeta:
    """TemplateMeta 데이터클래스 테스트."""

    def test_to_dict(self):
        """dict 변환."""
        meta = TemplateMeta(
            template_id="test",
            doc_type="inspection",
            display_name="테스트",
            status=TemplateStatus.READY,
        )

        d = meta.to_dict()

        assert d["template_id"] == "test"
        assert d["status"] == "ready"  # enum → string

    def test_from_dict(self):
        """dict에서 생성."""
        d = {
            "template_id": "test",
            "doc_type": "inspection",
            "display_name": "테스트",
            "status": "ready",
        }

        meta = TemplateMeta.from_dict(d)

        assert meta.template_id == "test"
        assert meta.status == TemplateStatus.READY
