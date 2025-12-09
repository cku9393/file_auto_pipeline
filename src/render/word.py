"""
Word (DOCX) 렌더러: docxtpl 기반.

spec-v2.md Section 9.1 참조:
- docxtpl 템플릿 렌더링
- placeholder: {{wo_no}}, {{line}}, {{measurements}} 등
- 이미지 삽입 지원
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from docx.shared import Mm
from docxtpl import DocxTemplate, InlineImage

from src.domain.errors import ErrorCodes, PolicyRejectError


class DocxRenderer:
    """
    Word 문서 렌더러.

    Usage:
        renderer = DocxRenderer(template_path)
        renderer.render(data, output_path)
    """

    def __init__(self, template_path: Path):
        """
        Args:
            template_path: DOCX 템플릿 파일 경로

        Raises:
            PolicyRejectError: TEMPLATE_NOT_FOUND
        """
        if not template_path.exists():
            raise PolicyRejectError(
                ErrorCodes.TEMPLATE_NOT_FOUND,
                path=str(template_path),
            )

        self.template_path = template_path
        self._doc: DocxTemplate | None = None

    def _load_template(self) -> DocxTemplate:
        """템플릿 로드 (lazy)."""
        if self._doc is None:
            self._doc = DocxTemplate(self.template_path)
        return self._doc

    def render(
        self,
        data: dict[str, Any],
        output_path: Path,
        photos: dict[str, Path] | None = None,
        photo_width_mm: int = 80,
    ) -> Path:
        """
        템플릿에 데이터를 채워 Word 문서 생성.

        Args:
            data: 템플릿에 채울 데이터
                - wo_no, line, part_no, lot, result (필수)
                - inspector, date, remark (선택)
                - measurements: list[dict] (측정 데이터)
            output_path: 출력 파일 경로
            photos: 사진 슬롯 → 파일 경로 매핑 (예: {"overview": Path(...)})
            photo_width_mm: 사진 너비 (mm)

        Returns:
            저장된 파일 경로

        Raises:
            PolicyRejectError: RENDER_FAILED
        """
        try:
            doc = self._load_template()

            # 컨텍스트 구성
            context = self._build_context(data, photos, photo_width_mm, doc)

            # 렌더링
            doc.render(context)

            # 저장
            output_path.parent.mkdir(parents=True, exist_ok=True)
            doc.save(output_path)

            return output_path

        except PolicyRejectError:
            raise
        except Exception as e:
            raise PolicyRejectError(
                ErrorCodes.RENDER_FAILED,
                template=str(self.template_path),
                error=str(e),
            ) from e

    def _build_context(
        self,
        data: dict[str, Any],
        photos: dict[str, Path] | None,
        photo_width_mm: int,
        doc: DocxTemplate,
    ) -> dict[str, Any]:
        """렌더링 컨텍스트 구성."""
        context = {
            # 기본 필드 (definition.yaml 키 그대로)
            "wo_no": data.get("wo_no", ""),
            "line": data.get("line", ""),
            "part_no": data.get("part_no", ""),
            "lot": data.get("lot", ""),
            "result": data.get("result", ""),
            "inspector": data.get("inspector", ""),
            "date": data.get("date", ""),
            "remark": data.get("remark", ""),
            # 측정 데이터
            "measurements": data.get("measurements", []),
            # 메타데이터
            "generated_at": datetime.now(UTC).isoformat(),
        }

        # 사진 추가 (InlineImage)
        if photos:
            for slot_key, photo_path in photos.items():
                if photo_path and photo_path.exists():
                    context[f"photo_{slot_key}"] = InlineImage(
                        doc,
                        str(photo_path),
                        width=Mm(photo_width_mm),
                    )

        return context

    def get_placeholders(self) -> list[str]:
        """
        템플릿에서 사용된 placeholder 목록 추출.

        Returns:
            placeholder 이름 목록 (예: ["wo_no", "line", ...])
        """
        doc = self._load_template()

        # docxtpl의 undeclared_template_variables 활용
        # 주의: Jinja2 문법으로 된 변수만 감지
        try:
            variables = doc.get_undeclared_template_variables()
            return list(variables)
        except Exception:
            return []


def render_docx(
    template_path: Path,
    data: dict[str, Any],
    output_path: Path,
    photos: dict[str, Path] | None = None,
) -> Path:
    """
    Word 문서 생성 (간편 함수).

    Args:
        template_path: DOCX 템플릿 파일 경로
        data: 템플릿에 채울 데이터
        output_path: 출력 파일 경로
        photos: 사진 슬롯 → 파일 경로 매핑

    Returns:
        저장된 파일 경로
    """
    renderer = DocxRenderer(template_path)
    return renderer.render(data, output_path, photos)
