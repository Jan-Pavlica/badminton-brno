"""Explorační skript: otevře každou stránku, dump rendered HTML + screenshot.

Použití: python3 scripts/explore.py
"""
import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path("/tmp/site_dumps")
OUT.mkdir(exist_ok=True)


async def dump(p, name, url, wait_for=None, wait_seconds=4):
    browser = await p.chromium.launch()
    ctx = await browser.new_context()
    page = await ctx.new_page()
    print(f"\n=== {name} ===")
    print(f"URL: {url}")
    try:
        await page.goto(url, wait_until="networkidle", timeout=30000)
    except Exception as e:
        print(f"  goto failed: {e}")
    if wait_for:
        try:
            await page.wait_for_selector(wait_for, timeout=10000)
            print(f"  selector {wait_for} found")
        except Exception as e:
            print(f"  selector {wait_for} not found: {e}")
    await page.wait_for_timeout(wait_seconds * 1000)
    html = await page.content()
    (OUT / f"{name}.html").write_text(html, encoding="utf-8")
    print(f"  saved {len(html):,} chars to {OUT / name}.html")
    await page.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
    await browser.close()


async def main():
    async with async_playwright() as p:
        await dump(
            p,
            "memberzone",
            "https://memberzone.cz/sprint_tenis/Sportoviste.aspx?ID_Sportoviste=3&NAZEV=Badminton%20hala",
            wait_for="table, .dxsc-scheduler, [id*='Scheduler']",
        )
        await dump(
            p,
            "fit4all",
            "https://www.fit4all.cz/cs/online-rezervace?activity=6&date=2026-05-25",
            wait_for="table, .reservation-table, .slots",
        )
        await dump(
            p,
            "sportkuklenska",
            "https://sportkuklenska.e-rezervace.cz/Branch/pages/Schedule.faces",
            wait_for="table, .schedule, [class*='Schedule']",
        )


if __name__ == "__main__":
    asyncio.run(main())
