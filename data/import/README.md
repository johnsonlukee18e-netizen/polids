# data/import

Tu wrzuć pliki z pakietu sektorowego EuroScope (PL vACC / GNG). Aplikacja wczyta je przy starcie
(i ponownie, gdy plik się zmieni). Pliki są trzymane w repozytorium, więc po sklonowaniu aplikacja ma od razu pełne dane.

| Plik | Co daje |
|------|---------|
| `*.sct` / `*.sct2` | VOR, NDB, FIX z sektorówki (mapa, trasy) |
| `*.ese` | stanowiska ATC i częstotliwości, sektory EPWW (mapa sektoryzacji) |
| `airway.txt` | drogi lotnicze (rozwijanie tras, warstwa na mapie) |
| `isec.txt` | punkty nawigacyjne z całego świata (trasy) |
| `icao.txt` | lotniska z całego świata (trasy) |
| `ICAO_Airlines.txt` | baza callsignów (zakładka CALLSIGN) |
| `GRpluginOperatorInfo.txt` | oznaczenie operatorów CARGO (`C`) i wojskowych (`Mil`) w zakładce CALLSIGN |
| `ICAO_Aircraft.json` | typy samolotów z WTC / RECAT-EU / wymiarami (zakładka AIRCRAFT) |

Ponowny import wszystkiego: `python -m backend.app.importers.seed --force`
