"""
E2E 테스트용 Playwright 설정.

설정 항목:
- 기본 타임아웃: 30초
- 뷰포트: 1280x720
- headless 모드 (CI 기본, 로컬에서 --headed 옵션)
- 실패 시 디버깅 정보 저장:
  - 스크린샷 (.png)
  - HTML 덤프 (.html) - 민감 정보 마스킹
  - 콘솔 로그 (.log) - 민감 정보 마스킹
  - Playwright trace (.zip) - CI에서만

보안 주의사항:
- 아티팩트는 실패 시에만 저장
- retention: 14일 (CI에서 설정)
- 민감 패턴 자동 마스킹: API 키, 토큰, 비밀번호
"""

import os
import re
from datetime import datetime
from pathlib import Path
from collections.abc import Generator
from typing import TYPE_CHECKING

import pytest

# Playwright는 선택적 의존성 - 설치되어 있을 때만 import
try:
    from playwright.sync_api import Browser, BrowserContext, Page

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    Browser = None  # type: ignore[misc,assignment]
    BrowserContext = None  # type: ignore[misc,assignment]
    Page = None  # type: ignore[misc,assignment]

if TYPE_CHECKING:
    from playwright.sync_api import Browser, BrowserContext, Page

# =============================================================================
# 상수
# =============================================================================

ARTIFACTS_DIR = Path(__file__).parent / "artifacts"
IS_CI = os.getenv("CI") == "true"

# =============================================================================
# 민감 정보 마스킹
# =============================================================================

# 마스킹할 패턴들 (API 키, 토큰, 비밀번호 등)
SENSITIVE_PATTERNS = [
    # API 키 패턴
    (
        r'(api[_-]?key|apikey)["\']?\s*[:=]\s*["\']?([a-zA-Z0-9_-]{20,})',
        r"\1: [MASKED]",
    ),
    (r"(sk-[a-zA-Z0-9]{20,})", r"[MASKED_API_KEY]"),  # OpenAI 스타일
    (r"(anthropic-[a-zA-Z0-9]{20,})", r"[MASKED_API_KEY]"),  # Anthropic 스타일
    # Bearer 토큰
    (r"(Bearer\s+)([a-zA-Z0-9._-]{20,})", r"\1[MASKED_TOKEN]"),
    # Authorization 헤더
    (r'(authorization)["\']?\s*[:=]\s*["\']?([^"\'>\s]{20,})', r"\1: [MASKED]"),
    # 비밀번호
    (r'(password|passwd|pwd)["\']?\s*[:=]\s*["\']?([^"\'>\s]+)', r"\1: [MASKED]"),
    # 세션/쿠키
    (
        r'(session[_-]?id|sessionid)["\']?\s*[:=]\s*["\']?([a-zA-Z0-9_-]{16,})',
        r"\1: [MASKED]",
    ),
    # JWT 토큰 (eyJ로 시작)
    (r"(eyJ[a-zA-Z0-9_-]+\.eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+)", r"[MASKED_JWT]"),
]


def mask_sensitive_data(content: str) -> str:
    """민감 정보를 마스킹한 문자열 반환."""
    masked = content
    for pattern, replacement in SENSITIVE_PATTERNS:
        masked = re.sub(pattern, replacement, masked, flags=re.IGNORECASE)
    return masked


# =============================================================================
# Playwright 기본 설정 (Playwright가 설치된 경우에만 활성화)
# =============================================================================

if PLAYWRIGHT_AVAILABLE:

    @pytest.fixture(scope="session")
    def browser_context_args(browser_context_args: dict) -> dict:
        """브라우저 컨텍스트 설정."""
        args = {
            **browser_context_args,
            "viewport": {"width": 1280, "height": 720},
            "ignore_https_errors": True,
        }

        # CI에서만 trace 활성화 (로컬은 선택적)
        if IS_CI:
            args["record_video_dir"] = str(ARTIFACTS_DIR / "videos")

        return args

    @pytest.fixture
    def context(
        browser: "Browser", browser_context_args: dict
    ) -> "Generator[BrowserContext, None, None]":
        """브라우저 컨텍스트 생성."""
        context = browser.new_context(**browser_context_args)
        yield context
        context.close()

    @pytest.fixture
    def page(context: "BrowserContext") -> "Generator[Page, None, None]":
        """
        페이지 fixture with 타임아웃 + 콘솔 로그 수집.

        타임아웃:
        - 기본 액션: 30초
        - 네비게이션: 30초
        """
        # CI에서 trace 시작 (page 생성 전에)
        if IS_CI:
            context.tracing.start(screenshots=True, snapshots=True, sources=True)

        page = context.new_page()
        page.set_default_timeout(30000)
        page.set_default_navigation_timeout(30000)

        # 콘솔 로그 수집
        console_logs: list[str] = []
        page.on("console", lambda msg: console_logs.append(f"[{msg.type}] {msg.text}"))
        page.on("pageerror", lambda err: console_logs.append(f"[PAGE_ERROR] {err}"))

        # 테스트에서 접근 가능하도록 저장
        page._console_logs = console_logs  # type: ignore[attr-defined]

        yield page

        page.close()


# =============================================================================
# 환경 설정
# =============================================================================


@pytest.fixture(scope="session")
def base_url() -> str:
    """
    테스트 대상 서버 URL.

    환경 변수 BASE_URL이 설정되면 사용, 아니면 기본값.
    """
    return os.getenv("BASE_URL", "http://127.0.0.1:8765")


# =============================================================================
# 실패 시 디버깅 정보 저장
# =============================================================================


def _generate_artifact_name(item_name: str, extension: str) -> str:
    """고유한 artifact 파일명 생성 (테스트명 + 타임스탬프)."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # 테스트 파라미터 제거 (예: test_foo[chromium] -> test_foo)
    clean_name = item_name.split("[")[0]
    return f"{clean_name}_{timestamp}{extension}"


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """테스트 실패 시 디버깅 정보 저장."""
    outcome = yield
    rep = outcome.get_result()

    # call 단계에서 실패한 경우만
    if rep.when == "call" and rep.failed:
        page = item.funcargs.get("page")
        context = item.funcargs.get("context")

        if page:
            ARTIFACTS_DIR.mkdir(exist_ok=True)
            base_name = _generate_artifact_name(item.name, "")

            # 1. 스크린샷
            screenshot_path = ARTIFACTS_DIR / f"{base_name}.png"
            try:
                page.screenshot(path=str(screenshot_path), full_page=True)
                print(f"\n📸 Screenshot: {screenshot_path}")
            except Exception as e:
                print(f"\n⚠️ Screenshot failed: {e}")

            # 2. HTML 덤프 (민감 정보 마스킹)
            html_path = ARTIFACTS_DIR / f"{base_name}.html"
            try:
                html_content = page.content()
                masked_html = mask_sensitive_data(html_content)
                html_path.write_text(masked_html, encoding="utf-8")
                print(f"📄 HTML dump: {html_path}")
            except Exception as e:
                print(f"⚠️ HTML dump failed: {e}")

            # 3. 콘솔 로그 (민감 정보 마스킹)
            log_path = ARTIFACTS_DIR / f"{base_name}.log"
            try:
                console_logs = getattr(page, "_console_logs", [])
                if console_logs:
                    raw_logs = "\n".join(console_logs)
                    masked_logs = mask_sensitive_data(raw_logs)
                    log_path.write_text(masked_logs, encoding="utf-8")
                    print(f"📋 Console log: {log_path}")
            except Exception as e:
                print(f"⚠️ Console log failed: {e}")

            # 4. Trace (CI에서만)
            if IS_CI and context:
                trace_path = ARTIFACTS_DIR / f"{base_name}.zip"
                try:
                    context.tracing.stop(path=str(trace_path))
                    print(f"🔍 Trace: {trace_path}")
                except Exception as e:
                    print(f"⚠️ Trace failed: {e}")
