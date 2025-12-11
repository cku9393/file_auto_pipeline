"""
test_extract.py - Extraction 서비스 테스트

ADR-0003:
- 정규식 선 추출 → LLM (비용 절감)
- LLM은 구조화 제안만, 최종 판정은 core/validate
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from src.app.providers.base import ExtractionResult
from src.app.services.extract import ExtractionService

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def definition_path(tmp_path: Path) -> Path:
    """테스트용 definition.yaml."""
    definition = {
        "definition_version": "1.0.0",
        "fields": {
            "wo_no": {
                "type": "token",
                "importance": "critical",
                "aliases": ["WO No", "작업번호", "W/O No"],
            },
            "line": {
                "type": "token",
                "importance": "critical",
                "aliases": ["Line", "라인", "라인번호"],
            },
            "part_no": {
                "type": "token",
                "importance": "critical",
                "aliases": ["Part No", "품번"],
            },
            "lot": {
                "type": "token",
                "importance": "critical",
                "aliases": ["LOT", "LOT번호"],
            },
            "result": {
                "type": "token",
                "importance": "critical",
                "aliases": ["Result", "결과", "판정"],
            },
            "inspector": {
                "type": "token",
                "importance": "reference",
                "aliases": ["Inspector", "검사자", "담당자"],
            },
            "date": {
                "type": "token",
                "importance": "reference",
                "aliases": ["Date", "날짜", "검사일"],
            },
        },
    }

    path = tmp_path / "definition.yaml"
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(definition, f, allow_unicode=True)

    return path


@pytest.fixture
def prompts_dir(tmp_path: Path) -> Path:
    """테스트용 프롬프트 디렉터리."""
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    return prompts


@pytest.fixture
def config() -> dict:
    """테스트용 설정."""
    return {
        "ai": {
            "llm": {
                "model": "claude-opus-4-5-20251101",
            },
        },
    }


@pytest.fixture
def mock_provider():
    """Mock LLM provider."""
    provider = MagicMock()
    provider.extract_fields = AsyncMock(
        return_value=ExtractionResult(
            success=True,
            fields={"wo_no": "WO-001", "line": "L1"},
            model_requested="claude-opus-4-5-20251101",
            model_used="claude-opus-4-5-20251101",
        )
    )
    return provider


@pytest.fixture
def extraction_service(
    config: dict,
    definition_path: Path,
    prompts_dir: Path,
    mock_provider,
) -> ExtractionService:
    """ExtractionService 인스턴스."""
    return ExtractionService(
        config=config,
        definition_path=definition_path,
        prompts_dir=prompts_dir,
        provider=mock_provider,
    )


# =============================================================================
# 초기화 테스트
# =============================================================================


class TestExtractionServiceInit:
    """ExtractionService 초기화 테스트."""

    def test_init_with_provider(
        self,
        config,
        definition_path,
        prompts_dir,
        mock_provider,
    ):
        """Provider 주입."""
        service = ExtractionService(
            config=config,
            definition_path=definition_path,
            prompts_dir=prompts_dir,
            provider=mock_provider,
        )

        assert service.provider is mock_provider

    def test_init_creates_default_provider(
        self,
        config,
        definition_path,
        prompts_dir,
        monkeypatch,
    ):
        """Provider 없으면 config 기반 생성."""
        monkeypatch.setenv("MY_ANTHROPIC_KEY", "test-api-key")

        service = ExtractionService(
            config=config,
            definition_path=definition_path,
            prompts_dir=prompts_dir,
        )

        assert service.provider is not None
        assert service.provider.model == "claude-opus-4-5-20251101"

    def test_definition_lazy_load(
        self,
        config,
        definition_path,
        prompts_dir,
        mock_provider,
    ):
        """definition은 lazy load."""
        service = ExtractionService(
            config=config,
            definition_path=definition_path,
            prompts_dir=prompts_dir,
            provider=mock_provider,
        )

        assert service._definition is None
        _ = service.definition
        assert service._definition is not None


# =============================================================================
# 정규식 추출 테스트
# =============================================================================


class TestRegexExtraction:
    """정규식 추출 테스트."""

    def test_extracts_wo_no(self, extraction_service):
        """WO No 추출."""
        text = "작업번호: WO-001"

        result = extraction_service._extract_with_regex(text, None)

        assert result.get("wo_no") == "WO-001"

    def test_extracts_line(self, extraction_service):
        """Line 추출."""
        text = "라인: L1"

        result = extraction_service._extract_with_regex(text, None)

        assert result.get("line") == "L1"

    def test_extracts_multiple_fields(self, extraction_service):
        """여러 필드 추출."""
        text = """
        작업번호: WO-001
        라인: L1
        품번: PART-A
        LOT: LOT-001
        결과: PASS
        검사자: 홍길동
        날짜: 2024-01-15
        """

        result = extraction_service._extract_with_regex(text, None)

        assert result["wo_no"] == "WO-001"
        assert result["line"] == "L1"
        assert result["part_no"] == "PART-A"
        assert result["lot"] == "LOT-001"
        assert result["result"] == "PASS"
        assert result["inspector"] == "홍길동"
        assert result["date"] == "2024-01-15"

    def test_uses_aliases(self, extraction_service):
        """aliases 사용."""
        text1 = "WO No: WO-001"
        text2 = "W/O No: WO-002"

        result1 = extraction_service._extract_with_regex(text1, None)
        result2 = extraction_service._extract_with_regex(text2, None)

        assert result1.get("wo_no") == "WO-001"
        assert result2.get("wo_no") == "WO-002"

    def test_combines_user_input_and_ocr(self, extraction_service):
        """user_input + ocr_text 결합."""
        user_input = "작업번호: WO-001"
        ocr_text = "라인: L1"

        result = extraction_service._extract_with_regex(user_input, ocr_text)

        assert result["wo_no"] == "WO-001"
        assert result["line"] == "L1"

    def test_case_insensitive(self, extraction_service):
        """대소문자 구분 없음."""
        text = "RESULT: PASS"

        result = extraction_service._extract_with_regex(text, None)

        assert result.get("result") == "PASS"

    def test_handles_colon_variants(self, extraction_service):
        """콜론 변형 처리 (: 또는 ：)."""
        text1 = "작업번호: WO-001"
        text2 = "작업번호：WO-002"

        result1 = extraction_service._extract_with_regex(text1, None)
        result2 = extraction_service._extract_with_regex(text2, None)

        assert result1["wo_no"] == "WO-001"
        assert result2["wo_no"] == "WO-002"

    def test_stops_at_newline(self, extraction_service):
        """값은 줄바꿈에서 끝남."""
        text = "작업번호: WO-001\n라인: L1"

        result = extraction_service._extract_with_regex(text, None)

        assert result["wo_no"] == "WO-001"
        assert "라인" not in result["wo_no"]


# =============================================================================
# _build_field_pattern 테스트
# =============================================================================


class TestBuildFieldPattern:
    """_build_field_pattern 테스트."""

    def test_builds_pattern_from_aliases(self, extraction_service):
        """aliases로 패턴 생성."""
        pattern = extraction_service._build_field_pattern(
            "wo_no",
            ["WO No", "작업번호", "W/O No"],
        )

        import re

        assert re.search(pattern, "WO No: WO-001", re.IGNORECASE)
        assert re.search(pattern, "작업번호: WO-002", re.IGNORECASE)

    def test_uses_field_name_if_no_aliases(self, extraction_service):
        """aliases 없으면 필드명 사용."""
        pattern = extraction_service._build_field_pattern("custom_field", [])

        import re

        assert re.search(pattern, "custom_field: value", re.IGNORECASE)


# =============================================================================
# _get_required_fields 테스트
# =============================================================================


class TestGetRequiredFields:
    """_get_required_fields 테스트."""

    def test_returns_critical_fields(self, extraction_service):
        """critical 필드 반환."""
        required = extraction_service._get_required_fields()

        assert "wo_no" in required
        assert "line" in required
        assert "part_no" in required
        assert "lot" in required
        assert "result" in required

    def test_excludes_reference_fields(self, extraction_service):
        """reference 필드 제외."""
        required = extraction_service._get_required_fields()

        assert "inspector" not in required
        assert "date" not in required


# =============================================================================
# extract 테스트
# =============================================================================


class TestExtract:
    """extract 메서드 테스트."""

    @pytest.mark.asyncio
    async def test_regex_only_when_all_required_found(self, extraction_service):
        """필수 필드 모두 있으면 LLM 스킵."""
        user_input = """
        작업번호: WO-001
        라인: L1
        품번: PART-A
        LOT: LOT-001
        결과: PASS
        """

        result = await extraction_service.extract(user_input)

        assert result.success is True
        assert result.model_requested == "regex"
        assert result.model_used == "regex"

        # LLM 호출 안 함
        extraction_service.provider.extract_fields.assert_not_called()

    @pytest.mark.asyncio
    async def test_calls_llm_when_required_missing(self, extraction_service):
        """필수 필드 누락 시 LLM 호출."""
        user_input = "작업번호: WO-001"  # line, part_no, lot, result 누락

        await extraction_service.extract(user_input)

        # LLM 호출됨
        extraction_service.provider.extract_fields.assert_called_once()

    @pytest.mark.asyncio
    async def test_merges_regex_and_llm_results(self, extraction_service):
        """정규식 + LLM 결과 병합."""
        extraction_service.provider.extract_fields = AsyncMock(
            return_value=ExtractionResult(
                success=True,
                fields={
                    "wo_no": "WO-FROM-LLM",
                    "line": "L1",
                    "part_no": "P1",
                    "lot": "LOT1",
                    "result": "PASS",
                },
                model_used="claude",
            )
        )

        user_input = "작업번호: WO-001"  # 정규식으로 wo_no 추출

        result = await extraction_service.extract(user_input)

        # 정규식 결과 우선
        assert result.fields["wo_no"] == "WO-001"  # 정규식
        assert result.fields["line"] == "L1"  # LLM

    @pytest.mark.asyncio
    async def test_llm_result_fills_gaps(self, extraction_service):
        """LLM이 정규식 못 찾은 필드 채움."""
        extraction_service.provider.extract_fields = AsyncMock(
            return_value=ExtractionResult(
                success=True,
                fields={"line": "L1", "part_no": "P1", "lot": "LOT1", "result": "PASS"},
                model_used="claude",
            )
        )

        user_input = "작업번호: WO-001"  # 정규식은 wo_no만 찾음

        result = await extraction_service.extract(user_input)

        assert result.fields["wo_no"] == "WO-001"  # 정규식
        assert result.fields["line"] == "L1"  # LLM
        assert result.fields["part_no"] == "P1"  # LLM

    @pytest.mark.asyncio
    async def test_with_ocr_text(self, extraction_service):
        """OCR 텍스트 포함."""
        extraction_service.provider.extract_fields = AsyncMock(
            return_value=ExtractionResult(
                success=True,
                fields={"wo_no": "WO-001"},
                model_used="claude",
            )
        )

        await extraction_service.extract(
            user_input="Please check this",
            ocr_text="WO No: WO-001",
        )

        # LLM에 ocr_text 전달됨
        call_kwargs = extraction_service.provider.extract_fields.call_args.kwargs
        assert call_kwargs["ocr_text"] == "WO No: WO-001"


# =============================================================================
# 프롬프트 테스트
# =============================================================================


class TestPromptTemplate:
    """프롬프트 템플릿 테스트."""

    def test_loads_custom_prompt(
        self,
        config,
        definition_path,
        prompts_dir,
        mock_provider,
    ):
        """커스텀 프롬프트 로드."""
        prompt_file = prompts_dir / "extract_fields.txt"
        prompt_file.write_text("Custom prompt: {user_input}", encoding="utf-8")

        service = ExtractionService(
            config=config,
            definition_path=definition_path,
            prompts_dir=prompts_dir,
            provider=mock_provider,
        )

        assert "Custom prompt" in service.prompt_template

    def test_uses_default_prompt_if_missing(
        self,
        config,
        definition_path,
        prompts_dir,
        mock_provider,
    ):
        """프롬프트 파일 없으면 기본 사용."""
        service = ExtractionService(
            config=config,
            definition_path=definition_path,
            prompts_dir=prompts_dir,
            provider=mock_provider,
        )

        assert "{user_input}" in service.prompt_template
        assert "{definition_yaml_content}" in service.prompt_template

    def test_default_prompt_includes_json_format(
        self,
        config,
        definition_path,
        prompts_dir,
        mock_provider,
    ):
        """기본 프롬프트에 JSON 형식 포함."""
        service = ExtractionService(
            config=config,
            definition_path=definition_path,
            prompts_dir=prompts_dir,
            provider=mock_provider,
        )

        assert "fields" in service.prompt_template
        assert "measurements" in service.prompt_template
        assert "missing_fields" in service.prompt_template
