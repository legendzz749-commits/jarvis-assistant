"""Regression tests for UI robustness: slot exceptions, colours, clipboard, launchers."""
import subprocess
import sys

import pytest


def test_bad_colour_is_rejected_not_raised():
    import ui
    for bad in ("#0x12ab", "#12_345", "#12345g", "123456"):
        assert ui.apply_ui_accent(bad) is False


def test_exception_in_a_slot_does_not_abort_the_app(tmp_path):
    # PyQt6 aborts the process when a slot raises and no excepthook is set.
    probe = (
        "import sys, os; os.environ['QT_QPA_PLATFORM']='offscreen'; sys.path.insert(0, %r)\n"
        "import ui\n"
        "from PyQt6.QtCore import QTimer\n"
        "j = ui.JarvisUI('face.png')\n"
        "def boom(): raise ValueError('bad payload')\n"
        "QTimer.singleShot(50, boom)\n"
        "QTimer.singleShot(300, j._app.quit)\n"
        "j._app.exec()\n"
        "print('still alive')\n"
    ) % str(__import__("pathlib").Path(__file__).resolve().parent.parent)
    r = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True,
                       timeout=60, cwd=tmp_path)
    assert "still alive" in r.stdout, r.stderr[-800:]


def test_concealed_clipboard_is_not_shown(jarvis_ui, pump):
    from PyQt6.QtCore import QMimeData
    from PyQt6.QtWidgets import QApplication
    shown = []
    jarvis_ui._win._clipboard_sig.connect(shown.append)
    mime = QMimeData()
    mime.setText("hunter2-super-secret-password")
    mime.setData("x-kde-passwordManagerHint", b"secret")
    QApplication.clipboard().setMimeData(mime)
    pump(50)
    jarvis_ui._win._on_clipboard_changed()
    assert shown == []


def test_desktop_exec_quotes_paths_with_spaces():
    import shlex
    import ui
    line = ui._desktop_exec("/usr/bin/python3", "/home/me/My Projects/jarvis/main.py")
    assert shlex.split(line) == ["/usr/bin/python3", "/home/me/My Projects/jarvis/main.py"]
    assert "%%" in ui._desktop_exec("/tmp/100%/main.py")


def test_review_findings_are_ordered_by_severity(jarvis_ui, pump):
    win = jarvis_ui._win
    win._show_review("Lease", "ok", [
        {"severity": "note", "heading": "NOTE-ITEM"},
        {"severity": "serious", "heading": "SERIOUS-ITEM"},
        {"severity": "caution", "heading": "CAUTION-ITEM"}], [])
    pump(20)
    html = win._content_display.toPlainText()
    order = [html.find(k) for k in ("SERIOUS-ITEM", "CAUTION-ITEM", "NOTE-ITEM")]
    assert -1 not in order and order == sorted(order)


def test_quiz_and_review_panels_do_not_squash_each_other(jarvis_ui, pump):
    win = jarvis_ui._win
    win.resize(1100, 900)
    pump(50)
    win._show_quiz("history", [{"type": "short", "question": "Year of the moon landing?",
                                "answer": "1969"}], None)
    pump(20)
    win._show_review("Lease", "ok", [{"severity": "note", "heading": "x"}], [])
    pump(20)
    _hud, content, quiz = win._center_split.sizes()
    assert content > 0 and quiz > 0, win._center_split.sizes()


def test_log_colours_replies_by_the_custom_name_and_errors_by_prefix(qapp, config_file, pump):
    import json
    import ui
    config_file.write_text(json.dumps({"gemini_api_key": "k" * 20, "assistant_name": "Friday"}))
    j = ui.JarvisUI("face.png")
    try:
        log = j._win._log
        for line, tag in (("Friday: done", "ai"), ("SYS: call Jerry back", "sys"),
                          ("ERR: mic failed", "err")):
            log._queue = [line]
            log._next()
            log._tmr.stop()
            assert log._tag == tag, line
    finally:
        j._win.close()


def test_facade_glance_reaches_the_avatar(jarvis_ui, monkeypatch):
    seen = []
    monkeypatch.setattr(jarvis_ui._win.hud, "glance", lambda *a: seen.append(a))
    jarvis_ui.glance(0.0, -0.8)
    assert seen


def test_new_log_lines_do_not_steal_the_users_selection_or_scroll(jarvis_ui, pump):
    log = jarvis_ui._win._log
    log.resize(300, 120)
    for i in range(60):
        log._append(f"line {i}\n")
    log.verticalScrollBar().setValue(0)                  # user scrolled up to read
    cur = log.textCursor()
    cur.setPosition(0)
    cur.setPosition(4, cur.MoveMode.KeepAnchor)          # and selected "line"
    log.setTextCursor(cur)
    log._append("new line\n")
    assert log.textCursor().selectedText() == "line"
    assert log.verticalScrollBar().value() == 0


def test_clearing_the_file_resets_the_hint(jarvis_ui, tmp_path, pump):
    win = jarvis_ui._win
    f = tmp_path / "notes.txt"
    f.write_text("x")
    win._drop_zone._set_file(str(f))
    pump(20)
    win._drop_zone.clear_file()
    pump(20)
    assert win._current_file is None and "No file loaded" in win._file_hint.text()


def test_content_title_keeps_the_users_casing(jarvis_ui, pump):
    jarvis_ui._win._show_content("SEARCH — istanbul hava", "…")
    assert jarvis_ui._win._content_title_lbl.text() == "SEARCH — istanbul hava"


def test_muting_from_a_worker_thread_is_marshalled(jarvis_ui, pump):
    import threading
    seen = []
    win = jarvis_ui._win
    orig = win._toggle_mute
    win._toggle_mute = lambda: (seen.append(threading.current_thread() is threading.main_thread()), orig())
    t = threading.Thread(target=lambda: setattr(jarvis_ui, "muted", True))
    t.start(); t.join()
    pump(50)
    assert seen == [True] and jarvis_ui.muted


def test_closed_overlays_are_deleted(jarvis_ui, pump):
    from PyQt6.QtCore import QCoreApplication, QEvent
    from PyQt6.QtWidgets import QPushButton
    from ui import CustomizeOverlay, PluginManagerOverlay
    win = jarvis_ui._win
    win.get_plugins = lambda: []
    cw = win.centralWidget()
    for _ in range(3):
        win._open_customize()
        win._customize_overlay._cancel()
        win._open_plugin_manager()
        next(b for b in win._plugin_manager_overlay.findChildren(QPushButton) if b.text() == "CLOSE").click()
        pump(20)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not cw.findChildren(CustomizeOverlay) and not cw.findChildren(PluginManagerOverlay)
    win.resize(win.width() + 10, win.height())       # resize must not touch a deleted overlay
    pump(20)


def test_many_plugins_keep_close_on_screen_and_toggles_rebuild(jarvis_ui, pump, monkeypatch):
    from PyQt6.QtWidgets import QPushButton
    from memory import config_manager
    win = jarvis_ui._win
    monkeypatch.setattr(config_manager, "save_plugin_enabled", lambda n, v: None)
    monkeypatch.setattr(config_manager, "get_plugin_enabled", lambda n: False)
    win.get_plugins = lambda: [{"name": f"p{i}", "valid": True, "enabled": False, "file": "",
                                "description": "", "error": ""} for i in range(40)]
    rebuilt = []
    jarvis_ui.on_plugins_change = lambda: rebuilt.append(True)
    win._open_plugin_manager()
    pump(20)
    ov, cw = win._plugin_manager_overlay, win.centralWidget()
    assert ov.y() >= 0 and ov.geometry().bottom() <= cw.height()
    next(b for b in ov.findChildren(QPushButton) if b.text() == "OFF").click()
    assert rebuilt == [True]


@pytest.fixture
def restore_palette():
    import ui
    saved = ui.current_palette()
    yield
    for k, v in saved.items():
        setattr(ui.C, k, v)


def test_cpu_bar_follows_a_live_recolour(qapp, restore_palette):
    import ui
    bar = ui.MetricBar("CPU", ui.C.PRI)
    bar.resize(120, 38)
    bar.set_value(50, "50%")
    ui.apply_ui_accent("#ff0000")
    pixel = bar.grab().toImage().pixelColor(12, 31).name()
    assert pixel == ui.C.PRI


@pytest.mark.parametrize("accent", ["#00ff88", "#ff6b00", "#ffcc00", "#808080"])
def test_derived_colours_never_collide_with_fixed_ones(qapp, restore_palette, accent):
    import ui
    ui.apply_ui_accent(accent)
    derived = list(ui.current_palette().values())
    assert len(set(derived)) == len(derived)
    assert not set(derived) & {ui.C.GREEN, ui.C.ACC, ui.C.ACC2, "#00140a"}


def test_recolour_repaints_an_open_review(jarvis_ui, pump, restore_palette):
    import ui
    win = jarvis_ui._win
    win._show_review("Contract", "Looks fine.", [], [])
    win._preview_ui_color("#ff0000")
    assert ui.C.WHITE in win._content_display.toHtml().lower()


def test_viseme_batches_append_and_survive_concurrent_ticks(jarvis_ui):
    import threading
    import time
    hud = jarvis_ui._win.hud
    t0 = time.time()
    hud.push_visemes([(0.5, 0.1, 0.0)] * 5, 0.02, t0)
    hud.push_visemes([(0.5, 0.6, 0.0)] * 5, 0.02, t0 + 0.1)
    assert len(hud._visemes[0]) == 10                # one continuous timeline

    errors = []
    def feed():
        try:
            for k in range(300):
                hud.push_visemes([(0.4, 0.3, 0.1)] * 10, 0.02, time.time() + k * 0.001)
        except Exception as e:                        # pragma: no cover
            errors.append(e)
    t = threading.Thread(target=feed)
    t.start()
    while t.is_alive():
        hud._step()
    t.join()
    assert not errors and hud._visemes is not None
