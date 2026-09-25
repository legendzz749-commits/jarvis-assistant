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
