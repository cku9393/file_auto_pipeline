"""
test_scaffolder.py - 템플릿 스캐폴더 테스트

ADR-0002 검증:
- Level 1 (자동): placeholder가 이미 있음 → requires_review=False
- Level 2 (반자동): 완성본 → 패턴 감지 → requires_review=True
- 검수 없는 100% 자동 생성 금지
"""

from pathlib import Path

import pytest
import yaml

from src.templates.scaffolder import (
    DetectedField,
    ScaffoldLevel,
    ScaffoldResult,
    TemplateScaffolder,
    analyze_example_document,
    detect_labels_rule_based,
    detect_placeholders,
    has_placeholders,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def sample_definition(tmp_path: Path) -> Path:
    """테스트용 definition.yaml."""
    definition = {
        "definition_version": "1.0.0",
        "fields": {
            "wo_no": {"type": "token", "importance": "critical"},
            "line": {"type": "token", "importance": "critical"},
            "part_no": {"type": "token", "importance": "critical"},
            "lot": {"type": "token", "importance": "critical"},
            "result": {"type": "token", "importance": "critical"},
            "inspector": {"type": "token", "importance": "reference"},
            "date": {"type": "token", "importance": "reference"},
            "remark": {"type": "free_text", "importance": "optional"},
        },
    }

    definition_path = tmp_path / "definition.yaml"
    with open(definition_path, "w", encoding="utf-8") as f:
        yaml.dump(definition, f, allow_unicode=True)

    return definition_path


@pytest.fixture
def scaffolder(sample_definition: Path) -> TemplateScaffolder:
    """TemplateScaffolder 인스턴스."""
    return TemplateScaffolder(sample_definition)


# =============================================================================
# detect_placeholders 테스트
# =============================================================================


class TestDetectPlaceholders:
    """detect_placeholders 함수 테스트."""

    def test_detects_simple_placeholders(self):
        """간단한 placeholder 감지."""
        text = "작업번호: {{wo_no}}\n라인: {{line}}"

        placeholders = detect_placeholders(text)

        assert "wo_no" in placeholders
        assert "line" in placeholders

    def test_detects_with_spaces(self):
        """공백 포함 placeholder."""
        text = "{{ wo_no }}"

        placeholders = detect_placeholders(text)

        assert "wo_no" in placeholders

    def test_no_placeholders(self):
        """placeholder 없음."""
        text = "작업번호: WO-001\n라인: L1"

        placeholders = detect_placeholders(text)

        assert placeholders == []

    def test_multiple_same_placeholder(self):
        """동일 placeholder 중복."""
        text = "{{wo_no}} and again {{wo_no}}"

        placeholders = detect_placeholders(text)

        # findall은 모든 매치 반환
        assert placeholders.count("wo_no") == 2


class TestHasPlaceholders:
    """has_placeholders 함수 테스트."""

    def test_returns_true(self):
        """placeholder 있으면 True."""
        assert has_placeholders("Hello {{name}}")

    def test_returns_false(self):
        """placeholder 없으면 False."""
        assert not has_placeholders("Hello World")


# =============================================================================
# detect_labels_rule_based 테스트
# =============================================================================


class TestDetectLabelsRuleBased:
    """detect_labels_rule_based 함수 테스트."""

    def test_detects_wo_no(self):
        """WO No 패턴 감지."""
        texts = [
            "WO No.: WO-001",
            "W/O No. WO-002",
            "작업지시번호: WO-003",
            "Work Order: WO-004",
        ]

        for text in texts:
            detected = detect_labels_rule_based(text)
            assert any(f.field_name == "wo_no" for f in detected), f"Failed for: {text}"

    def test_detects_line(self):
        """Line 패턴 감지."""
        texts = [
            "Line: L1",
            "라인: 라인A",
            "Line No.: LINE-001",
        ]

        for text in texts:
            detected = detect_labels_rule_based(text)
            assert any(f.field_name == "line" for f in detected), f"Failed for: {text}"

    def test_detects_inspector(self):
        """Inspector 패턴 감지."""
        texts = [
            "Inspector: 홍길동",
            "검사자: 김철수",
            "담당자: 이영희",
            "Inspected By: John",
        ]

        for text in texts:
            detected = detect_labels_rule_based(text)
            assert any(f.field_name == "inspector" for f in detected), (
                f"Failed for: {text}"
            )

    def test_extracts_values(self):
        """값 추출."""
        text = "WO No.: WO-001"

        detected = detect_labels_rule_based(text)

        wo_field = next(f for f in detected if f.field_name == "wo_no")
        assert wo_field.original_value == "WO-001"
        assert "WO" in wo_field.label_text

    def test_skips_placeholders(self):
        """placeholder는 건너뜀."""
        text = "WO No.: {{wo_no}}"

        detected = detect_labels_rule_based(text)

        # placeholder는 값으로 감지되지 않음
        assert not any(f.original_value == "{{wo_no}}" for f in detected)

    def test_confidence_is_medium(self):
        """규칙 기반은 중간 신뢰도 (0.7)."""
        text = "Line: L1"

        detected = detect_labels_rule_based(text)

        assert all(f.confidence == 0.7 for f in detected)


# =============================================================================
# TemplateScaffolder.analyze_document 테스트
# =============================================================================


class TestTemplateScaffolderAnalyze:
    """TemplateScaffolder.analyze_document 테스트."""

    def test_level1_with_placeholders(self, scaffolder: TemplateScaffolder):
        """
        Level 1 (자동): placeholder가 있으면.

        ADR-0002: requires_review=False (선택적)
        """
        text = """
        검사 성적서

        작업번호: {{wo_no}}
        라인: {{line}}
        결과: {{result}}
        """

        result = scaffolder.analyze_document(text)

        assert result.level == ScaffoldLevel.AUTO
        assert result.requires_review is False

        detected_names = {f.field_name for f in result.detected_fields}
        assert "wo_no" in detected_names
        assert "line" in detected_names
        assert "result" in detected_names

    def test_level1_warns_unknown_placeholders(self, scaffolder: TemplateScaffolder):
        """Level 1: definition.yaml에 없는 placeholder 경고."""
        text = "{{wo_no}} {{unknown_field}}"

        result = scaffolder.analyze_document(text)

        assert result.level == ScaffoldLevel.AUTO
        assert any("unknown" in w.lower() for w in result.warnings)

    def test_level2_without_placeholders(self, scaffolder: TemplateScaffolder):
        """
        Level 2 (반자동): placeholder가 없으면.

        ADR-0002: requires_review=True (필수)
        """
        text = """
        검사 성적서

        작업번호: WO-001
        라인: L1
        검사자: 홍길동
        결과: PASS
        """

        result = scaffolder.analyze_document(text)

        assert result.level == ScaffoldLevel.SEMI_AUTO
        assert result.requires_review is True

    def test_level2_detects_fields(self, scaffolder: TemplateScaffolder):
        """Level 2: 필드 감지."""
        text = """
        WO No.: WO-001
        Line: L1
        Inspector: 홍길동
        """

        result = scaffolder.analyze_document(text)

        detected_names = {f.field_name for f in result.detected_fields}
        assert "wo_no" in detected_names
        assert "line" in detected_names
        assert "inspector" in detected_names

    def test_level2_warns_missing_critical(self, scaffolder: TemplateScaffolder):
        """Level 2: critical 필드 누락 경고."""
        text = """
        WO No.: WO-001
        Inspector: 홍길동
        """
        # line, part_no, lot, result 누락

        result = scaffolder.analyze_document(text)

        assert any("critical" in w.lower() for w in result.warnings)

    def test_detects_measurements_table(self, scaffolder: TemplateScaffolder):
        """측정 테이블 감지."""
        text = """
        WO No.: WO-001

        항목 | SPEC | MEASURED | 결과
        길이 | 10±0.1 | 10.05 | PASS
        폭 | 5±0.1 | 5.02 | PASS
        """

        result = scaffolder.analyze_document(text)

        assert result.detected_measurements is True


# =============================================================================
# ScaffoldResult 테스트
# =============================================================================


class TestScaffoldResult:
    """ScaffoldResult 데이터클래스 테스트."""

    def test_to_dict(self):
        """dict 변환."""
        result = ScaffoldResult(
            level=ScaffoldLevel.AUTO,
            detected_fields=[
                DetectedField(
                    field_name="wo_no",
                    label_text="{{wo_no}}",
                    original_value="(placeholder)",
                    confidence=1.0,
                ),
            ],
            detected_measurements=True,
            suggested_manifest={"template_id": "test"},
            warnings=["test warning"],
            requires_review=False,
        )

        d = result.to_dict()

        assert d["level"] == "auto"
        assert len(d["detected_fields"]) == 1
        assert d["detected_fields"][0]["field_name"] == "wo_no"
        assert d["detected_measurements"] is True
        assert d["requires_review"] is False


# =============================================================================
# analyze_example_document 간편 함수 테스트
# =============================================================================


class TestAnalyzeExampleDocument:
    """analyze_example_document 간편 함수 테스트."""

    def test_basic_usage(self, sample_definition: Path):
        """기본 사용."""
        text = "{{wo_no}} {{line}}"

        result = analyze_example_document(text, sample_definition)

        assert result.level == ScaffoldLevel.AUTO
        assert len(result.detected_fields) >= 2


# =============================================================================
# 검수 플래그 테스트 (ADR-0002 핵심)
# =============================================================================


class TestRequiresReviewFlag:
    """
    ADR-0002: 검수 없는 100% 자동 생성 금지.

    - Level 1 (placeholder 있음): requires_review=False (선택적)
    - Level 2 (완성본): requires_review=True (필수)
    """

    def test_level1_review_optional(self, scaffolder: TemplateScaffolder):
        """Level 1은 검수 선택적."""
        text = "{{wo_no}} {{line}} {{result}}"

        result = scaffolder.analyze_document(text)

        assert result.level == ScaffoldLevel.AUTO
        assert result.requires_review is False

    def test_level2_review_required(self, scaffolder: TemplateScaffolder):
        """Level 2는 검수 필수."""
        text = "WO No.: WO-001\nLine: L1"

        result = scaffolder.analyze_document(text)

        assert result.level == ScaffoldLevel.SEMI_AUTO
        assert result.requires_review is True

    def test_suggested_manifest_generated(self, scaffolder: TemplateScaffolder):
        """manifest 초안 생성."""
        text = "{{wo_no}} {{line}}"

        result = scaffolder.analyze_document(text)

        assert "docx_placeholders" in result.suggested_manifest
        assert "wo_no" in result.suggested_manifest["docx_placeholders"]
        assert "line" in result.suggested_manifest["docx_placeholders"]
