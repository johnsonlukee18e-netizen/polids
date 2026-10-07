import os
import tempfile

os.environ.setdefault("POLIDS_DATABASE_URL", "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test.db").replace("\\", "/"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.app import main  # noqa: E402
from backend.app.config import settings  # noqa: E402

ADMIN, MEMBER, STRANGER = "1000001", "1234567", "7654321"


def login(c, cid, rating=2, name="Jan Test"):
    return c.post("/auth/dev", data={"cid": cid, "name": name, "rating": rating, "next": "/"})


@pytest.fixture
def admin(monkeypatch, state):
    monkeypatch.setattr(settings, "auth_mode", "dev")
    monkeypatch.setattr(settings, "auth_admin_cids", ADMIN)
    state.add_user(MEMBER, "kontroler", by=ADMIN)
    c = TestClient(main.app, follow_redirects=False)
    assert login(c, ADMIN).status_code == 303
    return c


def test_only_admin_can_use_admin_api(admin, state):
    member = TestClient(main.app, follow_redirects=False)
    assert member.get("/api/admin/users").status_code == 401
    login(member, MEMBER)
    for method, url in (("get", "/api/admin/users"), ("post", "/api/admin/users"), ("delete", f"/api/admin/users/{MEMBER}"),
                        ("get", "/api/admin/denied"), ("delete", "/api/admin/denied")):
        assert getattr(member, method)(url).status_code == 403, url
    assert member.get("/auth/me").json()["admin"] is False
    assert admin.get("/auth/me").json()["admin"] is True


def test_list_add_edit_remove(admin):
    d = admin.get("/api/admin/users").json()
    assert d["admins"] == [ADMIN] and [u["cid"] for u in d["users"]] == [MEMBER]

    r = admin.post("/api/admin/users", json={"cid": "2222222", "note": " Ola, EPWA TWR "})
    assert r.status_code == 201 and r.json()["note"] == "Ola, EPWA TWR" and r.json()["added_by"] == ADMIN
    assert admin.post("/api/admin/users", json={"cid": "2222222"}).status_code == 409
    for bad in ("abc", "12345", "123456789", "12 345"):
        assert admin.post("/api/admin/users", json={"cid": bad}).status_code == 422, bad

    assert admin.patch("/api/admin/users/2222222", json={"note": "APP"}).json()["note"] == "APP"
    assert admin.patch("/api/admin/users/3333333", json={"note": "x"}).status_code == 404
    assert admin.delete("/api/admin/users/2222222").status_code == 204
    assert admin.delete("/api/admin/users/2222222").status_code == 404
    assert [u["cid"] for u in admin.get("/api/admin/users").json()["users"]] == [MEMBER]


def test_denied_then_added_by_admin(admin):
    stranger = TestClient(main.app, follow_redirects=False)
    for _ in range(2):
        assert login(stranger, STRANGER, name="Obcy Pilot").headers["location"] == "/auth/login"
    denied = admin.get("/api/admin/denied").json()
    assert [(d["cid"], d["name"], d["count"]) for d in denied] == [(STRANGER, "Obcy Pilot", 2)]

    admin.post("/api/admin/users", json={"cid": STRANGER})
    assert admin.get("/api/admin/denied").json() == []  # dodany znika z odmów
    added = next(u for u in admin.get("/api/admin/users").json()["users"] if u["cid"] == STRANGER)
    assert added["name"] == "Obcy Pilot" and added["last_login"] is None

    assert login(stranger, STRANGER, name="Obcy Pilot").headers["location"] == "/"
    assert stranger.get("/api/config").status_code == 200
    added = next(u for u in admin.get("/api/admin/users").json()["users"] if u["cid"] == STRANGER)
    assert added["last_login"]

    login(TestClient(main.app, follow_redirects=False), "5555555")
    assert admin.delete("/api/admin/denied").status_code == 204
    assert admin.get("/api/admin/denied").json() == []


def test_removal_logs_user_out(admin):
    member = TestClient(main.app, follow_redirects=False)
    login(member, MEMBER)
    assert member.get("/api/config").status_code == 200
    admin.delete(f"/api/admin/users/{MEMBER}")
    assert member.get("/api/config").status_code == 401
    assert login(member, MEMBER).headers["location"] == "/auth/login"


def test_list_survives_restart(admin, state):
    admin.post("/api/admin/users", json={"cid": "2222222", "note": "trwały"})
    state.reset()  # jak restart kontenera: nowe połączenie, pusty cache
    assert state.is_allowed("2222222")
    assert {u["cid"]: u["note"] for u in state.list_users()}["2222222"] == "trwały"


def test_admin_post_from_other_site_rejected(admin):
    r = admin.post("/api/admin/users", json={"cid": "2222222"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert [u["cid"] for u in admin.get("/api/admin/users").json()["users"]] == [MEMBER]
