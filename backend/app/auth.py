"""Logowanie: VATSIM Connect (OAuth2) na serwerze, formularz "dev" do testów lokalnych, "none" bez logowania.
Sesja w podpisanym ciasteczku (SessionMiddleware)."""

import html
import logging
import secrets
import time
from urllib.parse import urlencode, urlsplit

import httpx
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from . import access
from .config import VERSION, csv_set, settings

log = logging.getLogger("polids.auth")
router = APIRouter(prefix="/auth", tags=["auth"])

MODES = ("none", "dev", "vatsim")
RATINGS = {-1: "INA", 0: "SUS", 1: "OBS", 2: "S1", 3: "S2", 4: "S3", 5: "C1", 6: "C2", 7: "C3",
           8: "I1", 9: "I2", 10: "I3", 11: "SUP", 12: "ADM"}
# dostępne bez logowania (manifest PWA przeglądarka pobiera bez ciasteczek)
PUBLIC_PREFIXES = ("/auth/", "/static/icons/")
PUBLIC_PATHS = {"/healthz", "/manifest.webmanifest", "/sw.js", "/favicon.ico", "/static/offline.html"}
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
_DEV_SECRET = "dev-only-insecure-secret-do-not-use-on-a-server"  # noqa: S105


def check_settings() -> str:
    """Zwraca klucz sesji. Przy złej konfiguracji rzuca wyjątek, żeby serwer nie wstał bez logowania."""
    mode = settings.auth_mode
    if mode not in MODES:
        raise RuntimeError(f"POLIDS_AUTH_MODE={mode!r}, dozwolone: {', '.join(MODES)}")
    host = (urlsplit(settings.public_url).hostname or "").lower()
    if mode == "dev" and not (host in LOCAL_HOSTS or host.endswith((".localhost", ".test"))):
        raise RuntimeError(f"POLIDS_AUTH_MODE=dev działa tylko lokalnie (POLIDS_PUBLIC_URL={settings.public_url})")
    if mode == "vatsim":
        missing = [n for n in ("vatsim_client_id", "vatsim_client_secret") if not getattr(settings, n)]
        if missing:
            raise RuntimeError("Brak ustawień: " + ", ".join("POLIDS_" + m.upper() for m in missing))
        if len(settings.secret_key) < 32:
            raise RuntimeError("POLIDS_SECRET_KEY musi mieć min. 32 znaki (openssl rand -hex 32)")
        return settings.secret_key
    if not settings.secret_key:
        log.warning("Brak POLIDS_SECRET_KEY, używam klucza deweloperskiego")
    return settings.secret_key or _DEV_SECRET


def https_only() -> bool:
    return settings.public_url.startswith("https://")


def is_admin_cid(cid) -> bool:
    return str(cid) in csv_set(settings.auth_admin_cids)


def access_denied_reason(user: dict) -> str | None:
    """None = wpuszczamy, inaczej komunikat dla użytkownika. Wchodzą admini i CID-y z listy (zakładka ADMIN)."""
    cid = str(user.get("cid"))
    if user.get("rating", -1) < 1:
        return "Konto VATSIM jest nieaktywne albo zawieszone."
    if is_admin_cid(cid) or access.is_allowed(cid):
        return None
    return f"Brak dostępu dla CID {cid}. Poproś administratora o dodanie Cię do listy."


def is_admin(user: dict | None) -> bool:
    if settings.auth_mode == "none":
        return True
    return bool(user) and is_admin_cid(user.get("cid"))


def current_user(request: Request) -> dict | None:
    # reguły sprawdzamy przy każdym zapytaniu, żeby zmiana listy dostępu działała od razu po restarcie
    if "session" not in request.scope:
        return None
    user = request.session.get("user")
    if not user:
        return None
    if user.get("exp", 0) < time.time() or access_denied_reason(user):
        request.session.clear()
        return None
    return user


def require_admin(request: Request) -> None:
    if not is_admin(current_user(request)):
        raise HTTPException(403, "Tylko dla administratorów (POLIDS_AUTH_ADMIN_CIDS)")


def _is_public(path: str) -> bool:
    # StaticFiles rozwija "..", więc /static/icons/../js/app.js nie może przejść jako publiczne
    if "/." in path or "//" in path:
        return False
    return path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES)


def _cross_origin(request: Request) -> bool:
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return False
    origin = request.headers.get("origin")
    if origin is None:
        return False  # nie przeglądarka (curl, testy)
    return origin == "null" or urlsplit(origin).netloc.lower() != request.headers.get("host", "").lower()


async def gate(request: Request, call_next):
    path = request.url.path
    if _cross_origin(request):
        log.warning("Odrzucono %s %s z Origin %s", request.method, path, request.headers.get("origin"))
        return JSONResponse({"detail": "Zapytanie z innej strony odrzucone"}, status_code=403)
    if settings.auth_mode == "none" or _is_public(path) or current_user(request):
        return await call_next(request)
    if path.startswith("/api/") or path == "/openapi.json":
        return JSONResponse({"detail": "Wymagane logowanie"}, status_code=401)
    return RedirectResponse("/auth/login?" + urlencode({"next": path}), status_code=303)


def _safe_next(nxt: str | None) -> str:
    # tylko ścieżki w obrębie aplikacji (bez open redirect)
    if not nxt or not nxt.startswith("/") or nxt.startswith("//") or "\\" in nxt or any(ord(c) < 32 for c in nxt):
        return "/"
    return nxt


def _fail(request: Request, message: str) -> RedirectResponse:
    # komunikat przez sesję, nie w adresie - inaczej dałoby się podsunąć dowolny tekst linkiem
    request.session["flash"] = message
    return RedirectResponse("/auth/login", status_code=303)


def _start_session(request: Request, user: dict, nxt: str):
    reason = access_denied_reason(user)
    if reason:
        log.info("Odmowa dostępu dla CID %s: %s", user.get("cid"), reason)
        access.record_denied(user["cid"], user.get("name"), user.get("rating_short"))
        return _fail(request, reason)
    request.session.clear()
    request.session["user"] = {**user, "exp": int(time.time()) + settings.session_days * 86400}
    access.record_login(user["cid"], user.get("name"))
    log.info("Zalogowano CID %s (%s, %s)", user["cid"], user.get("rating_short"), user.get("subdivision") or "-")
    return RedirectResponse(_safe_next(nxt), status_code=303)


def _login_page(error: str = "", nxt: str = "/") -> HTMLResponse:
    page = (settings.frontend_dir / "login.html").read_text("utf-8")
    nxt_q = html.escape(urlencode({"next": _safe_next(nxt)}))
    if settings.auth_mode == "vatsim":
        body = f'<a class="btn" href="/auth/vatsim?{nxt_q}">Zaloguj przez VATSIM</a>'
        if "auth-dev." in settings.vatsim_auth_url:
            body += '<p class="hint">Sandbox VATSIM: konta 10000000-10000010, hasło = CID.</p>'
    else:
        options = "".join(f'<option value="{k}"{" selected" if k == 2 else ""}>{v}</option>'
                          for k, v in RATINGS.items() if k >= 0)
        body = f"""<p class="warn">Tryb dev - logowanie bez VATSIM, tylko lokalnie.</p>
        <form method="post" action="/auth/dev">
          <input type="hidden" name="next" value="{html.escape(_safe_next(nxt))}">
          <label>CID <input name="cid" value="10000002" required pattern="[0-9]{{6,8}}"></label>
          <label>Imię i nazwisko <input name="name" value="Test Kontroler" required maxlength="60"></label>
          <label>Rating <select name="rating">{options}</select></label>
          <label>Dywizja <input name="division" value="EUD" maxlength="5"></label>
          <label>vACC <input name="subdivision" value="POL" maxlength="5"></label>
          <button class="btn" type="submit">Zaloguj</button>
        </form>"""
    page = (page.replace("{{NAME}}", html.escape(settings.name))
            .replace("{{TAGLINE}}", html.escape(settings.tagline))
            .replace("{{VERSION}}", VERSION)
            .replace("{{ERROR}}", f'<p class="error">{html.escape(error)}</p>' if error else "")
            .replace("{{BODY}}", body))
    return HTMLResponse(page, headers={"Cache-Control": "no-store"})


@router.get("/login", include_in_schema=False)
def login(request: Request, next: str = "/"):  # noqa: A002
    if settings.auth_mode == "none" or current_user(request):
        return RedirectResponse(_safe_next(next), status_code=303)
    return _login_page(request.session.pop("flash", ""), next)


@router.post("/dev", include_in_schema=False)
def dev_login(request: Request, cid: str = Form(..., pattern=r"^\d{6,8}$"), name: str = Form(..., max_length=60),
              rating: int = Form(2), division: str = Form("", max_length=5), subdivision: str = Form("", max_length=5),
              next: str = Form("/")):  # noqa: A002
    if settings.auth_mode != "dev":
        raise HTTPException(404)
    user = {"cid": cid, "name": name.strip(), "rating": rating, "rating_short": RATINGS.get(rating, str(rating)),
            "division": division.strip().upper() or None, "subdivision": subdivision.strip().upper() or None}
    return _start_session(request, user, next)


def _redirect_uri() -> str:
    return settings.public_url.rstrip("/") + "/auth/callback"


@router.get("/vatsim", include_in_schema=False)
def vatsim_start(request: Request, next: str = "/"):  # noqa: A002
    if settings.auth_mode != "vatsim":
        raise HTTPException(404)
    state = secrets.token_urlsafe(32)
    request.session["oauth"] = {"state": state, "next": _safe_next(next), "t": int(time.time())}
    params = {"client_id": settings.vatsim_client_id, "redirect_uri": _redirect_uri(), "response_type": "code",
              "scope": "full_name vatsim_details", "state": state}
    return RedirectResponse(settings.vatsim_auth_url.rstrip("/") + "/oauth/authorize?" + urlencode(params),
                            status_code=303)


async def fetch_vatsim_user(code: str) -> dict:
    base = settings.vatsim_auth_url.rstrip("/")
    async with httpx.AsyncClient(timeout=settings.http_timeout, headers={"User-Agent": settings.user_agent,
                                                                         "Accept": "application/json"}) as client:
        tok = await client.post(base + "/oauth/token", data={
            "grant_type": "authorization_code", "client_id": settings.vatsim_client_id,
            "client_secret": settings.vatsim_client_secret, "redirect_uri": _redirect_uri(), "code": code})
        tok.raise_for_status()
        resp = await client.get(base + "/api/user", headers={"Authorization": f"Bearer {tok.json()['access_token']}"})
        resp.raise_for_status()
    return parse_vatsim_user(resp.json())


def parse_vatsim_user(payload: dict) -> dict:
    d = payload.get("data") or {}
    personal, vatsim = d.get("personal") or {}, d.get("vatsim") or {}
    rating = vatsim.get("rating") or {}
    name = personal.get("name_full") or " ".join(filter(None, (personal.get("name_first"), personal.get("name_last"))))
    rating_id = rating.get("id")
    return {"cid": str(d["cid"]), "name": (name or "")[:80] or None,
            "rating": int(rating_id) if rating_id is not None else -1,
            "rating_short": rating.get("short"), "division": (vatsim.get("division") or {}).get("id"),
            "subdivision": (vatsim.get("subdivision") or {}).get("id")}


@router.get("/callback", include_in_schema=False)
async def vatsim_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    if settings.auth_mode != "vatsim":
        raise HTTPException(404)
    saved = request.session.pop("oauth", None) or {}
    if error:
        return _fail(request, "Logowanie w VATSIM zostało przerwane.")
    if not code or not state or not secrets.compare_digest(state, saved.get("state", "")) \
            or time.time() - saved.get("t", 0) > 600:
        return _fail(request, "Sesja logowania wygasła, spróbuj jeszcze raz.")
    try:
        user = await fetch_vatsim_user(code)
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
        log.warning("VATSIM Connect: %s", exc)
        return _fail(request, "VATSIM Connect nie odpowiada, spróbuj za chwilę.")
    return _start_session(request, user, saved.get("next", "/"))


@router.post("/logout", include_in_schema=False)
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/auth/login" if settings.auth_mode != "none" else "/", status_code=303)


@router.get("/me")
def me(request: Request):
    if settings.auth_mode == "none":
        return {"mode": "none", "user": None, "admin": True}
    user = current_user(request)
    if not user:
        raise HTTPException(401, "Wymagane logowanie")
    return {"mode": settings.auth_mode, "admin": is_admin(user),
            "user": {k: user.get(k) for k in ("cid", "name", "rating_short", "division", "subdivision")}}
