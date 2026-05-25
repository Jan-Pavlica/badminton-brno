from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .models import ScrapeResult, Slot

CZ_WEEKDAYS = ["Po", "Út", "St", "Čt", "Pá", "So", "Ne"]

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = ROOT / "templates"

SLOT_MINUTES = 30
DAY_START_HOUR = 7
DAY_END_HOUR = 22


def _build_availability(
    slots_per_day: dict[str, list[Slot]],
    day_isos: list[str],
) -> dict:
    """Pro každý den, pro každé sportoviště, pro každý kurt — seřazený seznam
    minut (od půlnoci), na kterých je dostupný 30min slot.

    Z 60min slotů (memberzone, sportkuklenska) tím vyrobíme dvě 30min položky.
    """
    avail: dict[str, dict] = {iso: {} for iso in day_isos}
    for day_iso, slots in slots_per_day.items():
        if day_iso not in avail:
            continue
        for s in slots:
            if not s.available:
                continue
            venue_entry = avail[day_iso].setdefault(
                s.venue_name, {"url": s.booking_url, "courts": {}}
            )
            court_set = venue_entry["courts"].setdefault(s.court, set())
            slot_start = s.start.hour * 60 + s.start.minute
            slot_end = s.end.hour * 60 + s.end.minute
            for m in range(slot_start, slot_end, SLOT_MINUTES):
                court_set.add(m)

    # set → setřízený list pro JSON
    for day_iso in avail:
        for venue_name in avail[day_iso]:
            courts = avail[day_iso][venue_name]["courts"]
            for court in courts:
                courts[court] = sorted(courts[court])
    return avail


def render(
    results: list[ScrapeResult],
    start_date: date,
    days_count: int,
    out_dir: Path,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "data").mkdir(exist_ok=True)

    raw = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "start_date": start_date.isoformat(),
        "days": days_count,
        "venues": [r.to_dict() for r in results],
    }
    (out_dir / "data" / "slots.json").write_text(
        json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    days = []
    for i in range(days_count):
        d = start_date + timedelta(days=i)
        days.append(
            {
                "iso": d.isoformat(),
                "weekday": CZ_WEEKDAYS[d.weekday()],
                "short": d.strftime("%-d.%-m."),
                "full": d.strftime("%-d.%-m.%Y"),
            }
        )

    slots_per_day: dict[str, list[Slot]] = {d["iso"]: [] for d in days}
    for r in results:
        for s in r.slots:
            iso = s.start.date().isoformat()
            if iso in slots_per_day:
                slots_per_day[iso].append(s)

    availability = _build_availability(slots_per_day, [d["iso"] for d in days])

    weeks = [days[i : i + 7] for i in range(0, len(days), 7)]

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    template = env.get_template("index.html.j2")

    now_local = datetime.now().astimezone()
    rendered = template.render(
        scraped_at_human=now_local.strftime("%-d.%-m.%Y %H:%M"),
        venues_meta=[
            {
                "venue_id": r.venue_id,
                "venue_name": r.venue_name,
                "venue_url": r.venue_url,
                "error": r.error,
            }
            for r in results
        ],
        # předáváme raw dicty — Jinja `| tojson` v šabloně escapuje < > & ',
        # aby šly bezpečně do <script> i kdyby scrapovaná data obsahovala </script>
        availability=availability,
        weeks=weeks,
        day_start_hour=DAY_START_HOUR,
        day_end_hour=DAY_END_HOUR,
        slot_minutes=SLOT_MINUTES,
    )
    (out_dir / "index.html").write_text(rendered, encoding="utf-8")
