"""SQUAWK: kody SSR (Mode A) – cztery cyfry ósemkowe 0000–7777, zawsze jako napis (0100, nigdy 100 ani 100.0).

Pule z arkusza EUROCONTROL / ICAO EUR CAL (importers/squawk_cal.py) i kody specjalne leżą w data/seed/squawk.json.
Tu: sprawdzanie kodu, rozmiar puli, rozpoznawanie zakresów w komórkach arkusza i wyszukiwanie kodu w pulach
wszystkich kategorii (to samo liczy frontend w tabs/squawk.js)."""

import re

# kategorie pul (importer squawk_cal): epww = FIR EPWW przydziela sam (PA EUR-E, Unit EP), ccams = przydział
# centralny CCAMS, nato = pule wojskowe NATO, eur-e = pozostałe wpisy obszaru EUR-E (sąsiedzi i retencja)
CATEGORIES = ("epww", "ccams", "nato", "eur-e")

OCTAL4 = re.compile(r"^[0-7]{4}$")
# kod w komórce arkusza: 1–4 cyfry ósemkowe (liczba 100.0 z arkusza to po normalizacji "100" = 0100)
_SINGLE = re.compile(r"^[0-7]{1,4}$")
_RANGE = re.compile(r"^([0-7]{1,4})\s*(?:-|–|—|/|\.\.|TO)\s*([0-7]{1,4})$", re.I)
_SERIES2 = re.compile(r"^([0-7]{2})XX$", re.I)   # 01XX = 0100–0177 (cała seria 64 kodów)
_SERIES3 = re.compile(r"^([0-7]{3})X$", re.I)    # 010X = 0100–0107
_SPLIT = re.compile(r"[,;\n]+|\s+AND\s+|\s+&\s+", re.I)


def valid_code(code) -> bool:
    return isinstance(code, str) and bool(OCTAL4.match(code))


def code_value(code: str) -> int:
    return int(code, 8)


def pool_size(first: str, last: str) -> int:
    """Liczba kodów w puli first–last (włącznie), liczona ósemkowo: 0100–0177 = 64."""
    return code_value(last) - code_value(first) + 1


def in_pool(code: str, pool: dict) -> bool:
    return code_value(pool["from"]) <= code_value(code) <= code_value(pool["to"])


def parse_codes(text: str) -> list[tuple[str, str]] | None:
    """Zakresy kodów z komórki arkusza: "0100-0177", "0100 – 0177", "0100 TO 0177", "01XX", "010X", "0100", "100"
    (kod zapisany w arkuszu jako liczba), kilka zakresów po przecinku, średniku albo w nowych wierszach.
    None: to nie są kody SSR (cyfra 8/9, tekst, odwrócony zakres)."""
    parts = [p.strip() for p in _SPLIT.split(str(text or "").strip()) if p.strip()]
    if not parts:
        return None
    out = []
    for p in parts:
        if _SINGLE.match(p):
            out.append((p.zfill(4), p.zfill(4)))
        elif m := _RANGE.match(p):
            a, b = m.group(1).zfill(4), m.group(2).zfill(4)
            if code_value(a) > code_value(b):
                return None
            out.append((a, b))
        elif m := _SERIES2.match(p):
            out.append((m.group(1) + "00", m.group(1) + "77"))
        elif m := _SERIES3.match(p):
            out.append((m.group(1) + "0", m.group(1) + "7"))
        else:
            return None
    return out


def _pool(p) -> dict | None:
    if not isinstance(p, dict) or not valid_code(p.get("from")):
        return None
    last = p.get("to") or p["from"]
    if not valid_code(last) or code_value(last) < code_value(p["from"]):
        return None
    # bez kategorii (plik sprzed podziału na kategorie): pula EPWW
    cat = p.get("category") if isinstance(p.get("category"), str) and p.get("category") else "epww"
    return {**p, "to": last, "count": pool_size(p["from"], last), "category": cat}


def _order(p: dict) -> tuple:
    cat = CATEGORIES.index(p["category"]) if p["category"] in CATEGORIES else len(CATEGORIES)
    row = p.get("row") if isinstance(p.get("row"), int) else 0
    return cat, code_value(p["from"]), code_value(p["to"]), str(p.get("unit") or ""), row


def normalize(data) -> dict:
    """Treść squawk.json dla /api/squawk: pule z poprawnymi kodami posortowane po kategorii i kodzie (count
    przeliczony, brak kategorii = epww), kody specjalne z poprawnym kodem."""
    data = data if isinstance(data, dict) else {}
    pools = sorted((x for x in map(_pool, data.get("pools") or []) if x), key=_order)
    special = [s for s in data.get("special") or [] if isinstance(s, dict) and valid_code(s.get("code"))]
    meta = data.get("meta")
    return {"note": data.get("_uwaga") or None, "meta": meta if isinstance(meta, dict) else None,
            "pools": pools, "special": special}


def lookup(data: dict, code: str) -> dict:
    """Znaczenie kodu: wpisy z listy kodów specjalnych i wszystkie pule (każdej kategorii), w których leży
    (data = wynik normalize)."""
    return {"code": code, "special": [s for s in data["special"] if s["code"] == code],
            "pools": [p for p in data["pools"] if in_pool(code, p)]}
