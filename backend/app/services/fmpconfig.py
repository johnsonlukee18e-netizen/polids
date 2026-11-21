"""OTHER › FMP: konfiguracje sektorów ACC EPWW (0.14.0, Marek: "Zedytuj zakładkę FMP aby użytkownik mógł wybrać dane
konfiguracje"; GET /api/radio/configs).

Tabela konfiguracji jest w data/seed/fmp_configs.json: kod (1X … 5X), napis jak w tabeli Marka ("ALL+NFIR") i otwarte
stanowiska pod nazwami z tabeli (ALL, SFIR, NFIR, EFIR, DTC, DBFG, JR, ALH, FG, DBT, TCJ, NE → stanowiska ACC
z ownership.json). Warstwa sektora (LOW, MID, HIGH) należy w konfiguracji do pierwszego stanowiska swojej kolejności
przejmowania (ownership.json sectors), które jest w tej konfiguracji otwarte – ta sama zasada, którą RADIO stosuje do
stanowisk online (radioboard.first_online, acc_sectors). Warstwa bez żadnego otwartego stanowiska kolejności to "free"
(nikt jej w tej konfiguracji nie obsługuje).
Konfiguracja teraz (current): zestaw stanowisk ACC EPWW online, dopasowanych po częstotliwości jak na RADIO (0.13.6:
on_frequency + match_positions, 199.998 się nie liczy), i kod konfiguracji o dokładnie tym zestawie (None = żadna)."""

import logging
import re

from .radioboard import LAYERS, acc_sectors, first_online, is_on

log = logging.getLogger("polids.fmp")
# kod konfiguracji: cyfra (liczba stanowisk) i litera, np. 2N
CODE = re.compile(r"^[1-9][A-Z]$")


def table_names(data: dict, own: dict) -> dict[str, str]:
    """Nazwy z tabeli → znak stanowiska ACC EPWW; tylko stanowiska z ownership.json (acc_positions)."""
    acc = own.get("acc_positions") or {}
    names = (data or {}).get("positions") or {}
    return {str(n): cs for n, cs in names.items() if isinstance(cs, str) and cs in acc}


def owned(callsigns, own: dict) -> tuple[dict[str, dict[str, list[str]]], dict[str, list[str]]]:
    """Warstwy sektorów stanowisk zestawu: ({znak: {LOW: [litery], MID: [...], HIGH: [...]}}, {warstwa: litery bez
    nikogo}). Właściciel warstwy = pierwsze stanowisko jej kolejności przejmowania, które jest w zestawie."""
    on = dict.fromkeys(callsigns, True)
    out = {cs: {ly: [] for ly in LAYERS} for cs in on}
    free: dict[str, list[str]] = {ly: [] for ly in LAYERS}
    for s in acc_sectors(own):
        o = first_online(s["chain"], on)
        (out[o][s["layer"]] if o else free[s["layer"]]).append(s["letter"])
    return out, free


def configs(data: dict, own: dict) -> list[dict]:
    """Konfiguracje z fmp_configs.json z przeliczonymi warstwami: [{code, label, size, positions: [{name, callsign,
    short, frequency, sectors: {LOW, MID, HIGH}}], free: {LOW, MID, HIGH}}] w kolejności tabeli. Wpis z nieznaną nazwą
    stanowiska, złym albo powtórzonym kodem pomijamy (wpis w logu), reszta zostaje."""
    acc = own.get("acc_positions") or {}
    names = table_names(data, own)
    out, seen = [], set()
    for c in (data or {}).get("configs") or ():
        if not isinstance(c, dict):
            continue
        code = str(c.get("code") or "").strip().upper()
        pos = [str(n) for n in c.get("positions") or ()]
        if not CODE.match(code) or code in seen or not pos or any(n not in names for n in pos) \
                or len({names[n] for n in pos}) != len(pos):
            log.warning("FMP: pomijam konfigurację %r z data/seed/fmp_configs.json", c.get("code"))
            continue
        seen.add(code)
        by, free = owned([names[n] for n in pos], own)
        out.append({"code": code, "label": str(c.get("label") or "+".join(pos)), "size": len(pos),
                    "positions": [{"name": n, "callsign": names[n], "short": (acc[names[n]] or {}).get("short") or n,
                                   "frequency": (acc[names[n]] or {}).get("frequency") or "",
                                   "sectors": by[names[n]]} for n in pos],
                    "free": free})
    return out


def current(online: dict, own: dict, cfgs: list[dict], data: dict | None = None) -> dict:
    """Konfiguracja teraz dla stanowisk online (online: znak stanowiska → kontroler, jak /api/radio/board): positions =
    stanowiska ACC EPWW online (najpierw w kolejności nazw tabeli, potem pozostałe po skrócie), names = ich nazwy jak
    w tabeli (inne stanowiska: skrót z ownership.json, np. C), code = konfiguracja o dokładnie tym zestawie (None:
    żadna albo nikt online)."""
    acc = own.get("acc_positions") or {}
    names = table_names(data or {}, own)
    order = {cs: i for i, cs in enumerate(names.values())}
    label = {cs: n for n, cs in names.items()}
    on = sorted((cs for cs in acc if is_on(cs, online)),
                key=lambda cs: (order.get(cs, len(order)), (acc[cs] or {}).get("short") or cs))
    code = next((c["code"] for c in cfgs if {p["callsign"] for p in c["positions"]} == set(on)), None) if on else None
    return {"positions": on, "names": [label.get(cs) or (acc[cs] or {}).get("short") or cs for cs in on], "code": code}
