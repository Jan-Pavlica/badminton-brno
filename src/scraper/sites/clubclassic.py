from __future__ import annotations

import asyncio
import re
from datetime import date, datetime, timedelta, timezone

import httpx
from bs4 import BeautifulSoup

from ..base import BaseScraper
from ..models import ScrapeResult, Slot

BASE = "https://rezervace.clubclassic.cz/"
DAY_URL = BASE + "index.php?page=day_overview&id=22&date={date}"

TIME_RE = re.compile(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})")


class ClubClassicScraper(BaseScraper):
    venue_id = "clubclassic"
    venue_name = "Club Classic"
    venue_url = BASE + "?page=day_overview&id=22"

    async def fetch_window(self, start_date: date, days: int) -> ScrapeResult:
        scraped_at = datetime.now(timezone.utc)
        slots: list[Slot] = []

        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            tasks = [self._fetch_day(client, start_date + timedelta(days=i)) for i in range(days)]
            day_results = await asyncio.gather(*tasks, return_exceptions=True)

        for r in day_results:
            if isinstance(r, Exception):
                continue
            slots.extend(r)

        return ScrapeResult(
            venue_id=self.venue_id,
            venue_name=self.venue_name,
            venue_url=self.venue_url,
            scraped_at=scraped_at,
            slots=slots,
        )

    async def _fetch_day(self, client: httpx.AsyncClient, day: date) -> list[Slot]:
        url = DAY_URL.format(date=day.isoformat())
        resp = await client.get(url)
        resp.raise_for_status()
        return self._parse_day(resp.text, day)

    def _parse_day(self, html: str, day: date) -> list[Slot]:
        soup = BeautifulSoup(html, "lxml")
        table = soup.find("table", class_="denni-prehled")
        if not table:
            return []

        header_cells = table.find("tr").find_all("th")
        courts = [c.get_text(strip=True) for c in header_cells[1:]]

        # proklik vede vždy jen na denní přehled (rezervační formulář vyžaduje login)
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
