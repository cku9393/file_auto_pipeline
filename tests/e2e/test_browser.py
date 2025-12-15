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
    page.wait_for_selector('text="ok"', timeout=30000)


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
    page.wait_for_selector('text="ok"', timeout=30000)


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


# =============================================================================
# 검증 오류 카드 E2E (진짜 브라우저 렌더링)
# =============================================================================


def test_validation_error_card_renders_in_browser(page: Page, live_server: str) -> None:
    """
    불완전한 입력 제출 시 validation error card가 브라우저에 렌더링되는지 확인.

    이 테스트는 외부 LLM API를 호출하지 않습니다.
    입력이 너무 짧으면 LLM 호출 없이 안내 메시지를 반환하는 로직을 사용합니다.

    목적:
    - CSS가 정상 로드되는지
    - HTMX swap이 DOM에 카드를 삽입하는지
    - .chat-container selector가 실제로 동작하는지
    """
    # Given: /chat 페이지 로드
    page.goto(f"{live_server}/chat")
    page.wait_for_selector(".chat-container", state="visible")

    # When: 불완전한 짧은 입력 제출 (LLM 호출 없이 안내 메시지 반환)
    textarea = page.locator("textarea[name='content']")
    textarea.fill("hello")  # 20자 미만 → LLM 호출 안 함
    page.click("button[type='submit']")

    # Then: HTMX가 응답을 DOM에 삽입하고, 사용자 메시지가 나타남
    # "hello"가 사용자 메시지로 표시될 때까지 대기
    page.wait_for_selector(".message.user", timeout=10000)

    # 안내 메시지가 assistant 메시지로 나타남
    assistant_message = page.locator(".message.assistant").last
    assert assistant_message.is_visible()

    # 안내 메시지에 "필수 정보" 또는 "정보를 입력" 텍스트 포함 확인
    assistant_text = assistant_message.text_content() or ""
    assert "필수 정보" in assistant_text or "정보를 입력" in assistant_text


def test_chat_htmx_swap_works(page: Page, live_server: str) -> None:
    """
    HTMX swap이 정상 작동하는지 확인.

    DOM에 새 메시지가 추가되는 기본 메커니즘 검증.

    Flaky 방지: page.wait_for_function 대신 locator 기반 대기 사용.
    - locator.nth()와 wait_for()는 Playwright의 내장 재시도 메커니즘 활용
    - DOM 상태 변화를 안정적으로 감지
    """
    # Given: /chat 페이지 로드
    page.goto(f"{live_server}/chat")
    page.wait_for_selector(".chat-container", state="visible")

    # 초기 메시지 개수 확인
    messages_locator = page.locator(".message")
    initial_count = messages_locator.count()

    # When: 메시지 전송
    textarea = page.locator("textarea[name='content']")
    textarea.fill("테스트 메시지")
    page.click("button[type='submit']")

    # Then: 새 메시지가 DOM에 추가됨 (최소 1개 증가)
    # locator 기반 대기: (initial_count + 1)번째 메시지가 나타날 때까지 대기
    # nth()는 0-indexed이므로 initial_count가 곧 다음 인덱스
    new_message = messages_locator.nth(initial_count)
    new_message.wait_for(state="visible", timeout=15000)

    final_count = messages_locator.count()
    assert final_count > initial_count, "새 메시지가 DOM에 추가되지 않았습니다"


def test_css_validation_errors_class_applied(page: Page, live_server: str) -> None:
    """
    validation-errors CSS 클래스가 로드되고 적용 가능한지 확인.

    Note: 실제 validation error를 트리거하려면 LLM API가 필요합니다.
    이 테스트는 CSS link 태그가 존재하고 기본 selector가 유효한지만 확인합니다.

    Flaky 방지: computed style 체크 대신 link 태그 존재만 확인.
    - computed style은 CSS 파싱 타이밍에 민감하여 flaky할 수 있음
    - link 태그 존재 확인은 안정적인 최소 검증
    """
    # Given: /chat 페이지 로드
    page.goto(f"{live_server}/chat")
    page.wait_for_selector(".chat-container", state="visible")

    # Then: style.css link 태그가 존재하는지 확인
    # (computed style 체크는 flaky하므로 link 태그 존재만 확인)
    css_link = page.locator('link[rel="stylesheet"][href*="style.css"]')
    assert css_link.count() >= 1, "style.css link 태그가 없습니다"

    # chat-container가 존재하고 visible한지 확인
    chat_container = page.locator(".chat-container")
    assert chat_container.is_visible(), ".chat-container가 visible하지 않습니다"
