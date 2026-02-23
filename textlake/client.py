"""Moltbook API client: Bearer auth, rate limiting, retries, optional raw capture."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from aiolimiter import AsyncLimiter

from textlake.config import CrawlerSettings


class TransientAuthError(Exception):
    """Unexpected 401 on GET; worker should backoff task, not kill process."""

    pass


class RateLimitResetError(Exception):
    """429 or rate limit hit; includes server-indicated reset time for not_before."""

    def __init__(self, reset_at: datetime) -> None:
        self.reset_at = reset_at
        super().__init__(f"Rate limit until {reset_at}")


def _parse_reset_time(response: httpx.Response) -> datetime | None:
    """Parse Retry-After (seconds) or X-RateLimit-Reset (epoch) from response."""
    retry_after = response.headers.get("Retry-After")
    if retry_after is not None:
        try:
            secs = int(retry_after)
            return datetime.now(timezone.utc) + timedelta(seconds=secs)
        except ValueError:
            pass
    reset = response.headers.get("X-RateLimit-Reset")
    if reset is not None:
        try:
            ts = int(reset)
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except ValueError, OSError:
            pass
    return None


def _should_retry(e: BaseException) -> bool:
    if isinstance(e, httpx.TransportError):
        return True
    if isinstance(e, TransientAuthError):
        return True
    if isinstance(e, RateLimitResetError):
        return False
    if isinstance(e, httpx.HTTPStatusError):
        code = e.response.status_code
        if code == 429:
            return False
        if code >= 500:
            return True
    return False


class MoltbookClient:
    """Async Moltbook API client: rate limiting, retries, optional raw capture."""

    def __init__(self, settings: CrawlerSettings) -> None:
        self._settings = settings
        self._limiter = AsyncLimiter(settings.mb_rate_limit_rpm, 60)
        self._semaphore = asyncio.Semaphore(settings.mb_http_semaphore)
        self._client: httpx.AsyncClient | None = None
        self._raw_capture_factory: Any = None  # async_sessionmaker if enabled

    async def __aenter__(self) -> MoltbookClient:
        self._client = httpx.AsyncClient(
            base_url=self._settings.mb_api_base.rstrip("/"),
            timeout=self._settings.mb_http_timeout,
            headers={
                "Authorization": f"Bearer {self._settings.mb_crawler_api_key}",
                "Content-Type": "application/json",
            },
        )
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def set_raw_capture(self, session_factory: Any) -> None:
        """Enable logging each request/response to raw_capture table (optional)."""
        self._raw_capture_factory = session_factory

    def _adjust_limiter_from_headers(self, response: httpx.Response) -> None:
        """Tighten limiter when X-RateLimit-Remaining is 0 (optional)."""
        remaining = response.headers.get("X-RateLimit-Remaining")
        if remaining is not None:
            try:
                n = int(remaining)
                if (
                    n <= 0
                    and hasattr(self._limiter, "max_rate")
                    and self._limiter.max_rate > 1
                ):
                    try:
                        self._limiter.max_rate = max(1, self._limiter.max_rate // 2)
                    except AttributeError, TypeError:
                        pass
            except ValueError:
                pass

    async def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """GET path (relative to api base); return JSON.
        Raises TransientAuthError on 401, RateLimitResetError on 429."""
        if self._client is None:
            raise RuntimeError("Client not started; use async with MoltbookClient(...)")
        path_norm = path if path.startswith("/") else f"/{path}"

        async def _do() -> dict[str, Any]:
            await self._semaphore.acquire()
            try:
                await self._limiter.acquire()
                t0 = time.perf_counter()
                resp = await self._client.get(path_norm, params=params or {})
                elapsed_ms = int((time.perf_counter() - t0) * 1000)
                self._adjust_limiter_from_headers(resp)

                if resp.status_code == 401:
                    raise TransientAuthError("Unexpected 401 on GET")
                if resp.status_code == 429:
                    reset_at = _parse_reset_time(resp) or (
                        datetime.now(timezone.utc) + timedelta(minutes=1)
                    )
                    raise RateLimitResetError(reset_at)

                if self._raw_capture_factory is not None:
                    url_str = f"{self._client.base_url}{path_norm}"
                    await self._log_raw_capture(
                        "GET", url_str, resp.status_code, elapsed_ms, None, resp
                    )

                resp.raise_for_status()
                return resp.json()
            finally:
                self._semaphore.release()

        from tenacity import (
            retry_if_exception,
            stop_after_attempt,
            wait_exponential_jitter,
        )
        from tenacity.asyncio import AsyncRetrying

        async for attempt in AsyncRetrying(
            retry=retry_if_exception(_should_retry),
            stop=stop_after_attempt(self._settings.mb_http_retry_max_attempts),
            wait=wait_exponential_jitter(initial=1, max=60),
            reraise=True,
        ):
            with attempt:
                return await _do()

    async def _log_raw_capture(
        self,
        method: str,
        url: str,
        status_code: int,
        response_ms: int,
        request_json: dict | None,
        response: httpx.Response,
    ) -> None:
        """Write one row to raw_capture if session factory is set."""
        if self._raw_capture_factory is None:
            return
        try:
            async with self._raw_capture_factory() as session:
                from textlake.models.crawl import RawCapture

                try:
                    body = response.json()
                except Exception:
                    body = None
                row = RawCapture(
                    fetched_at=datetime.now(timezone.utc),
                    method=method,
                    url=url,
                    status_code=status_code,
                    response_ms=response_ms,
                    request_json=request_json,
                    response_json=body,
                    headers_json=dict(response.headers),
                )
                session.add(row)
                await session.commit()
        except Exception:
            pass
