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


def test_success_is_judged_by_exit_code_not_words(tmp_path):
    ok = tmp_path / "ok.py"
    ok.write_text("print('0 errors, build complete')")
    crash = tmp_path / "crash.py"
    crash.write_text("import sys; sys.exit(3)")
    assert not ch._has_error(ch._run_file(ok, [], 30))
    assert ch._has_error(ch._run_file(crash, [], 30))


def test_run_accepts_args_as_the_declared_string(tmp_path):
    script = tmp_path / "echo.py"
    script.write_text("import sys; print(sys.argv[1:])")
    assert "['--name', 'Ada Lovelace']" in ch._run_file(script, '--name "Ada Lovelace"', 30)


def test_optimizing_a_snippet_never_overwrites_the_named_file(tmp_path, fake_gemini):
    target = tmp_path / "app.py"
    target.write_text("def main():\n    pass\n# lots more code\n")
    fake_gemini.append("x = 1")
    ch._optimize_action(str(target), "x=1", "python", str(tmp_path / "out.py"), None)
    assert target.read_text() == "def main():\n    pass\n# lots more code\n"


def test_screenshot_is_not_left_on_the_desktop(tmp_path, monkeypatch):
    monkeypatch.setattr(ch.Path, "home", classmethod(lambda cls: tmp_path))
    import pyautogui
    monkeypatch.setattr(pyautogui, "screenshot", lambda: SimpleNamespace(save=lambda p: open(p, "wb").close()))
    shot = ch._take_screenshot()
    assert shot is not None and tmp_path not in shot.parents
    shot.unlink()


def test_home_relative_paths_are_expanded(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "script.py").write_text("print(1)")
    assert ch._resolve_save_path("~/out.py", "python") == tmp_path / "out.py"
    assert ch._read_file("~/script.py")[0] == "print(1)"
