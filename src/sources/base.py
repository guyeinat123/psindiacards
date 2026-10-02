"""Base class for all price sources.

Sources are defensive: a network error, a block page or a layout change
must NOT crash the run - it becomes a SourceResult with status error/blocked
and the other sources carry on.
"""
import asyncio
from abc import ABC, abstractmethod

import httpx
import structlog

from src.models import Offer, SourceResult


log = structlog.get_logger()


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/129.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


class Blocked(Exception):
    """The site served a bot-check / captcha / 403 instead of content. We skip, never bypass."""


class Skipped(Exception):
    """Source not configured (e.g. no API key)."""


class BaseSource(ABC):
    name: str = "base"

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def get(self, url: str, **kwargs) -> httpx.Response:
        resp = await self.client.get(url, **kwargs)
        if resp.status_code in (403, 429, 503):
            raise Blocked(f"HTTP {resp.status_code}")
        resp.raise_for_status()
        return resp

    @abstractmethod
    async def fetch(self) -> list[Offer]:
        raise NotImplementedError

    async def safe_fetch(self) -> SourceResult:
        """Fetch with full error handling - never raises."""
        try:
            offers = await self.fetch()
            log.info("source.fetched", source=self.name, count=len(offers))
            return SourceResult(self.name, "ok", offers)
        except Blocked as e:
            log.warning("source.blocked", source=self.name, error=str(e))
            return SourceResult(self.name, "blocked", error=str(e))
        except Skipped as e:
            log.info("source.skipped", source=self.name, reason=str(e))
            return SourceResult(self.name, "skipped", error=str(e))
        except Exception as e:
            log.error("source.failed", source=self.name, error=str(e), error_type=type(e).__name__)
            return SourceResult(self.name, "error", error=f"{type(e).__name__}: {e}")


async def fetch_all(sources: list[BaseSource]) -> list[SourceResult]:
    return list(await asyncio.gather(*(s.safe_fetch() for s in sources)))
