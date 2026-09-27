"""Shared HTTP helpers: a polite rate limit and retries on 429."""

import asyncio
import time

import httpx

from paperpath.errors import UpstreamError


class RateLimiter:
    def __init__(self, min_interval: float) -> None:
        self._interval = min_interval
        self._next = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        if self._interval <= 0:
            return
        async with self._lock:
            now = time.monotonic()
            delay = self._next - now
            if delay > 0:
                await asyncio.sleep(delay)
                now = time.monotonic()
            self._next = now + self._interval


async def request_with_retries(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    limiter: RateLimiter | None = None,
    max_retries: int = 3,
    **kwargs: object,
) -> httpx.Response:
    last_error: Exception | None = None
    for attempt in range(max_retries):
        if limiter is not None:
            await limiter.wait()
        try:
            response = await client.request(method, url, **kwargs)  # type: ignore[arg-type]
        except httpx.HTTPError as exc:
            last_error = exc
            if attempt == max_retries - 1:
                break
            await asyncio.sleep(2**attempt)
            continue
        if response.status_code == 429 and attempt < max_retries - 1:
            retry_after = float(response.headers.get("Retry-After", 2**attempt))
            await asyncio.sleep(retry_after)
            continue
        if response.status_code >= 500 and attempt < max_retries - 1:
            await asyncio.sleep(2**attempt)
            continue
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise UpstreamError(f"{method} {url} failed with {response.status_code}.") from exc
        return response
    raise UpstreamError(f"{method} {url} failed.") from last_error