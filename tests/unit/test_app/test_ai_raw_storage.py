"""
test_ai_raw_storage.py - AI Raw 데이터 저장 테스트

AI 호출의 조건부 재현성(Conditional Reproducibility) 확보:
- provider, model_params, request_id, prompt_hash 등 메타데이터
- llm_raw_output: API 응답 원문 (storage_level에 따라)
- 프롬프트 분리 저장: template_id + user_variables (보안)
- 정규식 추출 시: extraction_method="regex", regex_version
- 파싱 성공/실패 무관하게 항상 저장

주의: LLM은 동일 입력에도 약간 다른 결과를 반환할 수 있음.
저장된 메타데이터는 "유사한 결과"를 기대할 수 있게 하지만, 완전한 재현은 보장하지 않음.

테스트 케이스:
- TC1: LLM raw output 저장 확인
- TC2: prompt 저장 확인
- TC3: 파싱 실패해도 raw 저장
- TC4: OCR raw 저장 확인 (선택)
- TC5: 재현성 검증
- TC6: RunLog에 raw 없음 확인 (보안)
- TC7: 조건부 재현성 메타데이터 (provider, model_params, request_id, prompt_hash)
- TC8: Raw Storage Level (NONE, MINIMAL, FULL)
- TC9: 프롬프트 분리 저장 (template_id + variables)
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.app.providers.anthropic import ClaudeProvider
from src.app.providers.base import ExtractionResult, OCRResult
from src.app.services.intake import IntakeService

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def job_dir(tmp_path: Path) -> Path:
    """테스트용 job 디렉터리."""
    job_path = tmp_path / "jobs" / "test_job"
    job_path.mkdir(parents=True)
    return job_path


@pytest.fixture
def intake_service(job_dir: Path) -> IntakeService:
    """IntakeService 인스턴스."""
    return IntakeService(job_dir)


@pytest.fixture
def provider():
    """Claude provider 인스턴스."""
    return ClaudeProvider(
        model="claude-opus-4-5-20251101",
        api_key="test-api-key",
    )


@pytest.fixture
def sample_definition():
    """테스트용 definition."""
    return {
        "fields": {
            "wo_no": {
                "type": "token",
                "importance": "critical",
                "aliases": ["WO No"],
            },
            "line": {
                "type": "token",
                "importance": "critical",
                "aliases": ["Line"],
            },
        },
    }


@pytest.fixture
def sample_prompt_template():
    """테스트용 프롬프트 템플릿."""
    return """## Definition
{definition_yaml_content}

## User Input
{user_input}

## OCR Text
{ocr_text}
"""


# =============================================================================
# TC1: LLM raw output 저장 확인
# =============================================================================


class TestLLMRawOutputStorage:
    """LLM raw output 저장 테스트."""

    @pytest.mark.asyncio
    async def test_extraction_stores_llm_raw_output(
        self,
        provider,
        sample_definition,
        sample_prompt_template,
    ):
        """ExtractionResult에 llm_raw_output이 저장됨."""
        # API 응답 Mock
        raw_api_response = """{
  "fields": {"wo_no": "WO-001", "line": "L1"},
  "measurements": [],
  "missing_fields": [],
  "warnings": [],
  "confidence": 0.95
}"""

        mock_response = MagicMock()
        mock_response.content = [MagicMock()]
        mock_response.content[0].text = raw_api_response

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        # 추출 수행
        result = await provider.extract_fields(
            user_input="WO-001, L1",
            ocr_text=None,
            definition=sample_definition,
            prompt_template=sample_prompt_template,
        )

        # 검증: llm_raw_output 존재 및 빈 문자열 아님
        assert result.llm_raw_output is not None
        assert result.llm_raw_output != ""
        assert result.llm_raw_output == raw_api_response

    @pytest.mark.asyncio
    async def test_raw_output_preserved_in_intake_session(
        self,
        intake_service: IntakeService,
        provider,
        sample_definition,
        sample_prompt_template,
    ):
        """intake_session.json에 llm_raw_output이 저장됨."""
        raw_api_response = '{"fields": {"wo_no": "WO-001"}, "confidence": 0.9}'

        mock_response = MagicMock()
        mock_response.content = [MagicMock()]
        mock_response.content[0].text = raw_api_response
        # 조건부 재현성: model과 id 속성 명시적 설정
        mock_response.model = "claude-opus-4-5-20251101"
        mock_response.id = "msg_test_12345"

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        # 추출 후 세션에 저장
        intake_service.create_session()
        result = await provider.extract_fields(
            user_input="WO-001",
            ocr_text=None,
            definition=sample_definition,
            prompt_template=sample_prompt_template,
        )
        intake_service.add_extraction_result(result)

        # 파일에서 직접 확인
        data = json.loads(intake_service.session_path.read_text(encoding="utf-8"))

        assert data["extraction_result"]["llm_raw_output"] == raw_api_response


# =============================================================================
# TC2: prompt 저장 확인
# =============================================================================


class TestPromptStorage:
    """prompt_used 저장 테스트."""

    @pytest.mark.asyncio
    async def test_extraction_stores_prompt_used(
        self,
        provider,
        sample_definition,
        sample_prompt_template,
    ):
        """ExtractionResult에 prompt_used가 저장됨."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock()]
        mock_response.content[0].text = '{"fields": {}}'

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        # 추출 수행
        result = await provider.extract_fields(
            user_input="Test input with WO-001",
            ocr_text="Scanned: Line L1",
            definition=sample_definition,
            prompt_template=sample_prompt_template,
        )

        # 검증: prompt_used 존재
        assert result.prompt_used is not None
        assert result.prompt_used != ""
        # definition 기반 프롬프트가 포함되어 있는지
        assert "wo_no" in result.prompt_used
        assert "Test input with WO-001" in result.prompt_used
        assert "Scanned: Line L1" in result.prompt_used

    @pytest.mark.asyncio
    async def test_prompt_preserved_in_intake_session(
        self,
        intake_service: IntakeService,
        provider,
        sample_definition,
        sample_prompt_template,
    ):
        """intake_session.json에 prompt_used가 저장됨."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock()]
        mock_response.content[0].text = '{"fields": {"wo_no": "WO-001"}}'
        # 조건부 재현성: model과 id 속성 명시적 설정
        mock_response.model = "claude-opus-4-5-20251101"
        mock_response.id = "msg_test_12345"

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        intake_service.create_session()
        result = await provider.extract_fields(
            user_input="Custom user input",
            ocr_text=None,
            definition=sample_definition,
            prompt_template=sample_prompt_template,
        )
        intake_service.add_extraction_result(result)

        # 파일에서 직접 확인
        data = json.loads(intake_service.session_path.read_text(encoding="utf-8"))

        assert data["extraction_result"]["prompt_used"] is not None
        assert "Custom user input" in data["extraction_result"]["prompt_used"]


# =============================================================================
# TC3: 파싱 실패해도 raw 저장
# =============================================================================


class TestParseFailureStoresRaw:
    """파싱 실패 시에도 raw 저장 테스트."""

    @pytest.mark.asyncio
    async def test_extraction_failure_still_stores_raw(
        self,
        provider,
        sample_definition,
        sample_prompt_template,
    ):
        """파싱 실패해도 llm_raw_output은 저장됨."""
        # 잘못된 JSON 응답 (파싱 실패 유도)
        invalid_json_response = "This is not JSON at all, just plain text response"

        mock_response = MagicMock()
        mock_response.content = [MagicMock()]
        mock_response.content[0].text = invalid_json_response

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        # 추출 수행 (파싱 실패하지만 에러는 아님)
        result = await provider.extract_fields(
            user_input="WO-001",
            ocr_text=None,
            definition=sample_definition,
            prompt_template=sample_prompt_template,
        )

        # 검증: success=False이지만 llm_raw_output은 저장됨
        assert result.success is False
        assert result.llm_raw_output is not None
        assert result.llm_raw_output == invalid_json_response
        # prompt_used도 저장됨
        assert result.prompt_used is not None

    @pytest.mark.asyncio
    async def test_partial_json_still_stores_raw(
        self,
        provider,
        sample_definition,
        sample_prompt_template,
    ):
        """부분적인 JSON 응답도 raw로 저장됨."""
        partial_json = '{"fields": {"wo_no": "WO-001", "incomplete...'

        mock_response = MagicMock()
        mock_response.content = [MagicMock()]
        mock_response.content[0].text = partial_json

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        result = await provider.extract_fields(
            user_input="test",
            ocr_text=None,
            definition=sample_definition,
            prompt_template=sample_prompt_template,
        )

        # 파싱 실패해도 원본 저장
        assert result.success is False
        assert result.llm_raw_output == partial_json


# =============================================================================
# TC4: OCR raw 저장 확인 (선택 - 현재 구현에서는 OCRResult에 raw 없음)
# =============================================================================


class TestOCRRawStorage:
    """OCR raw 저장 테스트 (현재 구현 상태 확인)."""

    def test_ocr_result_has_text(self, intake_service: IntakeService):
        """OCRResult.text에 추출된 텍스트가 저장됨."""
        intake_service.create_session()

        ocr_result = OCRResult(
            success=True,
            text="WO-001\nLine: L1\nPart: P-100",
            confidence=0.95,
            model_requested="gemini-2.0-flash",
            model_used="gemini-2.0-flash",
        )

        intake_service.add_ocr_result("label.jpg", ocr_result)

        # 로드해서 확인
        session = intake_service.load_session()
        assert session.ocr_results["label.jpg"].text is not None
        assert "WO-001" in session.ocr_results["label.jpg"].text


# =============================================================================
# TC5: 재현성 검증
# =============================================================================


class TestReproducibility:
    """재현성 검증 테스트."""

    @pytest.mark.asyncio
    async def test_can_reproduce_extraction_from_stored_data(
        self,
        intake_service: IntakeService,
        provider,
        sample_definition,
        sample_prompt_template,
    ):
        """저장된 데이터로 추출 재현 가능."""
        # 원본 추출
        mock_response = MagicMock()
        mock_response.content = [MagicMock()]
        mock_response.content[0].text = '{"fields": {"wo_no": "WO-123"}}'
        # 조건부 재현성: model과 id 속성 명시적 설정
        mock_response.model = "claude-opus-4-5-20251101"
        mock_response.id = "msg_test_12345"

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        intake_service.create_session()
        result = await provider.extract_fields(
            user_input="Original input",
            ocr_text="OCR text",
            definition=sample_definition,
            prompt_template=sample_prompt_template,
        )
        intake_service.add_extraction_result(result)

        # 저장된 세션에서 재현 정보 로드
        session = intake_service.load_session()
        stored_result = session.extraction_result

        # 재현에 필요한 모든 정보가 있는지 확인
        assert stored_result.model_requested is not None
        assert stored_result.model_used is not None
        assert stored_result.prompt_used is not None
        assert stored_result.llm_raw_output is not None

        # 입력 → 프롬프트 → 응답 → 결과 추적 가능
        assert "Original input" in stored_result.prompt_used
        assert "OCR text" in stored_result.prompt_used
        assert "WO-123" in stored_result.llm_raw_output

    def test_stored_data_contains_full_trace(
        self,
        intake_service: IntakeService,
    ):
        """저장된 데이터에 전체 추적 정보 포함."""
        intake_service.create_session()

        # 완전한 ExtractionResult 저장
        result = ExtractionResult(
            success=True,
            fields={"wo_no": "WO-001"},
            model_requested="claude-opus-4-5-20251101",
            model_used="claude-opus-4-5-20251101",
            llm_raw_output='{"fields": {"wo_no": "WO-001"}}',
            prompt_used="Full prompt with user input and definition",
            extracted_at="2024-01-15T09:30:00Z",
        )
        intake_service.add_extraction_result(result)

        # 파일에서 직접 확인
        data = json.loads(intake_service.session_path.read_text(encoding="utf-8"))
        er = data["extraction_result"]

        # 감사/분쟁 시 필요한 모든 정보
        assert er["model_requested"] is not None
        assert er["model_used"] is not None
        assert er["prompt_used"] is not None
        assert er["llm_raw_output"] is not None
        assert er["extracted_at"] is not None


# =============================================================================
# TC6: RunLog에 raw 없음 확인 (보안)
# =============================================================================


class TestRunLogSecurity:
    """RunLog 보안 테스트 - raw 데이터 미포함."""

    def test_run_log_does_not_contain_raw_data(self, job_dir: Path):
        """RunLog에는 llm_raw_output, prompt_used가 없음."""
        from src.domain.schemas import RunLog

        # RunLog 생성
        run_log = RunLog(
            run_id="test-run-001",
            job_id="WO001-L1-abc123",
            started_at="2024-01-15T09:30:00Z",
            finished_at="2024-01-15T09:30:05Z",
            result="success",
            packet_hash="sha256:abc...",
        )

        # to_dict() 결과 확인
        log_dict = run_log.to_dict()

        # raw 데이터 필드가 없어야 함
        assert "llm_raw_output" not in log_dict
        assert "prompt_used" not in log_dict

        # 메타데이터만 있어야 함
        assert "run_id" in log_dict
        assert "job_id" in log_dict
        assert "packet_hash" in log_dict

    def test_run_log_warnings_do_not_contain_raw(self, job_dir: Path):
        """RunLog.warnings에도 raw 데이터 없음."""
        from src.domain.schemas import RunLog, WarningLog

        warning = WarningLog(
            code="PARSE_ERROR_REFERENCE",
            field_or_slot="inspector",
            original_value="John Doe",
            resolved_value=None,
            message="Failed to parse",
        )

        run_log = RunLog(
            run_id="test",
            job_id="job",
            started_at="2024-01-15T09:30:00Z",
            warnings=[warning],
        )

        log_dict = run_log.to_dict()

        # warnings 배열의 각 항목에도 raw 없음
        for w in log_dict["warnings"]:
            assert "llm_raw_output" not in w
            assert "prompt_used" not in w

    def test_intake_session_contains_raw_but_run_log_does_not(
        self,
        intake_service: IntakeService,
        job_dir: Path,
    ):
        """intake_session에는 raw가 있고 run_log에는 없음."""
        from src.domain.schemas import RunLog

        # intake_session에 raw 저장
        intake_service.create_session()
        intake_service.add_extraction_result(
            ExtractionResult(
                success=True,
                fields={"wo_no": "WO-001"},
                model_used="claude",
                llm_raw_output='{"fields": {"wo_no": "WO-001"}}',
                prompt_used="Full prompt here...",
            )
        )

        # intake_session.json 확인 - raw 있음
        intake_data = json.loads(
            intake_service.session_path.read_text(encoding="utf-8")
        )
        assert intake_data["extraction_result"]["llm_raw_output"] is not None
        assert intake_data["extraction_result"]["prompt_used"] is not None

        # RunLog 확인 - raw 없음
        run_log = RunLog(
            run_id="test",
            job_id="WO001-L1",
            started_at="2024-01-15T09:30:00Z",
            result="success",
        )
        run_log_dict = run_log.to_dict()

        assert "llm_raw_output" not in run_log_dict
        assert "prompt_used" not in run_log_dict


# =============================================================================
# 추가: 정규식 추출 시 raw 없음 확인
# =============================================================================


class TestRegexExtractionNoRaw:
    """정규식 추출 시 raw 데이터 없음 테스트."""

    @pytest.mark.asyncio
    async def test_regex_extraction_has_no_llm_raw(self, tmp_path: Path, monkeypatch):
        """정규식으로 추출 시 llm_raw_output은 None."""
        from src.app.services.extract import ExtractionService

        # ExtractionService 초기화 시 ClaudeProvider가 API 키를 요구하므로 환경변수 설정
        monkeypatch.setenv("MY_ANTHROPIC_KEY", "test-api-key")

        # definition.yaml 생성
        definition_path = tmp_path / "definition.yaml"
        definition_path.write_text(
            """
fields:
  wo_no:
    type: token
    importance: critical
    aliases: ["WO No", "작업번호"]
  line:
    type: token
    importance: critical
    aliases: ["Line"]
  part_no:
    type: token
    importance: critical
    aliases: ["Part No"]
  lot:
    type: token
    importance: critical
    aliases: ["Lot"]
  result:
    type: token
    importance: critical
    aliases: ["Result"]
""",
            encoding="utf-8",
        )

        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()

        service = ExtractionService(
            config={},
            definition_path=definition_path,
            prompts_dir=prompts_dir,
        )

        # 모든 필수 필드가 있는 입력 (정규식으로 충분)
        result = await service.extract(
            user_input="WO No: WO-001, Line: L1, Part No: P-100, Lot: LOT-001, Result: PASS"
        )

        # 정규식 추출은 LLM이 아니므로 raw 없음
        assert result.model_used == "regex"
        assert result.llm_raw_output is None
        assert result.prompt_used is None

        # 정규식 추출 메타데이터 확인
        assert result.extraction_method == "regex"
        assert result.provider == "regex"
        assert result.regex_version is not None
        assert "1.0.0:" in result.regex_version  # version:hash 형식


# =============================================================================
# TC7: 조건부 재현성 메타데이터 테스트
# =============================================================================


class TestConditionalReproducibilityMetadata:
    """조건부 재현성 메타데이터 테스트.

    완전한 재현은 불가능하지만, 유사한 결과를 기대할 수 있는
    메타데이터가 저장되는지 확인.
    """

    @pytest.mark.asyncio
    async def test_provider_and_model_params_stored(
        self,
        sample_definition,
        sample_prompt_template,
    ):
        """provider와 model_params가 저장됨."""
        provider = ClaudeProvider(
            model="claude-opus-4-5-20251101",
            api_key="test-api-key",
            max_tokens=2048,
            temperature=0.5,
            top_p=0.9,
        )

        mock_response = MagicMock()
        mock_response.content = [MagicMock()]
        mock_response.content[0].text = '{"fields": {}}'
        mock_response.model = "claude-opus-4-5-20251101"
        mock_response.id = "msg_12345"

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        result = await provider.extract_fields(
            user_input="Test",
            ocr_text=None,
            definition=sample_definition,
            prompt_template=sample_prompt_template,
        )

        # 조건부 재현성 메타데이터 확인
        assert result.provider == "anthropic"
        assert result.model_params is not None
        assert result.model_params["max_tokens"] == 2048
        assert result.model_params["temperature"] == 0.5
        assert result.model_params["top_p"] == 0.9

    @pytest.mark.asyncio
    async def test_request_id_stored(
        self,
        provider,
        sample_definition,
        sample_prompt_template,
    ):
        """request_id가 저장됨 (가능한 경우)."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock()]
        mock_response.content[0].text = '{"fields": {}}'
        mock_response.model = "claude-opus-4-5-20251101"
        mock_response.id = "msg_request_id_abc123"

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        result = await provider.extract_fields(
            user_input="Test",
            ocr_text=None,
            definition=sample_definition,
            prompt_template=sample_prompt_template,
        )

        assert result.request_id == "msg_request_id_abc123"

    @pytest.mark.asyncio
    async def test_prompt_hash_always_stored(
        self,
        provider,
        sample_definition,
        sample_prompt_template,
    ):
        """prompt_hash는 항상 저장됨."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock()]
        mock_response.content[0].text = '{"fields": {}}'
        mock_response.model = "claude-opus-4-5-20251101"
        mock_response.id = "msg_12345"

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        result = await provider.extract_fields(
            user_input="Test input",
            ocr_text=None,
            definition=sample_definition,
            prompt_template=sample_prompt_template,
        )

        # prompt_hash는 항상 존재
        assert result.prompt_hash is not None
        assert result.prompt_hash.startswith("sha256:")

    @pytest.mark.asyncio
    async def test_extraction_method_llm_for_provider(
        self,
        provider,
        sample_definition,
        sample_prompt_template,
    ):
        """LLM 추출 시 extraction_method='llm'."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock()]
        mock_response.content[0].text = '{"fields": {}}'
        mock_response.model = "claude-opus-4-5-20251101"
        mock_response.id = "msg_12345"

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        result = await provider.extract_fields(
            user_input="Test",
            ocr_text=None,
            definition=sample_definition,
            prompt_template=sample_prompt_template,
        )

        assert result.extraction_method == "llm"


# =============================================================================
# TC8: Raw Storage Level 테스트
# =============================================================================


class TestRawStorageLevel:
    """storage_level에 따른 raw 저장 동작 테스트."""

    @pytest.mark.asyncio
    async def test_full_level_stores_raw_output(
        self,
        sample_definition,
        sample_prompt_template,
    ):
        """FULL 레벨: raw output 전체 저장."""
        from src.app.providers.base import AIRawStorageConfig, RawStorageLevel

        provider = ClaudeProvider(
            model="claude-opus-4-5-20251101",
            api_key="test-api-key",
            raw_storage_config=AIRawStorageConfig(
                storage_level=RawStorageLevel.FULL,
            ),
        )

        raw_output = '{"fields": {"wo_no": "WO-001"}}'
        mock_response = MagicMock()
        mock_response.content = [MagicMock()]
        mock_response.content[0].text = raw_output
        mock_response.model = "claude-opus-4-5-20251101"
        mock_response.id = "msg_12345"

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        result = await provider.extract_fields(
            user_input="Test",
            ocr_text=None,
            definition=sample_definition,
            prompt_template=sample_prompt_template,
        )

        assert result.llm_raw_output == raw_output
        assert result.llm_raw_output_hash is not None
        assert result.llm_raw_truncated is False

    @pytest.mark.asyncio
    async def test_minimal_level_stores_hash_only(
        self,
        sample_definition,
        sample_prompt_template,
    ):
        """MINIMAL 레벨: 해시만 저장, raw는 None."""
        from src.app.providers.base import AIRawStorageConfig, RawStorageLevel

        provider = ClaudeProvider(
            model="claude-opus-4-5-20251101",
            api_key="test-api-key",
            raw_storage_config=AIRawStorageConfig(
                storage_level=RawStorageLevel.MINIMAL,
            ),
        )

        mock_response = MagicMock()
        mock_response.content = [MagicMock()]
        mock_response.content[0].text = '{"fields": {}}'
        mock_response.model = "claude-opus-4-5-20251101"
        mock_response.id = "msg_12345"

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        result = await provider.extract_fields(
            user_input="Test",
            ocr_text=None,
            definition=sample_definition,
            prompt_template=sample_prompt_template,
        )

        # raw output은 None, 해시만 있음
        assert result.llm_raw_output is None
        assert result.llm_raw_output_hash is not None
        assert result.llm_raw_output_hash.startswith("sha256:")

    @pytest.mark.asyncio
    async def test_none_level_stores_nothing(
        self,
        sample_definition,
        sample_prompt_template,
    ):
        """NONE 레벨: 아무것도 저장 안 함."""
        from src.app.providers.base import AIRawStorageConfig, RawStorageLevel

        provider = ClaudeProvider(
            model="claude-opus-4-5-20251101",
            api_key="test-api-key",
            raw_storage_config=AIRawStorageConfig(
                storage_level=RawStorageLevel.NONE,
            ),
        )

        mock_response = MagicMock()
        mock_response.content = [MagicMock()]
        mock_response.content[0].text = '{"fields": {}}'
        mock_response.model = "claude-opus-4-5-20251101"
        mock_response.id = "msg_12345"

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        result = await provider.extract_fields(
            user_input="Test",
            ocr_text=None,
            definition=sample_definition,
            prompt_template=sample_prompt_template,
        )

        # 아무것도 저장 안 함
        assert result.llm_raw_output is None
        assert result.llm_raw_output_hash is None
        assert result.prompt_rendered is None

    @pytest.mark.asyncio
    async def test_truncation_on_large_response(
        self,
        sample_definition,
        sample_prompt_template,
    ):
        """큰 응답은 truncation됨."""
        from src.app.providers.base import AIRawStorageConfig, RawStorageLevel

        # 작은 max_raw_size 설정
        provider = ClaudeProvider(
            model="claude-opus-4-5-20251101",
            api_key="test-api-key",
            raw_storage_config=AIRawStorageConfig(
                storage_level=RawStorageLevel.FULL,
                max_raw_size=100,  # 100 bytes
            ),
        )

        # 큰 응답 생성
        large_response = '{"fields": {' + '"key": "value", ' * 50 + "}}"
        mock_response = MagicMock()
        mock_response.content = [MagicMock()]
        mock_response.content[0].text = large_response
        mock_response.model = "claude-opus-4-5-20251101"
        mock_response.id = "msg_12345"

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        result = await provider.extract_fields(
            user_input="Test",
            ocr_text=None,
            definition=sample_definition,
            prompt_template=sample_prompt_template,
        )

        # truncation 발생
        assert result.llm_raw_truncated is True
        assert len(result.llm_raw_output) == 100
        # 원본 해시는 truncation 전 전체 데이터 기준
        assert result.llm_raw_output_hash is not None


# =============================================================================
# TC9: 프롬프트 분리 저장 테스트
# =============================================================================


class TestPromptSeparation:
    """프롬프트 분리 저장 테스트 (보안)."""

    @pytest.mark.asyncio
    async def test_prompt_template_and_variables_separated(
        self,
        sample_definition,
        sample_prompt_template,
    ):
        """템플릿과 유저 변수가 분리 저장됨."""
        provider = ClaudeProvider(
            model="claude-opus-4-5-20251101",
            api_key="test-api-key",
        )

        mock_response = MagicMock()
        mock_response.content = [MagicMock()]
        mock_response.content[0].text = '{"fields": {}}'
        mock_response.model = "claude-opus-4-5-20251101"
        mock_response.id = "msg_12345"

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        result = await provider.extract_fields(
            user_input="User input text",
            ocr_text="OCR extracted text",
            definition=sample_definition,
            prompt_template=sample_prompt_template,
            template_id="test_template",
        )

        # 프롬프트 분리 저장
        assert result.prompt_template_id == "test_template"
        assert result.prompt_template_version == "1.0.0"
        assert result.prompt_user_variables is not None
        assert result.prompt_user_variables["user_input"] == "User input text"
        assert result.prompt_user_variables["ocr_text"] == "OCR extracted text"
