"""Общий асинхронный HTTP-слой с ограничением частоты и повторными попытками."""
from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class SourceError(RuntimeError):
    pass


class AuthRequired(SourceError):
    pass


class RateLimiter:
    """Простой глобальный лимит: не более 1 запроса за min_interval секунд."""

    def __init__(self, min_interval: float = 0.75):
        self.min_interval = max(0.0, min_interval)
        self._lock = asyncio.Lock()
        self._next_at = 0.0

    async def wait(self) -> None:
        async with self._lock:
            loop = asyncio.get_running_loop()
            now = loop.time()
            delay = max(0.0, self._next_at - now)
            if delay:
                await asyncio.sleep(delay)
            self._next_at = max(now, self._next_at) + self.min_interval


class AsyncHTTP:
    def __init__(
        self,
        base_url: str,
        headers: dict[str, str],
        rate_limiter: RateLimiter,
        timeout: float = 20.0,
        max_retries: int = 3,
    ):
        self.base_url = base_url.rstrip("/")
        self.default_headers = headers
        self.limiter = rate_limiter
        self.timeout = timeout
        self.max_retries = max_retries
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers,
            timeout=httpx.Timeout(timeout),
            limits=httpx.Limits(max_connections=12, max_keepalive_connections=6),
            follow_redirects=True,
        )

    async def request(
        self,
        path: str,
        *,
        method: str = "GET",
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            await self.limiter.wait()
            try:
                response = await self.client.request(
                    method, path, params=params, data=data, headers=headers,
                )
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                await asyncio.sleep((2 ** attempt) * 0.8 + random.random() * 0.3)
                continue

            if response.status_code in (429, 500, 502, 503, 504):
                retry_after = response.headers.get("Retry-After")
                try:
                    delay = float(retry_after) if retry_after else (2 ** attempt) * 1.2
                except ValueError:
                    delay = (2 ** attempt) * 1.2
                delay = min(30.0, max(1.0, delay + random.random() * 0.4))
                last_error = SourceError(f"HTTP {response.status_code}: {response.text[:120]}")
                if attempt >= self.max_retries:
                    break
                logger.warning("Повтор после HTTP %s, пауза %.1f с", response.status_code, delay)
                await asyncio.sleep(delay)
                continue
            return response
        raise SourceError(f"Не удалось выполнить запрос {path}: {last_error}")

    async def aclose(self) -> None:
        await self.client.aclose()
