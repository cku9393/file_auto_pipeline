"""
OCR Service: 이미지/PDF → 텍스트 추출.

ADR-0003:
- OCR은 별도 단계로 분리 (디버깅 용이)
- 실패 시 사람 확인 UX로 되돌림
- confidence 기반 처리: >= 0.8 성공, 0.5~0.8 경고, < 0.5 실패
"""

from pathlib import Path

from src.app.providers.base import OCRError, OCRResult
from src.app.providers.gemini import GeminiOCRProvider


class OCRService:
    """
    OCR 서비스.

    이미지/PDF에서 텍스트 추출.
    """

    # Confidence 임계값
    CONFIDENCE_HIGH = 0.8  # 성공
    CONFIDENCE_LOW = 0.5  # 실패

    def __init__(
        self,
        config: dict,
        provider: GeminiOCRProvider | None = None,
    ):
        """
        Args:
            config: 설정 (ai.ocr 포함)
            provider: OCR Provider (None이면 config 기반 생성)
        """
        self.config = config

        if provider is not None:
            self.provider = provider
        else:
            ocr_config = config.get("ai", {}).get("ocr", {})
            self.provider = GeminiOCRProvider(
                model=ocr_config.get("model", "gemini-3-pro-preview"),
                fallback=ocr_config.get("fallback", "gemini-2.5-flash"),
            )

    async def extract_from_file(
        self,
        file_path: Path,
    ) -> OCRResult:
        """
        파일에서 텍스트 추출.

        Args:
            file_path: 파일 경로

        Returns:
            OCRResult
        """
        file_bytes = file_path.read_bytes()
        file_type = file_path.suffix.lower()

        return await self.extract_from_bytes(file_bytes, file_type)

    async def extract_from_bytes(
        self,
        file_bytes: bytes,
        file_type: str,
    ) -> OCRResult:
        """
        바이트에서 텍스트 추출.

        Args:
            file_bytes: 파일 바이트
            file_type: 파일 타입 (확장자 또는 MIME)

        Returns:
            OCRResult
        """
        try:
            result = await self.provider.extract_text(file_bytes, file_type)
            return result
        except OCRError as e:
            return OCRResult(
                success=False,
                error_code=e.code,
                error_message=e.message,
                model_requested=self.provider.model,
                model_used=None,
            )

    def evaluate_result(self, result: OCRResult) -> str:
        """
        OCR 결과 평가.

        Returns:
            "success" | "warning" | "failure"
        """
        if not result.success:
            return "failure"

        if result.confidence is None:
            # confidence 없으면 텍스트 존재 여부로 판단
            return "success" if result.text else "failure"

        if result.confidence >= self.CONFIDENCE_HIGH:
            return "success"
        elif result.confidence >= self.CONFIDENCE_LOW:
            return "warning"
        else:
            return "failure"

    def needs_human_review(self, result: OCRResult) -> bool:
        """사람 확인이 필요한지 여부."""
        evaluation = self.evaluate_result(result)
        return evaluation in ("warning", "failure")

    def get_user_message(self, result: OCRResult) -> str:
        """
        OCR 결과에 따른 사용자 메시지.

        ADR-0003: 실패 시 "이미지를 인식하지 못했습니다. 직접 입력해주세요."
        """
        evaluation = self.evaluate_result(result)

        if evaluation == "success":
            return "이미지에서 텍스트를 성공적으로 추출했습니다."
        elif evaluation == "warning":
            return "이미지 인식 결과가 불확실합니다. 추출된 텍스트를 확인해주세요."
        else:
            return "이미지를 인식하지 못했습니다. 직접 입력해주세요."
