from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from datetime import date, datetime, timezone

from .models import ScrapeResult

log = logging.getLogger(__name__)


class BaseScraper(ABC):
    venue_id: str
    venue_name: str
    venue_url: str
    timeout_seconds: int = 90

    @abstractmethod
    async def fetch_window(self, start_date: date, days: int) -> ScrapeResult:
        """Vrátí ScrapeResult se sloty pro `days` dní počínaje start_date."""

    async def run(self, start_date: date, days: int) -> ScrapeResult:
        """Wrapper s timeoutem a error capture — výjimka tu nesmí prosáknout."""
        started = datetime.now(timezone.utc)
        try:
            return await asyncio.wait_for(
                self.fetch_window(start_date, days), timeout=self.timeout_seconds
            )
        except asyncio.TimeoutError:
            log.warning("Scraper %s timed out", self.venue_id)
            return ScrapeResult(
                venue_id=self.venue_id,
                venue_name=self.venue_name,
                venue_url=self.venue_url,
                scraped_at=started,
                error=f"timeout after {self.timeout_seconds}s",
            )
        except Exception as exc:
            log.exception("Scraper %s failed", self.venue_id)
            return ScrapeResult(
                venue_id=self.venue_id,
                venue_name=self.venue_name,
                venue_url=self.venue_url,
                scraped_at=started,
                error=f"{type(exc).__name__}: {exc}",
            )
