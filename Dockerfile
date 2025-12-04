# =============================================================================
# Manufacturing Docs Pipeline - Dockerfile
# =============================================================================
# Python 3.12 + uv 기반 FastAPI 애플리케이션
#
# 빌드: docker build -t file-auto-pipeline .
# 실행: docker run -p 8000:8000 file-auto-pipeline
# =============================================================================

FROM python:3.12-slim AS base

# 환경 변수 설정
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 작업 디렉토리
WORKDIR /app

# =============================================================================
# Builder Stage: uv 설치 및 의존성 설치
# =============================================================================
FROM base AS builder

# uv 설치
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# 의존성 파일 복사
COPY pyproject.toml uv.lock* ./

# 의존성 설치 (개발 의존성 제외)
RUN uv sync --no-dev --frozen

# =============================================================================
# Runtime Stage: 최종 이미지
# =============================================================================
FROM base AS runtime

# 보안: 비루트 사용자 생성
RUN groupadd --gid 1000 appgroup && \
    useradd --uid 1000 --gid appgroup --shell /bin/bash --create-home appuser

# uv 복사 (런타임에도 필요할 수 있음)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# 가상환경 복사
COPY --from=builder /app/.venv /app/.venv

# 소스 코드 복사
COPY src/ ./src/
COPY pyproject.toml ./

# 설정 파일 복사 (있는 경우)
COPY definition.yaml* ./
COPY default.yaml* ./

# 템플릿 기본 구조 복사
COPY templates/ ./templates/

# 디렉토리 생성 및 권한 설정
RUN mkdir -p /app/jobs /app/logs && \
    chown -R appuser:appgroup /app

# 비루트 사용자로 전환
USER appuser

# 가상환경 PATH 설정
ENV PATH="/app/.venv/bin:$PATH"

# 헬스체크
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8000/health').raise_for_status()" || exit 1

# 포트 노출
EXPOSE 8000

# 실행 명령
CMD ["uvicorn", "src.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
