"""
FastAPI 애플리케이션 진입점.

실행:
- 개발: uv run uvicorn src.app.main:app --reload
- 프로덕션: uv run uvicorn src.app.main:app
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Routes
from src.app.routes import chat, generate, jobs, templates

# =============================================================================
# Configuration
# =============================================================================


def load_config(config_path: Path | None = None) -> dict:
    """설정 파일 로드."""
    if config_path is None:
        # 프로젝트 루트의 default.yaml
        config_path = Path(__file__).parent.parent.parent / "default.yaml"

    if not config_path.exists():
        return {}

    with open(config_path, encoding="utf-8") as f:
        data: dict[Any, Any] = yaml.safe_load(f)
        return data


# =============================================================================
# Lifespan
# =============================================================================


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    애플리케이션 생명주기 관리.

    시작 시: 설정 로드, 리소스 초기화
    종료 시: 리소스 정리
    """
    # Startup
    app.state.config = load_config()
    app.state.templates_root = Path(__file__).parent.parent.parent / "templates"
    app.state.jobs_root = Path(__file__).parent.parent.parent / "jobs"
    app.state.definition_path = Path(__file__).parent.parent.parent / "definition.yaml"

    yield

    # Shutdown
    # (리소스 정리 필요 시 여기에 추가)


# =============================================================================
# App Instance
# =============================================================================

app = FastAPI(
    title="Manufacturing Docs Pipeline",
    description="제조 현장 검사 데이터 → 고객용 보고서 자동 생성",
    version="0.1.0",
    lifespan=lifespan,
)

# Static files (CSS, JS)
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Jinja2 templates
templates_dir = Path(__file__).parent / "templates"
jinja_templates = (
    Jinja2Templates(directory=templates_dir) if templates_dir.exists() else None
)


# =============================================================================
# Routes
# =============================================================================

# 페이지 라우트 (HTML)
app.include_router(chat.router, prefix="", tags=["Chat"])
app.include_router(templates.router, prefix="/templates", tags=["Templates"])
app.include_router(generate.router, prefix="/generate", tags=["Generate"])
app.include_router(jobs.router, prefix="/jobs", tags=["Jobs"])

# API 라우트
app.include_router(chat.api_router, prefix="/api/chat", tags=["Chat API"])
app.include_router(
    templates.api_router, prefix="/api/templates", tags=["Templates API"]
)
app.include_router(generate.api_router, prefix="/api/generate", tags=["Generate API"])
app.include_router(jobs.api_router, prefix="/api/jobs", tags=["Jobs API"])


# =============================================================================
# Root Endpoints
# =============================================================================


@app.get("/")
async def root() -> dict[str, Any]:
    """홈 페이지 (대시보드)."""
    # TODO: Jinja2 템플릿으로 렌더링
    return {
        "message": "Manufacturing Docs Pipeline",
        "endpoints": {
            "chat": "/chat",
            "templates": "/templates",
            "jobs": "/jobs",
        },
    }


@app.get("/health")
async def health() -> dict[str, str]:
    """헬스 체크."""
    return {"status": "ok"}


# =============================================================================
# CLI Entry Point
# =============================================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
    )
