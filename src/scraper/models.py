from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Slot:
    venue_id: str
    venue_name: str
    court: str
    start: datetime
    end: datetime
    available: bool
    booking_url: str

    def to_dict(self) -> dict:
        return {
            "venue_id": self.venue_id,
            "venue_name": self.venue_name,
            "court": self.court,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "available": self.available,
            "booking_url": self.booking_url,
        }


@dataclass
class ScrapeResult:
    venue_id: str
    venue_name: str
    venue_url: str
    scraped_at: datetime
    slots: list[Slot] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "venue_id": self.venue_id,
            "venue_name": self.venue_name,
            "venue_url": self.venue_url,
            "scraped_at": self.scraped_at.isoformat(),
            "error": self.error,
            "slots": [s.to_dict() for s in self.slots],
        }
