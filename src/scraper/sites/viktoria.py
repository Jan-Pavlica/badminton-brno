from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta, timezone

from playwright.async_api import async_playwright

from ..base import BaseScraper
from ..models import ScrapeResult, Slot

BASE_URL = "https://rezervace.centrumviktoria.cz:18443/timeline/day"
BADMINTON_CLASS = "c_08"   # CSS třída span.activity pro badminton
SLOT_MINUTES = 30
PARALLELISM = 3   # paralelní záložky v jednom contextu


class CentrumViktoriaScraper(BaseScraper):
    """Centrum Viktoria má Java-aplikaci s `/timeline/day?criteriaTimestamp=<ms>`.
    Stránka explicitně zobrazuje JEN bookable sloty (jako `<a class="book">`
    s `objectId`, `sportId`, `reservationStartTime` v hrefu). Cokoli neuvedené
    NENÍ volné. Filtrujeme objectId na seznam badmintonových kurtů (zjištěn
    ze sidebar `li.activity.c_08`).
    """

    venue_id = "centrumviktoria"
    venue_name = "Centrum Viktoria"
    venue_url = BASE_URL
    timeout_seconds = 180

    async def fetch_window(self, start_date: date, days: int) -> ScrapeResult:
        scraped_at = datetime.now(timezone.utc)
        slots: list[Slot] = []

        async with async_playwright() as p:
            browser = await p.chromium.launch()
            ctx = await browser.new_context(
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                locale="cs-CZ",
                viewport={"width": 1800, "height": 1200},
                ignore_https_errors=True,
            )
            try:
                sem = asyncio.Semaphore(PARALLELISM)

                async def fetch_one(day: date) -> list[Slot] | Exception:
                    async with sem:
                        page = await ctx.new_page()
                        try:
                            ts = self._noon_ms(day)
                            url = f"{BASE_URL}?criteriaTimestamp={ts}"
                            resp = await page.goto(url, wait_until="networkidle", timeout=25000)
                            if resp and resp.status >= 400:
                                return RuntimeError(f"HTTP {resp.status} for {url}")
                            await page.wait_for_selector("li.activity, .activity", timeout=10000)
                            data = await self._extract(page)
                            return self._build_slots(data, day)
                        except Exception as e:
                            return e
                        finally:
                            await page.close()

                results = await asyncio.gather(
                    *(fetch_one(start_date + timedelta(days=i)) for i in range(days))
                )
                errors: list[str] = []
                for r in results:
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

    @staticmethod
    def _noon_ms(day: date) -> int:
        # 12:00 lokálního času konkrétního dne → ms timestamp
        noon = datetime.combine(day, time(12, 0))
        return int(noon.timestamp() * 1000)

    @staticmethod
    async def _extract(page) -> dict:
        return await page.evaluate(
            r"""() => {
                // sidebar — uuid → název pro badmintonové kurty
                const courts = [];
                document.querySelectorAll('li.disabled, li[id^=activity_hall_]').forEach(act => {
                    if (act.querySelector('.activity.""" + BADMINTON_CLASS + r"""')) {
                        act.querySelectorAll('li.hall').forEach(c => {
                            const id = c.id || '';
                            const parts = id.split('_');
                            const uuid = parts[parts.length - 1];
                            courts.push({ uuid, name: c.textContent.trim() });
                        });
                    }
                });
                // všechny anchory s reservationStartTime
                const slots = [];
                document.querySelectorAll('a.book, a.ajax_popup_trigger').forEach(a => {
                    const href = a.getAttribute('href') || '';
                    const obj = href.match(/objectId\/([a-f0-9]+)/)?.[1];
                    const t = href.match(/reservationStartTime\/([0-9T:.+-]+)/)?.[1];
                    if (obj && t) slots.push({ obj, t });
                });
                return { courts, slots };
            }"""
        )

    def _build_slots(self, data: dict, day: date) -> list[Slot]:
        court_by_uuid = {c["uuid"]: c["name"] for c in data["courts"]}
        if not court_by_uuid:
            return []
        ts = self._noon_ms(day)
        day_url = f"{BASE_URL}?criteriaTimestamp={ts}"
        out: list[Slot] = []
        seen: set[tuple[datetime, str]] = set()
        for s in data["slots"]:
            uuid = s["obj"]
            if uuid not in court_by_uuid:
                continue
            try:
                start_tz = datetime.fromisoformat(s["t"])
            except ValueError:
                continue
            start = start_tz.replace(tzinfo=None)
            if start.date() != day:
                continue
            key = (start, uuid)
            if key in seen:
                continue
            seen.add(key)
            end = start + timedelta(minutes=SLOT_MINUTES)
            out.append(
                Slot(
                    venue_id=self.venue_id,
                    venue_name=self.venue_name,
                    court=court_by_uuid[uuid],
                    start=start,
                    end=end,
                    available=True,
                    booking_url=day_url,
                )
            )
        return out
