"""
test_anthropic.py - Claude Provider 테스트

ADR-0003:
- LLM은 구조화 제안만, 최종 판정은 core/validate
- model_requested + model_used 필수 기록

Mock 주의사항:
- MagicMock은 접근되지 않은 속성에 자동으로 새 MagicMock을 반환
- response.model, response.id 등 실제 API 응답 속성을 명시적으로 설정해야 함
- make_anthropic_response() factory 사용 권장
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.providers.anthropic import ClaudeProvider
from src.app.providers.base import ExtractionError

# =============================================================================
# Mock Factories
# =============================================================================


def make_anthropic_response(
    text: str,
    model: str = "claude-opus-4-5-20251101",
    request_id: str = "msg_test_default",
) -> MagicMock:
    """
    Anthropic API 응답 mock 생성.

    MagicMock의 자동 속성 생성으로 인한 버그 방지.
    모든 테스트에서 이 factory를 사용하면 동일한 실수를 반복하지 않음.

    Args:
        text: API 응답 텍스트 (JSON 문자열)
        model: 사용된 모델 이름
        request_id: API 요청 ID

    Returns:
        Anthropic Message 응답을 모방한 MagicMock
    """
    response = MagicMock()
    response.content = [MagicMock()]
    response.content[0].text = text
    response.model = model  # 명시적 설정 필수!
    response.id = request_id  # 명시적 설정 필수!
    return response


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def provider():
    """기본 Claude provider."""
    return ClaudeProvider(
        model="claude-opus-4-5-20251101",
        api_key="test-api-key",
        max_tokens=4096,
    )


@pytest.fixture
def sample_definition():
    """테스트용 definition."""
    return {
        "fields": {
            "wo_no": {
                "type": "token",
                "importance": "critical",
                "aliases": ["WO No", "작업번호"],
            },
            "line": {
                "type": "token",
                "importance": "critical",
                "aliases": ["Line", "라인"],
            },
            "inspector": {
                "type": "token",
                "importance": "reference",
                "aliases": ["Inspector", "검사자"],
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
# 초기화 테스트
# =============================================================================


class TestClaudeProviderInit:
    """ClaudeProvider 초기화 테스트."""

    def test_init_with_defaults(self):
        """기본값으로 초기화."""
        provider = ClaudeProvider()

        assert provider.model == "claude-opus-4-5-20251101"
        assert provider.max_tokens == 4096

    def test_init_with_custom_model(self):
        """커스텀 모델로 초기화."""
        provider = ClaudeProvider(model="claude-sonnet-4-20250514", max_tokens=2048)

        assert provider.model == "claude-sonnet-4-20250514"
        assert provider.max_tokens == 2048

    def test_init_with_api_key(self):
        """API 키 설정."""
        provider = ClaudeProvider(api_key="my-api-key")

        assert provider.api_key == "my-api-key"

    def test_init_uses_env_api_key(self, monkeypatch):
        """환경변수에서 API 키 로드."""
        monkeypatch.setenv("MY_ANTHROPIC_KEY", "env-api-key")

        provider = ClaudeProvider()

        assert provider.api_key == "env-api-key"

    def test_client_lazy_init(self, provider):
        """클라이언트는 lazy init."""
        assert provider._client is None


# =============================================================================
# _build_prompt 테스트
# =============================================================================


class TestBuildPrompt:
    """_build_prompt 메서드 테스트."""

    def test_substitutes_variables(
        self,
        provider,
        sample_definition,
        sample_prompt_template,
    ):
        """변수 치환."""
        prompt = provider._build_prompt(
            user_input="WO-001, L1, PASS",
            ocr_text="Scanned: WO-001",
            definition=sample_definition,
            prompt_template=sample_prompt_template,
        )

        assert "WO-001, L1, PASS" in prompt
        assert "Scanned: WO-001" in prompt

    def test_handles_none_ocr_text(
        self,
        provider,
        sample_definition,
        sample_prompt_template,
    ):
        """OCR 텍스트 None 처리."""
        prompt = provider._build_prompt(
            user_input="WO-001",
            ocr_text=None,
            definition=sample_definition,
            prompt_template=sample_prompt_template,
        )

        assert "(없음)" in prompt

    def test_includes_field_info(
        self,
        provider,
        sample_definition,
        sample_prompt_template,
    ):
        """필드 정보 포함."""
        prompt = provider._build_prompt(
            user_input="test",
            ocr_text=None,
            definition=sample_definition,
            prompt_template=sample_prompt_template,
        )

        assert "wo_no" in prompt
        assert "critical" in prompt


# =============================================================================
# _format_fields_info 테스트
# =============================================================================


class TestFormatFieldsInfo:
    """_format_fields_info 메서드 테스트."""

    def test_formats_fields(self, provider, sample_definition):
        """필드 포맷팅."""
        result = provider._format_fields_info(sample_definition["fields"])

        assert "wo_no" in result
        assert "line" in result
        assert "inspector" in result
        assert "type=token" in result
        assert "importance=critical" in result

    def test_includes_aliases(self, provider, sample_definition):
        """aliases 포함."""
        result = provider._format_fields_info(sample_definition["fields"])

        assert "WO No" in result or "작업번호" in result


# =============================================================================
# _parse_response 테스트
# =============================================================================


class TestParseResponse:
    """_parse_response 메서드 테스트."""

    def test_parses_json_block(self, provider):
        """```json 블록 파싱."""
        response = """Here is the extracted data:

```json
{
  "fields": {"wo_no": "WO-001", "line": "L1"},
  "measurements": [],
  "missing_fields": ["inspector"],
  "warnings": [],
  "confidence": 0.95
}
```

That's all."""

        result = provider._parse_response(response)

        assert result.success is True
        assert result.fields == {"wo_no": "WO-001", "line": "L1"}
        assert result.missing_fields == ["inspector"]
        assert result.confidence == 0.95

    def test_parses_raw_json(self, provider):
        """순수 JSON 응답 파싱."""
        response = """{"fields": {"wo_no": "WO-001"}, "measurements": []}"""

        result = provider._parse_response(response)

        assert result.success is True
        assert result.fields == {"wo_no": "WO-001"}

    def test_parses_measurements(self, provider):
        """측정 데이터 파싱."""
        response = """{
  "fields": {"wo_no": "WO-001"},
  "measurements": [
    {"item": "길이", "spec": "10±0.1", "measured": "10.05", "result": "PASS"}
  ]
}"""

        result = provider._parse_response(response)

        assert len(result.measurements) == 1
        assert result.measurements[0]["item"] == "길이"

    def test_parses_suggested_template_id(self, provider):
        """suggested_template_id 파싱."""
        response = """{
  "fields": {},
  "suggested_template_id": "customer_a_inspection"
}"""

        result = provider._parse_response(response)

        assert result.suggested_template_id == "customer_a_inspection"

    def test_handles_parse_error(self, provider):
        """파싱 실패 처리."""
        response = "This is not JSON at all"

        result = provider._parse_response(response)

        assert result.success is False
        assert "parse" in result.error_message.lower()

    def test_handles_invalid_json(self, provider):
        """잘못된 JSON 처리."""
        response = """{"fields": {"wo_no": "incomplete..."""

        result = provider._parse_response(response)

        assert result.success is False


# =============================================================================
# extract_fields 테스트 (Mock)
# =============================================================================


class TestExtractFields:
    """extract_fields 메서드 테스트."""

    @pytest.mark.asyncio
    async def test_successful_extraction(
        self,
        provider,
        sample_definition,
        sample_prompt_template,
    ):
        """성공적인 추출."""
        # factory 사용으로 mock 설정 실수 방지
        mock_response = make_anthropic_response(
            text="""{
  "fields": {"wo_no": "WO-001", "line": "L1"},
  "measurements": [],
  "missing_fields": [],
  "warnings": [],
  "confidence": 0.95
}""",
            model="claude-opus-4-5-20251101",
            request_id="msg_test_123",
        )

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        result = await provider.extract_fields(
            user_input="WO-001, L1",
            ocr_text=None,
            definition=sample_definition,
            prompt_template=sample_prompt_template,
        )

        assert result.success is True
        assert result.fields["wo_no"] == "WO-001"
        assert result.model_requested == "claude-opus-4-5-20251101"
        assert result.model_used == "claude-opus-4-5-20251101"
        assert result.extracted_at is not None

    @pytest.mark.asyncio
    async def test_model_tracking(
        self,
        sample_definition,
        sample_prompt_template,
    ):
        """ADR-0003: model_requested + model_used 기록."""
        provider = ClaudeProvider(model="claude-sonnet-4-20250514")

        # factory 사용으로 mock 설정 실수 방지
        mock_response = make_anthropic_response(
            text='{"fields": {}}',
            model="claude-sonnet-4-20250514",
            request_id="msg_test_456",
        )

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        result = await provider.extract_fields(
            user_input="test",
            ocr_text=None,
            definition=sample_definition,
            prompt_template=sample_prompt_template,
        )

        # Claude는 fallback 없으므로 requested == used
        assert result.model_requested == "claude-sonnet-4-20250514"
        assert result.model_used == "claude-sonnet-4-20250514"

    @pytest.mark.asyncio
    async def test_api_error_raises_extraction_error(
        self,
        provider,
        sample_definition,
        sample_prompt_template,
    ):
        """API 에러 → ExtractionError."""
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(side_effect=Exception("API Error"))
        provider._client = mock_client

        with pytest.raises(ExtractionError) as exc_info:
            await provider.extract_fields(
                user_input="test",
                ocr_text=None,
                definition=sample_definition,
                prompt_template=sample_prompt_template,
            )

        assert exc_info.value.code == "EXTRACTION_FAILED"
        assert "API Error" in exc_info.value.message


# =============================================================================
# complete 테스트 (Mock)
# =============================================================================


class TestComplete:
    """complete 메서드 테스트."""

    @pytest.mark.asyncio
    async def test_successful_completion(self, provider):
        """성공적인 완성."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock()]
        mock_response.content[0].text = "Hello, how can I help you?"

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        result = await provider.complete("Say hello")

        assert result == "Hello, how can I help you?"

    @pytest.mark.asyncio
    async def test_complete_with_custom_max_tokens(self, provider):
        """커스텀 max_tokens."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock()]
        mock_response.content[0].text = "Short response"

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        provider._client = mock_client

        await provider.complete("Say hello", max_tokens=100)

        # max_tokens가 전달되었는지 확인
        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert call_kwargs["max_tokens"] == 100

    @pytest.mark.asyncio
    async def test_complete_error_raises_extraction_error(self, provider):
        """완성 에러 → ExtractionError."""
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(side_effect=Exception("Network error"))
        provider._client = mock_client

        with pytest.raises(ExtractionError) as exc_info:
            await provider.complete("Say hello")

        assert exc_info.value.code == "COMPLETION_FAILED"


# =============================================================================
# Client 초기화 테스트
# =============================================================================


class TestGetClient:
    """_get_client 메서드 테스트."""

    def test_raises_error_if_not_installed(self, provider):
        """anthropic 미설치 시 에러."""
        with patch.dict("sys.modules", {"anthropic": None}):
            with patch("builtins.__import__", side_effect=ImportError):
                with pytest.raises(ExtractionError) as exc_info:
                    provider._get_client()

                assert exc_info.value.code == "ANTHROPIC_NOT_INSTALLED"
