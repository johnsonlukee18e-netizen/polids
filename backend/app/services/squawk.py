"""SQUAWK: kody SSR (Mode A) – cztery cyfry ósemkowe 0000–7777, zawsze jako napis (0100, nigdy 100 ani 100.0).

Pule FIR EPWW z arkusza EUROCONTROL / ICAO EUR CAL (importers/squawk_cal.py) i kody specjalne leżą w
data/seed/squawk.json. Tu: sprawdzanie kodu, rozmiar puli, rozpoznawanie zakresów w komórkach arkusza
i wyszukiwanie kodu w pulach (to samo liczy frontend w tabs/squawk.js)."""

import re

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
    return {**p, "to": last, "count": pool_size(p["from"], last)}


def normalize(data) -> dict:
    """Treść squawk.json dla /api/squawk: pule z poprawnymi kodami posortowane po kodzie (count przeliczony),
    kody specjalne z poprawnym kodem; status = notatka "_status" (np. import CAL jeszcze nie zrobiony)."""
    data = data if isinstance(data, dict) else {}
    pools = [x for x in map(_pool, data.get("pools") or []) if x]
    pools.sort(key=lambda p: (code_value(p["from"]), code_value(p["to"]), str(p.get("unit") or "")))
    special = [s for s in data.get("special") or [] if isinstance(s, dict) and valid_code(s.get("code"))]
    meta = data.get("meta")
    return {"status": data.get("_status") or None, "note": data.get("_uwaga") or None,
            "meta": meta if isinstance(meta, dict) else None, "pools": pools, "special": special}


def lookup(data: dict, code: str) -> dict:
    """Znaczenie kodu: wpisy z listy kodów specjalnych i pule, w których leży (data = wynik normalize)."""
    return {"code": code, "imported": bool(data["pools"]),
            "special": [s for s in data["special"] if s["code"] == code],
            "pools": [p for p in data["pools"] if in_pool(code, p)]}
