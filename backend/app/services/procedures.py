"""SID i STAR z pliku sektorowego .ese oraz paski postępu lotu (jak EFES) do AERODROME › RUCH.

Linie w .ese: "SID:EPWA:29:SOXER7G:WA901 WA902 WA903 MAKUS SOXER" (lotnisko:pas:nazwa:punkty).
STAR z podejściem ma nazwę "AGAVA6UxILS·Z" (STAR x podejście); same podejścia ("ILS·Z", "RNP") pomijamy.
SID dobieramy po ostatnim punkcie = pierwszy punkt trasy, STAR po pierwszym punkcie = ostatni punkt trasy,
zawsze dla pasa w użyciu. Nazwa procedury wpisana w trasę wygrywa, jeśli istnieje dla tego pasa."""

import re
from datetime import datetime, timedelta
from functools import lru_cache

from ..config import DATA_DIR
from .vatsim import level_ft
from .viff import hhmm

PROC_NAME = re.compile(r"^([A-Z]{2,5})(\d[A-Z])$")  # SOXER7G, LOZ1N
FIX = re.compile(r"^[A-Z]{2,5}$")
SPEED_LEVEL = re.compile(r"^[NKM]\d{3,4}(?:[FAMS]\d{3,4}|VFR)$")  # N0450F370
# na ziemi dalej niż tyle NM od lotniska: przylot jeszcze na lotnisku odlotu, odlot już po przylocie gdzie indziej
AWAY_NM = 5


def parse_procedures(text: str) -> dict:
    """{lotnisko: {"sid"|"star": {pas: [{"name", "fixes", "approaches"}]}}}; kolejność jak w pliku."""
    out: dict = {}
    for line in text.splitlines():
        kind = "sid" if line.startswith("SID:") else "star" if line.startswith("STAR:") else None
        parts = line.split(":")
        if not kind or len(parts) < 5:
            continue
        ad, rwy = parts[1].strip().upper(), parts[2].strip().upper()
        name, _, app = parts[3].strip().partition("x")
        fixes = parts[4].upper().split()
        if not fixes or not PROC_NAME.match(name):
            continue
        approach = re.sub(r"[^A-Z0-9]+", " ", app.upper()).strip() or None
        lst = out.setdefault(ad, {"sid": {}, "star": {}})[kind].setdefault(rwy, [])
        hit = next((p for p in lst if p["name"] == name), None)
        if hit is None:
            lst.append({"name": name, "fixes": fixes, "approaches": [approach] if approach else []})
        elif approach and approach not in hit["approaches"]:
            hit["approaches"].append(approach)
    return out


@lru_cache(maxsize=1)
def procedures() -> dict:
    """Procedury ze wszystkich plików data/import/*.ese (brak pliku = brak procedur)."""
    out: dict = {}
    for f in sorted((DATA_DIR / "import").glob("*.ese")):
        try:
            text = f.read_bytes().decode("latin-1")
        except OSError:
            continue
        for ad, kinds in parse_procedures(text).items():
            for kind, rwys in kinds.items():
                for rwy, lst in rwys.items():
                    have = out.setdefault(ad, {"sid": {}, "star": {}})[kind].setdefault(rwy, [])
                    have += [p for p in lst if all(p["name"] != q["name"] for q in have)]
    return out


def route_points(route: str | None, skip: tuple = ()) -> list[str]:
    """Elementy trasy bez DCT, grup prędkość/poziom, dopisków po '/' i kodów lotnisk z `skip`."""
    out = []
    for tok in (route or "").upper().split():
        tok = tok.split("/")[0]
        if tok and tok not in ("DCT", "IFR", "VFR") and tok not in skip and not SPEED_LEVEL.match(tok):
            out.append(tok)
    return out


def _for_runway(kind: str, icao: str, runway: str, procs: dict | None) -> list[dict]:
    return (procs if procs is not None else procedures()).get(icao.upper(), {}).get(kind, {}).get(runway.upper(), [])


def _match(kind: str, icao: str, runway: str | None, token: str | None, procs: dict | None) -> dict | None:
    if not runway or not token:
        return None
    lst = _for_runway(kind, icao, runway, procs)
    m = PROC_NAME.match(token)
    if m:
        named = next((p for p in lst if p["name"] == token), None)
        if named:
            return {**named, "fix": m.group(1), "runway": runway, "source": "route"}
        fix = m.group(1)
    elif FIX.match(token):
        fix = token
    else:
        return None
    end = -1 if kind == "sid" else 0
    hit = next((p for p in lst if p["fixes"][end] == fix), None)
    return {**hit, "fix": fix, "runway": runway, "source": "fix"} if hit else None


def match_sid(icao: str, runway: str | None, route: str | None, procs: dict | None = None) -> dict | None:
    """SID dla pasu startowego: nazwa z trasy albo ten, którego ostatni punkt = pierwszy punkt trasy."""
    pts = route_points(route, (icao.upper(),))
    return _match("sid", icao, runway, pts[0] if pts else None, procs)


def match_star(icao: str, runway: str | None, route: str | None, procs: dict | None = None) -> dict | None:
    """STAR dla pasu do lądowania: nazwa z trasy albo ten, którego pierwszy punkt = ostatni punkt trasy."""
    pts = route_points(route, (icao.upper(),))
    return _match("star", icao, runway, pts[-1] if pts else None, procs)


def first_fix(route: str | None, icao: str, last: bool = False) -> str | None:
    """Punkt, po którym szukamy procedury (do podpowiedzi, gdy nic nie pasuje)."""
    pts = route_points(route, (icao.upper(),))
    if not pts:
        return None
    tok = pts[-1] if last else pts[0]
    m = PROC_NAME.match(tok)
    return m.group(1) if m else tok if FIX.match(tok) else None


# --- paski postępu lotu

def _rel(t: str | None, now: datetime) -> int | None:
    """'HHMM' jako minuty względem teraz, w zakresie -720..719 (przejście przez północ)."""
    t = hhmm(t)
    if t is None:
        return None
    return (int(t[:2]) * 60 + int(t[2:]) - now.hour * 60 - now.minute + 720) % 1440 - 720


def _cdm_dep(v: dict | None) -> tuple[str | None, str | None]:
    """depInfo z wtyczki CDM w EuroScope: 'pas/SID' przydzielone przez kontrolera."""
    rwy, _, sid = str((v or {}).get("dep_info") or "").partition("/")
    rwy, sid = rwy.strip().upper(), sid.strip().upper()
    return (rwy if re.fullmatch(r"\d{2}[LRC]?", rwy) else None), (sid if PROC_NAME.match(sid) else None)


def make_strip(kind: str, p: dict, v: dict | None, icao: str, runway: dict, wtc: dict, now: datetime,
               planned: str | None = None, procs: dict | None = None) -> dict:
    """Jeden pasek: kind = dep (niebieski), arr (żółty), local (różowy, ADEP = ADES);
    planned = "prefile" (plan złożony przed połączeniem) albo "viff" (lot znany tylko z vIFF)."""
    rules = (p.get("rules") or "").upper()[:1] or None
    deptime = hhmm(p.get("deptime"))
    rwy_key = "arr" if kind == "arr" else "dep"
    rwy, rwy_src = runway.get(rwy_key), runway.get("source")
    proc, proc_fix = None, None
    if kind == "dep" and rules != "V":
        c_rwy, c_sid = _cdm_dep(v)
        if c_rwy:
            rwy, rwy_src = c_rwy, "CDM"
        if c_sid:  # punkty z .ese, jeśli ten SID tam jest
            known = next((x for x in _for_runway("sid", icao, rwy or "", procs) if x["name"] == c_sid), {})
            proc = {"fixes": [], "approaches": [], **known, "name": c_sid, "fix": PROC_NAME.match(c_sid).group(1),
                    "runway": rwy, "source": "CDM"}
        else:
            proc = match_sid(icao, rwy, p.get("route"), procs)
        proc_fix = first_fix(p.get("route"), icao)
    elif kind == "arr" and rules != "V":
        proc = match_star(icao, rwy, p.get("route"), procs)
        proc_fix = first_fix(p.get("route"), icao, last=True)
    ac = p.get("aircraft")
    wake = wtc.get(ac) or p.get("wake")
    away = p.get("state") == "ground" and (p.get("dist_nm") or 0) > AWAY_NM
    eta_min = p.get("eta_min")
    return {
        "kind": kind, "planned": planned, "callsign": p.get("callsign"),
        "aircraft": ac, "aircraft_icao": p.get("aircraft_icao"), "wake": wake,
        "wake_source": "db" if wtc.get(ac) else "fpl" if wake else None,
        "departure": p.get("departure"), "arrival": p.get("arrival"), "route": p.get("route"),
        "remarks": p.get("remarks"), "rules": rules, "rfl": p.get("rfl"), "rfl_ft": level_ft(p.get("rfl")),
        "squawk": p.get("squawk"), "assigned_squawk": p.get("assigned_squawk"),
        "deptime": deptime, "eobt": (v or {}).get("eobt") or deptime,
        "eobt_source": "vIFF" if (v or {}).get("eobt") else "FPL" if deptime else None,
        "state": p.get("state") or "offline", "away": away, "altitude": p.get("altitude"),
        "groundspeed": p.get("groundspeed"), "dist_nm": p.get("dist_nm"), "eta_min": eta_min,
        "eta": (now + timedelta(minutes=eta_min)).strftime("%H%M") if eta_min is not None else None,
        "runway": rwy, "runway_source": rwy_src, "proc": proc, "proc_fix": proc_fix, "viff": v,
    }


def strip_board(icao: str, traffic: dict, viff: dict | None, runway: dict, wtc: dict, now: datetime,
                procs: dict | None = None) -> dict:
    """Tablica pasków: odloty (na ziemi wg TSAT/CTOT/EOBT, potem w powietrzu), przyloty wg ETA,
    na końcu obu list samoloty na ziemi daleko od lotniska (away); loty lokalne i planowane
    (prefile oraz loty znane tylko z vIFF, pilot jeszcze niepołączony)."""
    icao = icao.upper()
    vmap = {f["callsign"]: f for f in (viff or {}).get("flights", []) if f.get("callsign")}

    def mk(kind: str, p: dict, planned: str | None = None) -> dict:
        return make_strip(kind, p, vmap.get(p.get("callsign")), icao, runway, wtc, now, planned, procs)

    deps, local = [], []
    for p in traffic.get("departures", []):  # w departures zawsze ADEP = icao; ADES = icao to krąg
        if p.get("arrival") == icao:
            local.append(mk("local", p))
        else:
            deps.append(mk("dep", p))
    arrs = [mk("arr", p) for p in traffic.get("arrivals", [])]

    online = {s["callsign"] for s in deps + local + arrs}
    planned = []
    prefiles = {p.get("callsign"): p for p in traffic.get("prefiles", []) if p.get("callsign") not in online}
    for p in prefiles.values():
        dep, arr = p.get("departure"), p.get("arrival")
        planned.append(mk("local" if dep == arr == icao else "dep" if dep == icao else "arr", p, "prefile"))
    for cs, f in vmap.items():
        if cs not in online and cs not in prefiles and not f.get("atot"):
            planned.append(mk("dep", {"callsign": cs, "departure": icao, "arrival": f.get("arrival")}, "viff"))

    def when(s: dict, *times) -> int:
        t = _rel(next((x for x in times if x), None), now)
        return 9999 if t is None else t

    def dep_key(s: dict) -> tuple:
        if s["away"]:
            return (2, s["dist_nm"] or 0, s["callsign"])
        if s["state"] == "air":
            return (1, s["dist_nm"] or 0, s["callsign"])
        v = s["viff"] or {}
        return (0, when(s, v.get("tsat"), v.get("ctot"), s["eobt"]), s["callsign"])

    deps.sort(key=dep_key)
    # po lądowaniu, w powietrzu wg ETA, na końcu jeszcze na ziemi na lotnisku odlotu
    arrs.sort(key=lambda s: (2 if s["away"] else 0 if s["state"] == "ground" else 1, s["eta_min"] is None,
                             s["eta_min"] or 0, s["dist_nm"] or 0))
    local.sort(key=lambda s: (s["state"] == "air", s["callsign"]))
    planned.sort(key=lambda s: (when(s, s["eobt"]), s["callsign"]))
    return {"departures": deps, "arrivals": arrs, "local": local, "planned": planned}
