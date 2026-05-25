from __future__ import annotations

from ..base import BaseScraper
from .clubclassic import ClubClassicScraper
from .fit4all import Fit4AllScraper
from .memberzone import MemberzoneScraper
from .sportkuklenska import SportKuklenskaScraper


def all_scrapers() -> list[BaseScraper]:
    return [
        ClubClassicScraper(),
        MemberzoneScraper(),
        Fit4AllScraper(),
        SportKuklenskaScraper(),
    ]
