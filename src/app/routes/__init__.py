"""
FastAPI Routes.

페이지 라우트 (HTML) + API 라우트 (REST + SSE)
"""

from . import chat, generate, jobs, templates

__all__ = ["chat", "generate", "jobs", "templates"]
