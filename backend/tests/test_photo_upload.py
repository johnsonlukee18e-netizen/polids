"""0.15.0: zdjęcia typów wrzucane przez adminów w AIRCRAFT (POST/DELETE /api/photos/type/<ICAO>,
services/photos.save_upload). Pliki w katalogu tymczasowym, bez sieci."""
import os
import tempfile

os.environ.setdefault("POLIDS_DATABASE_URL", "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test.db").replace("\\", "/"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.app import main  # noqa: E402
from backend.app.config import ROOT_DIR, settings  # noqa: E402
from backend.app.services import photos  # noqa: E402

ADMIN, MEMBER = "1000001", "1234567"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 64


def login(c, cid):
    return c.post("/auth/dev", data={"cid": cid, "name": "Jan Test", "rating": 2, "next": "/"})


def _empty(d):
    for f in d.iterdir():
        f.unlink()


@pytest.fixture
def folder():
    """Katalog z conftest (POLIDS_UPLOADED_PHOTOS_DIR, ten sam co w mount /files/photos-uploaded), pusty na test."""
    d = settings.uploaded_photos_dir
    d.mkdir(parents=True, exist_ok=True)
    _empty(d)
    yield d
    _empty(d)


@pytest.fixture
def clients(monkeypatch, state, folder):
    monkeypatch.setattr(settings, "auth_mode", "dev")
    monkeypatch.setattr(settings, "auth_admin_cids", ADMIN)
    state.add_user(MEMBER, "kontroler", by=ADMIN)
    with TestClient(main.app, follow_redirects=False) as admin, TestClient(main.app, follow_redirects=False) as member:
        assert login(admin, ADMIN).status_code == 303 and login(member, MEMBER).status_code == 303
        yield admin, member


def upload(c, data, name="x.jpg", author="", icao="B738", **kw):
    return c.post(f"/api/photos/type/{icao}", files={"file": (name, data, "image/jpeg")}, data={"author": author}, **kw)


def test_sniff():
    assert photos.sniff(JPEG) == "jpg" and photos.sniff(PNG) == "png" and photos.sniff(WEBP) == "webp"
    assert photos.sniff(b"<svg xmlns='http://www.w3.org/2000/svg'/>") is None and photos.sniff(b"") is None
    assert photos.sniff(b"GIF89a") is None


def test_save_replace_and_delete(folder):
    p = photos.save_upload("b738", JPEG, "  Photo:  Jan   Kowalski \nsecond line")
    assert p["url"].startswith("/files/photos-uploaded/B738.jpg?v=") and p["author"] == "Jan Kowalski" and p["uploaded"]
    assert (folder / "B738.jpg").read_bytes() == JPEG and (folder / "B738.txt").read_text("utf-8") == "Jan Kowalski\n"
    # nowe zdjęcie w innym formacie zastępuje stare, pusty autor usuwa podpis
    p = photos.save_upload("B738", PNG, "")
    assert p["url"].startswith("/files/photos-uploaded/B738.png") and p["author"] == ""
    assert not (folder / "B738.jpg").exists() and not (folder / "B738.txt").exists()
    assert not list(folder.glob(".*.part"))
    # wrzucone zdjęcie wygrywa ze wszystkim innym, bez pytania Wikipedii
    import asyncio
    assert asyncio.run(photos.type_photo("B738", "BOEING", "737-800"))["uploaded"] is True
    assert photos.delete_upload("B738") is True and photos.delete_upload("B738") is False
    assert photos.uploaded_photo("B738") is None


def test_save_rejects_bad_files(folder, monkeypatch):
    for data, msg in ((b"", "Empty file"), (b"GIF89a....", "Only JPEG, PNG or WebP images"),
                      (b"<svg onload=alert(1)>", "Only JPEG, PNG or WebP images")):
        with pytest.raises(photos.UploadError, match=msg):
            photos.save_upload("B738", data, "")
    monkeypatch.setattr(settings, "photo_upload_max_bytes", 10)
    with pytest.raises(photos.UploadError, match="too large"):
        photos.save_upload("B738", JPEG, "")
    with pytest.raises(photos.UploadError):
        photos.save_upload("../", JPEG, "")
    assert not list(folder.iterdir())


def test_api_admin_only(clients, folder):
    admin, member = clients
    assert upload(member, JPEG).status_code == 403
    assert member.delete("/api/photos/type/B738").status_code == 403
    r = upload(admin, JPEG, author="Jan Kowalski")
    assert r.status_code == 200, r.text
    assert r.json()["author"] == "Jan Kowalski" and (folder / "B738.jpg").exists()
    # AIRCRAFT pokazuje wrzucone zdjęcie, a plik jest serwowany
    a = admin.get("/api/aircraft", params={"q": "B738"}).json()[0]
    p = admin.get(f"/api/aircraft/{a['id']}/photo").json()
    assert p["uploaded"] is True and p["url"].startswith("/files/photos-uploaded/B738.jpg")
    assert admin.get(p["url"]).content == JPEG
    assert admin.delete("/api/photos/type/B738").status_code == 204
    assert admin.delete("/api/photos/type/B738").status_code == 404


def test_api_validation(clients, folder):
    admin, _ = clients
    assert upload(admin, b"not an image").status_code == 400
    # ZZZZ to w ICAO prawdziwy kod ("typ nieznany"), więc kod spoza bazy z cyframi
    assert upload(admin, JPEG, icao="Q9Q9").status_code == 404
    assert upload(admin, JPEG, icao="B7%2F8").status_code in (404, 422)
    # formularz z innej strony odrzuca CSRF (Origin), zanim cokolwiek zostanie zapisane
    assert upload(admin, JPEG, headers={"Origin": "https://evil.example"}).status_code == 403
    assert not list(folder.iterdir())


def test_upload_dir_mounted_and_documented():
    main_src = (ROOT_DIR / "backend" / "app" / "main.py").read_text("utf-8")
    assert 'app.mount("/files/photos-uploaded"' in main_src
    # mount zdjęć wrzuconych przed ogólnym /files/photos
    assert main_src.index('"/files/photos-uploaded"') < main_src.index('app.mount("/files/photos",')
