"""Ustawienia aplikacji. Każdą wartość można nadpisać zmienną środowiskową
z prefiksem POLIDS_ albo wpisem w pliku .env w katalogu głównym projektu."""

import re
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"

VERSION = "0.15.0"


def csv_set(value: str) -> set[str]:
    return {v.strip().upper() for v in value.split(",") if v.strip()}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="POLIDS_", env_file=ROOT_DIR / ".env", extra="ignore")

    name: str = "PolIDS"
    tagline: str = "Polish Integrated Display System · VATSIM PL vACC"
    public_url: str = "http://localhost:1337"  # bez / na końcu; z tego jest redirect_uri dla VATSIM Connect

    # none | dev (formularz testowy, tylko localhost) | vatsim
    auth_mode: str = "none"
    secret_key: str = ""  # wymagany przy vatsim, min. 32 znaki
    session_days: int = 7
    vatsim_auth_url: str = "https://auth.vatsim.net"  # sandbox: https://auth-dev.vatsim.net
    # API członków VATSIM (godziny pilota i ATC w OTHER › FLIGHT PLAN: /v2/members/{cid}/stats); bez klucza
    vatsim_api_url: str = "https://api.vatsim.net"
    vatsim_client_id: str = ""
    vatsim_client_secret: str = ""
    # CID-y administratorów, po przecinku. Resztę dostępu nadaje admin w zakładce ADMIN.
    auth_admin_cids: str = ""

    database_url: str = f"sqlite:///{(DATA_DIR / 'polids.db').as_posix()}"
    # lista dostępu - osobno, bo polids.db jest przebudowywana z repo
    state_database_url: str = f"sqlite:///{(DATA_DIR / 'state' / 'polids-state.db').as_posix()}"
    seed_dir: Path = DATA_DIR / "seed"
    docs_dir: Path = DATA_DIR / "docs"
    photos_dir: Path = DATA_DIR / "photos"
    # 0.14.2 (issue #35): zdjęcia typów dodane ręcznie (<ICAO>.jpg + <ICAO>.txt z autorem), w repozytorium i w obrazie
    # dockera, poza wolumenem data/photos; mają pierwszeństwo przed data/photos/ (services/photos.manual_photo)
    manual_photos_dir: Path = DATA_DIR / "photos-manual"
    # 0.15.0: zdjęcia typów wrzucone przez adminów w AIRCRAFT (podkatalog wolumenu data/photos: przetrwają przebudowę
    # obrazu); mają pierwszeństwo przed wszystkim innym (services/photos.uploaded_photo)
    uploaded_photos_dir: Path = DATA_DIR / "photos" / "uploaded"
    frontend_dir: Path = ROOT_DIR / "frontend"

    default_aerodrome: str = "EPWA"
    http_timeout: float = 10.0
    weather_cache_seconds: int = 120
    notam_cache_seconds: int = 600

    # METAR: "vatsim" (metar.vatsim.net, to samo co widzą piloci) albo "awc" (aviationweather.gov)
    metar_source: str = "vatsim"
    awc_api: str = "https://aviationweather.gov/api/data"
    vatsim_metar_url: str = "https://metar.vatsim.net/{icao}"

    # NOTAM z serwera PL vACC (ten sam format co w pliku konfiguracyjnym vATIS/Euroscope)
    notam_server: str = "https://cv.plvacc.pl/"
    notam_prefix: str = "notam/get-icao-format?icao="
    notam_suffix: str = "&read=true"
    # 0.15.0: zapasowe źródło NOTAM, gdy serwer PL vACC nie odpowiada: FAA NOTAM API (https://api.faa.gov, darmowe
    # konto, nagłówki client_id i client_secret). Bez obu kluczy zapasowe źródło jest wyłączone.
    faa_notam_url: str = "https://external-api.faa.gov/notamapi/v1/notams"
    faa_client_id: str = ""
    faa_client_secret: str = ""

    # 0.15.0: zdjęcia konkretnych samolotów po rejestracji (REG/ w planie lotu) z Planespotters.net Photo API. Bez klucza;
    # zdjęcia pobiera przeglądarka prosto z Planespotters (warunki API zabraniają zapisywania ich na serwerze).
    # Pusty adres wyłącza zdjęcia po rejestracji.
    planespotters_url: str = "https://api.planespotters.net/pub/photos"
    planespotters_cache_seconds: int = 6 * 3600  # warunki API: odpowiedź JSON najwyżej 24 h w cache
    # adres kontaktowy w User-Agent (warunki API Planespotters); pusty = POLIDS_PUBLIC_URL
    contact_url: str = ""
    # 0.15.0: zdjęcia typów wrzucane przez adminów w AIRCRAFT; największy plik w bajtach
    photo_upload_max_bytes: int = 2 * 1024 * 1024

    # Zewnętrzne strony osadzane w zakładkach. eAIP PAŻP: puste = katalog poprawki bieżącego cyklu AIRAC, liczony przy
    # każdym zapytaniu (services/eaip.py, np. eaipifr/AIRAC%20AMDT%2010-26_2026_10_01/index-v2.html) i sprawdzony
    # na serwerze PAŻP (cykl bez poprawki → poprzednia); wpisany adres wygrywa bez zmian (np. gdy PAŻP zmieni nazwy)
    aip_ifr_url: str = ""
    aip_vfr_url: str = ""
    aip_mil_url: str = ""
    inop_url: str = "https://om.plvacc.pl/"
    imgw_url: str = "https://awiacja.imgw.pl/"
    sectors_url: str = "https://plvacc.pl/acc-sectors/"
    performance_db_url: str = "https://learningzone.eurocontrol.int/ilp/customs/ATCPFDB/default.aspx"

    # Mapa: podkład lotniczy. OpenAIP wymaga darmowego klucza API (https://www.openaip.net)
    openaip_api_key: str = ""
    # Klucz CARTO do podkładów mapy (opcjonalny; trzymaj go tylko w lokalnym pliku .env, nie w repozytorium)
    carto_api_key: str = ""

    # vIFF (VATSIM IFPS/ETFMS/CDM, https://api.viffsys.com): odloty z EOBT/CTOT/statusem i ruch vs przepustowość sektorów.
    # Odczyt działa bez klucza. Klucz (nagłówek x-api-key) ustaw tylko, jeśli dostaniesz go od autora vIFF.
    viff_url: str = "https://api.viffsys.com"
    viff_api_key: str = ""
    viff_cache_seconds: int = 60
    # Lotniska z A-CDM (TOBT/TSAT/TTOT); vIFF podaje to też sam (isCdm), ta lista jest zapasowa
    viff_cdm_airports: str = "EPWA"
    # Prefiks "traffic volumes" (sektorów) vIFF dla FIR EPWW
    viff_sector_prefix: str = "EP"

    @property
    def public_origin(self) -> str:
        u = urlsplit(self.public_url)
        return f"{u.scheme}://{u.netloc}"

    @property
    def user_agent(self) -> str:
        # nagłówki HTTP muszą być w ASCII (Żółw -> Zolw)
        name = unicodedata.normalize("NFKD", self.name.replace("ł", "l").replace("Ł", "L"))
        name = re.sub(r"[^A-Za-z0-9._-]", "", name.encode("ascii", "ignore").decode()) or "polids"
        origin = (self.contact_url.strip() or self.public_origin).encode("ascii", "ignore").decode()
        return f"{name}/{VERSION} (VATSIM PL vACC; +{origin})"


settings = Settings()
