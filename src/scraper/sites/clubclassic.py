from __future__ import annotations

import asyncio
import re
from datetime import date, datetime, timedelta, timezone

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from ..base import BaseScraper
from ..models import ScrapeResult, Slot

BASE = "https://rezervace.clubclassic.cz/"
DAY_URL = BASE + "index.php?page=day_overview&id=22&date={date}"

TIME_RE = re.compile(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})")
PARALLELISM = 4   # paralelní záložky v jednom browser contextu


class ClubClassicScraper(BaseScraper):
    """Server-rendered PHP stránka, ale clubclassic.cz odmítá requesty z cloud
    datacenter IP s 403 (`python-httpx` UA i běžný Chrome UA bez TLS handshake
    z reálného browseru). Proto Playwright, stejně jako u ostatních zdrojů.
    """

    venue_id = "clubclassic"
    venue_name = "Club Classic"
    venue_url = BASE + "?page=day_overview&id=22"
    timeout_seconds = 180

    async def fetch_window(self, start_date: date, days: int) -> ScrapeResult:
        scraped_at = datetime.now(timezone.utc)
        slots: list[Slot] = []
        errors: list[str] = []

        async with async_playwright() as p:
            browser = await p.chromium.launch()
            ctx = await browser.new_context(
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                locale="cs-CZ",
            )
            try:
                sem = asyncio.Semaphore(PARALLELISM)

                async def fetch_one(day: date) -> list[Slot] | Exception:
                    async with sem:
                        page = await ctx.new_page()
                        try:
                            url = DAY_URL.format(date=day.isoformat())
                            await page.goto(url, wait_until="domcontentloaded", timeout=25000)
                            await page.wait_for_selector("table.denni-prehled", timeout=15000)
                            html = await page.content()
                            return self._parse_day(html, day)
                        except Exception as e:
                            return e
                        finally:
                            await page.close()

                day_results = await asyncio.gather(
                    *(fetch_one(start_date + timedelta(days=i)) for i in range(days))
                )
                for r in day_results:
                    if isinstance(r, Exception):
                        errors.append(f"{type(r).__name__}: {r}")
                    else:
                        slots.extend(r)
            finally:
                await browser.close()

        first_error = errors[0] if errors and not slots else None
        return ScrapeResult(
            venue_id=self.venue_id,
            venue_name=self.venue_name,
            venue_url=self.venue_url,
            scraped_at=scraped_at,
            slots=slots,
            error=first_error,
        )

    def _parse_day(self, html: str, day: date) -> list[Slot]:
        soup = BeautifulSoup(html, "lxml")
        table = soup.find("table", class_="denni-prehled")
        if not table:
            return []

        header_cells = table.find("tr").find_all("th")
        courts = [c.get_text(strip=True) for c in header_cells[1:]]
        day_booking_url = DAY_URL.format(date=day.isoformat())

        slots: list[Slot] = []
        for row in table.find_all("tr", class_="rows"):
            time_th = row.find("th")
            if not time_th:
                continue
            match = TIME_RE.search(time_th.get_text(" ", strip=True))
            if not match:
                continue
            sh, sm, eh, em = (int(x) for x in match.groups())
            start = datetime(day.year, day.month, day.day, sh, sm)
            end = datetime(day.year, day.month, day.day, eh, em)
            if end <= start:
                end += timedelta(days=1)

            for idx, td in enumerate(row.find_all("td")):
                if idx >= len(courts):
                    break
                klass = td.get("class") or []
                available = "volno" in klass
                slots.append(
                    Slot(
                        venue_id=self.venue_id,
                        venue_name=self.venue_name,
                        court=courts[idx],
                        start=start,
                        end=end,
                        available=available,
                        booking_url=day_booking_url,
                    )
                )
        return slots
