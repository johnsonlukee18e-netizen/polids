import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import current_user
from ..config import settings
from ..database import get_db
from ..models import Aerodrome, AtcPosition, NavPoint
from ..services.eptraffic import ep_traffic
from ..services.http_cache import UpstreamError
from ..services.neighbours import nb_owners
from ..services.positions import online_stations
from ..services.route import RouteResolver
from ..services.vatsim import (airport_atc, airport_traffic, bookings_by_callsign, controller_info, fir_boundaries,
                               get_bookings, get_feed, match_positions, online_firs, pilot_info, user_bookings,
                               user_connections)

router = APIRouter(prefix="/api/vatsim", tags=["vatsim"])


async def _feed() -> dict:
    try:
        return await get_feed()
    except (UpstreamError, ValueError) as exc:
        raise HTTPException(502, f"VATSIM data feed niedostępny: {exc}") from exc


@router.get("/online")
async def online(db: Session = Depends(get_db)):
    """Zalogowani kontrolerzy: dopasowani do stanowisk (`positions`) i wszyscy z FIR-ów wokół EPWW (`firs`).

    Stanowiska: najpierw plik .ese EPWW (w kolejności z pliku), potem pozostałe stanowiska sąsiadów z vacs-data
    i z plików .ese sąsiadów (właściciele sektorów sąsiadów na mapie)."""
    data = await _feed()
    ctrls = data.get("controllers", []) + data.get("atis", [])
    return {"positions": match_positions(ctrls, online_stations(db), nb_owners(db)), "firs": online_firs(ctrls),
            "controllers": [controller_info(c) for c in ctrls if c.get("callsign", "").startswith("EP")],
            "updated": data.get("general", {}).get("update_timestamp")}


@router.get("/atc")
async def atc(db: Session = Depends(get_db)):
    """Kontrolerzy online do plakietek na mapie: lotniska (DEL/GND/TWR/APP/ATIS) z pozycją i FIR-y (CTR/FSS)."""
    data = await _feed()
    ctrls = data.get("controllers", []) + data.get("atis", [])
    groups = airport_atc(ctrls)
    ads = {a.icao: a for a in db.scalars(select(Aerodrome).where(Aerodrome.icao.in_(groups)))}
    pts = {p.ident: p for p in db.scalars(select(NavPoint).where(NavPoint.kind == "AD", NavPoint.ident.in_(groups)))}
    airports = []
    for icao, facilities in sorted(groups.items()):
        a = ads.get(icao) or pts.get(icao)
        if a:  # prefiksów spoza bazy lotnisk (np. 3-literowych z USA) nie umiemy postawić na mapie
            airports.append({"icao": icao, "name": a.name, "lat": a.lat, "lon": a.lon, "facilities": facilities})
    return {"airports": airports, "firs": online_firs(ctrls),
            "updated": data.get("general", {}).get("update_timestamp")}


@router.get("/bookings")
async def bookings(prefix: str = "EP", hours: int | None = Query(None, ge=1, le=168)):
    """Rezerwacje stanowisk z atc-bookings.vatsim.net: trwające i zaczynające się jeszcze dziś (doba UTC),
    albo w ciągu `hours` godzin, jeśli podano."""
    try:
        data = await get_bookings()
    except (UpstreamError, ValueError) as exc:
        raise HTTPException(502, f"VATSIM ATC bookings niedostępne: {exc}") from exc
    until = datetime.now(timezone.utc) + timedelta(hours=hours) if hours else None
    result = bookings_by_callsign(data, prefix, until=until)
    # API rezerwacji podaje tylko CID; imię i nazwisko znamy, jeśli ta osoba jest teraz zalogowana w sieci
    try:
        feed = await get_feed()
        names = {c.get("cid"): c.get("name") for c in feed.get("controllers", []) + feed.get("pilots", [])}
    except (UpstreamError, ValueError):
        names = {}
    for lst in result.values():
        for b in lst:
            b["name"] = names.get(b["cid"])
    return result


@router.get("/me")
async def me(request: Request, db: Session = Depends(get_db)):
    """Zalogowany użytkownik PolIDS (CID z sesji) w sieci VATSIM, do HOME: jego połączenia z data feed (`online`:
    callsign, częstotliwość, od kiedy, rating, facility; `position` = stanowisko z pliku .ese EPWW dopasowane jak
    w EuroScope, np. EPWW_CTR na częstotliwości sektora) i jego rezerwacje z atc-bookings (dowolny znak), które się
    jeszcze nie skończyły i zaczynają w ciągu 24 h (UTC). Bez logowania (tryb none) puste listy i cid null.
    Awaria jednego ze źródeł nie psuje drugiego: zostaje to, co się udało, a powód jest w `error` (oba razem)
    i osobno w `online_error` / `bookings_error` (HOME nie pisze wtedy "nie jesteś zalogowany")."""
    user = current_user(request) if settings.auth_mode != "none" else None
    cid = str(user["cid"]) if user and user.get("cid") else None
    out = {"cid": cid, "online": [], "bookings": [], "updated": None, "error": None, "online_error": None,
           "bookings_error": None}
    if not cid:
        return out
    feed, books = await asyncio.gather(get_feed(), get_bookings(), return_exceptions=True)
    # każde źródło osobno: HOME pokazuje to, co się udało, i powód awarii drugiego
    try:
        if isinstance(feed, BaseException):
            raise feed
        online = user_connections(feed, cid)
        stations = list(db.scalars(select(AtcPosition)))
        hits = match_positions([{"callsign": c["callsign"] or "", "frequency": c["frequency"] or ""} for c in online],
                               stations)
        pos = {info["callsign"]: cs for cs, info in hits.items()}
        out["online"] = [c | {"position": pos.get(c["callsign"])} for c in online]
        out["updated"] = (feed.get("general") or {}).get("update_timestamp")
    except Exception as exc:  # noqa: BLE001 - błąd sieci (UpstreamError), zły JSON albo nieoczekiwany kształt danych
        out["online_error"] = f"VATSIM data feed niedostępny: {exc}"
    try:
        if isinstance(books, BaseException):
            raise books
        out["bookings"] = user_bookings(books, cid)
    except Exception as exc:  # noqa: BLE001 - jak wyżej
        out["bookings_error"] = f"VATSIM ATC bookings niedostępne: {exc}"
    out["error"] = " · ".join(e for e in (out["online_error"], out["bookings_error"]) if e) or None
    return out


@router.get("/airport/{icao}")
async def airport(icao: str, db: Session = Depends(get_db)):
    """Bieżące loty z/do lotniska (piloci w sieci z planem lotu i prefile)."""
    data = await _feed()
    ad = db.get(Aerodrome, icao.upper())
    return {"icao": icao.upper(), **airport_traffic(data, icao, ad.lat if ad else None, ad.lon if ad else None),
            "updated": data.get("general", {}).get("update_timestamp")}


@router.get("/firs")
def firs():
    """Granice FIR z projektu VATSpy (wycinek Europy środkowej)."""
    return fir_boundaries()


@router.get("/pilots")
async def pilots(bbox: str = "46,8,58,30", ep: bool = False, keep: str = "", db: Session = Depends(get_db)):
    """Samoloty w obszarze bbox = południe,zachód,północ,wschód, każdy z relacją z ruchem EP w polu `ep`:
    "dep" = odlot z lotniska EP**, "arr" = przylot na EP**, "trn" = tranzyt przez FIR EPWW (jest w nim teraz
    albo reszta trasy z planu lotu w niego wchodzi; bez planu: tylko w FIR-ze), null = bez związku z Polską
    (services/eptraffic.py). ep=1 (MAP): tylko samoloty z relacją. keep: znaki po przecinku, które są w odpowiedzi
    zawsze, także bez relacji i poza bbox (MAP: wybrany lot i loty z wykresu vIFF); te, które są w niej tylko dzięki
    keep (poza bbox albo, przy ep=1, bez relacji), mają "kept": true i nie liczą się do ruchu w obszarze."""
    try:
        s, w, n, e = (float(x) for x in bbox.split(","))
    except ValueError as exc:
        raise HTTPException(400, "bbox = poludnie,zachod,polnoc,wschod") from exc
    data = await _feed()
    keep_cs = {x.strip().upper() for x in keep.split(",")[:200] if x.strip()}

    def inside(p: dict) -> bool:
        return s <= p["latitude"] <= n and w <= p["longitude"] <= e

    found = [(pilot_info(p), inside(p)) for p in data.get("pilots", []) if p.get("latitude") is not None and (
        inside(p) or (p.get("callsign") or "").upper() in keep_cs)]
    # rozpisywanie nowych tras (zapytania do bazy) poza pętlą zdarzeń
    rels = await run_in_threadpool(ep_traffic.relations, [p for p, _ in found], RouteResolver(db))
    out = []
    for (p, inb), r in zip(found, rels):
        if inb and (r or not ep):
            out.append(p | {"ep": r})
        elif (p["callsign"] or "").upper() in keep_cs:
            out.append(p | {"ep": r, "kept": True})
    return out


@router.get("/pilots/{callsign}/route")
async def pilot_route(callsign: str, db: Session = Depends(get_db)):
    """Trasa z planu lotu pilota rozpisana na punkty (lotnisko odlotu, trasa, lotnisko docelowe)."""
    data = await _feed()
    p = next((x for x in data.get("pilots", []) if x.get("callsign") == callsign.upper()), None)
    if not p:
        raise HTTPException(404, f"{callsign} nie jest online")
    info = pilot_info(p)
    if not info["route"] and not info["departure"]:
        return {**info, "points": [], "distance_nm": 0, "warnings": ["Brak planu lotu"]}
    text = " ".join(x for x in (info["departure"], info["route"], info["arrival"]) if x)
    return {**info, **RouteResolver(db).resolve(text)}
