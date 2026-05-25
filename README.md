# Badminton Brno — přehled volných kapacit

Statický web s dvoutýdenním přehledem volných slotů na badmintonových kurtech v Brně.
Data se obnovují každých 10 minut přes GitHub Actions a publikují na GitHub Pages.

Rozsah okna se řídí konstantou `DAYS` v `src/scraper/main.py`. Scrapery sportovišť, která veřejně
zobrazují jen jeden týden (memberzone, sportkuklenska), si na další týden samy nakliknou.

## Zdroje

| ID | Sportoviště | Stav | Poznámka |
|---|---|---|---|
| `clubclassic` | Club Classic | ✅ | Server-rendered, 30min granularita; proklik vede na denní přehled (rezervační formulář vyžaduje login) |
| `memberzone` | Sprint Tenis (Badminton hala) | ✅ | Tabulka `tableLekce` vystavuje explicitně dostupné rezervační varianty (čas + kurty); cokoli neuvedené **není** volné |
| `fit4all` | Fit4All | ✅ | 30min sloty, 4 kurty |
| `sportkuklenska` | Sport Kuklenská | ✅ | JSF schedule, hodinové sloty, 4 kurty. Rezervace jsou modré `.event` divy nad mřížkou — mapujeme přes překryv bounding boxů |
| `centrumviktoria` | Centrum Viktoria | ✅ | Java aplikace, 3 kurty, jen explicitně volné sloty (z `<a class="book">` anchorů). Datum přes `?criteriaTimestamp=<ms>` |
| `badmintonlisen` | Badminton Líšeň | ✅ | Stejná e-rezervace.cz platforma jako Kuklenská, ale 30min granularita a defaultní 1-day view → klikáme šipkou vpravo (1 den/klik) |

## Lokální spuštění

```bash
# vytvoř venv (Ubuntu/Debian: nejprve `apt install python3-venv`)
python3 -m venv .venv
source .venv/bin/activate

pip install -e .
python -m playwright install chromium
# Pokud Chromium nenastartuje (chybí systémové knihovny), zkus:
#   python -m playwright install --with-deps chromium
# To vyžaduje fungující `apt` (žádné rozbité PPA).

PYTHONPATH=src python -m scraper.main
python -m http.server -d site 8000   # otevři http://localhost:8000
```

Výstupy:
- `site/index.html` — týdenní mřížka + per-day detaily
- `site/data/slots.json` — raw data všech zdrojů

## Architektura

```
src/scraper/
├── models.py          # Slot, ScrapeResult
├── base.py            # BaseScraper (abstract + run() s timeout + error capture)
├── render.py          # Jinja2 → site/
├── main.py            # asyncio.gather všech scraperů
└── sites/
    ├── __init__.py    # registr: all_scrapers()
    ├── clubclassic.py
    ├── memberzone.py
    ├── fit4all.py
    └── sportkuklenska.py
```

Každý scraper rozšiřuje `BaseScraper` a implementuje `async def fetch_week(start_date) -> ScrapeResult`.
Pokud scraper hodí výjimku nebo překročí `timeout_seconds`, `BaseScraper.run()` ji zachytí a vrátí
`ScrapeResult` s vyplněným `error`. Tj. selhání jednoho zdroje neshodí ostatní.

## Přidání nového sportoviště

1. Vytvoř `src/scraper/sites/<name>.py` s třídou, která rozšiřuje `BaseScraper`:
   ```python
   class NewScraper(BaseScraper):
       venue_id = "new"
       venue_name = "Nové sportoviště"
       venue_url = "https://..."
       async def fetch_week(self, start_date): ...
   ```
2. Přidej ji do `all_scrapers()` v `src/scraper/sites/__init__.py`.
3. Pokud potřebuješ Playwright (dynamic JS), použij `async_playwright()` jako v `memberzone.py`/`fit4all.py`.
   Statické stránky stačí `httpx` (viz `clubclassic.py`).
4. Pro průzkum struktury použij `scripts/explore.py`.

## Deployment

GitHub Actions workflow `.github/workflows/scrape.yml`:
- spouští se `*/10 * * * *` (každých 10 min — GitHub může v peaku zpozdit o 5–15 min)
- také na `workflow_dispatch` (manuál) a `push` do `main` (po změně kódu)
- buildí `site/` a force-pushe na branch `gh-pages` přes `peaceiris/actions-gh-pages`
- výstup: `https://<user>.github.io/<repo>/`

### Předpoklady pro hosting

1. **Public repo** — kvůli unlimited GitHub Actions minutám (private má 2000 min/měsíc).
2. **Pages settings**: Settings → Pages → Source: `gh-pages` branch / `/ (root)`.
3. **Workflow permissions**: Settings → Actions → General → Workflow permissions = "Read and write".

## Limitace a vědomé kompromisy

- **memberzone** vystavuje veřejně jen seznam dostupných variant; obsazené sloty ani zavřené hodiny nejsou viditelné jako takové.
- **sportkuklenska** používá pixelové překryvy event-divů přes mřížku — pokud se v JSF/RichFaces změní layout (např. odlišná výška/šířka cell), je nutné upravit toleranci v `_build_slots`.
- GitHub Actions cron není přesný; reálný interval bývá 10–25 min.
- Žádná databáze; data jsou snapshot, historie se neukládá.
