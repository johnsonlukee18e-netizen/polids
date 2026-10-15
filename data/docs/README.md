# data/docs

Wrzuć tu PDF-y (np. ICAO Doc 4444, Doc 9432, instrukcje PL vACC). Podfolder = kategoria w OTHER › DOCS,
np. `data/docs/ICAO/Doc4444.pdf`. Można je też dodać przez przycisk w aplikacji.
Pliki są trzymane w repozytorium.

LOA (`data/docs/LOA/`) i LOP (`data/docs/LOP/`, też w podfolderach: `LOP/LOP ACC/`, `LOP/LOP APP/`, `LOP/LOP TWR/`)
są w zakładce COORDINATION › DOKUMENTY, nie w OTHER › DOCS. Każdy taki PDF potrzebuje wpisu w
`data/seed/coordination.json` (nazwa wyświetlana, FIR-y, sektory, AIRAC, wersja; `file` = ścieżka dokładnie jak na dysku,
np. `LOP/LOP TWR/LOP TWR Okęcie.pdf`; opis pól w kluczu `_format`). Przekazania z LOA z sąsiadami są w
`data/seed/loa.json`, a LOP-ów – w polu `agreements` dokumentu. Spacje i polskie litery w nazwie są w porządku, ale
bez `_` i `-`. PDF bez wpisu też jest w COORDINATION › DOKUMENTY (nazwa z pliku, bez przekazań), a pod listą
dokumentów pojawia się uwaga „Do poprawienia w danych”.
