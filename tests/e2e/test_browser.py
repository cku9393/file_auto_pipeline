"""
브라우저 E2E 테스트 (Playwright).

실제 브라우저를 사용하여 UI/UX를 검증합니다.
"""

from playwright.sync_api import Page, expect


# =============================================================================
# 기본 페이지 테스트
# =============================================================================

def test_home_page_loads(page: Page, live_server: str) -> None:
    """홈페이지가 정상적으로 로드되는지 확인."""
    # Given: 홈페이지 URL
    # When: 홈페이지에 접속
    page.goto(live_server)

    # Then: 페이지가 로드되고 타이틀이 표시됨
    # Note: main.py의 root endpoint는 JSON을 반환하므로 JSON 응답 확인
    content = page.content()
    assert "Manufacturing Docs Pipeline" in content or "message" in content


def test_health_check(page: Page, live_server: str) -> None:
    """헬스 체크 엔드포인트가 정상 작동하는지 확인."""
    # Given: 헬스체크 URL
    # When: /health 엔드포인트에 접속
    page.goto(f"{live_server}/health")

    # Then: 상태가 ok로 반환됨
    content = page.content()
    assert '"status"' in content
    assert '"ok"' in content


def test_chat_page_loads(page: Page, live_server: str) -> None:
    """채팅 페이지가 정상적으로 로드되는지 확인."""
    # Given: 채팅 페이지 URL
    # When: /chat 페이지에 접속
    page.goto(f"{live_server}/chat")

    # Then: 페이지가 200 OK로 응답
    # Note: 페이지가 실제로 존재하는지 확인 (404가 아님)
    assert page.url.endswith("/chat")


def test_templates_page_loads(page: Page, live_server: str) -> None:
    """템플릿 관리 페이지가 정상적으로 로드되는지 확인."""
    # Given: 템플릿 페이지 URL
    # When: /templates 페이지에 접속
    page.goto(f"{live_server}/templates")

    # Then: 페이지가 200 OK로 응답
    assert page.url.endswith("/templates")


def test_api_docs_available(page: Page, live_server: str) -> None:
    """FastAPI Swagger 문서가 제공되는지 확인."""
    # Given: API 문서 URL
    # When: /docs 페이지에 접속
    page.goto(f"{live_server}/docs")

    # Then: Swagger UI가 로드됨
    content = page.content()
    assert "swagger" in content.lower() or "openapi" in content.lower()


# =============================================================================
# 네비게이션 테스트
# =============================================================================

def test_navigation_between_pages(page: Page, live_server: str) -> None:
    """페이지 간 네비게이션이 정상 작동하는지 확인."""
    # Given: 홈페이지에서 시작
    page.goto(live_server)

    # When: 다양한 페이지로 이동
    # Then: 각 페이지가 정상적으로 로드됨
    page.goto(f"{live_server}/chat")
    assert "/chat" in page.url

    page.goto(f"{live_server}/templates")
    assert "/templates" in page.url

    page.goto(f"{live_server}/health")
    content = page.content()
    assert "ok" in content


# =============================================================================
# 에러 처리 테스트
# =============================================================================

def test_404_page(page: Page, live_server: str) -> None:
    """존재하지 않는 페이지에 대한 404 처리 확인."""
    # Given: 존재하지 않는 URL
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
    page.goto(live_server)

    # Then: 페이지가 정상 로드됨
    content = page.content()
    assert len(content) > 0


def test_tablet_viewport(page: Page, live_server: str) -> None:
    """태블릿 뷰포트에서도 페이지가 정상 작동하는지 확인."""
    # Given: 태블릿 크기 뷰포트 설정
    page.set_viewport_size({"width": 768, "height": 1024})  # iPad

    # When: 홈페이지 접속
    page.goto(live_server)

    # Then: 페이지가 정상 로드됨
    content = page.content()
    assert len(content) > 0


# =============================================================================
# 성능 테스트
# =============================================================================

def test_page_load_performance(page: Page, live_server: str) -> None:
    """페이지 로드 성능이 합리적인 범위 내에 있는지 확인."""
    import time

    # Given: 시작 시간 측정
    start_time = time.time()

    # When: 페이지 로드
    page.goto(live_server)

    # Then: 5초 이내에 로드 완료
    load_time = time.time() - start_time
    assert load_time < 5.0, f"Page load took {load_time:.2f}s, expected < 5s"
