"""
Templates layer: 템플릿 관리 모듈.

역할:
- 템플릿 CRUD (manager.py)
- 예시 → 템플릿 스캐폴딩 (scaffolder.py)

주의: 폴더 구분
- src/templates/ → 코드 (이 모듈)
- templates/ (루트) → 데이터 저장소 (base/, custom/)
- src/app/templates/ → UI (Jinja2 HTML)
"""

from .manager import (
    TemplateError,
    TemplateManager,
    get_template_path,
    validate_template_id,
)
from .scaffolder import (
    ScaffoldResult,
    TemplateScaffolder,
)

__all__ = [
    # manager
    "TemplateManager",
    "TemplateError",
    "validate_template_id",
    "get_template_path",
    # scaffolder
    "TemplateScaffolder",
    "ScaffoldResult",
]
