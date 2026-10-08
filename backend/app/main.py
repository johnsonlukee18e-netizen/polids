import html
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from . import access, auth
from .config import VERSION, settings
from .importers.seed import init_db
from .routers import admin, aerodromes, aircraft, callsigns, docs, meteo, nav, notam, radio, system, vatsim, viff

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
# healthcheck dockera co 30 s, nie potrzebujemy tego w logu
logging.getLogger("uvicorn.access").addFilter(lambda record: "/healthz" not in record.getMessage())

SECRET_KEY = auth.check_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    access.init_state()
    logging.getLogger("polids").info("%s %s: %s, logowanie: %s", settings.name, VERSION, settings.public_url,
                                     settings.auth_mode)
    yield


app = FastAPI(title=f"{settings.name} API", version=VERSION, lifespan=lifespan)

app.include_router(auth.router)
for r in (system, meteo, aerodromes, notam, aircraft, callsigns, nav, radio, vatsim, viff, docs, admin):
    app.include_router(r.router)


@app.middleware("http")
async def revalidate_frontend(request: Request, call_next):
    """Przeglądarka ma sprawdzać pliki interfejsu przy każdym wczytaniu (ETag -> 304), żeby po aktualizacji
    aplikacji nie zostawały stare skrypty z pamięci podręcznej."""
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers.setdefault("Cache-Control", "no-cache")
    return response


# kolejność: ostatnio dodany middleware jest najbardziej zewnętrzny (sesja -> nagłówki -> gate -> cache)
app.middleware("http")(auth.gate)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    return response


app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, session_cookie="session",
                   max_age=settings.session_days * 86400, same_site="lax", https_only=auth.https_only())

settings.docs_dir.mkdir(parents=True, exist_ok=True)
settings.photos_dir.mkdir(parents=True, exist_ok=True)
app.mount("/files/docs", StaticFiles(directory=settings.docs_dir), name="docs-files")
app.mount("/files/photos", StaticFiles(directory=settings.photos_dir), name="photo-files")
app.mount("/static", StaticFiles(directory=settings.frontend_dir), name="static")


def _page(name: str) -> HTMLResponse:
    text = (settings.frontend_dir / name).read_text("utf-8")
    return HTMLResponse(text.replace("{{NAME}}", html.escape(settings.name)), headers={"Cache-Control": "no-cache"})


@app.get("/", include_in_schema=False)
def index():
    return _page("index.html")


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"status": "ok", "version": VERSION}


@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest():
    icons = [{"src": f"/static/icons/icon-{s}.png", "sizes": f"{s}x{s}", "type": "image/png"} for s in (192, 512)]
    icons += [{"src": "/static/icons/icon-maskable-512.png", "sizes": "512x512", "type": "image/png",
               "purpose": "maskable"},
              {"src": "/static/icons/icon.svg", "sizes": "any", "type": "image/svg+xml"}]
    data = {"name": settings.name, "short_name": settings.name[:12], "description": settings.tagline, "lang": "pl",
            "id": "/", "start_url": "/", "scope": "/", "display": "standalone", "background_color": "#000000",
            "theme_color": "#000000", "icons": icons}
    return JSONResponse(data, media_type="application/manifest+json")


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    # z / zamiast /static, inaczej scope service workera to tylko /static
    return FileResponse(settings.frontend_dir / "sw.js", media_type="text/javascript",
                        headers={"Cache-Control": "no-cache"})


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(settings.frontend_dir / "icons" / "favicon.ico")
