from __future__ import annotations

import asyncio
import logging
from datetime import date
from pathlib import Path

from .render import render
from .sites import all_scrapers

DAYS = 14

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("scraper")


async def run_all(start_date: date, days: int) -> list:
    scrapers = all_scrapers()
    log.info("Running %d scrapers for %d days from %s", len(scrapers), days, start_date)
    results = await asyncio.gather(*(s.run(start_date, days) for s in scrapers))
    for r in results:
        if r.error:
            log.warning("  %s: ERROR — %s", r.venue_id, r.error)
        else:
            log.info("  %s: %d slots", r.venue_id, len(r.slots))
    return results


def main() -> None:
    today = date.today()
    results = asyncio.run(run_all(today, DAYS))
    out_dir = Path(__file__).resolve().parents[2] / "site"
    render(results, today, DAYS, out_dir)
    log.info("Output written to %s", out_dir)


if __name__ == "__main__":
    main()
