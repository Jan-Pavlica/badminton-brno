from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

from playwright.async_api import Page, async_playwright

from ..base import BaseScraper
from ..models import ScrapeResult, Slot

URL = "https://badmintonlisen.e-rezervace.cz/Branch/pages/Schedule.faces"
CELL_ID_RE = re.compile(r"^sched_(\d+)_i_(\d+)_(\d+)$")
DAY_HEADER_RE = re.compile(r"(\d{1,2})/(\d{1,2})")
TIME_HEADER_RE = re.compile(r"(\d{1,2}):(\d{2})")
NEXT_DAY_SELECTOR = '#scheduleNavigForm\\:j_id200'
CAL_INPUT_SELECTOR = '#scheduleNavigForm\\:schedule_calendarInputDate'


class BadmintonLisenScraper(BaseScraper):
    """Badminton Líšeň běží na stejné e-rezervace.cz JSF/RichFaces platformě
    jako Sport Kuklenská, ale defaultně zobrazuje jen 1 den. Pro pokrytí
    okna klikáme na šipku vpravo (advance o 1 den).
    """

    venue_id = "badmintonlisen"
    venue_name = "Badminton Líšeň"
    venue_url = URL
    timeout_seconds = 180

    async def fetch_window(self, start_date: date, days: int) -> ScrapeResult:
        scraped_at = datetime.now(timezone.utc)
        seen: set[tuple[date, int, int]] = set()
        slots: list[Slot] = []

        async with async_playwright() as p:
            browser = await p.chromium.launch()
            ctx = await browser.new_context(
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                locale="cs-CZ",
                viewport={"width": 2000, "height": 1400},
            )
            page = await ctx.new_page()
            try:
                await page.goto(URL, wait_until="networkidle", timeout=30000)
                await page.wait_for_function(
                    "() => document.querySelectorAll('#resContainer .event').length >= 0",
                    timeout=20000,
                )
                # Inicial: scrape den 0, pak klikat vpravo a scrapovat až do days
                for fetch_idx in range(days):
                    if fetch_idx > 0:
                        await self._click_next(page)
                    await page.wait_for_timeout(1200)
                    data = await self._extract(page)
                    courts = await self._extract_courts(page)
                    self._merge(data, courts, start_date, slots, seen)
            finally:
                await browser.close()

        return ScrapeResult(
            venue_id=self.venue_id,
            venue_name=self.venue_name,
            venue_url=self.venue_url,
            scraped_at=scraped_at,
            slots=slots,
        )

    async def _click_next(self, page: Page) -> None:
        current = await page.input_value(CAL_INPUT_SELECTOR)
        await page.click(NEXT_DAY_SELECTOR)
        try:
            await page.wait_for_function(
                "(prev) => { const el = document.getElementById('scheduleNavigForm:schedule_calendarInputDate');"
                " return el && el.value && el.value !== prev; }",
                arg=current,
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
                    cells.push({ id: c.id,
                        l: r.left + window.scrollX, t: r.top + window.scrollY,
                        r: r.right + window.scrollX, b: r.bottom + window.scrollY });
                });
                const events = [];
                document.querySelectorAll('#resContainer .event').forEach(e => {
                    const r = e.getBoundingClientRect();
                    events.push({
                        l: r.left + window.scrollX, t: r.top + window.scrollY,
                        r: r.right + window.scrollX, b: r.bottom + window.scrollY });
                });
                const days = [];
                for (let i = 0; ; i++) {
                    const t = document.getElementById('schedule_' + i);
                    if (!t) break;
                    days.push({ idx: i, label: t.querySelector('caption')?.textContent.trim() || '' });
                }
                const t0 = document.getElementById('schedule_0');
                const timeHeaders = Array.from(t0?.querySelectorAll('th.scheduleTimeHeader') || [])
                    .map(h => h.textContent.trim());
                return { cells, events, days, timeHeaders };
            }"""
        )

    @staticmethod
    async def _extract_courts(page: Page) -> list[str]:
        return await page.evaluate(
            """() => {
                const out = [];
                document.querySelectorAll('#schedule_0 .horizontalRowHeader p').forEach(p => {
                    out.push(p.textContent.trim());
                });
                return out;
            }"""
        )

    def _merge(
        self,
        data: dict,
        courts: list[str],
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
            dd, mm = int(m.group(1)), int(m.group(2))
            try:
                candidate = date(year, mm, dd)
            except ValueError:
                continue
            if (candidate - ref_date).days < -180:
                try:
                    candidate = date(year + 1, mm, dd)
                except ValueError:
                    pass
            day_dates[d["idx"]] = candidate

        if not day_dates:
            return

        # parsovat time headers — určí granularitu (30 vs 60 min) i offset
        time_grid: list[tuple[int, int]] = []
        for h in data.get("timeHeaders", []):
            m = TIME_HEADER_RE.search(h)
            if m:
                time_grid.append((int(m.group(1)), int(m.group(2))))
        if not time_grid:
            return
        if len(time_grid) >= 2:
            (h0, m0), (h1, m1) = time_grid[0], time_grid[1]
            slot_minutes = (h1 - h0) * 60 + (m1 - m0)
        else:
            slot_minutes = 60

        # eventy → busy cells přes překryv bboxů
        busy: set[str] = set()
        for ev in data["events"]:
            for c in data["cells"]:
                if (ev["l"] < c["r"] - 2 and ev["r"] > c["l"] + 2
                        and ev["t"] < c["b"] - 2 and ev["b"] > c["t"] + 2):
                    busy.add(c["id"])

        for c in data["cells"]:
            m = CELL_ID_RE.match(c["id"])
            if not m:
                continue
            sched_idx, row, col = int(m.group(1)), int(m.group(2)), int(m.group(3))
            day = day_dates.get(sched_idx)
            if day is None:
                continue
            if col >= len(time_grid):
                continue
            if row >= len(courts):
                continue
            hour, minute = time_grid[col]
            key = (day, row, col)
            if key in seen:
                continue
            seen.add(key)
            start = datetime(day.year, day.month, day.day, hour, minute)
            end = start + timedelta(minutes=slot_minutes)
            court_name = courts[row]
            if court_name and court_name[0].islower():
                court_name = court_name[:1].upper() + court_name[1:]
            slots.append(
                Slot(
                    venue_id=self.venue_id,
                    venue_name=self.venue_name,
                    court=court_name,
                    start=start,
                    end=end,
                    available=c["id"] not in busy,
                    booking_url=self.venue_url,
                )
            )
