"""Poziom przejściowy (TL) i wysokość przejściowa (TA) w FIR EPWW.

Wysokość przejściowa w FIR EPWW to 6500 ft (OM PL vACC; w eAIP PAŻP ENR 1.7 nie dało się tego sprawdzić z serwera).

Zasada wyznaczania poziomu przejściowego (OM PL vACC, om.plvacc.pl/docs/2610/airspace, rozdział
"Airspace structure" → "Transition level", AIRAC 2610, sprawdzone 2026-10-08):
- QNH na którymkolwiek z kontrolowanych lotnisk w vFIR Warszawa niższe niż 995 hPa  → TL = FL 90,
- QNH na wszystkich kontrolowanych lotniskach równe 995 hPa lub wyższe             → TL = FL 80.
Poziom jest więc jeden dla całego FIR-u, a nie osobny dla każdego lotniska.

Przy bardzo niskim ciśnieniu (poniżej ok. 959 hPa, w Polsce praktycznie niespotykanym) FL 90 przestaje dawać
wymagane 1000 ft nad wysokością przejściową, więc podnosimy poziom co 5 FL, aż ten odstęp będzie zachowany.
To już nie jest zapis z OM, tylko zabezpieczenie PolIDS – takie przypadki podpisujemy jako "wyliczony".

Gdy lotnisko nadaje ATIS w sieci VATSIM, pokazujemy poziom z ATIS (to, co naprawdę słyszą piloci),
a wyliczony z QNH zostaje jako sprawdzenie.
"""

import re

TA_FT = 6500                 # wysokość przejściowa w FIR EPWW
LOW_QNH_HPA = 995            # progowe QNH z OM PL vACC
FL_NORMAL = 80               # TL przy QNH >= 995 hPa na wszystkich kontrolowanych lotniskach
FL_LOW_QNH = 90              # TL, gdy gdziekolwiek QNH < 995 hPa
MIN_SEP_FT = 1000            # minimalny odstęp poziomu przejściowego nad wysokością przejściową
FT_PER_HPA = 27.3            # ok. 27 ft na 1 hPa w okolicach poziomu morza
SOURCE = "OM PL vACC, vFIR Warszawa Airspace › Transition level (AIRAC 2610)"
SOURCE_URL = "https://om.plvacc.pl/docs/2610/airspace"

# "TRANSITION LEVEL 80", "TRANSITION LEVEL FL80", "TRL 80", "TL80", "TRL FL 90"
_ATIS_TL = [
    re.compile(r"\bTRANSITION\s+LEVEL\s*(?:IS\s*)?(?:FL\s*)?(\d{2,3})\b"),
    re.compile(r"\b(?:TRL|TL)\s*(?:FL\s*)?(\d{2,3})\b"),
]


def altitude_ft(fl: int, qnh: float) -> float:
    """Wysokość (ft AMSL) poziomu lotu przy danym QNH – do sprawdzenia odstępu nad wysokością przejściową."""
    return fl * 100 - (1013.25 - qnh) * FT_PER_HPA


def from_qnh(qnh: float | None) -> dict:
    """Poziom przejściowy z najniższego QNH kontrolowanych lotnisk FIR EPWW.

    Zwraca {"fl": 80, "rule": opis po polsku, "computed": False} albo {"fl": None, ...}, gdy nie ma QNH."""
    if qnh is None:
        return {"fl": None, "rule": "brak QNH z METAR-ów – nie można wyznaczyć poziomu przejściowego",
                "computed": False}
    low = qnh < LOW_QNH_HPA
    fl = FL_LOW_QNH if low else FL_NORMAL
    rule = (f"QNH {qnh:g} hPa < {LOW_QNH_HPA} hPa → FL{FL_LOW_QNH}" if low
            else f"QNH {qnh:g} hPa ≥ {LOW_QNH_HPA} hPa na wszystkich lotniskach → FL{FL_NORMAL}")
    computed = False
    while altitude_ft(fl, qnh) < TA_FT + MIN_SEP_FT:   # zabezpieczenie przy skrajnie niskim ciśnieniu
        fl += 5
        computed = True
    if computed:
        rule += f"; podniesiony do FL{fl}, żeby zostało {MIN_SEP_FT} ft nad TA {TA_FT} ft"
    return {"fl": fl, "rule": rule, "computed": computed}


def from_atis(lines) -> int | None:
    """Poziom przejściowy z tekstu ATIS z sieci VATSIM (text_atis). None, gdy ATIS go nie podaje."""
    items = lines if isinstance(lines, list) else [lines]
    text = re.sub(r"\s+", " ", " ".join(str(x) for x in items if x)).upper()
    for pattern in _ATIS_TL:
        for m in pattern.finditer(text):
            fl = int(m.group(1))
            if 30 <= fl <= 300:
                return fl
    return None


def fir_level(qnhs: dict[str, float | None]) -> dict:
    """Poziom przejściowy FIR EPWW z QNH lotnisk: {"fl", "qnh_min", "qnh_icao", "rule", "stations", "source"}."""
    have = {i: q for i, q in qnhs.items() if q is not None}
    icao = min(have, key=lambda i: (have[i], i)) if have else None
    qnh = have[icao] if icao else None
    return {**from_qnh(qnh), "qnh_min": qnh, "qnh_icao": icao, "stations": len(have),
            "ta_ft": TA_FT, "source": SOURCE, "source_url": SOURCE_URL}


def levels(qnhs: dict[str, float | None], atis: dict[str, list | None]) -> dict:
    """Poziom przejściowy dla każdego lotniska: z ATIS, gdy lotnisko je nadaje, inaczej wyliczony z QNH FIR-u.

    qnhs: {ICAO: QNH z METAR}, atis: {ICAO: linie text_atis}. Zwraca {"fir": {...}, "aerodromes": {ICAO: {...}}}."""
    fir = fir_level(qnhs)
    out = {}
    for icao in sorted(set(qnhs) | set(atis)):
        tl = from_atis(atis.get(icao))
        out[icao] = {"fl": tl if tl is not None else fir["fl"], "source": "ATIS" if tl is not None else "QNH",
                     "qnh": qnhs.get(icao), "fir_fl": fir["fl"],
                     # ATIS podaje inny poziom niż zasada z QNH: warto to zobaczyć (np. stary ATIS)
                     "differs": tl is not None and fir["fl"] is not None and tl != fir["fl"]}
    return {"fir": fir, "aerodromes": out}
