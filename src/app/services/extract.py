"""
Extraction Service: 자연어 → 구조화 JSON.

ADR-0003:
- LLM은 구조화 제안만, 최종 판정은 core/validate
- 간단한 패턴은 정규식으로 먼저 시도 (비용 절감)
"""

import re
from pathlib import Path

import yaml

from src.app.providers.anthropic import ClaudeProvider
from src.app.providers.base import ExtractionResult


class ExtractionService:
    """
    추출 서비스.

    자연어 입력을 구조화된 JSON으로 변환.
    """

    def __init__(
        self,
        config: dict,
        definition_path: Path,
        prompts_dir: Path,
        provider: ClaudeProvider | None = None,
    ):
        """
        Args:
            config: 설정 (ai.llm 포함)
            definition_path: definition.yaml 경로
            prompts_dir: 프롬프트 템플릿 디렉터리
            provider: LLM Provider (None이면 config 기반 생성)
        """
        self.config = config
        self.definition_path = definition_path
        self.prompts_dir = prompts_dir
        self._definition: dict | None = None
        self._prompt_template: str | None = None

        if provider is not None:
            self.provider = provider
        else:
            llm_config = config.get("ai", {}).get("llm", {})
            self.provider = ClaudeProvider(
                model=llm_config.get("model", "claude-opus-4-5-20251101"),
            )

    @property
    def definition(self) -> dict:
        """definition.yaml 로드 (lazy)."""
        if self._definition is None:
            with open(self.definition_path, encoding="utf-8") as f:
                self._definition = yaml.safe_load(f)
        return self._definition

    @property
    def prompt_template(self) -> str:
        """프롬프트 템플릿 로드 (lazy)."""
        if self._prompt_template is None:
            prompt_path = self.prompts_dir / "extract_fields.txt"
            if prompt_path.exists():
                self._prompt_template = prompt_path.read_text(encoding="utf-8")
            else:
                self._prompt_template = self._default_prompt()
        return self._prompt_template

    async def extract(
        self,
        user_input: str,
        ocr_text: str | None = None,
    ) -> ExtractionResult:
        """
        입력에서 필드 추출.

        1단계: 정규식으로 간단한 패턴 시도 (비용 절감)
        2단계: LLM 호출

        Args:
            user_input: 사용자 채팅 입력
            ocr_text: OCR로 추출된 텍스트 (있는 경우)

        Returns:
            ExtractionResult
        """
        # 정규식 선 추출 시도
        regex_fields = self._extract_with_regex(user_input, ocr_text)

        # 필수 필드가 모두 있으면 LLM 스킵 가능
        required_fields = self._get_required_fields()
        if all(f in regex_fields for f in required_fields):
            return ExtractionResult(
                success=True,
                fields=regex_fields,
                model_requested="regex",
                model_used="regex",
            )

        # LLM 호출
        result = await self.provider.extract_fields(
            user_input=user_input,
            ocr_text=ocr_text,
            definition=self.definition,
            prompt_template=self.prompt_template,
        )

        # 정규식 결과와 병합 (정규식 우선 - 더 신뢰할 수 있음)
        if regex_fields:
            for field, value in regex_fields.items():
                if value:
                    result.fields[field] = value

        return result

    def _extract_with_regex(
        self,
        user_input: str,
        ocr_text: str | None,
    ) -> dict[str, str]:
        """
        정규식으로 간단한 패턴 추출.

        ADR-0003: 비용 절감을 위해 정규식 먼저 시도
        """
        text = f"{user_input}\n{ocr_text or ''}"
        fields = {}

        # definition.yaml의 aliases 기반 패턴 생성
        for field_name, field_config in self.definition.get("fields", {}).items():
            aliases = field_config.get("aliases", [])
            pattern = self._build_field_pattern(field_name, aliases)

            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                value = match.group(1).strip()
                if value:
                    fields[field_name] = value

        return fields

    def _build_field_pattern(
        self,
        field_name: str,
        aliases: list[str],
    ) -> str:
        """필드용 정규식 패턴 생성."""
        # aliases를 OR로 연결
        labels = [re.escape(a) for a in aliases]
        if not labels:
            labels = [field_name]

        label_pattern = "|".join(labels)

        # 라벨 + 값 패턴
        return rf"(?:{label_pattern})\s*[:：]?\s*([^\n\r,;]+)"

    def _get_required_fields(self) -> list[str]:
        """필수 필드 목록."""
        return [
            name
            for name, config in self.definition.get("fields", {}).items()
            if config.get("importance") == "critical"
        ]

    def _default_prompt(self) -> str:
        """기본 프롬프트 템플릿."""
        return """당신은 제조 검사 문서에서 정보를 추출하는 전문가입니다.

## 입력 계약 (definition.yaml 기준)
{definition_yaml_content}

## 사용자 입력
{user_input}

## OCR 추출 텍스트 (있는 경우)
{ocr_text}

## 지시사항
1. 위 입력에서 필드를 추출하세요
2. 측정 데이터가 있다면 표 형식으로 추출하세요
3. 누락된 필수 필드가 있으면 missing_fields에 명시하세요

## 응답 형식 (JSON만)
{
  "fields": {
    "wo_no": "...",
    "line": "...",
    ...
  },
  "measurements": [
    {"item": "...", "spec": "...", "measured": "...", "result": "..."}
  ],
  "missing_fields": ["inspector"],
  "warnings": ["LOT 번호가 불명확함"],
  "confidence": 0.95,
  "suggested_template_id": null
}"""
