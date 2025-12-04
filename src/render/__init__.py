"""
Render layer: DOCX/XLSX 출력 생성.

역할:
- 템플릿 + 데이터 → 최종 파일
- docxtpl (Word), openpyxl (Excel)
"""

from .excel import ExcelRenderer, render_xlsx
from .word import DocxRenderer, render_docx

__all__ = [
    "render_docx",
    "render_xlsx",
    "DocxRenderer",
    "ExcelRenderer",
]
