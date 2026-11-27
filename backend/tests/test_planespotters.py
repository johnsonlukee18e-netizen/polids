"""0.15.0: zdjęcie samolotu po rejestracji z Planespotters.net Photo API (services/planespotters.py,
GET /api/photos/registration/<REG>) i jego wyświetlanie (api.js planespottersHtml, registrationOf) w Node.
Odpowiedzi API są podstawione (httpx.MockTransport), bez sieci."""
import asyncio
import json
import os
import re
import shutil
import subprocess
import tempfile

os.environ.setdefault("POLIDS_DATABASE_URL", "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test.db").replace("\\", "/"))

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.app import main  # noqa: E402
from backend.app.config import ROOT_DIR, settings  # noqa: E402
from backend.app.services import http_cache, planespotters  # noqa: E402

REAL_CLIENT = httpx.AsyncClient
PHOTO = {"id": "000001",
         "thumbnail": {"src": "https://t.plnspttrs.net/1/sp-lwa_t.jpg", "size": {"width": 200, "height": 133}},
         "thumbnail_large": {"src": "https://t.plnspttrs.net/1/sp-lwa_280.jpg", "size": {"width": 420, "height": 280}},
         "link": "https://www.planespotters.net/photo/000001/sp-lwa-lot", "photographer": "Jan  Kowalski"}


@pytest.fixture
def api(monkeypatch):
    """Podstawione API: state["photos"] = {rejestracja: [zdjęcia]}; state["down"] = brak połączenia."""
    state = {"photos": {"SP-LWA": [PHOTO]}, "down": False, "calls": []}

    def handler(request):
        state["calls"].append((request.url.path, request.headers.get("user-agent")))
        if state["down"]:
            raise httpx.ConnectError("down", request=request)
        reg = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json={"photos": state["photos"].get(reg, [])})

    monkeypatch.setattr(http_cache.httpx, "AsyncClient", lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(handler), **kw))
    http_cache.clear_cache()
    yield state
    http_cache.clear_cache()


def test_candidates():
    assert planespotters.candidates("SPLWA") == ["SPLWA", "SP-LWA", "S-PLWA"]
    assert planespotters.candidates("DABCD") == ["DABCD", "D-ABCD", "DA-BCD"]
    assert planespotters.candidates("sp-lwa") == ["SP-LWA"]
    assert planespotters.candidates("N12345") == ["N12345"] and planespotters.candidates("JA801A") == ["JA801A"]
    assert planespotters.candidates("") == [] and planespotters.candidates("<x>") == ["X"]


def test_parse_keeps_urls_and_requires_credit():
    p = planespotters.parse({"photos": [PHOTO]})
    assert p["thumbnail"] == PHOTO["thumbnail"]["src"] and p["thumbnail_large"] == PHOTO["thumbnail_large"]["src"]
    assert p["link"] == PHOTO["link"] and p["photographer"] == "Jan Kowalski" and (p["width"], p["height"]) == (420, 280)
    assert planespotters.parse({"photos": []}) is None and planespotters.parse({"error": "x"}) is None
    # bez autora, bez strony zdjęcia albo z adresem spoza Planespotters zdjęcia nie wolno pokazać
    for bad in ({"photographer": ""}, {"link": None}, {"thumbnail": {"src": "https://evil.example/x.jpg"}},
                {"link": "javascript:alert(1)"}, {"thumbnail": {"src": "http://t.plnspttrs.net/x.jpg"}}):
        assert planespotters.parse({"photos": [{**PHOTO, **bad}]}) is None, bad


def test_registration_without_dash_found(api):
    r = asyncio.run(planespotters.by_registration("SPLWA"))
    assert r["registration"] == "SP-LWA" and r["photo"]["link"] == PHOTO["link"]
    paths = [c[0] for c in api["calls"]]
    assert paths == ["/pub/photos/reg/SPLWA", "/pub/photos/reg/SP-LWA"]
    # warunki API: własny User-Agent z adresem kontaktowym
    assert all(ua.startswith(settings.user_agent.split(" ")[0]) and "+" in ua for _, ua in api["calls"])
    # druga prośba z cache
    api["calls"].clear()
    asyncio.run(planespotters.by_registration("SPLWA"))
    assert api["calls"] == []


def test_no_photo_and_down(api):
    r = asyncio.run(planespotters.by_registration("SPXYZ"))
    assert r == {"registration": "SPXYZ", "photo": None}
    http_cache.clear_cache()
    api["down"] = True
    with pytest.raises(http_cache.UpstreamError):
        asyncio.run(planespotters.by_registration("SPLWA"))


def test_endpoint(api):
    with TestClient(main.app) as c:
        r = c.get("/api/photos/registration/SPLWA")
        assert r.status_code == 200 and r.json()["photo"]["photographer"] == "Jan Kowalski"
        assert c.get("/api/photos/registration/SP%20LWA").status_code == 422
        http_cache.clear_cache()
        api["down"] = True
        r = c.get("/api/photos/registration/SPLWA")
        assert r.status_code == 502 and r.json()["detail"] == "Photos unavailable"


NODE_SCRIPT = r"""
const m = await import(process.argv[2]);
const fp = await import(process.argv[3]);
const photo = JSON.parse(process.argv[4]);
const r = { registration: "SP-LWA", photo };
const d = { callsign: "LOT3827", status: "prefiled", flight_plan: { remarks: "PBN/A1B1 REG/SPLWA", aircraft_icao: "B738/M-SDE3FGHIRWY/LB1" } };
console.log(JSON.stringify({
  reg: [m.registrationOf("PBN/A1B1 DOF/261006 REG/SPLWA /V/"), m.registrationOf("reg/d-abcd"), m.registrationOf("RMK/TCAS"),
        m.registrationOf(null)],
  html: m.planespottersHtml(r),
  small: m.planespottersHtml(r, { large: false }),
  none: m.planespottersHtml({ registration: "<b>", photo: null }),
  fplPlain: fp.fplHtml(d),
  fplLoading: fp.fplHtml(d, { reg: "SPLWA" }),
  fplPhoto: fp.fplHtml(d, { reg: "SPLWA", photo: r }),
  fplError: fp.fplHtml(d, { reg: "SPLWA", photo: { error: "Photos unavailable" } }),
}));
"""


def test_planespotters_html_in_node(tmp_path):
    node = shutil.which("node") or shutil.which("node", path="/opt/node22/bin")
    if not node:
        pytest.skip("brak Node.js")
    js = ROOT_DIR / "frontend" / "js"
    for name in ("api", "flightplan", "xlabel"):
        src = (js / f"{name}.js").read_text("utf-8")
        (tmp_path / f"{name}.mjs").write_text(re.sub(r'"\./([a-z]+)\.js"', r'"./\1.mjs"', src), "utf-8")
    (tmp_path / "t.mjs").write_text(NODE_SCRIPT, "utf-8")
    photo = {**planespotters.parse({"photos": [PHOTO]}), "photographer": "O'Brien <x>"}
    r = subprocess.run([node, str(tmp_path / "t.mjs"), (tmp_path / "api.mjs").as_uri(), (tmp_path / "flightplan.mjs").as_uri(),
                        json.dumps(photo)], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["reg"] == ["SPLWA", "D-ABCD", None, None]
    html = out["html"]
    # miniatura z adresem bez zmian, w zwykłym odnośniku do strony zdjęcia (bez nofollow), autor obok
    assert f'<img src="{PHOTO["thumbnail_large"]["src"]}"' in html and f'<a href="{PHOTO["link"]}"' in html
    assert "nofollow" not in html and "Photo: O&#39;Brien &lt;x&gt;" in html
    assert f'<img src="{PHOTO["thumbnail"]["src"]}"' in out["small"]
    assert "&lt;b&gt;" in out["none"] and "<img" not in out["none"]
    # FLIGHT PLAN: bez rejestracji w opcjach bez sekcji zdjęcia (jak dotąd), z rejestracją wczytywanie, zdjęcie albo błąd
    assert "fpl-photo" not in out["fplPlain"]
    assert '<h3 class="fpl-h">Aircraft SPLWA</h3><p class="hint">Loading photo' in out["fplLoading"]
    assert 'class="ps-photo"' in out["fplPhoto"] and PHOTO["link"] in out["fplPhoto"]
    assert '<p class="hint">Photos unavailable</p>' in out["fplError"]
