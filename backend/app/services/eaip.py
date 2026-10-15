"""Adresy eAIP PAŻP (IFR, VFR, MIL) dla bieżącego cyklu AIRAC.

PAŻP publikuje każdą poprawkę AIRAC w osobnym katalogu, np. eaipifr/AIRAC AMDT 10-26_2026_10_01/index-v2.html
(numer cyklu w roku, rok, data wejścia w życie). Stare katalogi zostają na serwerze, więc stały adres po zmianie cyklu
nie daje błędu, tylko po cichu pokazuje nieaktualną poprawkę. Dlatego bez POLIDS_AIP_*_URL w .env adres jest liczony
przy każdym zapytaniu z cyklu na dziś (UTC: AIRAC zmienia się o 00:00 UTC), a jawny adres z .env wygrywa bez zmian."""

from datetime import date, datetime, timezone

from ..config import settings
from .airac import current_airac

BASE = "https://docs.pansa.pl/ais"
# klucz linku w /api/config -> (katalog eAIP, wstawka w nazwie poprawki)
PACKAGES = {"aip_ifr": ("eaipifr", ""), "aip_vfr": ("eaipvfr", "VFR%20"), "aip_mil": ("eaipmil", "MIL%20")}


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


def package_url(link: str, airac: dict) -> str:
    """index-v2.html poprawki dla cyklu z current_airac(): ident "2610" -> AMDT 10-26, data wejścia 2026-10-01."""
    folder, infix = PACKAGES[link]
    ident = airac["ident"]
    return (f"{BASE}/{folder}/AIRAC%20AMDT%20{infix}{ident[2:]}-{ident[:2]}_{airac['effective'].replace('-', '_')}"
            "/index-v2.html")


def aip_url(link: str, today: date | None = None) -> str:
    """Adres z .env (POLIDS_AIP_IFR_URL itd.), a bez niego liczony z cyklu AIRAC na dziś (UTC)."""
    override = (getattr(settings, f"{link}_url") or "").strip()
    return override or package_url(link, current_airac(today or utc_today()))


def aip_links(today: date | None = None) -> dict[str, str]:
    today = today or utc_today()
    return {link: aip_url(link, today) for link in PACKAGES}
