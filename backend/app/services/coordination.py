"""COORDINATION (0.12.3): porozumienia LOA i LOP w jednym miejscu, jak „Agreements” w ATCISS (VATSIM Germany).

Źródła (wszystkie w data/seed, czytane przez seed_json – poprawiony plik widać bez restartu):
- coordination.json: rejestr dokumentów (nazwa wyświetlana, PDF, FIR-y, sektory, AIRAC, wersja) i tabela etykiet
  polskich sektorów z LOA (ep_sectors); LOP i uzupełnienia mają przekazania wpisane w dokumencie (agreements),
- loa.json: przekazania z LOA z sąsiadami (wyciąg z PDF-ów, ten sam plik co panel LOA w RADIO),
- ownership.json: kolejność przejmowania sektorów ACC i TMA (om.plvacc.pl) – kto „ma” sektor z LOA.

Każde przekazanie zamieniamy na wiersz jak w ATCISS: lotniska z pola traffic (ARR/DEP), FL i kierunek zmiany
poziomu z pola level (↑ = C, ↓ = D), strona polska (ep) i sąsiada (nb). Stanowisko obsługuje etykietę, gdy jest
w kolejności przejmowania jej sektora, a nikt przed nim nie jest online."""

import re

from .airac import current_airac

DIRS = ("out", "in")
TYPES = ("LOA", "LOP")
ICAO = re.compile(r"^[A-Z]{4}$")
COP = re.compile(r"^[A-Z]{2,5}$")            # punkt koordynacyjny (ALUKA, BODLA); "-", "wszystkie COP" – bez punktu
FL = re.compile(r"FL\s?(\d{2,3})")
ACC_SECTOR = re.compile(r"^([A-Z]) (LOW|MID|HIGH)$")
ACC_CS = re.compile(r"^EPWW_[A-Z0-9]+_CTR$")
UNKNOWN = "sektor nieokreślony w LOA"
GROUPS = (("ACC", "ACC / FIR"), ("APP", "APP / zbliżanie"), ("TWR", "TWR / lotnisko"))


# --- parsowanie pól z loa.json
def parse_traffic(text: str) -> tuple[list[str], list[str]]:
    """Lotniska z pola traffic: "ARR EPKS, EPPW" → ades, "DEP EDDC, EDAB" → adep, "DEP EPRZ, ARR UKLL" → oba.
    Człon z czymś innym niż kod ICAO ("ARR pozostałe LKAA") pomijamy: zostaje tylko tekst do wyświetlenia."""
    adep: list[str] = []
    ades: list[str] = []
    mode = None
    for seg in str(text or "").split(","):
        words = seg.split()
        if words and words[0].upper() in ("ARR", "DEP"):
            mode = words[0].upper()
            words = words[1:]
        if not words or mode is None or not all(ICAO.match(w) for w in words):
            continue
        target = ades if mode == "ARR" else adep
        target.extend(w for w in words if w not in target)
    return adep, ades


def parse_level(text: str) -> tuple[int | None, str | None]:
    """Poziom przekazania: pierwszy FL z tekstu (FL250, "↑ FL230-FL270" → 230, "max. FL350" → 350) i kierunek:
    ↑ = C (we wznoszeniu), ↓ = D (w zniżaniu). Tekst bez FL ("uzgodniony z EPWW") → None (koordynacja indywidualna)."""
    s = str(text or "").strip()
    transfer = "C" if s.startswith("↑") else "D" if s.startswith("↓") else None
    m = FL.search(s)
    return (int(m.group(1)) if m else None), transfer


def cop_key(cop: str) -> str:
    """Oznaczenie punktu do dopasowania i listy podpowiedzi; "", "-", "wszystkie COP" → ""."""
    c = str(cop or "").strip().upper()
    return c if COP.match(c) else ""


# --- etykiety polskich sektorów → kolejności przejmowania
def ref_chain(ref: str, own: dict) -> list[str] | None:
    m = ACC_SECTOR.match(ref)
    if m:
        chain = (own.get("sectors") or {}).get(m.group(1), {}).get(m.group(2))
        return list(chain) if chain else None
    tma = (own.get("tma_topdown") or {}).get(ref)
    return list(tma["chain"]) if tma and tma.get("chain") else None


def _candidates(label: str) -> list[str]:
    """Warianty etykiety do szukania w tabeli: całość, bez przedrostka EPWW, bez nawiasu, sam nawias.
    "B LOW (BWW)" → B LOW; "Rzeszów Tower (TRZ)" → TRZ; "EPWW J LOW" → J LOW."""
    s = " ".join(str(label or "").split())
    out = [s]
    if s.upper().startswith("EPWW "):
        out.append(s[5:])
    m = re.match(r"^(.*?)\s*\(([^)]*)\)\s*$", s)
    if m:
        out += [m.group(1), m.group(2)]
        if m.group(1).upper().startswith("EPWW "):
            out.append(m.group(1)[5:])
    return [x.strip() for x in out if x.strip()]


def resolve_label(label: str, aliases: dict, own: dict) -> tuple[str, dict[str, list[str]]] | None:
    """Etykieta polskiego sektora z LOA → (etykieta z tabeli, {klucz kolejności: [stanowiska]}).

    Najpierw tabela ep_sectors z coordination.json (stare nazwy, TMA ze stanowiskami APP/TWR), potem wprost
    sektory ACC "X LOW|MID|HIGH" i TMA z ownership.json. Klucz kolejności: etykieta albo "etykieta/sektor",
    gdy etykieta obejmuje kilka sektorów. Nie da się przypisać (puste, FIS) → None."""
    for cand in _candidates(label):
        entry = aliases.get(cand)
        if isinstance(entry, dict):
            refs = [r for r in entry.get("refs") or [] if isinstance(r, str)]
            local = [cs for cs in entry.get("local") or [] if isinstance(cs, str)]
        elif ref_chain(cand, own):
            refs, local = [cand], []
        else:
            continue
        chains: dict[str, list[str]] = {}
        for ref in refs:
            base = ref_chain(ref, own)
            if base is None:
                continue
            chain = list(local) + [cs for cs in base if cs not in local]
            # bez stanowisk APP/TWR kolejność to sam sektor ("SWW" → R LOW, R MID)
            chains[ref if not local else cand if len(refs) == 1 else f"{cand}/{ref}"] = chain
        if chains:
            return cand, chains
    return None


def register(chains: dict[str, list[str]], new: dict[str, list[str]]) -> list[str]:
    """Dopisuje kolejności do wspólnego słownika i zwraca ich klucze; ta sama kolejność pod inną etykietą
    ("EPPO S" i "EPPO-S" z dwóch LOA) dostaje klucz zapisany wcześniej."""
    keys = []
    for k, chain in new.items():
        # sektory ACC zostają pod własną nazwą (N MID i N HIGH mają tę samą kolejność, ale to dwa sektory)
        same = None if ACC_SECTOR.match(k) else next(
            (x for x, c in chains.items() if c == chain and not ACC_SECTOR.match(x)), None)
        key = same or k
        chains.setdefault(key, chain)
        if key not in keys:
            keys.append(key)
    return keys


def owns(chain: list[str], position: str, online: set[str]) -> bool:
    """Stanowisko obsługuje sektor: jest w jego kolejności, a nikt przed nim nie jest online
    (bez nikogo online: każdy sektor, w którego kolejności jest)."""
    if position not in chain:
        return False
    return not any(cs in online for cs in chain[:chain.index(position)])


def owned_keys(chains: dict[str, list[str]], position: str, online: set[str]) -> list[str]:
    return [k for k, ch in chains.items() if owns(ch, position, online)]


def row_applies(row: dict, owned: set[str], position: str) -> bool:
    """Wiersz dotyczy stanowiska, gdy obsługuje ono któryś z sektorów wiersza; wiersz bez sektorów
    (nieokreślony i bez sektorów z LOA) – każde stanowisko ACC."""
    if not row["ep_chains"]:
        return bool(ACC_CS.match(position))
    return any(k in owned for k in row["ep_chains"])


# --- budowa odpowiedzi
def _str(v) -> str:
    return v.strip() if isinstance(v, str) else ""


def _fir_scope(fir: dict, aliases: dict, own: dict, chains: dict) -> tuple[list[str], list[str]]:
    """Polskie sektory wymienione w LOA (stanowiska strony EP, bez FIS): zakres wierszy bez sektora."""
    labels, keys = [], []
    for p in fir.get("positions") or []:
        if not isinstance(p, dict) or p.get("side") != "EP" or "FIS" in _str(p.get("sector")).upper():
            continue
        hit = resolve_label(_str(p.get("sector")), aliases, own)
        if not hit:
            continue
        lab, ch = hit
        if lab not in labels:
            labels.append(lab)
        keys += [k for k in register(chains, ch) if k not in keys]
    return labels, keys


def _row(t: dict, *, doc: dict | None, fir: str, idx: str, aliases: dict, own: dict, chains: dict,
         scope: tuple[list[str], list[str]], lop: bool) -> dict:
    d = _str(t.get("dir"))
    frm, to = _str(t.get("from")), _str(t.get("to"))
    ep, nb = (frm, to) if d == "out" else (to, frm)
    adep, ades = parse_traffic(t.get("traffic"))
    level, transfer = parse_level(t.get("level"))
    keys: list[str] = []
    ep_label = ""
    # w LOP obie strony to sektory EPWW
    for side in ([ep, nb] if lop else [ep]):
        hit = resolve_label(side, aliases, own) if side else None
        if hit:
            ep_label = ep_label or hit[0]
            keys += [k for k in register(chains, hit[1]) if k not in keys]
    unknown = not ep
    if unknown:
        keys = list(scope[1])
    return {
        "id": idx, "doc": doc["id"] if doc else "", "type": doc["type"] if doc else "LOA", "fir": fir, "dir": d,
        "cop": _str(t.get("cop")), "cop_key": cop_key(t.get("cop")), "traffic": _str(t.get("traffic")),
        "adep": adep, "ades": ades, "level_text": _str(t.get("level")), "level": level, "transfer": transfer,
        "from": frm, "to": to, "ep": ep, "ep_label": ep_label, "nb": nb, "conditions": _str(t.get("conditions")),
        "ep_chains": keys, "ep_unknown": unknown, "ep_unmapped": bool(ep) and not keys,
        "scope": list(scope[0]) if unknown else [],
    }


def build(coord: dict, loa: dict, own: dict, *, airac: str | None = None,
          names: dict[str, dict] | None = None, file_exists=None) -> dict:
    """Cała odpowiedź GET /api/coordination (bez wyboru stanowiska).

    coord, loa, own: zawartość coordination.json, loa.json i ownership.json; airac: bieżący cykl (domyślnie dziś);
    names: {znak: {name, frequency}} z bazy stanowisk; file_exists(ścieżka w data/docs) → bool."""
    airac = airac or current_airac()["ident"]
    aliases = coord.get("ep_sectors") if isinstance(coord.get("ep_sectors"), dict) else {}
    loa_firs = loa.get("firs") if isinstance(loa.get("firs"), dict) else {}
    chains: dict[str, list[str]] = {}
    documents, rows, errors = [], [], []
    doc_of_fir: dict[str, dict] = {}
    # najpierw etykiety z przekazań (EPPO S, EPGD APP): nazwy kluczy jak w tabelach, nie jak na liście stanowisk LOA
    for f in loa_firs.values():
        for t in (f.get("transfers") or []) if isinstance(f, dict) else []:
            ep = _str(t.get("from") if t.get("dir") == "out" else t.get("to")) if isinstance(t, dict) else ""
            if ep and (hit := resolve_label(ep, aliases, own)):
                register(chains, hit[1])
    for d in coord.get("documents") or []:
        if not isinstance(d, dict) or not _str(d.get("id")):
            continue
        typ = _str(d.get("type")).upper()
        doc = {
            "id": _str(d["id"]), "type": typ if typ in TYPES else "LOA", "name": _str(d.get("name")) or _str(d.get("file")),
            "file": _str(d.get("file")), "firs": [f for f in d.get("firs") or [] if isinstance(f, str)],
            "positions": [p for p in d.get("positions") or [] if isinstance(p, str)],
            "airac": _str(d.get("airac")), "effective": _str(d.get("effective")), "version": _str(d.get("version")),
            "loa": [k for k in d.get("loa") or [] if isinstance(k, str)], "note": _str(d.get("note")),
        }
        doc["url"] = f"/files/docs/{doc['file']}" if doc["file"] else ""
        doc["current"] = bool(doc["airac"]) and doc["airac"] == airac
        doc["exists"] = bool(doc["file"]) and (file_exists(doc["file"]) if file_exists else True)
        n = 0
        for key in doc["loa"]:
            if key not in loa_firs:
                errors.append(f"{doc['id']}: brak FIR {key} w loa.json")
                continue
            doc_of_fir.setdefault(key, doc)
        own_fir = next((f for f in doc["firs"] if f != "EPWW"), "EPWW")
        for i, t in enumerate(d.get("agreements") or []):
            if not isinstance(t, dict) or _str(t.get("dir")) not in DIRS:
                continue
            fir = _str(t.get("fir")) or (own_fir if doc["type"] == "LOA" else "EPWW")
            rows.append(_row(t, doc=doc, fir=fir, idx=f"{doc['id']}-{i}", aliases=aliases, own=own, chains=chains,
                             scope=([], []), lop=doc["type"] == "LOP"))
            n += 1
        doc["count"] = n
        documents.append(doc)
    notes = {}
    for key, f in loa_firs.items():
        if not isinstance(f, dict):
            continue
        doc = doc_of_fir.get(key)
        scope = _fir_scope(f, aliases, own, chains)
        for i, t in enumerate(f.get("transfers") or []):
            if isinstance(t, dict) and _str(t.get("dir")) in DIRS:
                rows.append(_row(t, doc=doc, fir=key, idx=f"{key}-{i}", aliases=aliases, own=own, chains=chains,
                                 scope=scope, lop=False))
                if doc:
                    doc["count"] += 1
        notes[key] = {"title": _str(f.get("title")), "version": _str(f.get("version")),
                      "silent": [s for s in f.get("silent") or [] if isinstance(s, str)],
                      "vfr": [s for s in f.get("vfr") or [] if isinstance(s, str)],
                      "other": [s for s in f.get("other") or [] if isinstance(s, str)]}
    firs = []
    for r in rows:
        if r["fir"] not in firs:
            firs.append(r["fir"])
        if r["ep_unmapped"]:
            errors.append(f"{r['id']}: nieznany sektor EPWW „{r['ep']}” (dopisz go do ep_sectors w coordination.json)")
    return {"current_airac": airac, "documents": documents, "agreements": rows, "chains": chains,
            "positions": positions(chains, own, names or {}, loa_firs), "firs": firs, "notes": notes,
            "cops": sorted({r["cop_key"] for r in rows if r["cop_key"]}), "unknown_label": UNKNOWN, "errors": errors}


def _kind(cs: str) -> str:
    suffix = cs.rsplit("_", 1)[-1]
    if ACC_CS.match(cs):
        return "ACC"
    return "APP" if suffix in ("APP", "DEP") else "TWR"


def positions(chains: dict[str, list[str]], own: dict, names: dict[str, dict], loa_firs: dict) -> list[dict]:
    """Stanowiska do wyboru: wszystkie z kolejności przejmowania sektorów z LOA (ACC, APP, TWR), z sektorami,
    które mogą obsługiwać. Nazwa i częstotliwość z bazy (.ese), dalej z ownership.json i loa.json."""
    acc = own.get("acc_positions") or {}
    from_loa = {}
    for f in loa_firs.values():
        for p in (f.get("positions") or []) if isinstance(f, dict) else []:
            if isinstance(p, dict) and p.get("side") == "EP" and _str(p.get("callsign")):
                from_loa.setdefault(p["callsign"], p)
    sectors: dict[str, list[str]] = {}
    for key, chain in chains.items():
        for cs in chain:
            lst = sectors.setdefault(cs, [])
            if key not in lst:
                lst.append(key)
    order = {k: i for i, (k, _) in enumerate(GROUPS)}
    out = []
    for cs, keys in sectors.items():
        n = names.get(cs) or {}
        lp = from_loa.get(cs) or {}
        a = acc.get(cs) or {}
        out.append({"callsign": cs, "kind": _kind(cs), "short": _str(a.get("short")) or cs.split("_")[0],
                    "name": _str(n.get("name")) or _str(lp.get("radio")),
                    "frequency": _str(n.get("frequency")) or _str(a.get("frequency")) or _str(lp.get("frequency")),
                    "sectors": keys})
    out.sort(key=lambda p: (order[p["kind"]], p["callsign"]))
    return out


def for_position(data: dict, position: str, online: set[str]) -> dict:
    """Wybór stanowiska: obsługiwane sektory (klucze kolejności) i przy każdym wierszu applies."""
    owned = owned_keys(data["chains"], position, online)
    owned_set = set(owned)
    rows = [r | {"applies": row_applies(r, owned_set, position)} for r in data["agreements"]]
    return data | {"agreements": rows, "selected": {"position": position, "online": sorted(online), "owned": owned}}
