"""
템플릿 스캐폴더: 예시 문서 → 템플릿 생성.

ADR-0002 2단계 접근:
- Level 1 (자동): placeholder가 이미 있는 문서 → 그대로 compiled/에 복사
- Level 2 (반자동): 완성본 → LLM 패턴 감지 → 사용자 검수 → 확정

⚠️ 검수 없는 100% 자동 생성은 금지 (유령버그 방지)
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

import yaml

# =============================================================================
# Types
# =============================================================================


class ScaffoldLevel(str, Enum):
    """스캐폴딩 레벨."""

    AUTO = "auto"  # Level 1: placeholder 있음
    SEMI_AUTO = "semi-auto"  # Level 2: LLM 감지 + 검수
    MANUAL = "manual"  # 수동 편집


@dataclass
class DetectedField:
    """감지된 필드."""

    field_name: str  # definition.yaml 키 (wo_no, line 등)
    label_text: str  # 원본에서 발견된 라벨 ("작업지시:", "W/O No." 등)
    original_value: str  # 원본에서 발견된 값 ("WO-001" 등)
    confidence: float  # 감지 신뢰도 (0.0 ~ 1.0)
    position: str | None = None  # 위치 정보 (셀 주소, 문단 번호 등)


@dataclass
class ScaffoldResult:
    """스캐폴딩 결과."""

    level: ScaffoldLevel
    detected_fields: list[DetectedField] = field(default_factory=list)
    detected_measurements: bool = False
    suggested_manifest: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    requires_review: bool = True  # 검수 필요 여부

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level.value,
            "detected_fields": [
                {
                    "field_name": f.field_name,
                    "label_text": f.label_text,
                    "original_value": f.original_value,
                    "confidence": f.confidence,
                    "position": f.position,
                }
                for f in self.detected_fields
            ],
            "detected_measurements": self.detected_measurements,
            "suggested_manifest": self.suggested_manifest,
            "warnings": self.warnings,
            "requires_review": self.requires_review,
        }


# =============================================================================
# LLM Provider Protocol (for dependency injection)
# =============================================================================


class LLMExtractor(Protocol):
    """LLM 기반 필드 추출 인터페이스."""

    async def extract_fields(
        self,
        document_text: str,
        field_definitions: dict[str, Any],
    ) -> list[DetectedField]:
        """
        문서 텍스트에서 필드 추출.

        Args:
            document_text: 문서 전체 텍스트
            field_definitions: definition.yaml의 fields 섹션

        Returns:
            DetectedField 목록
        """
        ...


# =============================================================================
# Placeholder Detection
# =============================================================================

# Jinja2/docxtpl 스타일 placeholder 패턴
PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def detect_placeholders(text: str) -> list[str]:
    """
    텍스트에서 placeholder 감지.

    {{wo_no}}, {{ line }} 등의 패턴을 찾음.

    Args:
        text: 검색할 텍스트

    Returns:
        placeholder 이름 목록
    """
    return PLACEHOLDER_PATTERN.findall(text)


def has_placeholders(text: str) -> bool:
    """placeholder가 있는지 확인."""
    return bool(PLACEHOLDER_PATTERN.search(text))


# =============================================================================
# Label Pattern Detection (규칙 기반)
# =============================================================================

# 라벨 → 필드 매핑 (definition.yaml aliases 기반으로 확장 가능)
DEFAULT_LABEL_PATTERNS = {
    # wo_no
    r"(?:WO|W/O|작업지시|Work\s*Order)\s*(?:No\.?|번호)?": "wo_no",
    # line
    r"(?:Line|라인)\s*(?:No\.?|번호)?": "line",
    # part_no
    r"(?:Part|P/N|부품)\s*(?:No\.?|번호)?": "part_no",
    # lot
    r"(?:Lot|로트)\s*(?:No\.?|번호)?": "lot",
    # result
    r"(?:Result|결과|판정)": "result",
    # inspector
    r"(?:Inspector|검사자|담당자|Inspected\s*By)": "inspector",
    # date
    r"(?:Date|일자|검사일|Inspection\s*Date)": "date",
}


def detect_labels_rule_based(
    text: str,
    patterns: dict[str, str] | None = None,
) -> list[DetectedField]:
    """
    규칙 기반 라벨 패턴 감지.

    Args:
        text: 검색할 텍스트
        patterns: 라벨 패턴 → 필드명 매핑

    Returns:
        DetectedField 목록
    """
    if patterns is None:
        patterns = DEFAULT_LABEL_PATTERNS

    results = []

    for pattern, field_name in patterns.items():
        # 라벨 + 값 패턴 (예: "WO No.: WO-001")
        full_pattern = rf"({pattern})\s*[:：]?\s*([^\n\r,;]+)"
        matches = re.finditer(full_pattern, text, re.IGNORECASE)

        for match in matches:
            label_text = match.group(1).strip()
            value = match.group(2).strip()

            # 빈 값이나 placeholder는 건너뛰기
            if not value or PLACEHOLDER_PATTERN.match(value):
                continue

            results.append(
                DetectedField(
                    field_name=field_name,
                    label_text=label_text,
                    original_value=value,
                    confidence=0.7,  # 규칙 기반은 중간 신뢰도
                )
            )

    return results


# =============================================================================
# Template Scaffolder
# =============================================================================


class TemplateScaffolder:
    """
    템플릿 스캐폴더.

    예시 문서를 분석하여 템플릿 초안 생성.
    """

    def __init__(
        self,
        definition_path: Path,
        llm_extractor: LLMExtractor | None = None,
    ):
        """
        Args:
            definition_path: definition.yaml 경로
            llm_extractor: LLM 추출기 (Level 2 사용 시)
        """
        self.definition_path = definition_path
        self.llm_extractor = llm_extractor
        self._definition: dict | None = None

    @property
    def definition(self) -> dict:
        """definition.yaml 로드 (lazy)."""
        if self._definition is None:
            with open(self.definition_path, encoding="utf-8") as f:
                self._definition = yaml.safe_load(f)
        return self._definition

    def analyze_document(self, text: str) -> ScaffoldResult:
        """
        문서 분석 및 스캐폴딩 레벨 결정.

        Args:
            text: 문서 전체 텍스트

        Returns:
            ScaffoldResult
        """
        # Level 1 체크: placeholder가 있는가?
        placeholders = detect_placeholders(text)
        if placeholders:
            return self._scaffold_level1(text, placeholders)

        # Level 2: 규칙 기반 + (선택적) LLM
        return self._scaffold_level2(text)

    def _scaffold_level1(
        self,
        text: str,
        placeholders: list[str],
    ) -> ScaffoldResult:
        """
        Level 1 (자동): placeholder가 이미 있는 경우.

        → 그대로 compiled/에 복사 가능
        → 검수 권장하지만 필수는 아님
        """
        # placeholder가 definition.yaml 필드와 매칭되는지 확인
        defined_fields = set(self.definition.get("fields", {}).keys())
        matched = [p for p in placeholders if p in defined_fields]
        unknown = [p for p in placeholders if p not in defined_fields]

        warnings = []
        if unknown:
            warnings.append(f"Unknown placeholders (not in definition.yaml): {unknown}")

        # manifest 생성
        manifest = self._build_manifest_from_placeholders(matched)

        return ScaffoldResult(
            level=ScaffoldLevel.AUTO,
            detected_fields=[
                DetectedField(
                    field_name=p,
                    label_text=f"{{{{{p}}}}}",
                    original_value="(placeholder)",
                    confidence=1.0,
                )
                for p in matched
            ],
            detected_measurements="measurements" in placeholders,
            suggested_manifest=manifest,
            warnings=warnings,
            requires_review=False,  # Level 1은 검수 선택적
        )

    def _scaffold_level2(self, text: str) -> ScaffoldResult:
        """
        Level 2 (반자동): 완성본에서 패턴 감지.

        → 규칙 기반 먼저 시도
        → LLM은 보조적으로 사용
        → 사용자 검수 필수
        """
        # 규칙 기반 감지
        detected = detect_labels_rule_based(text)

        warnings = []

        # 필수 필드 누락 체크
        detected_names = {f.field_name for f in detected}
        required_fields = [
            name
            for name, config in self.definition.get("fields", {}).items()
            if config.get("importance") == "critical"
        ]
        missing = set(required_fields) - detected_names
        if missing:
            warnings.append(f"Critical fields not detected: {list(missing)}")

        # 측정 테이블 감지 (간단한 휴리스틱)
        measurement_keywords = ["SPEC", "MEASURED", "측정", "규격"]
        has_measurements = any(
            kw.lower() in text.lower() for kw in measurement_keywords
        )

        # manifest 생성
        manifest = self._build_manifest_from_detected(detected)

        return ScaffoldResult(
            level=ScaffoldLevel.SEMI_AUTO,
            detected_fields=detected,
            detected_measurements=has_measurements,
            suggested_manifest=manifest,
            warnings=warnings,
            requires_review=True,  # Level 2는 검수 필수
        )

    async def scaffold_with_llm(self, text: str) -> ScaffoldResult:
        """
        LLM을 활용한 스캐폴딩 (Level 2 강화).

        Args:
            text: 문서 전체 텍스트

        Returns:
            ScaffoldResult
        """
        if self.llm_extractor is None:
            return self._scaffold_level2(text)

        # 규칙 기반 먼저
        rule_result = self._scaffold_level2(text)

        # LLM 추출
        llm_detected = await self.llm_extractor.extract_fields(
            text,
            self.definition.get("fields", {}),
        )

        # 결과 병합 (LLM이 더 높은 confidence면 교체)
        merged = self._merge_detected_fields(
            rule_result.detected_fields,
            llm_detected,
        )

        return ScaffoldResult(
            level=ScaffoldLevel.SEMI_AUTO,
            detected_fields=merged,
            detected_measurements=rule_result.detected_measurements,
            suggested_manifest=self._build_manifest_from_detected(merged),
            warnings=rule_result.warnings,
            requires_review=True,
        )

    def _merge_detected_fields(
        self,
        rule_detected: list[DetectedField],
        llm_detected: list[DetectedField],
    ) -> list[DetectedField]:
        """규칙 기반 + LLM 결과 병합."""
        merged = {f.field_name: f for f in rule_detected}

        for llm_field in llm_detected:
            existing = merged.get(llm_field.field_name)
            if existing is None or llm_field.confidence > existing.confidence:
                merged[llm_field.field_name] = llm_field

        return list(merged.values())

    def _build_manifest_from_placeholders(
        self,
        placeholders: list[str],
    ) -> dict[str, Any]:
        """placeholder 목록에서 manifest 생성."""
        return {
            "docx_placeholders": placeholders,
            "xlsx_mappings": {
                "named_ranges": {},
                "cell_addresses": {},
                "measurements": {
                    "sheet": "Sheet1",
                    "start_row": 5,
                    "columns": {
                        "item": "A",
                        "spec": "B",
                        "measured": "C",
                        "result": "D",
                    },
                },
                "conflict_policy": "fail",
            },
        }

    def _build_manifest_from_detected(
        self,
        detected: list[DetectedField],
    ) -> dict[str, Any]:
        """감지된 필드에서 manifest 생성."""
        placeholders = [f.field_name for f in detected]

        # 라벨 매핑 (반자동 생성 시 유용)
        label_mappings = {f.label_text: f.field_name for f in detected}

        return {
            "docx_placeholders": placeholders,
            "xlsx_mappings": {
                "named_ranges": {},
                "cell_addresses": {},
                "measurements": {
                    "sheet": "Sheet1",
                    "start_row": 5,
                    "columns": {
                        "item": "A",
                        "spec": "B",
                        "measured": "C",
                        "result": "D",
                    },
                },
                "conflict_policy": "fail",
            },
            "label_mappings": label_mappings,
        }


# =============================================================================
# Convenience Functions
# =============================================================================


def analyze_example_document(
    text: str,
    definition_path: Path,
) -> ScaffoldResult:
    """
    예시 문서 분석 (간편 함수).

    Args:
        text: 문서 전체 텍스트
        definition_path: definition.yaml 경로

    Returns:
        ScaffoldResult
    """
    scaffolder = TemplateScaffolder(definition_path)
    return scaffolder.analyze_document(text)
