import os
import tempfile
from urllib.parse import parse_qs, urlsplit

os.environ.setdefault("POLIDS_DATABASE_URL", "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test.db").replace("\\", "/"))

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.app import access, auth, main  # noqa: E402
from backend.app.config import settings  # noqa: E402
from backend.app.routers import system  # noqa: E402
from backend.app.services.embed import frame_policy  # noqa: E402

ADMIN = "1000001"
MEMBER = "1234567"
STRANGER = "7654321"


@pytest.fixture
def client(monkeypatch, state):
    # bez `with` -> bez lifespan, baza niepotrzebna
    monkeypatch.setattr(settings, "auth_mode", "dev")
    monkeypatch.setattr(settings, "auth_admin_cids", ADMIN)
    state.add_user(MEMBER, "test", by=ADMIN)
    return TestClient(main.app, follow_redirects=False)


def dev_login(c, cid=MEMBER, rating=2, subdivision="POL", division="EUD"):
    return c.post("/auth/dev", data={"cid": cid, "name": "Jan Test", "rating": rating, "division": division,
                                     "subdivision": subdivision, "next": "/"})


def test_public_paths_without_login(client):
    assert client.get("/healthz").json()["status"] == "ok"
    man = client.get("/manifest.webmanifest")
    assert man.status_code == 200 and man.json()["name"] == settings.name
    assert man.headers["content-type"].startswith("application/manifest+json")
    assert {i["src"] for i in man.json()["icons"]} >= {"/static/icons/icon-192.png", "/static/icons/icon-512.png"}
    assert client.get("/static/icons/icon-192.png").status_code == 200
    assert client.get("/static/offline.html").status_code == 200
    sw = client.get("/sw.js")
    assert sw.status_code == 200 and "javascript" in sw.headers["content-type"]
    page = client.get("/auth/login")
    assert page.status_code == 200 and 'action="/auth/dev"' in page.text and settings.name in page.text


def test_gate_blocks_everything_else(client):
    r = client.get("/api/config")
    assert r.status_code == 401 and r.json()["detail"] == "Wymagane logowanie"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert client.get("/openapi.json").status_code == 401
    for path in ("/", "/docs", "/static/js/app.js", "/files/docs/Doc_4444_pl.pdf"):
        r = client.get(path)
        assert r.status_code == 303, path
        assert r.headers["location"].startswith("/auth/login?next=")


def test_dev_login_flow(client):
    r = dev_login(client)
    assert r.status_code == 303 and r.headers["location"] == "/"
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert client.get("/api/config").json()["name"] == settings.name
    me = client.get("/auth/me").json()
    assert me["user"]["cid"] == "1234567" and me["user"]["rating_short"] == "S1" and me["admin"] is False
    assert settings.name in client.get("/").text
    assert client.post("/api/import").status_code == 403
    assert client.post("/auth/logout").status_code == 303
    assert client.get("/api/config").status_code == 401


def test_admin_can_import(client, monkeypatch):
    monkeypatch.setattr(system, "init_db", lambda force=False: [{"file": "x", "force": force}])
    dev_login(client, cid=ADMIN)
    assert client.get("/auth/me").json()["admin"] is True
    assert client.post("/api/import?force=true").json() == {"results": [{"file": "x", "force": True}]}


def test_denied_login_shows_reason(client):
    r = dev_login(client, cid=STRANGER)
    assert r.status_code == 303 and r.headers["location"] == "/auth/login"
    assert f"Brak dostępu dla CID {STRANGER}" in client.get("/auth/login").text
    assert "Brak dostępu" not in client.get("/auth/login").text
    assert client.get("/api/config").status_code == 401
    assert [d["cid"] for d in access.denied_attempts()] == [STRANGER]


def test_access_rules(client):
    assert auth.access_denied_reason({"cid": ADMIN, "rating": 1}) is None
    assert auth.access_denied_reason({"cid": MEMBER, "rating": 1}) is None
    assert "Brak dostępu" in auth.access_denied_reason({"cid": STRANGER, "rating": 12})
    for cid in (ADMIN, MEMBER):
        assert "nieaktywne" in auth.access_denied_reason({"cid": cid, "rating": 0})


def test_removed_user_loses_access_immediately(client):
    dev_login(client)
    assert client.get("/api/config").status_code == 200
    access.remove_user(MEMBER)
    assert client.get("/api/config").status_code == 401


def test_session_expiry(client, monkeypatch):
    monkeypatch.setattr(settings, "session_days", -1)
    dev_login(client)
    assert client.get("/api/config").status_code == 401


def test_safe_next():
    assert auth._safe_next("/#map") == "/#map"
    for bad in ("//evil.example", "https://evil.example", "/\\evil.example", "", None, "map"):
        assert auth._safe_next(bad) == "/"


def test_dev_endpoint_disabled_outside_dev(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "vatsim")
    assert dev_login(client).status_code == 404


def test_vatsim_login_flow(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "vatsim")
    monkeypatch.setattr(settings, "vatsim_client_id", "123")
    assert '/auth/vatsim?next=%2F' in client.get("/auth/login").text

    r = client.get("/auth/vatsim", params={"next": "/#map"})
    loc = urlsplit(r.headers["location"])
    q = {k: v[0] for k, v in parse_qs(loc.query).items()}
    assert r.status_code == 303 and f"{loc.scheme}://{loc.netloc}" == settings.vatsim_auth_url
    assert loc.path == "/oauth/authorize" and q["client_id"] == "123" and q["response_type"] == "code"
    assert q["redirect_uri"] == "http://localhost:1337/auth/callback" and q["scope"] == "full_name vatsim_details"

    r = client.get("/auth/callback", params={"code": "c", "state": "zly"})
    assert r.headers["location"] == "/auth/login" and client.get("/api/config").status_code == 401

    calls = []

    async def fake_fetch(code):
        calls.append(code)
        return auth.parse_vatsim_user({"data": {
            "cid": 1234567, "personal": {"name_first": "Jan", "name_last": "Kowalski", "name_full": "Jan Kowalski"},
            "vatsim": {"rating": {"id": 3, "short": "S2"}, "division": {"id": "EUD"},
                       "subdivision": {"id": "POL"}}}})
    monkeypatch.setattr(auth, "fetch_vatsim_user", fake_fetch)
    state = parse_qs(urlsplit(client.get("/auth/vatsim", params={"next": "/#map"}).headers["location"]).query)["state"][0]
    r = client.get("/auth/callback", params={"code": "kod", "state": state})
    assert r.status_code == 303 and r.headers["location"] == "/#map" and calls == ["kod"]
    me = client.get("/auth/me").json()
    assert me["mode"] == "vatsim" and me["user"] == {"cid": "1234567", "name": "Jan Kowalski", "rating_short": "S2",
                                                     "division": "EUD", "subdivision": "POL"}
    # state jednorazowy
    client.post("/auth/logout")
    r = client.get("/auth/callback", params={"code": "kod", "state": state})
    assert r.headers["location"] == "/auth/login" and calls == ["kod"]

    async def stranger(code):
        return auth.parse_vatsim_user({"data": {"cid": int(STRANGER), "personal": {"name_full": "Obcy Pilot"},
                                                "vatsim": {"rating": {"id": 1, "short": "OBS"}}}})
    monkeypatch.setattr(auth, "fetch_vatsim_user", stranger)
    state = parse_qs(urlsplit(client.get("/auth/vatsim").headers["location"]).query)["state"][0]
    assert client.get("/auth/callback", params={"code": "k", "state": state}).headers["location"] == "/auth/login"
    assert f"Brak dostępu dla CID {STRANGER}" in client.get("/auth/login").text
    assert access.denied_attempts()[0] | {"last": None} == {"cid": STRANGER, "name": "Obcy Pilot", "rating": "OBS",
                                                             "last": None, "count": 1}


def test_vatsim_upstream_error(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "vatsim")

    async def down(code):
        raise httpx.ConnectError("brak sieci")
    monkeypatch.setattr(auth, "fetch_vatsim_user", down)
    state = parse_qs(urlsplit(client.get("/auth/vatsim").headers["location"]).query)["state"][0]
    assert client.get("/auth/callback", params={"code": "k", "state": state}).headers["location"] == "/auth/login"
    assert "VATSIM Connect nie odpowiada" in client.get("/auth/login").text


def test_parse_vatsim_user_without_subdivision():
    u = auth.parse_vatsim_user({"data": {"cid": "1234567", "personal": {"name_first": "A", "name_last": "B"},
                                         "vatsim": {"rating": {"id": 1, "short": "OBS"}, "division": {"id": "USA"},
                                                    "subdivision": {"id": None, "name": None}}}})
    assert u == {"cid": "1234567", "name": "A B", "rating": 1, "rating_short": "OBS", "division": "USA",
                 "subdivision": None}


def test_check_settings(monkeypatch):
    monkeypatch.setattr(settings, "auth_mode", "dev")
    monkeypatch.setattr(settings, "public_url", "https://portal.example.pl")
    with pytest.raises(RuntimeError, match="tylko lokalnie"):
        auth.check_settings()
    monkeypatch.setattr(settings, "auth_mode", "vatsim")
    monkeypatch.setattr(settings, "vatsim_client_id", "id")
    monkeypatch.setattr(settings, "vatsim_client_secret", "sekret")
    monkeypatch.setattr(settings, "secret_key", "za-krotki")
    with pytest.raises(RuntimeError, match="POLIDS_SECRET_KEY"):
        auth.check_settings()
    monkeypatch.setattr(settings, "secret_key", "x" * 32)
    assert auth.check_settings() == "x" * 32
    monkeypatch.setattr(settings, "vatsim_client_secret", "")
    with pytest.raises(RuntimeError, match="POLIDS_VATSIM_CLIENT_SECRET"):
        auth.check_settings()
    monkeypatch.setattr(settings, "auth_mode", "cokolwiek")
    with pytest.raises(RuntimeError, match="dozwolone"):
        auth.check_settings()


def test_frame_policy_accepts_own_domain(monkeypatch):
    monkeypatch.setattr(settings, "public_url", "https://portal.example.pl")
    ours = httpx.Headers({"Content-Security-Policy": "frame-ancestors https://portal.example.pl"})
    theirs = httpx.Headers({"Content-Security-Policy": "frame-ancestors https://inny.example.com"})
    assert frame_policy(ours)[0] is True and frame_policy(theirs)[0] is False


def test_dot_segments_never_public():
    assert auth._is_public("/static/icons/icon-192.png") and auth._is_public("/auth/login")
    for path in ("/static/icons/../js/app.js", "/static/icons/./x", "/auth/../api/config", "/static/icons//x"):
        assert not auth._is_public(path), path


def test_cross_origin_post_rejected(client):
    dev_login(client)
    r = client.post("/auth/logout", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and client.get("/api/config").status_code == 200
    assert client.post("/auth/logout", headers={"Origin": "null"}).status_code == 403
    assert client.post("/auth/logout", headers={"Origin": "http://testserver"}).status_code == 303
    assert client.get("/api/config").status_code == 401


def test_vatsim_user_without_rating_is_denied(state):
    u = auth.parse_vatsim_user({"data": {"cid": 1, "personal": {}, "vatsim": {"rating": {"id": None}}}})
    assert u["rating"] == -1 and u["name"] is None and auth.access_denied_reason(u)
