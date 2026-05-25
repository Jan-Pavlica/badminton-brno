from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta, timezone

from bs4 import BeautifulSoup
from playwright.async_api import Page, async_playwright

from ..base import BaseScraper
from ..models import ScrapeResult, Slot

URL = "https://memberzone.cz/sprint_tenis/Sportoviste.aspx?ID_Sportoviste=3&NAZEV=Badminton%20hala"
COURT_RE = re.compile(r"Badminton kurt č\.\d")
TIME_RE = re.compile(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})")
DATE_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.?")


class MemberzoneScraper(BaseScraper):
    """Stránka veřejně vystavuje pouze tabulku `tableLekce`, kde každý řádek
    představuje konkrétní volnou rezervační variantu (časový rozsah + seznam
    dostupných kurtů). Cokoli, co v tabulce není, NENÍ automaticky volné.

    Stránka zobrazuje vždy jeden týden (Po–Ne). Pro delší okno měníme datum
    skrz `input#myDate` a re-scrapujeme tabulku.
    """

    venue_id = "memberzone"
    venue_name = "Sprint Tenis (Badminton hala)"
    venue_url = URL
    timeout_seconds = 120

    async def fetch_window(self, start_date: date, days: int) -> ScrapeResult:
        scraped_at = datetime.now(timezone.utc)
        weeks_needed = max(1, math.ceil((start_date.weekday() + days) / 7))

        seen: set[tuple[date, datetime, datetime, str]] = set()
        slots: list[Slot] = []

        async with async_playwright() as p:
            browser = await p.chromium.launch()
            ctx = await browser.new_context(
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = await ctx.new_page()
            try:
                await page.goto(URL, wait_until="networkidle", timeout=30000)
                await page.wait_for_selector("table#tableLekce", timeout=15000)

                for week_idx in range(weeks_needed):
                    target = start_date + timedelta(days=7 * week_idx)
                    if week_idx > 0:
                        await self._navigate_to(page, target)
                    html = await page.content()
                    for slot in self._parse(html, target, seen):
                        slots.append(slot)
            finally:
                await browser.close()

        return ScrapeResult(
            venue_id=self.venue_id,
            venue_name=self.venue_name,
            venue_url=self.venue_url,
            scraped_at=scraped_at,
            slots=slots,
        )

    async def _navigate_to(self, page: Page, target: date) -> None:
        await page.fill("input#myDate", target.isoformat())
        await page.dispatch_event("input#myDate", "change")
        # Tabulka se přerendruje; čekáme až hlavička obsahuje měsíc cílového data.
        expected_md = f"{target.day}.{target.month}."
        try:
            await page.wait_for_function(
                "([md]) => { const t = document.getElementById('tableLekce');"
                " return t && t.innerText.includes(md); }",
                arg=[expected_md],
                timeout=10000,
            )
        except Exception:
            # fallback: prostě počkat
            await page.wait_for_timeout(2000)

    def _parse(
        self,
        html: str,
        target: date,
        seen: set[tuple[date, datetime, datetime, str]],
    ) -> list[Slot]:
        soup = BeautifulSoup(html, "lxml")
        table = soup.find("table", id="tableLekce")
        if not table:
            return []
        rows = table.find_all("tr")
        if not rows:
            return []

        day_dates = self._parse_day_headers(
            rows[0].find_all(["td", "th"]), target
        )

        slots: list[Slot] = []
        for row in rows[1:]:
            tds = row.find_all("td")
            for col_idx, td in enumerate(tds):
                if col_idx >= len(day_dates) or day_dates[col_idx] is None:
                    continue
                text = td.get_text(" ", strip=True)
                if not text:
                    continue
                tm = TIME_RE.search(text)
                if not tm:
                    continue
                sh, sm, eh, em = (int(x) for x in tm.groups())
                day = day_dates[col_idx]
                start = datetime(day.year, day.month, day.day, sh, sm)
                end = datetime(day.year, day.month, day.day, eh, em)
                if end <= start:
                    continue
                for court in COURT_RE.findall(text):
                    key = (day, start, end, court)
                    if key in seen:
                        continue
                    seen.add(key)
                    slots.append(
                        Slot(
                            venue_id=self.venue_id,
                            venue_name=self.venue_name,
                            court=court,
                            start=start,
                            end=end,
                            available=True,
                            booking_url=self.venue_url,
                        )
                    )
        return slots

    @staticmethod
    def _parse_day_headers(cells, ref: date) -> list[date | None]:
        out: list[date | None] = []
        for cell in cells:
            m = DATE_RE.search(cell.get_text(" ", strip=True))
            if not m:
                out.append(None)
                continue
            d, mo = int(m.group(1)), int(m.group(2))
            year = ref.year
            try:
                candidate = date(year, mo, d)
            except ValueError:
                out.append(None)
                continue
            # přes přelom roku
            if (candidate - ref).days < -180:
                try:
                    candidate = date(year + 1, mo, d)
                except ValueError:
                    pass
            elif (candidate - ref).days > 180:
                try:
                    candidate = date(year - 1, mo, d)
                except ValueError:
                    pass
            out.append(candidate)
        return out
