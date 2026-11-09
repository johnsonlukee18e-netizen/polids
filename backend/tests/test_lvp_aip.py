"""0.13.2 (issue #27): progi LVP każdego lotniska porównane z eAIP PAŻP AIRAC AMDT 11-26 (29.10.2026) i ocena METAR
na granicach progów: przygotowanie, wprowadzenie, odwołanie (histereza), najniższy RVR, widzialność tylko bez RVR,
podstawa BKN/OVC/VV bez wartości, lotniska bez LVP (DEFAULT)."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from backend.app.config import settings
from backend.app.services import lvp
from backend.app.services.metar import parse_metar

UTC = timezone.utc

# Niezależny zapis tekstu AIP (operator i wartość jak w zdaniu AIP): (RVR, ceiling) dla przygotowania, wprowadzenia
# i odwołania; przygotowanie i wprowadzenie "or" ("and/or"), odwołanie "and" ("and/or" w AIP liczone jako "and").
# EPWA: tekst AD 2.22 z AMDT 10-26 (strona eAIP EPWA za duża, nie sprawdzona ponownie w 11-26).
AIP_CIV = {
    "EPWA": (None, ("<", 550, "<", 200), (">", 550, ">=", 200)),            # 7.1.2.1-7.1.2.2
    "EPPO": (("<=", 800, "<=", 300), ("<", 550, "<", 200), (">", 550, ">", 200)),       # 6.2.1-6.2.3
    # EPMO 5.2.1-5.2.3: wprowadzenie przy podstawie "at 200 ft or lower" (akapit numerowany)
    "EPMO": (("<=", 800, "<=", 300), ("<", 550, "<=", 200), (">=", 600, ">=", 200)),
    "EPLL": (None, ("<", 550, "<", 200), (">=", 550, ">=", 200)),           # 6.2-6.3
    "EPSY": (None, ("<", 550, "<=", 200), (">=", 550, ">", 200)),           # 4.2.1-4.2.2 ("to 200 ft or below")
    "EPKK": (None, ("<", 550, "<=", 200), (">=", 550, ">", 200)),           # 6.2.1-6.2.2
    "EPKT": (("<=", 800, "<=", 300), ("<", 550, "<", 200), (">=", 600, ">=", 200)),     # 5.2.1-5.2.3
    "EPRZ": (("<=", 800, "<=", 300), ("<", 550, "<", 200), (">=", 600, ">=", 200)),     # 4.1.1-4.1.4.1
    "EPLB": (("<=", 800, "<=", 300), ("<", 550, "<=", 200), (">=", 600, ">", 200)),     # 5.1.1-5.1.3
    "EPWR": (("<=", 800, "<=", 300), ("<", 550, "<", 200), (">", 600, ">=", 200)),      # 5.1.2.1-5.1.2.3
    "EPGD": (None, ("<", 550, "<=", 200), (">=", 600, ">=", 200)),          # 6.0.2.1-6.0.2.2
    "EPSC": (None, ("<", 550, "<=", 200), (">=", 550, ">", 200)),           # 7.3-7.4
    "EPBY": (None, ("<", 550, "<=", 200), (">=", 550, ">", 200)),           # 6.3-6.4
}
# AIP MIL AD 4.20: tylko odloty; VIS (odpowiednik RVR): przygotowanie "decreases to 1200 m (RVR - 800 m)",
# wprowadzenie "falls to 800 m (RVR - 550 m) or less", odwołanie "increases to 800 m or more (RVR - 550 m)"
AIP_MIL = ("EPKS", "EPMB", "EPMI", "EPPW", "EPSN")
MIL = (("<=", 1200, 800), ("<=", 800, 550), (">=", 800, 550))
# AD 2.22 / AD 4.20-4.23 bez LVP (EPZG: "LVO are not conducted"; EPOK tylko minima startu śmigłowców)
NO_LVP = ("EPRA", "EPZG", "EPDE", "EPLK", "EPMM", "EPCE", "EPDA", "EPIR", "EPLY", "EPOK", "EPPR", "EPTM")
OPS = {"<": lambda v, x: v < x, "<=": lambda v, x: v <= x, ">": lambda v, x: v > x, ">=": lambda v, x: v >= x}


def _cfg():
    return json.loads((settings.seed_dir / "lvp.json").read_text("utf-8"))


def _phase(t, logic):
    return {"rvr_m": [t[0], t[1]], "ceiling_ft": [t[2], t[3]], "logic": logic} if t else None


def test_lvp_json_matches_aip():
    cfg = _cfg()
    for icao, (prep, act, cancel) in AIP_CIV.items():
        e = cfg[icao]
        want = (_phase(prep, "or"), _phase(act, "or"), _phase(cancel, "and"))
        assert (e.get("prep"), e["lvp"], e["cancel"]) == want, icao
        assert e["source"].startswith("AIP AD 2.22 para") and "scope" not in e, icao
    for icao in AIP_MIL:
        e = cfg[icao]
        assert e["scope"] == "DEP" and e["source"].startswith("AIP MIL AD 4.20 para"), icao
        want = tuple({"vis_m": [op, v], "rvr_eq_m": eq, "logic": logic}
                     for (op, v, eq), logic in zip(MIL, ("or", "or", "and"), strict=True))
        assert (e["prep"], e["lvp"], e["cancel"]) == want, icao
        assert "suspended when the visibility falls below 400 m" in lvp.evaluate(None, icao)["note"], icao
    for icao in NO_LVP:
        assert cfg[icao]["applies"] is False and cfg[icao]["reason"], icao
    # każde lotnisko IFR z AD 1.3 i każde wojskowe ma wpis (inaczej DEFAULT: "brak LVP" bez sprawdzenia)
    from backend.app.services.eaip import AD2_AERODROMES, MIL_AERODROMES
    assert set(AD2_AERODROMES) | set(MIL_AERODROMES) == set(AIP_CIV) | set(AIP_MIL) | set(NO_LVP)
    assert set(cfg) - {"_uwaga", "DEFAULT"} == set(AIP_CIV) | set(AIP_MIL) | set(NO_LVP)


def _around(op, lim, step):
    """(wartość spełniająca warunek, najbliższa niespełniająca) na skali raportów METAR."""
    return {"<": (lim - step, lim), "<=": (lim, lim + step), ">": (lim + step, lim), ">=": (lim, lim - step)}[op]


def _metar(icao, t, rvr=None, ceil=None, vis=None):
    """METAR o czasie t: RVR (wszystkie pasy) albo widzialność, ceiling BKN albo FEW050 (bez ceilingu)."""
    sky = f"BKN{ceil // 100:03d}" if ceil is not None else "FEW050"
    rv = f"0600 R27/{rvr:04d}N R09/{rvr:04d}N BR" if rvr is not None else f"{vis if vis is not None else 9999:04d}"
    return parse_metar(f"{icao} {t:%d%H%M}Z 27004KT {rv} {sky} 08/07 Q1012")


def _state(icao, *metars):
    """Stan po kolejnych METAR-ach co 30 min od 14.10.2026 06:00 (od zera, bez historii)."""
    lvp.reset_memory()
    t = datetime(2026, 10, 14, 6, 0, tzinfo=UTC)
    out = None
    for kw in metars:
        out = lvp.evaluate(_metar(icao, t, **kw), icao, now=t + timedelta(minutes=2))
        t += timedelta(minutes=30)
    return out["state"]


def _cases_civ():
    for icao, (prep, act, cancel) in AIP_CIV.items():
        yield icao, prep, act, cancel


@pytest.mark.parametrize("icao, prep, act, cancel", list(_cases_civ()))
def test_lvp_boundaries_civil(icao, prep, act, cancel):
    on = {"rvr": 100, "ceil": 100}   # LVP w mocy na każdym lotnisku

    def met(ph, k, v):
        return bool(ph) and OPS[ph[0 if k == "rvr" else 2]](v, ph[1 if k == "rvr" else 3])
    for k, step in (("rvr", 25), ("ceil", 100)):
        op, lim = (act[0], act[1]) if k == "rvr" else (act[2], act[3])
        yes, no = _around(op, lim, step)
        # wprowadzenie: jeden warunek wystarczy ("or"), na progu i tuż obok
        assert _state(icao, {k: yes}) == "LVP", (icao, k, yes)
        assert _state(icao, {k: no}) == ("PREP" if met(prep, k, no) else None), (icao, k, no)
        # przygotowanie: na progu (poza progiem wprowadzenia) i tuż nad nim
        if prep:
            pyes, pno = _around(prep[0 if k == "rvr" else 2], prep[1 if k == "rvr" else 3], step)
            assert _state(icao, {k: pyes}) == "PREP" and _state(icao, {k: pno}) is None, (icao, k, pyes, pno)
        # odwołanie ("and": drugi warunek spełniony z zapasem); na wartości spełniającej wprowadzenie LVP trwa
        cop, clim = (cancel[0], cancel[1]) if k == "rvr" else (cancel[2], cancel[3])
        for v in _around(cop, clim, step):
            want = "LVP" if met(act, k, v) or not OPS[cop](v, clim) else "CANCELLED"
            assert _state(icao, on, {k: v}) == want, (icao, k, v)


@pytest.mark.parametrize("icao", AIP_MIL)
def test_lvp_boundaries_military(icao):
    (_, pv, _), (_, av, _), _ = MIL
    assert _state(icao, {"vis": av}) == "LVP" and _state(icao, {"vis": av + 100}) == "PREP"
    assert _state(icao, {"vis": pv}) == "PREP" and _state(icao, {"vis": pv + 100}) is None
    on = {"vis": 200}
    # odwołanie "800 m or more": przy 800 m wciąż warunek wprowadzenia ("800 m or less"), więc LVP trwa
    assert [_state(icao, on, {"vis": v}) for v in (700, 800, 900)] == ["LVP", "LVP", "CANCELLED"]


def test_lvp_lowest_rvr_and_all_for_cancel():
    def ev(raw, t):
        return lvp.evaluate(parse_metar(raw), "EPKT", now=t)
    t = datetime(2026, 10, 14, 6, 2, tzinfo=UTC)
    # wprowadzenie: najniższy RVR ze wszystkich pasów
    on = ev("EPKT 140600Z 27004KT 0600 R27/1000N R09/0500N BR BKN010 08/07 Q1012", t)
    assert on["state"] == "LVP" and on["reasons"] == ["RVR 09 500 m < 550 m"]
    # odwołanie: wszystkie RVR ≥ 600 m
    held = ev("EPKT 140630Z 27004KT 0800 R27/0600N R09/0575N BR BKN010 08/07 Q1012", t + timedelta(minutes=30))
    assert held["state"] == "LVP" and held["reasons"][-1] == "to cancel: RVR 09 ≥ 600 m (now 575 m)"
    off = ev("EPKT 140700Z 27004KT 0800 R27/0600N R09/0600N BR BKN010 08/07 Q1012", t + timedelta(minutes=60))
    assert off["state"] == "CANCELLED"
    # zmienny RVR (0500V0700): liczy się wartość najniższa
    lvp.reset_memory()
    assert ev("EPKT 140600Z 27004KT 0600 R27/0500V0700N BR BKN010 08/07 Q1012", t)["state"] == "LVP"


def test_lvp_visibility_only_without_rvr():
    t = datetime(2026, 10, 14, 6, 2, tzinfo=UTC)
    # RVR jest (P2000 przy płytkiej mgle): widzialność 400 m nie wprowadza LVP
    assert lvp.evaluate(parse_metar("EPKT 140600Z 27004KT 0400 R27/P2000N MIFG FEW050 08/07 Q1012"), "EPKT",
                        now=t)["state"] is None
    lvp.reset_memory()
    on = lvp.evaluate(parse_metar("EPKT 140600Z 27004KT 0400 FG FEW050 08/07 Q1012"), "EPKT", now=t)
    assert on["state"] == "LVP" and on["reasons"] == ["visibility 400 m < 550 m"]


def test_lvp_unreported_ceiling_does_not_cancel():
    """VV/// (zakryte niebo bez wartości) to brak danych o podstawie, a nie brak chmur: LVP nie jest odwołane, choć RVR
    spełnia warunek odwołania; sama podstawa bez wartości LVP nie wprowadza."""
    t = datetime(2026, 10, 14, 6, 2, tzinfo=UTC)

    def ev(raw, k):
        return lvp.evaluate(parse_metar(raw), "EPKT", now=t + timedelta(minutes=30 * k))
    assert ev("EPKT 140600Z 27004KT 0100 R27/0100N FG VV001 08/07 Q1012", 0)["state"] == "LVP"
    held = ev("EPKT 140630Z 27004KT 0800 R27/0800N R09/0800N BR VV/// 08/07 Q1012", 1)
    assert held["state"] == "LVP" and "to cancel: ceiling ≥ 200 ft (not reported)" in held["reasons"]
    assert ev("EPKT 140700Z 27004KT 0800 R27/0800N R09/0800N BR BKN003 08/07 Q1012", 2)["state"] == "CANCELLED"
    lvp.reset_memory()
    assert ev("EPKT 140600Z 27004KT 2000 BR BKN/// 08/07 Q1012", 0)["state"] is None


@pytest.mark.parametrize("icao", ["EPBC", "EPKX", "EDDB", *NO_LVP])
def test_lvp_default_and_not_applicable(icao):
    e = lvp.evaluate(parse_metar(f"{icao} 140600Z 27004KT 0100 R27/0100N FG VV001 08/07 Q1012"), icao,
                     now=datetime(2026, 10, 14, 6, 2, tzinfo=UTC))
    assert e["applies"] is False and e["state"] is None and e["reason"].startswith("No LVP at this aerodrome")
