"""
FastAPI Routes.

페이지 라우트 (HTML) + API 라우트 (REST + SSE)
"""

from . import chat, generate, templates

__all__ = ["chat", "templates", "generate"]
