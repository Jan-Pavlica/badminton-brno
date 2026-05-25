from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta, timezone

from playwright.async_api import Page, async_playwright

from ..base import BaseScraper
from ..models import ScrapeResult, Slot

URL = "https://sportkuklenska.e-rezervace.cz/Branch/pages/Schedule.faces"
CELL_ID_RE = re.compile(r"^sched_(\d+)_i_(\d+)_(\d+)$")
DAY_HEADER_RE = re.compile(r"(\d{1,2})/(\d{1,2})")
NEXT_WEEK_SELECTOR = '#scheduleNavigForm\\:j_id200'  # šipka vpravo (rarr.png)

START_HOUR = 7
SLOT_MINUTES = 60
COURT_COUNT = 4


class SportKuklenskaScraper(BaseScraper):
    """Sport Kuklenská (JSF/RichFaces). Stránka zobrazuje ~8 dní začínajících
    pondělím aktuálního týdne. Rezervace jsou modré `.event` divy absolutně
    umístěné nad mřížkou — mapujeme přes překryv bounding boxů s `td.scheduleCell`.

    Pro delší okno klikáme na šipku vpravo a re-scrapujeme.
    """

    venue_id = "sportkuklenska"
    venue_name = "Sport Kuklenská"
    venue_url = URL
    timeout_seconds = 120

    async def fetch_window(self, start_date: date, days: int) -> ScrapeResult:
        scraped_at = datetime.now(timezone.utc)
        # každý fetch pokryje 8 dní začínajících pondělím; ale stránka po kliknutí
        # posune o 7 dní (další pondělí). Pro pokrytí (weekday + days) dní stačí
        # ceil((weekday + days) / 7) fetchů.
        fetches = max(1, math.ceil((start_date.weekday() + days) / 7))

        seen: set[tuple[date, int, int]] = set()
        slots: list[Slot] = []

        async with async_playwright() as p:
            browser = await p.chromium.launch()
            ctx = await browser.new_context(
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                locale="cs-CZ",
                viewport={"width": 2000, "height": 1400},
            )
            page = await ctx.new_page()
            try:
                await page.goto(URL, wait_until="networkidle", timeout=30000)
                await page.wait_for_function(
                    "() => document.querySelectorAll('#resContainer .event').length > 0",
                    timeout=20000,
                )

                for fetch_idx in range(fetches):
                    if fetch_idx > 0:
                        await self._click_next_week(page)
                    await page.wait_for_timeout(1500)
                    data = await self._extract(page)
                    self._merge_slots(data, start_date, slots, seen)
            finally:
                await browser.close()

        return ScrapeResult(
            venue_id=self.venue_id,
            venue_name=self.venue_name,
            venue_url=self.venue_url,
            scraped_at=scraped_at,
            slots=slots,
        )

    async def _click_next_week(self, page: Page) -> None:
        # zaznamenat aktuální datum v inputu kalendáře, počkat než se změní
        current = await page.input_value("#scheduleNavigForm\\:schedule_calendarInputDate")
        await page.click(NEXT_WEEK_SELECTOR)
        try:
            await page.wait_for_function(
                "(prev) => { const el = document.getElementById('scheduleNavigForm:schedule_calendarInputDate');"
                " return el && el.value && el.value !== prev; }",
                arg=current,
                timeout=10000,
            )
        except Exception:
            pass
        # počkat na re-render eventů
        try:
            await page.wait_for_function(
                "() => document.querySelectorAll('#resContainer .event').length >= 0",
                timeout=10000,
            )
        except Exception:
            pass

    @staticmethod
    async def _extract(page: Page) -> dict:
        return await page.evaluate(
            """() => {
                const cells = [];
                document.querySelectorAll('td.scheduleCell').forEach(c => {
                    const r = c.getBoundingClientRect();
                    cells.push({
                        id: c.id,
                        l: r.left + window.scrollX,
                        t: r.top + window.scrollY,
                        r: r.right + window.scrollX,
                        b: r.bottom + window.scrollY,
                    });
                });
                const events = [];
                document.querySelectorAll('#resContainer .event').forEach(e => {
                    const r = e.getBoundingClientRect();
                    events.push({
                        l: r.left + window.scrollX,
                        t: r.top + window.scrollY,
                        r: r.right + window.scrollX,
                        b: r.bottom + window.scrollY,
                    });
                });
                const days = [];
                for (let i = 0; ; i++) {
                    const t = document.getElementById('schedule_' + i);
                    if (!t) break;
                    const cap = t.querySelector('caption .date, caption');
                    days.push({ idx: i, label: cap ? cap.textContent.trim() : '' });
                }
                return { cells, events, days };
            }"""
        )

    def _merge_slots(
        self,
        data: dict,
        ref_date: date,
        slots: list[Slot],
        seen: set[tuple[date, int, int]],
    ) -> None:
        day_dates: dict[int, date] = {}
        year = ref_date.year
        for d in data["days"]:
            m = DAY_HEADER_RE.search(d["label"])
            if not m:
                continue
            day, month = int(m.group(1)), int(m.group(2))
            try:
                candidate = date(year, month, day)
            except ValueError:
                continue
            # přes přelom roku
            if (candidate - ref_date).days < -180:
                try:
                    candidate = date(year + 1, month, day)
                except ValueError:
                    pass
            day_dates[d["idx"]] = candidate

        if not day_dates:
            return

        busy_cell_ids: set[str] = set()
        for ev in data["events"]:
            for c in data["cells"]:
                if (
                    ev["l"] < c["r"] - 2
                    and ev["r"] > c["l"] + 2
                    and ev["t"] < c["b"] - 2
                    and ev["b"] > c["t"] + 2
                ):
                    busy_cell_ids.add(c["id"])

        for c in data["cells"]:
            m = CELL_ID_RE.match(c["id"])
            if not m:
                continue
            sched_idx, row, col = int(m.group(1)), int(m.group(2)), int(m.group(3))
            day = day_dates.get(sched_idx)
            if day is None or row >= COURT_COUNT:
                continue
            key = (day, row, col)
            if key in seen:
                continue
            seen.add(key)
            hour = START_HOUR + col
            start = datetime(day.year, day.month, day.day, hour, 0)
            end = start + timedelta(minutes=SLOT_MINUTES)
            slots.append(
                Slot(
                    venue_id=self.venue_id,
                    venue_name=self.venue_name,
                    court=f"Kurt {row + 1}",
                    start=start,
                    end=end,
                    available=c["id"] not in busy_cell_ids,
                    booking_url=self.venue_url,
                )
            )
