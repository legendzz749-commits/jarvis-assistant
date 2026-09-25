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


def test_pairing_code_is_burned_after_repeated_wrong_guesses(dash):
    d, client, _ = dash
    code = d.new_key()
    for guess in ("AAAAAA", "BBBBBB", "CCCCCC", "DDDDDD", "EEEEEE"):
        assert client.post("/login", json={"pin": guess}).status_code == 401
    assert client.post("/login", json={"pin": code}).status_code == 401


def test_only_the_newest_pairing_code_is_valid(dash):
    d, client, _ = dash
    old = d.new_key()
    d.new_key()
    assert client.post("/login", json={"pin": old}).status_code == 401


def test_revoking_devices_invalidates_their_tokens(dash):
    d, client, _ = dash
    d._tokens.add("phone-token")
    r = client.post("/api/revoke-devices", headers={"Authorization": "Bearer good-token"})
    assert r.status_code == 200
    r = client.post("/api/wake", headers={"Authorization": "Bearer phone-token"})
    assert r.status_code == 401


def test_generated_certificate_meets_apple_tls_rules(tmp_path, monkeypatch):
    import datetime
    from cryptography import x509
    from cryptography.x509.oid import ExtendedKeyUsageOID
    monkeypatch.setattr(server, "BASE_DIR", tmp_path)
    assert server._ensure_certs()
    cert = x509.load_pem_x509_certificate((tmp_path / "config" / "certs" / "jarvis.crt").read_bytes())
    eku = cert.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
    assert ExtendedKeyUsageOID.SERVER_AUTH in eku
    assert cert.not_valid_after_utc - cert.not_valid_before_utc <= datetime.timedelta(days=826)


def test_upload_support_follows_the_multipart_package():
    import importlib.util
    has_parser = bool(importlib.util.find_spec("python_multipart") or importlib.util.find_spec("multipart"))
    assert server._UPLOAD_OK == has_parser


def test_without_cryptography_the_page_gets_no_cryptojs(dash, monkeypatch):
    d, client, _ = dash
    monkeypatch.setattr(server, "_CRYPTO_OK", False)
    assert client.get("/static/crypto.js", follow_redirects=False).status_code == 404
