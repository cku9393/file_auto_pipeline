"""
재시도 로직 유틸리티.

API 호출 실패 시 자동 재시도를 지원합니다.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


async def retry_with_exponential_backoff(
    func: Callable[..., Awaitable[T]],
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
    *args: Any,
    **kwargs: Any,
) -> T:
    """
    지수 백오프를 사용한 재시도.

    Args:
        func: 재시도할 비동기 함수
        max_retries: 최대 재시도 횟수
        initial_delay: 초기 대기 시간(초)
        max_delay: 최대 대기 시간(초)
        exponential_base: 지수 백오프 기수
        exceptions: 재시도할 예외 타입들
        *args: func에 전달할 위치 인자
        **kwargs: func에 전달할 키워드 인자

    Returns:
        func의 반환값

    Raises:
        마지막 시도에서 발생한 예외
    """
    delay = initial_delay

    for attempt in range(max_retries + 1):
        try:
            result = await func(*args, **kwargs)
            if attempt > 0:
                logger.info(
                    f"Retry succeeded on attempt {attempt + 1}/{max_retries + 1}"
                )
            return result

        except exceptions as e:
            if attempt == max_retries:
                logger.error(
                    f"All {max_retries + 1} attempts failed. Last error: {e}"
                )
                raise

            logger.warning(
                f"Attempt {attempt + 1}/{max_retries + 1} failed: {e}. "
                f"Retrying in {delay:.1f}s..."
            )

            await asyncio.sleep(delay)

            # 지수 백오프
            delay = min(delay * exponential_base, max_delay)

    # Should never reach here
    msg = "Unexpected retry logic error"
    raise RuntimeError(msg)


async def retry_with_fallback(
    primary_func: Callable[..., Awaitable[T]],
    fallback_func: Callable[..., Awaitable[T]] | None = None,
    max_retries: int = 2,
    exceptions: tuple[type[Exception], ...] = (Exception,),
    *args: Any,
    **kwargs: Any,
) -> T:
    """
    재시도 후 fallback 함수 실행.

    Args:
        primary_func: 주 함수
        fallback_func: fallback 함수 (None이면 재시도만 수행)
        max_retries: primary_func 최대 재시도 횟수
        exceptions: 재시도할 예외 타입들
        *args: 함수에 전달할 위치 인자
        **kwargs: 함수에 전달할 키워드 인자

    Returns:
        primary_func 또는 fallback_func의 반환값

    Raises:
        primary_func와 fallback_func 모두 실패 시 마지막 예외
    """
    try:
        return await retry_with_exponential_backoff(
            primary_func,
            *args,
            max_retries=max_retries,
            exceptions=exceptions,
            **kwargs,
        )
    except exceptions as primary_error:
        if fallback_func is None:
            raise

        logger.warning(
            f"Primary function failed after retries. "
            f"Attempting fallback... Error: {primary_error}"
        )

        try:
            result = await fallback_func(*args, **kwargs)
            logger.info("Fallback succeeded")
            return result
        except Exception as fallback_error:
            logger.error(f"Fallback also failed: {fallback_error}")
            raise fallback_error from primary_error


class RetryableError(Exception):
    """재시도 가능한 에러."""

    pass


class NonRetryableError(Exception):
    """재시도 불가능한 에러 (즉시 실패)."""

    pass
