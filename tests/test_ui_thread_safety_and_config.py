"""Regression tests for the API-key setup flow and cross-thread UI calls."""
import json
import threading


def test_reentering_api_key_keeps_other_settings(jarvis_ui, config_file, pump):
    # main.py calls prompt_reconfig() when Gemini rejects the key; the user then
    # types a new one. Only the key (and OS) may change — nothing else.
    settings = {
        "gemini_api_key": "OLD-REVOKED-KEY-1234567890",
        "os_system": "linux",
        "assistant_name": "FRIDAY",
        "user_name": "Tony",
        "ui_color": "#ff3355",
        "voice_name": "Kore",
        "wake_word_enabled": True,
        "plugin_config": {"email": {"imap_password": "secret"}},
    }
    config_file.write_text(json.dumps(settings), encoding="utf-8")

    jarvis_ui.prompt_reconfig()
    pump(50)
    jarvis_ui._win._on_setup_done("NEW-VALID-KEY-0987654321", "linux")

    saved = json.loads(config_file.read_text(encoding="utf-8"))
    assert saved == {**settings, "gemini_api_key": "NEW-VALID-KEY-0987654321"}
    assert jarvis_ui.assistant_name == "FRIDAY"


def test_first_run_setup_writes_key_and_os(jarvis_ui, config_file):
    jarvis_ui._win._on_setup_done("FIRST-KEY-1234567890", "mac")

    saved = json.loads(config_file.read_text(encoding="utf-8"))
    assert saved == {"gemini_api_key": "FIRST-KEY-1234567890", "os_system": "mac"}


def test_notify_phone_connected_from_worker_thread_is_marshalled(
        jarvis_ui, qt_messages, pump):
    # The dashboard's /login route runs on main.py's asyncio thread and calls
    # this; Qt objects may only be touched from the GUI thread.
    win = jarvis_ui._win
    win.on_remote_clicked = lambda: (
        "https://192.168.1.2:8000", "ABC123",
        "https://192.168.1.2:8000/auto-login?key=ABC123", "192.168.1.2:8001")
    win._open_remote()
    pump(50)
    overlay = win._remote_overlay
    assert overlay.isVisible()

    qt_messages.clear()
    worker = threading.Thread(target=jarvis_ui.notify_phone_connected)
    worker.start()
    worker.join()
    pump(100)

    assert not [m for m in qt_messages if "thread" in m.lower()], qt_messages
    assert overlay._key_lbl.text() == "CONNECTED"
    assert not overlay._ctimer.isActive()
