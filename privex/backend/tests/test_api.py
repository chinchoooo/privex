import io
import os
import tempfile

import cv2
import numpy as np
import pytest

os.environ.setdefault("PRIVEX_DATA_DIR", tempfile.mkdtemp(prefix="privex-test-"))

from fastapi.testclient import TestClient  # noqa: E402

from privex_server.app import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _png_with_text(text: str) -> bytes:
    img = np.full((120, 900, 3), 255, np.uint8)
    cv2.putText(img, text, (20, 75), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 0, 0), 3, cv2.LINE_AA)
    return cv2.imencode(".png", img)[1].tobytes()


def test_health(client):
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and h["llm"] is False


def test_text_scan(client):
    r = client.post("/api/text/scan", json={"text": "PAN ABCPE1234F", "style": "tag"})
    assert r.status_code == 200 and r.json()["redacted_text"] == "PAN [PAN]"


def test_image_roundtrip(client):
    r = client.post("/api/image/propose",
                    files={"file": ("t.png", io.BytesIO(_png_with_text("Email: jane.doe@gmail.com")), "image/png")})
    assert r.status_code == 200
    d = r.json()
    emails = [p for p in d["proposals"] if p["entity_type"] == "EMAIL"]
    assert emails and emails[0]["approved"]
    assert client.get(f"/api/image/session/{d['session_token']}").status_code == 200
    r = client.post("/api/image/apply", json={"session_token": d["session_token"],
                                              "boxes": [emails[0]["bbox"]], "style": "black"})
    assert r.status_code == 200 and r.json()["applied_count"] == 1
    assert client.get(f"/api/files/{r.json()['redacted_file']}").status_code == 200


def test_rejects_bad_input(client):
    assert client.post("/api/image/propose", files={"file": ("x.exe", b"MZ", "application/octet-stream")}).status_code == 415
    assert client.get("/api/files/..%2Fsecret").status_code == 404
    assert client.post("/api/image/apply", json={"session_token": "nope", "boxes": []}).status_code == 404


def test_cors_only_extensions(client):
    pre = {"Access-Control-Request-Method": "POST"}
    assert client.options("/api/text/scan", headers={**pre, "Origin": "https://evil.example"}).status_code == 400
    ok = client.options("/api/text/scan", headers={**pre, "Origin": "chrome-extension://abcdefghijklmnop"})
    assert ok.status_code == 200
