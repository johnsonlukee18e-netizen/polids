"""Poziom przejściowy (TL) w FIR EPWW: jeden dla całego kraju.

Zasada podana przez Marka 08.10.2026 (OM PL vACC › Transition level pisze „poniżej 995 hPa”, tu liczy się
także 995):
- normalnie TL = FL080,
- gdy na którymkolwiek kontrolowanym lotnisku QNH wynosi 995 hPa lub mniej, w całym kraju TL = FL090.
Nie ma osobnego TL dla lotniska ani poziomu z ATIS: pokazujemy jeden poziom i lotnisko z najniższym QNH.

Wysokość przejściowa (TA) 6500 ft jest tylko do informacji (OM PL vACC; w eAIP PAŻP ENR 1.7 nie dało się tego
sprawdzić z serwera).
"""

TA_FT = 6500                 # wysokość przejściowa w FIR EPWW
LOW_QNH_HPA = 995            # QNH ≤ 995 hPa na którymkolwiek lotnisku → FL090
FL_NORMAL = 80               # TL, gdy na wszystkich kontrolowanych lotniskach QNH > 995 hPa
FL_LOW_QNH = 90              # TL, gdy gdziekolwiek QNH ≤ 995 hPa
SOURCE = "OM PL vACC, vFIR Warszawa Airspace › Transition level (AIRAC 2610)"
SOURCE_URL = "https://om.plvacc.pl/docs/2610/airspace"


def fl_text(fl: int | None) -> str:
    """FL080 / FL090 – trzy cyfry, tak jak podaje się poziom przejściowy."""
    return f"FL{fl:03d}" if fl is not None else "–"


def from_qnh(qnh: float | None) -> dict:
    """Poziom przejściowy z najniższego QNH kontrolowanych lotnisk FIR EPWW.

    Zwraca {"fl": 80 albo 90, "rule": opis po polsku} albo {"fl": None, ...}, gdy nie ma żadnego QNH."""
    if qnh is None:
        return {"fl": None, "rule": "brak QNH z METAR-ów – nie można wyznaczyć poziomu przejściowego"}
    if qnh <= LOW_QNH_HPA:
        return {"fl": FL_LOW_QNH, "rule": f"QNH ≤ {LOW_QNH_HPA} hPa na co najmniej jednym lotnisku → {fl_text(FL_LOW_QNH)}"}
    return {"fl": FL_NORMAL, "rule": f"QNH na wszystkich lotniskach > {LOW_QNH_HPA} hPa → {fl_text(FL_NORMAL)}"}


def fir_level(qnhs: dict[str, float | None]) -> dict:
    """Jeden poziom przejściowy dla FIR EPWW z QNH kontrolowanych lotnisk.

    Zwraca {"fl", "text", "rule", "qnh_min", "qnh_icao", "low" (lotniska z QNH ≤ 995), "stations", "missing",
    "uncertain" (FL080, ale części QNH brakuje), "threshold_hpa", "normal", "raised", "ta_ft", "source",
    "source_url"}."""
    have = {i: q for i, q in qnhs.items() if q is not None}
    missing = sorted(i for i, q in qnhs.items() if q is None)
    icao = min(have, key=lambda i: (have[i], i)) if have else None
    qnh = have[icao] if icao else None
    level = from_qnh(qnh)
    # FL080 jest pewne tylko wtedy, gdy znamy QNH wszystkich lotnisk: brakujące mogło być ≤ 995 hPa
    uncertain = level["fl"] == FL_NORMAL and bool(missing)
    if uncertain:
        level["rule"] = (f"QNH > {LOW_QNH_HPA} hPa na {len(have)} z {len(qnhs)} lotnisk "
                         f"(brak QNH: {', '.join(missing)}) → {fl_text(FL_NORMAL)}")
    return {**level, "text": fl_text(level["fl"]), "qnh_min": qnh, "qnh_icao": icao,
            "low": sorted(i for i, q in have.items() if q <= LOW_QNH_HPA),
            "stations": len(have), "missing": missing, "uncertain": uncertain,
            "threshold_hpa": LOW_QNH_HPA, "normal": fl_text(FL_NORMAL), "raised": fl_text(FL_LOW_QNH),
            "ta_ft": TA_FT, "source": SOURCE, "source_url": SOURCE_URL}
