"""0.15.0: zapasowe źródło NOTAM (FAA NOTAM API), gdy serwer PL vACC nie odpowiada. Odpowiedzi obu serwerów są
podstawione (httpx.MockTransport), bez sieci."""
import asyncio
import json
from datetime import datetime, timezone

import httpx
import pytest

from backend.app.config import settings
from backend.app.services import http_cache, notam

REAL_CLIENT = httpx.AsyncClient
PL_TEXT = ("A1234/26 NOTAMN\nQ) EPWW/QMRLC/IV/NBO/A/000/999/5210N02058E005\nA) EPWA B) 2611010600 C) 2612012200\n"
           "E) RWY 11/29 CLSD")
FAA_ITEM = {"type": "Feature", "properties": {"coreNOTAMData": {"notam": {
    "number": "A2222/26", "type": "N", "affectedFIR": "EPWW", "selectionCode": "QFALC", "traffic": "IV",
    "purpose": "NBO", "scope": "A", "minimumFL": "000", "maximumFL": "999", "coordinates": "5210N02058E005",
    "icaoLocation": "EPWA", "effectiveStart": "2026-11-01T06:00:00.000Z", "effectiveEnd": "2026-12-01T22:00:00.000Z",
    "text": "AD CLSD FOR TFC"}}}}
FAA_ICAO = {"properties": {"coreNOTAMData": {"notam": {"text": "ignored"}, "notamTranslation": [
    {"type": "LOCAL_FORMAT", "simpleText": "x"},
    {"type": "ICAO", "formattedText": "A3333/26 NOTAMN\nQ) EPWW/QMXLC/IV/M/A/000/999/\nA) EPWA B) 2611010600 "
                                      "C) PERM\nE) TWY A CLSD"}]}}}


@pytest.fixture
def servers(monkeypatch):
    """Podstawiony serwer PL vACC i FAA; state["pl"] / state["faa"]: "ok", "down" albo funkcja odpowiedzi."""
    state = {"pl": "ok", "faa": "ok", "calls": []}

    def handler(request):
        url = str(request.url)
        faa = url.startswith(settings.faa_notam_url)
        state["calls"].append(("faa" if faa else "pl", url, dict(request.headers)))
        mode = state["faa" if faa else "pl"]
        if mode == "down":
            raise httpx.ConnectError("down", request=request)
        if callable(mode):
            return mode(request)
        if faa:
            return httpx.Response(200, json={"totalPages": 1, "items": [FAA_ITEM, FAA_ICAO]})
        return httpx.Response(200, text=PL_TEXT)

    monkeypatch.setattr(http_cache.httpx, "AsyncClient", lambda **kw: REAL_CLIENT(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(settings, "faa_client_id", "test-id")
    monkeypatch.setattr(settings, "faa_client_secret", "test-secret")
    http_cache.clear_cache()
    notam.reset_fallback()
    notam.clear_fir_failures()
    yield state
    http_cache.clear_cache()
    notam.reset_fallback()
    notam.clear_fir_failures()


def ids(data):
    return [n["id"] for n in data["notams"]]


def test_faa_text_from_fields_and_translation():
    built = notam.faa_notam_text(FAA_ITEM)
    assert built.splitlines()[0] == "A2222/26 NOTAMN"
    assert "Q) EPWW/QFALC/IV/NBO/A/000/999/5210N02058E005" in built and "A) EPWA" in built
    assert "B) 2611010600" in built and "C) 2612012200" in built and built.endswith("E) AD CLSD FOR TFC")
    # gotowe tłumaczenie ICAO wygrywa z polami
    assert notam.faa_notam_text(FAA_ICAO).startswith("A3333/26 NOTAMN") and "ignored" not in notam.faa_notam_text(FAA_ICAO)
    assert notam.faa_notam_text({"properties": {"coreNOTAMData": {"notam": {"text": ""}}}}) is None
    assert notam.faa_notam_text("x") is None
    # kod Q bez "Q" z przodu dostaje go; PERM bez zmian
    item = json.loads(json.dumps(FAA_ITEM))
    item["properties"]["coreNOTAMData"]["notam"].update(selectionCode="MRLC", effectiveEnd="PERM")
    text = notam.faa_notam_text(item)
    assert "/QMRLC/" in text and "C) PERM" in text
    parsed = notam.split_notams(text)[0]
    assert parsed["id"] == "A2222/26" and parsed["perm"] is True


def test_primary_ok_faa_not_asked(servers):
    data = asyncio.run(notam.get_notams("EPWA"))
    assert ids(data) == ["A1234/26"] and data["source"] == notam.notam_url("EPWA")
    assert [c[0] for c in servers["calls"]] == ["pl"]


def test_primary_down_falls_back_to_faa(servers):
    servers["pl"] = "down"
    data = asyncio.run(notam.get_notams("EPWA"))
    assert ids(data) == ["A2222/26", "A3333/26"] and data["source"] == notam.faa_url("EPWA")
    faa = [c for c in servers["calls"] if c[0] == "faa"]
    assert faa and faa[0][2]["client_id"] == "test-id" and faa[0][2]["client_secret"] == "test-secret"
    assert "icaoLocation=EPWA" in faa[0][1] and "responseFormat=geoJson" in faa[0][1]
    # klucze tylko w nagłówkach, nie w adresie (ani w "source" do interfejsu)
    assert "test-secret" not in data["source"] and "test-secret" not in faa[0][1]
    # zaraz potem serwer PL vACC nie jest pytany (PRIMARY_DOWN_SECONDS), od razu FAA z cache
    servers["calls"].clear()
    asyncio.run(notam.get_notams("EPKK"))
    assert [c[0] for c in servers["calls"]] == ["faa"]


def test_both_down_is_upstream_error(servers):
    servers["pl"] = servers["faa"] = "down"
    with pytest.raises(http_cache.UpstreamError):
        asyncio.run(notam.get_notams("EPWA"))


def test_bad_faa_reply_not_cached(servers):
    servers["pl"] = "down"
    servers["faa"] = lambda r: httpx.Response(200, json={"error": "invalid client"})
    with pytest.raises(http_cache.UpstreamError):
        asyncio.run(notam.get_notams("EPWA"))
    assert http_cache.peek(notam.faa_url("EPWA")) is None


def test_fallback_off_without_keys(servers, monkeypatch):
    monkeypatch.setattr(settings, "faa_client_secret", "")
    servers["pl"] = "down"
    with pytest.raises(http_cache.UpstreamError):
        asyncio.run(notam.get_notams("EPWA"))
    assert all(c[0] == "pl" for c in servers["calls"])


def test_fir_list_uses_fallback(servers):
    servers["pl"] = "down"
    now = datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)
    data = asyncio.run(notam.fir_notams(now=now, locations=["EPWW", "EPWA"]))
    assert data["failed"] == [] and data["stale"] == []
    assert {"A2222/26", "A3333/26"} <= set(ids(data))
