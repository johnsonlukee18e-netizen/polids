"""0.14.3: kolejność przejmowania w data/seed/ownership.json = listy OWNER z data/import/EPWW-Sector.ese.

Właściciel projektu 21.11.2026: "rób to wszystko według sct a nie tabelki" (tabela om.plvacc.pl gubiła ALH w T MID,
więc w konfiguracji 2U T MID dostawało ALL) i "jedynie to DBT które poprawiałem 14.11 zostaw" – D HIGH zostaje
z DBT przed DBF (ACC Ownership Manager), reszta dokładnie jak w pliku sektorowym. Przy nowym AIRAC ten test
pokaże, co trzeba poprawić w ownership.json."""
import json
import re
from pathlib import Path

from backend.app.importers.ese import ese_sections, parse_positions, read_airspace
from backend.app.importers.sct import read_text

ROOT = Path(__file__).resolve().parents[2]
OWN = json.loads((ROOT / "data/seed/ownership.json").read_text("utf-8"))
SECS = ese_sections(read_text(ROOT / "data/import/EPWW-Sector.ese"))
ID2CS = {p["position_id"]: p["callsign"] for p in parse_positions(SECS["[POSITIONS]"])}
SECTORS = read_airspace(SECS["[AIRSPACE]"])[1]
ACC_CS = re.compile(r"^EPWW_[A-Z0-9_]*(?:CTR|FSS)$")
SHORT = {cs: cs.removeprefix("EPWW_").removesuffix("_CTR") for cs in ID2CS.values()}
# jedyny świadomy wyjątek od pliku: poprawka właściciela projektu z 14.11.2026
D_HIGH = ["EPWW_DBT_CTR", "EPWW_DT_CTR", "EPWW_DTC_CTR", "EPWW_DBF_CTR", "EPWW_N_CTR", "EPWW_ALH_CTR",
          "EPWW_D_CTR", "EPWW_ALL_CTR"]


def chain(owners: str) -> list[str]:
    return [ID2CS[i] for i in owners.split(":") if i]


def ese_acc() -> dict[tuple[str, str], list[list[str]]]:
    """{(litera, warstwa): [różne listy OWNER wycinków sektora EPWWx w tej warstwie]}."""
    out: dict[tuple[str, str], list[list[str]]] = {}
    for s in SECTORS:
        # EPWWx oraz wycinki z przyrostkiem (EPWWR-N, EPWWR-S), tak jak w aplikacji
        m = re.fullmatch(r"EPWW([A-Z])(?:-[A-Z]+)?", s["name"].strip())
        if s["fir"] != "EPWW" or not m:
            continue
        layers = [ly for ly, lim in OWN["layers"].items()
                  if s["lower_ft"] >= lim["lower_ft"] and s["upper_ft"] <= lim["upper_ft"]]
        # każdy wycinek ACC mieści się dokładnie w jednej warstwie; inaczej porównanie by go pominęło
        assert len(layers) == 1, (s["name"], s["lower_ft"], s["upper_ft"], layers)
        ch = chain(s["owners"])
        lst = out.setdefault((m.group(1), layers[0]), [])
        if ch not in lst:
            lst.append(ch)
    return out


def test_acc_chains_follow_ese():
    ese = ese_acc()
    assert {k for k in ese} == {(x, ly) for x, lys in OWN["sectors"].items() for ly in lys}
    for (letter, layer), chains in sorted(ese.items()):
        # każdy wycinek warstwy ma tę samą kolejność, więc jedna lista na sektor i warstwę wystarcza
        assert len(chains) == 1, (letter, layer, chains)
        want = D_HIGH if (letter, layer) == ("D", "HIGH") else chains[0]
        assert OWN["sectors"][letter][layer] == want, (letter, layer)
    # wyjątek D HIGH naprawdę różni się od pliku i jest opisany w ese_differences
    assert ese[("D", "HIGH")][0] != D_HIGH
    assert [d.split(":")[0] for d in OWN["ese_differences"]] == ["D HIGH"] and OWN["source"] == "ese"
    # od 0.14.3 tabela om nie jest źródłem, więc plik nie wskazuje już na nią
    assert "url" not in OWN


def test_t_mid_has_alh_before_all():
    # zgłoszenie 21.11.2026: w 2U (ALL+ALH) T MID należy do ALH, tak jak każdy inny sektor MID
    for letter, layers in OWN["sectors"].items():
        mid = layers["MID"]
        assert mid.index("EPWW_ALH_CTR") < mid.index("EPWW_ALL_CTR"), letter


def test_tma_topdown_follows_ese():
    """Część ACC kolejności TMA (tma_topdown) = stanowiska ACC z listy OWNER każdego wycinka TMA w pliku."""
    for key, v in OWN["tma_topdown"].items():
        found = []
        for s in SECTORS:
            if s["fir"] == "EPWW" and any(s["name"].startswith(p) for p in v["ese_prefixes"]):
                acc = [cs for cs in chain(s["owners"]) if ACC_CS.match(cs)]
                if acc not in found:
                    found.append(acc)
        assert found == [v["chain"]], (key, [[SHORT[c] for c in f] for f in found])
