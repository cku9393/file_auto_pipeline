"""
브라우저 E2E 테스트 (Playwright).

실제 브라우저를 사용하여 UI/UX를 검증합니다.

Flaky 방지 원칙:
- "네트워크가 조용해질 때까지"가 아니라
- "내가 기다리는 UI 상태가 나타날 때까지" 기다린다
- networkidle은 보조, 최종 판정은 locator 기반

Selector 안정성 가이드:
- 텍스트 기반 selector는 i18n/UI 변경에 취약함
- 중요한 대기 포인트는 data-testid 사용 권장:
  - 예: [data-testid="submit-btn"], [data-testid="status-badge"]
- DOM 상태로 확인 (버튼 활성/비활성, 링크 생성, class 변경)
  - 예: button:not([disabled]), .status-complete, a[href*="download"]
"""

import time

from playwright.sync_api import Page

# =============================================================================
# 기본 페이지 테스트
# =============================================================================


def test_home_page_loads(page: Page, live_server: str) -> None:
    """홈페이지가 정상적으로 로드되는지 확인."""
    # When: 홈페이지에 접속
    response = page.goto(live_server)

    # Then: JSON 응답에 특정 키가 있는지 확인 (locator 기반)
    assert response is not None
    assert response.status == 200

    # locator 기반 대기: "message" 또는 "Manufacturing" 텍스트가 포함된 요소
    page.wait_for_selector("body", state="visible")
    content = page.content()
    assert "Manufacturing Docs Pipeline" in content or "message" in content


def test_health_check(page: Page, live_server: str) -> None:
    """헬스 체크 엔드포인트가 정상 작동하는지 확인."""
    # When: /health 엔드포인트에 접속
    response = page.goto(f"{live_server}/health")

    # Then: JSON 응답에 "ok" 포함
    assert response is not None
    assert response.status == 200

    # locator 기반: "ok" 텍스트가 보일 때까지 대기
    page.wait_for_selector('text="ok"', timeout=10000)


def test_chat_page_loads(page: Page, live_server: str) -> None:
    """채팅 페이지가 정상적으로 로드되는지 확인."""
    # When: /chat 페이지에 접속
    response = page.goto(f"{live_server}/chat")

    # Then: 페이지가 200 OK + URL 확인
    assert response is not None
    assert response.status == 200
    assert page.url.endswith("/chat")

    # locator 기반: body가 visible 상태인지 확인
    page.wait_for_selector("body", state="visible")


def test_templates_page_loads(page: Page, live_server: str) -> None:
    """템플릿 관리 페이지가 정상적으로 로드되는지 확인."""
    # When: /templates 페이지에 접속
    response = page.goto(f"{live_server}/templates")

    # Then: 페이지가 200 OK
    assert response is not None
    assert response.status == 200
    assert page.url.endswith("/templates")

    page.wait_for_selector("body", state="visible")


def test_api_docs_available(page: Page, live_server: str) -> None:
    """FastAPI Swagger 문서가 제공되는지 확인."""
    # When: /docs 페이지에 접속
    response = page.goto(f"{live_server}/docs")

    # Then: Swagger UI가 로드됨
    assert response is not None
    assert response.status == 200

    # locator 기반: Swagger UI 특유의 요소 대기
    # Swagger UI는 #swagger-ui 또는 특정 클래스를 가진다
    page.wait_for_selector("#swagger-ui, .swagger-ui", timeout=15000)


# =============================================================================
# 네비게이션 테스트
# =============================================================================


def test_navigation_between_pages(page: Page, live_server: str) -> None:
    """페이지 간 네비게이션이 정상 작동하는지 확인."""
    # Given: 홈페이지에서 시작
    page.goto(live_server)
    page.wait_for_selector("body", state="visible")

    # When: 다양한 페이지로 이동
    page.goto(f"{live_server}/chat")
    page.wait_for_selector("body", state="visible")
    assert "/chat" in page.url

    page.goto(f"{live_server}/templates")
    page.wait_for_selector("body", state="visible")
    assert "/templates" in page.url

    page.goto(f"{live_server}/health")
    page.wait_for_selector('text="ok"', timeout=10000)


# =============================================================================
# 에러 처리 테스트
# =============================================================================


def test_404_page(page: Page, live_server: str) -> None:
    """존재하지 않는 페이지에 대한 404 처리 확인."""
    # When: 잘못된 경로로 접속
    response = page.goto(f"{live_server}/nonexistent-page-12345")

    # Then: 404 응답 반환
    assert response is not None
    assert response.status == 404


# =============================================================================
# 반응형 테스트
# =============================================================================


def test_mobile_viewport(page: Page, live_server: str) -> None:
    """모바일 뷰포트에서도 페이지가 정상 작동하는지 확인."""
    # Given: 모바일 크기 뷰포트 설정
    page.set_viewport_size({"width": 375, "height": 667})  # iPhone SE

    # When: 홈페이지 접속
    response = page.goto(live_server)

    # Then: 페이지가 정상 로드됨
    assert response is not None
    assert response.status == 200
    page.wait_for_selector("body", state="visible")


def test_tablet_viewport(page: Page, live_server: str) -> None:
    """태블릿 뷰포트에서도 페이지가 정상 작동하는지 확인."""
    # Given: 태블릿 크기 뷰포트 설정
    page.set_viewport_size({"width": 768, "height": 1024})  # iPad

    # When: 홈페이지 접속
    response = page.goto(live_server)

    # Then: 페이지가 정상 로드됨
    assert response is not None
    assert response.status == 200
    page.wait_for_selector("body", state="visible")


# =============================================================================
# 성능 테스트
# =============================================================================


def test_page_load_performance(page: Page, live_server: str) -> None:
    """페이지 로드 성능이 합리적인 범위 내에 있는지 확인."""
    # Given: 시작 시간 측정
    start_time = time.time()

    # When: 페이지 로드
    page.goto(live_server)
    page.wait_for_selector("body", state="visible")

    # Then: 5초 이내에 로드 완료
    load_time = time.time() - start_time
    assert load_time < 5.0, f"Page load took {load_time:.2f}s, expected < 5s"
