from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from ..base import BaseScraper
from ..models import ScrapeResult, Slot

BASE_URL = "https://www.fit4all.cz/cs/online-rezervace?activity=6&date={date}"
PUBLIC_URL = "https://www.fit4all.cz/cs/online-rezervace?activity=6"
TIME_RE = re.compile(r"(\d{1,2}):(\d{2})")


class Fit4AllScraper(BaseScraper):
    venue_id = "fit4all"
    venue_name = "Fit4All"
    venue_url = PUBLIC_URL
    timeout_seconds = 180  # 14 page loads × ~3s + rezerva

    async def fetch_window(self, start_date: date, days: int) -> ScrapeResult:
        scraped_at = datetime.now(timezone.utc)
        slots: list[Slot] = []

        async with async_playwright() as p:
            browser = await p.chromium.launch()
            ctx = await browser.new_context(
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                locale="cs-CZ",
            )
            try:
                for i in range(days):
                    day = start_date + timedelta(days=i)
                    page = await ctx.new_page()
                    try:
                        url = BASE_URL.format(date=day.isoformat())
                        await page.goto(url, wait_until="networkidle", timeout=20000)
                        await page.wait_for_selector(".court-cell", timeout=10000)
                        html = await page.content()
                        slots.extend(self._parse(html, day, url))
                    finally:
                        await page.close()
            finally:
                await browser.close()

        return ScrapeResult(
            venue_id=self.venue_id,
            venue_name=self.venue_name,
            venue_url=self.venue_url,
            scraped_at=scraped_at,
            slots=slots,
        )

    def _parse(self, html: str, day: date, page_url: str) -> list[Slot]:
        soup = BeautifulSoup(html, "lxml")
        cells = soup.select(".court-cell")
        result: list[Slot] = []
        for cell in cells:
            cls = cell.get("class") or []
            start_time = cell.get("data-start-time")
            court = cell.get("data-name") or f"Kurt {cell.get('data-court-number', '?')}"
            if not start_time:
                continue
            m = TIME_RE.match(start_time)
            if not m:
                continue
            sh, sm = int(m.group(1)), int(m.group(2))
            start = datetime(day.year, day.month, day.day, sh, sm)
            end = start + timedelta(minutes=30)
            available = "court-cell-free" in cls
            result.append(
                Slot(
                    venue_id=self.venue_id,
                    venue_name=self.venue_name,
                    court=court,
                    start=start,
                    end=end,
                    available=available,
                    booking_url=page_url,
                )
            )
        return result
