"""Regression tests: code_helper must never destroy the file it was asked to improve."""
from types import SimpleNamespace

import pytest

from actions import code_helper as ch
from core import undo


@pytest.fixture
def fake_gemini(monkeypatch):
    replies = []
    monkeypatch.setattr(ch.gemini, "call",
                        lambda *a, **k: SimpleNamespace(text=replies.pop(0)))
    undo.clear()
    yield replies
    undo.clear()


def test_optimize_refuses_files_longer_than_the_prompt_window(tmp_path, fake_gemini):
    src = tmp_path / "big.py"
    original = "".join(f"x_{i} = {i}\n" for i in range(1200))   # ~11 KB
    src.write_text(original)
    fake_gemini.append("x_0 = 0\n")

    ch._optimize_action(str(src), "", "python", "", None)

    assert src.read_text() == original


def test_edit_can_be_undone(tmp_path, fake_gemini):
    src = tmp_path / "notes_app.py"
    src.write_bytes(b"print('hand written')\r\n")
    fake_gemini.append("print('model rewrote everything')")

    ch._edit_action(str(src), "rename things", None)
    assert undo.can_undo()
    undo.undo_last()

    assert src.read_bytes() == b"print('hand written')\r\n"


def test_screen_debug_never_overwrites_the_original(tmp_path, fake_gemini, monkeypatch):
    src = tmp_path / "app.py"
    src.write_text("total = 1\nprint(totl)\n")
    shot = tmp_path / "shot.png"
    shot.write_bytes(b"\x89PNG")
    monkeypatch.setattr(ch, "_take_screenshot", lambda: shot)
    fake_gemini.append(
        "The error is:\n```\nNameError: name 'totl' is not defined\n```\n"
        "Fix:\n```python\ntotal = 1\nprint(total)\n```")

    ch._screen_debug_action("why does it crash", str(src), None)

    assert src.read_text() == "total = 1\nprint(totl)\n"
    assert (tmp_path / "app.fixed.py").read_text() == "total = 1\nprint(total)"
