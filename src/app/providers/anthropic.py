"""
Anthropic (Claude) Provider.

ADR-0003:
- LLM은 구조화 제안만, 최종 판정은 core/validate
- model_requested + model_used 필수 기록
"""

import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

from src.utils.retry import retry_with_exponential_backoff

from .base import ExtractionError, ExtractionResult, LLMProvider

logger = logging.getLogger(__name__)


class ClaudeProvider(LLMProvider):
    """
    Claude API Provider.

    Usage:
        provider = ClaudeProvider(model="claude-opus-4-5-20251101")
        result = await provider.extract_fields(user_input, ocr_text, definition, prompt)
    """

    def __init__(
        self,
        model: str = "claude-opus-4-5-20251101",
        api_key: str | None = None,
        max_tokens: int = 4096,
    ):
        """
        Args:
            model: 모델 ID (config에서 주입)
            api_key: API 키 (환경변수 ANTHROPIC_API_KEY 사용 가능)
            max_tokens: 최대 토큰 수
        """
        self.model = model
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.max_tokens = max_tokens
        self._client: Any = None

    def _get_client(self) -> Any:
        """Anthropic 클라이언트 (lazy init)."""
        if self._client is None:
            try:
                import anthropic
                self._client = anthropic.AsyncAnthropic(api_key=self.api_key)
            except ImportError as e:
                raise ExtractionError(
                    "ANTHROPIC_NOT_INSTALLED",
                    "anthropic package not installed. Run: pip install anthropic",
                ) from e
        return self._client

    async def extract_fields(
        self,
        user_input: str,
        ocr_text: str | None,
        definition: dict[str, Any],
        prompt_template: str,
    ) -> ExtractionResult:
        """
        사용자 입력에서 필드 추출.

        ADR-0003: LLM은 구조화 제안만

        자동 재시도:
        - RateLimitError, APIConnectionError → 재시도
        - 최대 3회, 지수 백오프
        """
        model_requested = self.model

        try:
            # 프롬프트 구성
            prompt = self._build_prompt(
                user_input, ocr_text, definition, prompt_template
            )

            # API 호출 (재시도 로직 적용)
            response = await self._call_api_with_retry(prompt)

            # 응답 파싱
            response_text = response.content[0].text
            result = self._parse_response(response_text)

            now = datetime.now(UTC).isoformat()
            result.model_requested = model_requested
            result.model_used = self.model  # Claude는 fallback 없음
            result.extracted_at = now

            return result

        except ExtractionError:
            raise
        except Exception as e:
            logger.error(f"Field extraction failed: {e}", exc_info=True)
            user_friendly_message = self._get_user_friendly_error_message(e)
            raise ExtractionError(
                "EXTRACTION_FAILED",
                user_friendly_message,
                model=self.model,
            ) from e

    async def _call_api_with_retry(self, prompt: str) -> Any:
        """재시도 로직이 적용된 API 호출."""
        import anthropic

        # 재시도 가능한 예외 정의
        retryable_exceptions = (
            anthropic.RateLimitError,
            anthropic.APIConnectionError,
            anthropic.APITimeoutError,
            anthropic.InternalServerError,
        )

        async def _api_call() -> Any:
            client = self._get_client()
            return await client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )

        try:
            return await retry_with_exponential_backoff(
                _api_call,
                max_retries=3,
                initial_delay=1.0,
                max_delay=30.0,
                exceptions=retryable_exceptions,
            )
        except retryable_exceptions as e:
            # 재시도 실패 후 사용자 친화적 메시지
            logger.error(f"API call failed after retries: {e}")
            raise

    def _get_user_friendly_error_message(self, error: Exception) -> str:
        """사용자 친화적인 에러 메시지 생성."""
        try:
            import anthropic

            if isinstance(error, anthropic.APIConnectionError):
                return (
                    "인터넷 연결을 확인해주세요. "
                    "Anthropic API 서버에 연결할 수 없습니다."
                )
            elif isinstance(error, anthropic.RateLimitError):
                return (
                    "API 사용량 한도를 초과했습니다. "
                    "잠시 후 다시 시도해주세요."
                )
            elif isinstance(error, anthropic.AuthenticationError):
                return (
                    "API 인증에 실패했습니다. "
                    "ANTHROPIC_API_KEY 환경변수를 확인해주세요."
                )
            elif isinstance(error, anthropic.PermissionDeniedError):
                return (
                    "이 작업을 수행할 권한이 없습니다. "
                    "API 키의 권한을 확인해주세요."
                )
            elif isinstance(error, anthropic.BadRequestError):
                return (
                    "요청 형식이 올바르지 않습니다. "
                    "입력 데이터를 확인해주세요."
                )
            elif isinstance(error, anthropic.APITimeoutError):
                return (
                    "API 응답 시간이 초과되었습니다. "
                    "네트워크 상태를 확인하거나 잠시 후 다시 시도해주세요."
                )
        except ImportError:
            pass

        # 기본 메시지
        error_str = str(error)
        if "api_key" in error_str.lower():
            return "API 키 설정을 확인해주세요."
        elif "timeout" in error_str.lower():
            return "요청 시간이 초과되었습니다. 다시 시도해주세요."
        elif "connection" in error_str.lower():
            return "네트워크 연결 오류가 발생했습니다."

        return f"필드 추출 중 오류가 발생했습니다: {error_str}"

    async def complete(self, prompt: str, **kwargs: Any) -> str:
        """일반 완성 API."""
        try:
            client = self._get_client()
            response = await client.messages.create(
                model=self.model,
                max_tokens=kwargs.get("max_tokens", self.max_tokens),
                messages=[{"role": "user", "content": prompt}],
            )
            text: str = response.content[0].text
            return text
        except Exception as e:
            raise ExtractionError(
                "COMPLETION_FAILED",
                f"Claude API call failed: {e}",
            ) from e

    def _build_prompt(
        self,
        user_input: str,
        ocr_text: str | None,
        definition: dict[str, Any],
        prompt_template: str,
    ) -> str:
        """프롬프트 구성."""
        # definition에서 필드 정보 추출
        fields_info = self._format_fields_info(definition.get("fields", {}))

        # 템플릿 변수 치환
        prompt = prompt_template.replace("{definition_yaml_content}", fields_info)
        prompt = prompt.replace("{user_input}", user_input)
        prompt = prompt.replace("{ocr_text}", ocr_text or "(없음)")

        return prompt

    def _format_fields_info(self, fields: dict[str, Any]) -> str:
        """definition.yaml 필드 정보를 문자열로 포맷."""
        lines = []
        for name, config in fields.items():
            importance = config.get("importance", "reference")
            field_type = config.get("type", "token")
            aliases = config.get("aliases", [])
            lines.append(
                f"- {name}: type={field_type}, importance={importance}, aliases={aliases}"
            )
        return "\n".join(lines)

    def _parse_response(self, response_text: str) -> ExtractionResult:
        """Claude 응답 파싱."""
        # JSON 블록 추출 시도
        try:
            # ```json ... ``` 블록 찾기
            if "```json" in response_text:
                start = response_text.find("```json") + 7
                end = response_text.find("```", start)
                json_str = response_text[start:end].strip()
            elif "{" in response_text:
                # 순수 JSON 응답
                start = response_text.find("{")
                end = response_text.rfind("}") + 1
                json_str = response_text[start:end]
            else:
                raise ValueError("No JSON found in response")

            data = json.loads(json_str)

            return ExtractionResult(
                success=True,
                fields=data.get("fields", {}),
                measurements=data.get("measurements", []),
                missing_fields=data.get("missing_fields", []),
                warnings=data.get("warnings", []),
                confidence=data.get("confidence"),
                suggested_template_id=data.get("suggested_template_id"),
            )

        except (json.JSONDecodeError, ValueError) as e:
            return ExtractionResult(
                success=False,
                error_message=f"Failed to parse response: {e}",
                warnings=[f"Raw response: {response_text[:500]}..."],
            )
