"""RADIO: wspólna lista stanowisk (plik .ese + wszystkie stanowiska sąsiednich FIR-ów z vacs-data), zasięg stanowiska
na mapie (granica z VATSpy albo przybliżony okrąg wokół lotniska) i rodzaje wycinków sektorów z pliku .ese."""

import re
from dataclasses import dataclass

TYPES = ("CTR", "FSS", "APP", "DEP", "TWR", "GND", "DEL", "RMP", "ATIS", "FMP", "TMU", "OBS")
# Przybliżony zasięg stanowiska lotniskowego bez wycinków sektorów i bez granicy w VATSpy (NM)
CIRCLE_NM = {"APP": 30, "DEP": 30, "TWR": 10}
GROUND = ("GND", "DEL", "RMP", "ATIS")
# FIR-y sąsiadów (katalogi vacs-data): nazwa pokazywana przy stanowiskach bez nazwy w pliku .ese
FIR_NAMES = {"EDWW": "FIR Bremen", "EDMM": "FIR München", "EDUU": "UIR Rhein", "LK": "FIR Praha", "LZ": "FIR Bratislava",
             "ES": "FIR Sverige", "EY": "FIR Vilnius", "EK": "FIR København", "UMKK": "FIR Kaliningrad"}
# prefiksy, które w katalogu FIR-u vacs-data są innym organem (EDYY = Maastricht UAC nad FIR Bremen)
PREFIX_NAMES = {"EDYY": "UAC Maastricht", "EDUU": "UIR Rhein", "EDGG": "FIR Langen"}
# prefiksy bez własnej granicy w VATSpy: FIR-y, nad którymi leży stanowisko (UIR Rhein nad Langen i München,
# Maastricht UAC nad Bremen, szwedzkie ESCR/ESDK/ESPF – cała Szwecja)
NB_ALIAS = {"EDUU": ["EDGG", "EDMM"], "EDYY": ["EDWW"], "ESCR": ["ESAA"], "ESDK": ["ESAA"], "ESPF": ["ESAA"]}


@dataclass
class Station:
    """Stanowisko do dopasowania z kontrolerami w sieci (te same pola co AtcPosition)."""
    callsign: str
    prefix: str | None
    frequency: str


def facility(callsign: str) -> str:
    parts = (callsign or "").upper().split("_")
    return parts[-1] if len(parts) > 1 and parts[-1] in TYPES else ""


def merge_positions(ese: list[dict], vacs_positions: list[dict], nb: list[dict] = (),
                    nb_listed: set[str] = frozenset()) -> list[dict]:
    """Stanowiska z pliku .ese uzupełnione o stanowiska sąsiadów z vacs-data i z plików .ese sąsiadów
    (klucz: znak wywoławczy; pierwszeństwo: plik EPWW, vacs-data, pliki sąsiadów).

    Pozycje tylko z vacs-data nie mają nazwy ani ID z pliku .ese; FMP/TMU pomijamy (to nie są stanowiska ATC).
    nb: stanowiska z kolejności przejmowania sektorów sąsiadów ({callsign, name, frequency, prefix, source, fir});
    nb_listed: znaki z tych kolejności – `nb_ese` = zasięg z dokładnych sektorów sąsiada zamiast VATSpy."""
    fir_of = {p["id"]: p.get("fir_dir") for p in vacs_positions}
    out = {p["callsign"]: {**p, "fir": fir_of.get(p["callsign"]), "facility": facility(p["callsign"]),
                           "in_ese": True, "in_vacs": p["callsign"] in fir_of} for p in ese}
    # częstotliwość stanowiska z kolejności przejmowania sąsiada: z jego pliku .ese, z którego są też sektory
    # (vacs-data bywa inne: EKCH_P_APP Kastrup Final to w pliku Danii 120.205, w vacs-data 131.405)
    nb_freq = {n["callsign"]: n.get("frequency") for n in nb if n["callsign"] in nb_listed and n.get("frequency")}
    for v in vacs_positions:
        cs = v["id"]
        if cs in out or v.get("facility_type") in ("FMP", "TMU") or facility(cs) in ("FMP", "TMU"):
            continue
        out[cs] = {"callsign": cs, "name": None, "frequency": nb_freq.get(cs) or v.get("frequency") or "", "position_id": None,
                   "prefix": (v.get("prefixes") or [cs.split("_")[0]])[0], "fir": v.get("fir_dir"),
                   "facility": v.get("facility_type") or facility(cs), "in_ese": False, "in_vacs": True}
    for n in nb:
        cs = n["callsign"]
        if cs in out or cs.upper().startswith("EP") or facility(cs) in ("FMP", "TMU"):
            continue
        out[cs] = {"callsign": cs, "name": n.get("name"), "frequency": n.get("frequency") or "", "position_id": None,
                   "prefix": n.get("prefix") or cs.split("_")[0], "fir": n.get("fir"), "facility": facility(cs),
                   "in_ese": False, "in_vacs": False, "nb_source": n.get("source")}
    for p in out.values():
        p["nb_ese"] = p["callsign"] in nb_listed
        p["fir_name"] = PREFIX_NAMES.get(p.get("prefix") or "") or FIR_NAMES.get(p["fir"] or "")
    return sorted(out.values(), key=lambda p: p["callsign"])


def _vatspy_index(firs: dict) -> tuple[set[str], list[tuple[str, str]], dict[str, list[str]]]:
    ids = {f["properties"]["id"] for f in firs.get("features", [])}
    prefixes = sorted(((pre, f["properties"]["id"]) for f in firs.get("features", []) for pre in f["properties"].get("prefixes", [])),
                      key=lambda x: -len(x[0]))
    uirs = {u["id"]: [f for f in u.get("firs", []) if f in ids] for u in firs.get("uirs", [])}
    return ids, prefixes, uirs


def vatspy_range(callsign: str, firs: dict, prefix: str | None = None) -> dict | None:
    """Granica stanowiska CTR/FSS w VATSpy: EDWW_FLG_CTR → EDWW-FLG, ESMM_7_CTR → ESMM-7, LKAA_CTR → LKAA.

    Bez własnego sektora w VATSpy: cały FIR z pasującym prefiksem (exact=False, przybliżenie); UIR → jego FIR-y.
    Na końcu prefiks stanowiska z vacs-data (EKCH_FW_CTR → EKDK) i tabela NB_ALIAS (EDUU → EDGG + EDMM), zawsze
    jako przybliżenie."""
    ids, prefixes, uirs = _vatspy_index(firs)
    parts = callsign.upper().split("_")
    base = parts[:-1] if facility(callsign) else parts
    if not base:
        return None
    if (cand := "-".join(base)) in ids:
        return {"kind": "vatspy", "ids": [cand], "exact": True}
    key = "_".join(base)
    for pre, fid in prefixes:
        if key == pre or key.startswith(pre + "_"):
            return {"kind": "vatspy", "ids": [fid], "exact": key == pre}
    if uirs.get(key):
        return {"kind": "vatspy", "ids": uirs[key], "exact": True}
    if base[0] in ids:
        return {"kind": "vatspy", "ids": [base[0]], "exact": len(base) == 1}
    pre = (prefix or "").upper()
    if pre in ids:
        return {"kind": "vatspy", "ids": [pre], "exact": False}
    if alias := [a for a in NB_ALIAS.get(pre) or NB_ALIAS.get(base[0]) or [] if a in ids]:
        return {"kind": "vatspy", "ids": alias, "exact": False}
    return None


def position_range(callsign: str, firs: dict, lat: float | None = None, lon: float | None = None,
                   prefix: str | None = None) -> dict | None:
    """Zasięg stanowiska na mapie: CTR/FSS granica z VATSpy; APP/DEP/TWR przybliżony okrąg wokół lotniska
    (APP 30 NM, TWR 10 NM); GND/DEL/ATIS sam punkt lotniska. None = nie wiadomo, gdzie jest stanowisko.
    prefix: prefiks stanowiska z pliku .ese albo vacs-data (zapasowe dopasowanie do VATSpy)."""
    fac = facility(callsign)
    if fac in CIRCLE_NM and lat is not None:
        return {"kind": "circle", "nm": CIRCLE_NM[fac], "lat": lat, "lon": lon}
    if fac in GROUND and lat is not None:
        return {"kind": "point", "lat": lat, "lon": lon}
    if fac in ("CTR", "FSS", "APP", "DEP", ""):
        r = vatspy_range(callsign, firs, prefix)
        # APP bez lotniska (np. ESMM_IS_APP): FIR z VATSpy, zawsze jako przybliżenie
        return {**r, "exact": r["exact"] and fac in ("CTR", "FSS", "")} if r else None
    return None


# --- rodzaje wycinków sektorów z pliku .ese (warstwy mapy RADIO › GEO)
_ACC = re.compile(r"^EPWW([A-Z])(?:-[A-Z]+)?$")
_CTR = re.compile(r"^(EP[A-Z]{2})_M?CTR\d*$")
_TMA = re.compile(r"^(EP[A-Z]{2})_(?:[A-Z_]*TMA|APP_|DEP\d|DIR\d)|^CTA\d")
_FIS = re.compile(r"^FIS_|^[A-Z]{3}_FIS_|^EP[A-Z]{2}_ATZ|^EPTR\d|^EPWW-MIDSEA$")


def sector_kind(fir: str, name: str) -> str | None:
    """acc (sektory ACC EPWW), tma (TMA/APP/CTA), ctr, fis (FIS, ATZ, TRA), nb (FIR sąsiedni);
    None = wycinek techniczny sąsiada (TECH …, T-…), którego nie rysujemy."""
    fir, name = fir.upper(), name.upper()
    if fir != "EPWW":
        return None if name.startswith(("TECH ", "T-")) else "nb"
    if _ACC.match(name):
        return "acc"
    if _CTR.match(name):
        return "ctr"
    if _FIS.match(name):
        return "fis"
    return "tma"


EP_CITY = {"EPWA": "Warszawa", "EPKK": "Kraków", "EPGD": "Gdańsk", "EPPO": "Poznań", "EPKT": "Katowice", "EPWR": "Wrocław",
           "EPLL": "Łódź", "EPLB": "Lublin", "EPRZ": "Rzeszów", "EPSC": "Szczecin", "EPSY": "Olsztyn-Mazury",
           "EPBY": "Bydgoszcz", "EPZG": "Zielona Góra", "EPMO": "Modlin", "EPRA": "Radom", "EPDE": "Dęblin",
           "EPKS": "Krzesiny"}
FIS_REGION = {"WAW": "Warszawa", "GDN": "Gdańsk", "KRK": "Kraków", "POZ": "Poznań"}


def sector_group(fir: str, name: str, kind: str | None = None) -> str:
    """Nazwa zbiorcza wycinka do listy "kto co obsługuje": TMA Warszawa, CTR Kraków, FIS Gdańsk, ATZ EPBA, CTA 05,
    sąsiedzi bez numeru części (ESMM 8-3 → ESMM 8, EDWWFLG1 → EDWWFLG)."""
    kind = kind or sector_kind(fir, name)
    n = name.upper()
    if not kind:
        return n
    if kind == "nb":
        g = re.sub(r"(?:[-_ ]?PART\d*|[-_ ]\d|(?<=[A-Z])\d)$", "", n).strip() or n
        # krótkie nazwy bez kodu ICAO (LZBB "CTR", LKAA "NL") z kodem FIR-u
        return g if g[:2] == fir[:2] or re.match(r"^[ELU][A-Z]{3}[ _]", g) or len(g) > 12 else f"{fir} {g}"
    if kind == "acc":
        return f"Sektor {_ACC.match(n).group(1)}"
    if m := re.match(r"^CTA(\d+)", n):
        return f"CTA {m.group(1)}"
    if n == "EPWW-MIDSEA":
        return "FIS Gdańsk (MIDSEA)"
    if kind == "fis" and (m := re.match(r"^(?:FIS_)?([A-Z]{3})(?:_FIS)?_", n)):
        return f"FIS {FIS_REGION.get(m.group(1), m.group(1))}"
    if m := re.match(r"^(EP[A-Z]{2})_ATZ", n):
        return f"ATZ {m.group(1)}"
    if n.startswith("EPTR"):
        return f"TRA {re.sub(r'[A-Z]$', '', n)}"
    icao = n[:4]
    # TMA Poznań dzieli się na N i S z osobną kolejnością przejmowania (tma_topdown w ownership.json)
    part = m.group(1) if kind == "tma" and (m := re.match(r"^EP[A-Z]{2}_TMA_([NS])_", n)) else ""
    return f"{kind.upper()} {EP_CITY.get(icao, icao)} {part}".rstrip()
