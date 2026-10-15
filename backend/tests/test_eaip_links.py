"""0.12.3: adresy eAIP PAŻP (AD CIV / AD MIL / AD VFR) idą za cyklem AIRAC. Bez POLIDS_AIP_*_URL katalog poprawki
liczy się z cyklu na dziś (UTC), więc po 29.10.2026 zakładki nie pokazują po cichu starej poprawki 10-26."""
import os
import tempfile
from datetime import date

os.environ.setdefault("POLIDS_DATABASE_URL", "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test.db").replace("\\", "/"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.app import main  # noqa: E402
from backend.app.config import settings  # noqa: E402
from backend.app.services import eaip, embed  # noqa: E402
from backend.app.services.airac import current_airac  # noqa: E402

PANSA = "https://docs.pansa.pl/ais/"


def folders(day):
    return {k: v.removeprefix(PANSA) for k, v in eaip.aip_links(day).items()}


@pytest.fixture(autouse=True)
def no_override(monkeypatch):
    """Lokalny .env programisty nie wpływa na wynik: bez adresów z .env."""
    for link in eaip.PACKAGES:
        monkeypatch.setattr(settings, f"{link}_url", "")


def test_cycle_2610():
    # pierwszy i ostatni dzień cyklu (wejście 01.10.2026, następny 29.10.2026)
    for day in (date(2026, 10, 1), date(2026, 10, 15), date(2026, 10, 28)):
        assert folders(day) == {
            "aip_ifr": "eaipifr/AIRAC%20AMDT%2010-26_2026_10_01/index-v2.html",
            "aip_vfr": "eaipvfr/AIRAC%20AMDT%20VFR%2010-26_2026_10_01/index-v2.html",
            "aip_mil": "eaipmil/AIRAC%20AMDT%20MIL%2010-26_2026_10_01/index-v2.html",
        }


def test_cycle_2611():
    assert current_airac(date(2026, 10, 29))["ident"] == "2611"
    assert folders(date(2026, 10, 29)) == {
        "aip_ifr": "eaipifr/AIRAC%20AMDT%2011-26_2026_10_29/index-v2.html",
        "aip_vfr": "eaipvfr/AIRAC%20AMDT%20VFR%2011-26_2026_10_29/index-v2.html",
        "aip_mil": "eaipmil/AIRAC%20AMDT%20MIL%2011-26_2026_10_29/index-v2.html",
    }


def test_cycle_2601_and_year_change():
    assert folders(date(2026, 1, 22))["aip_ifr"] == "eaipifr/AIRAC%20AMDT%2001-26_2026_01_22/index-v2.html"
    # dzień wcześniej: ostatni cykl 2025 (2513 od 25.12.2025)
    assert folders(date(2026, 1, 21))["aip_mil"] == "eaipmil/AIRAC%20AMDT%20MIL%2013-25_2025_12_25/index-v2.html"
    # poprawka sprzed roku znaleziona w sieci: AIRAC AMDT 05-25_2025_05_15
    assert folders(date(2025, 5, 20))["aip_ifr"] == "eaipifr/AIRAC%20AMDT%2005-25_2025_05_15/index-v2.html"


def test_env_override_wins_unchanged(monkeypatch):
    own = "https://docs.pansa.pl/ais/eaipifr/AIRAC%20AMDT%2009-26_2026_09_03/index-v2.html"
    monkeypatch.setattr(settings, "aip_ifr_url", f"  {own} ")
    links = eaip.aip_links(date(2026, 11, 30))
    assert links["aip_ifr"] == own
    # pozostałe dwa bez wpisu w .env dalej liczone z cyklu
    assert links["aip_vfr"].endswith("AIRAC%20AMDT%20VFR%2012-26_2026_11_26/index-v2.html")


def test_utc_today_is_utc():
    assert eaip.utc_today() == eaip.datetime.now(eaip.timezone.utc).date()


def test_config_and_embed_check_follow_cycle(monkeypatch):
    """/api/config liczy adresy przy każdym zapytaniu (nowy cykl bez restartu), embed-check sprawdza ten sam adres."""
    client = TestClient(main.app)
    day = {"d": date(2026, 10, 28)}
    monkeypatch.setattr(eaip, "utc_today", lambda: day["d"])
    cfg = client.get("/api/config").json()
    assert cfg["airac"] == {"ident": "2610", "effective": "2026-10-01", "next": "2026-10-29"}
    assert cfg["links"]["aip_ifr"] == PANSA + "eaipifr/AIRAC%20AMDT%2010-26_2026_10_01/index-v2.html"
    day["d"] = date(2026, 10, 29)
    cfg = client.get("/api/config").json()
    assert cfg["airac"]["ident"] == "2611"
    assert cfg["links"]["aip_mil"] == PANSA + "eaipmil/AIRAC%20AMDT%20MIL%2011-26_2026_10_29/index-v2.html"
    assert cfg["links"]["inop"].startswith("https://om.plvacc.pl")

    checked = []

    async def fake_check(url, ttl=3600):
        checked.append(url)
        return {"url": url, "embeddable": True, "reason": ""}

    monkeypatch.setattr(embed, "check", fake_check)
    for link in ("aip_ifr", "aip_vfr", "aip_mil", "inop"):
        assert client.get(f"/api/embed-check/{link}").status_code == 200
    assert checked == [cfg["links"][k] for k in ("aip_ifr", "aip_vfr", "aip_mil", "inop")]
    monkeypatch.setattr(settings, "aip_vfr_url", "https://example.test/vfr/index-v2.html")
    assert client.get("/api/embed-check/aip_vfr").json()["url"] == "https://example.test/vfr/index-v2.html"
    assert client.get("/api/config").json()["links"]["aip_vfr"] == "https://example.test/vfr/index-v2.html"
    assert client.get("/api/embed-check/nieznany").status_code == 404
