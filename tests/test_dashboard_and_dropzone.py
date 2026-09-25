"""Regression tests for the phone dashboard's upload/serve paths and the HUD drop zone."""
import asyncio
import socket

import pytest
from fastapi.testclient import TestClient

from dashboard import server


@pytest.fixture
def dash(tmp_path, monkeypatch):
    d = server.DashboardServer()
    d._uploads_dir = tmp_path
    d._tokens.add("good-token")
    return d, TestClient(d.app), tmp_path


def test_upload_is_rejected_before_the_body_is_parsed(dash, monkeypatch):
    d, client, _ = dash
    parsed = []
    monkeypatch.setattr(server.Request, "form",
                        lambda self, **k: parsed.append(1) or (_ for _ in ()).throw(AssertionError))

    r = client.post("/api/upload", files={"file": ("a.bin", b"x" * 2_000_000)})

    assert r.status_code == 401
    assert parsed == []


def test_upload_over_the_limit_is_refused_from_its_header(dash, monkeypatch):
    d, client, _ = dash
    monkeypatch.setattr(server, "MAX_UPLOAD_MB", 1)
    parsed = []
    monkeypatch.setattr(server.Request, "form",
                        lambda self, **k: parsed.append(1) or (_ for _ in ()).throw(AssertionError))
    r = client.post("/api/upload", files={"file": ("big.bin", b"x" * 3_000_000)},
                    headers={"Authorization": "Bearer good-token"})
    assert r.status_code == 413
    assert parsed == []                                  # never spooled to disk


def test_authorised_upload_still_works(dash):
    d, client, folder = dash
    r = client.post("/api/upload", files={"file": ("notes.txt", b"hello")},
                    headers={"Authorization": "Bearer good-token"})
    assert r.status_code == 200, r.text
    assert (folder / "notes.txt").read_bytes() == b"hello"


def test_busy_port_disables_the_dashboard_instead_of_exiting():
    import uvicorn
    busy = socket.socket()
    busy.bind(("127.0.0.1", 0))
    busy.listen()
    port = busy.getsockname()[1]
    try:
        cfg = uvicorn.Config(lambda *a: None, host="127.0.0.1", port=port, log_level="critical")
        asyncio.run(server._serve_or_disable(cfg))      # must return, not raise SystemExit
    finally:
        busy.close()


def test_drop_zone_survives_its_file_disappearing(qapp, tmp_path, pump):
    import ui
    f = tmp_path / "report.pdf"
    f.write_bytes(b"%PDF")
    zone = ui.FileDropZone()
    zone.resize(300, 120)
    zone.show()
    zone._set_file(str(f))
    pump(20)
    f.unlink()

    canvas = zone.findChild(ui._DropCanvas)
    canvas.grab()                                       # forces a paintEvent
