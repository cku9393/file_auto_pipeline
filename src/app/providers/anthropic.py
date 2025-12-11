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

from .base import (
    AIRawStorageConfig,
    ExtractionError,
    ExtractionResult,
    LLMProvider,
    RawStorageLevel,
    compute_hash,
)

logger = logging.getLogger(__name__)


class ClaudeProvider(LLMProvider):
    """
    Claude API Provider.

    Usage:
        provider = ClaudeProvider(model="claude-opus-4-5-20251101")
        result = await provider.extract_fields(user_input, ocr_text, definition, prompt)
    """

    # 프롬프트 템플릿 버전 (변경 시 업데이트)
    PROMPT_TEMPLATE_VERSION = "1.0.0"

    def __init__(
        self,
        model: str = "claude-opus-4-5-20251101",
        api_key: str | None = None,
        max_tokens: int = 4096,
        temperature: float | None = None,
        top_p: float | None = None,
        raw_storage_config: AIRawStorageConfig | None = None,
    ):
        """
        Args:
            model: 모델 ID (config에서 주입)
            api_key: API 키 (환경변수 MY_ANTHROPIC_KEY 또는 ANTHROPIC_API_KEY 사용 가능)
            max_tokens: 최대 토큰 수
            temperature: 샘플링 온도 (None이면 API 기본값)
            top_p: top-p 샘플링 (None이면 API 기본값)
            raw_storage_config: AI raw 데이터 저장 설정

        Raises:
            ExtractionError: API 키가 없을 때 (fail-fast)
        """
        self.model = model
        # API 키 결정: 인자 > MY_ANTHROPIC_KEY > ANTHROPIC_API_KEY
        self.api_key = (
            api_key
            or os.environ.get("MY_ANTHROPIC_KEY")
            or os.environ.get("ANTHROPIC_API_KEY")
        )

        # Fail-fast: 키가 없으면 즉시 에러 (나중에 모호한 에러 방지)
        if not self.api_key:
            raise ExtractionError(
                "ANTHROPIC_KEY_MISSING",
                "Anthropic API 키가 없습니다. "
                "MY_ANTHROPIC_KEY 또는 ANTHROPIC_API_KEY 환경변수를 설정하세요.",
            )

        self.max_tokens = max_tokens
        self.temperature = temperature
        self.top_p = top_p
        self.raw_storage_config = raw_storage_config or AIRawStorageConfig()
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
        template_id: str | None = None,
    ) -> ExtractionResult:
        """
        사용자 입력에서 필드 추출.

        ADR-0003: LLM은 구조화 제안만

        자동 재시도:
        - RateLimitError, APIConnectionError → 재시도
        - 최대 3회, 지수 백오프

        조건부 재현성 (Conditional Reproducibility):
        - 동일 파라미터로 유사한 결과를 기대할 수 있으나, 완전한 재현은 보장하지 않음
        - LLM 특성상 동일 입력에도 약간의 변동 가능

        저장 메타데이터:
        - provider: "anthropic"
        - model_params: temperature, top_p, max_tokens 등
        - request_id: API 응답의 request ID (가능한 경우)
        - prompt_hash: 프롬프트 해시 (검색/중복 제거용)
        - llm_raw_output: API 응답 원문 (storage_level에 따라)
        """
        model_requested = self.model
        now = datetime.now(UTC).isoformat()

        # 프롬프트 구성 (재현성을 위해 저장)
        prompt = self._build_prompt(user_input, ocr_text, definition, prompt_template)
        prompt_hash = compute_hash(prompt)

        # 모델 파라미터 수집
        model_params = self._collect_model_params()

        # 유저 입력 변수 (보안: 템플릿과 분리)
        user_variables = {
            "user_input": user_input,
            "ocr_text": ocr_text or "",
        }

        try:
            # API 호출 (재시도 로직 적용)
            response = await self._call_api_with_retry(prompt)

            # 응답 원문 추출 (파싱 전 저장 - 재현성)
            response_text = response.content[0].text

            # request_id 추출 (Anthropic API 응답에서)
            request_id = getattr(response, "id", None)

            # 응답 파싱
            result = self._parse_response(response_text)

            # === 조건부 재현성 메타데이터 ===
            result.model_requested = model_requested
            result.model_used = (
                response.model if hasattr(response, "model") else self.model
            )
            result.extracted_at = now

            # Provider 정보
            result.provider = "anthropic"
            result.model_params = model_params
            result.request_id = request_id
            result.extraction_method = "llm"

            # === Raw 저장 (storage_level에 따라) ===
            self._apply_raw_storage(
                result, response_text, prompt, user_variables, template_id
            )

            # 프롬프트 해시 (항상 저장)
            result.prompt_hash = prompt_hash

            return result

        except ExtractionError:
            raise
        except Exception as e:
            logger.error(f"Field extraction failed: {e}", exc_info=True)
            user_friendly_message = self._get_user_friendly_error_message(e)

            # 실패해도 메타데이터는 저장 가능
            error_result = ExtractionResult(
                success=False,
                error_message=user_friendly_message,
                model_requested=model_requested,
                model_used=self.model,
                extracted_at=now,
                provider="anthropic",
                model_params=model_params,
                extraction_method="llm",
                prompt_hash=prompt_hash,
                prompt_used=prompt,  # 하위 호환
            )

            raise ExtractionError(
                "EXTRACTION_FAILED",
                user_friendly_message,
                model=self.model,
                extraction_result=error_result,
            ) from e

    def _collect_model_params(self) -> dict[str, Any]:
        """호출에 사용된 모델 파라미터 수집."""
        params: dict[str, Any] = {
            "max_tokens": self.max_tokens,
        }
        if self.temperature is not None:
            params["temperature"] = self.temperature
        if self.top_p is not None:
            params["top_p"] = self.top_p
        return params

    def _apply_raw_storage(
        self,
        result: ExtractionResult,
        response_text: str,
        prompt: str,
        user_variables: dict[str, str],
        template_id: str | None,
    ) -> None:
        """
        storage_level에 따라 raw 데이터 저장.

        - FULL: 원문 저장 (truncation 적용)
        - MINIMAL: 해시만 저장
        - NONE: 저장 안 함
        """
        config = self.raw_storage_config

        # 프롬프트 분리 저장 (보안)
        result.prompt_template_id = template_id
        result.prompt_template_version = self.PROMPT_TEMPLATE_VERSION
        result.prompt_user_variables = user_variables

        if config.storage_level == RawStorageLevel.NONE:
            # 저장 안 함
            result.llm_raw_output = None
            result.llm_raw_output_hash = None
            result.prompt_rendered = None
            result.prompt_used = None

        elif config.storage_level == RawStorageLevel.MINIMAL:
            # 해시만 저장
            result.llm_raw_output = None
            result.llm_raw_output_hash = compute_hash(response_text)
            result.prompt_rendered = None
            result.prompt_used = None

        else:  # FULL
            # 원문 저장 (truncation 적용)
            if len(response_text) > config.max_raw_size:
                result.llm_raw_output = response_text[: config.max_raw_size]
                result.llm_raw_truncated = True
            else:
                result.llm_raw_output = response_text
                result.llm_raw_truncated = False

            result.llm_raw_output_hash = compute_hash(response_text)

            # 프롬프트도 크기 제한 적용
            if len(prompt) > config.max_raw_size:
                result.prompt_rendered = prompt[: config.max_raw_size]
            else:
                result.prompt_rendered = prompt

            result.prompt_used = result.prompt_rendered  # 하위 호환

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
            # API 호출 파라미터 구성
            api_kwargs: dict[str, Any] = {
                "model": self.model,
                "max_tokens": self.max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            }
            # 선택적 파라미터 추가
            if self.temperature is not None:
                api_kwargs["temperature"] = self.temperature
            if self.top_p is not None:
                api_kwargs["top_p"] = self.top_p

            return await client.messages.create(**api_kwargs)

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
                return "API 사용량 한도를 초과했습니다. 잠시 후 다시 시도해주세요."
            elif isinstance(error, anthropic.AuthenticationError):
                return (
                    "API 인증에 실패했습니다. MY_ANTHROPIC_KEY 환경변수를 확인해주세요."
                )
            elif isinstance(error, anthropic.PermissionDeniedError):
                return "이 작업을 수행할 권한이 없습니다. API 키의 권한을 확인해주세요."
            elif isinstance(error, anthropic.BadRequestError):
                return "요청 형식이 올바르지 않습니다. 입력 데이터를 확인해주세요."
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
        """
        Claude 응답 파싱.

        파싱 실패해도 llm_raw_output은 extract_fields()에서 저장됨.
        여기서는 파싱 결과만 반환.
        """
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
            # 파싱 실패 시에도 ExtractionResult 반환
            # llm_raw_output은 extract_fields()에서 설정됨 (재현성)
            return ExtractionResult(
                success=False,
                error_message=f"Failed to parse response: {e}",
                warnings=[f"Parse error: {e}"],
            )
