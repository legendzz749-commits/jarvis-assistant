"""Regression tests: file actions must never destroy a file the user already had."""
import pytest

from actions import file_controller as fc
from core import undo


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(fc.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(fc, "_SAFE_ROOTS", [tmp_path])
    for d in ("Desktop", "Documents", "Downloads"):
        (tmp_path / d).mkdir()
    undo.clear()
    yield tmp_path
    undo.clear()


def test_move_refuses_to_overwrite(home):
    (home / "Desktop" / "report.pdf").write_text("draft")
    (home / "Documents" / "report.pdf").write_text("FINAL signed")

    msg = fc.move_file(str(home / "Desktop"), "report.pdf", str(home / "Documents"))

    assert "already exists" in msg
    assert (home / "Documents" / "report.pdf").read_text() == "FINAL signed"
    assert (home / "Desktop" / "report.pdf").read_text() == "draft"


def test_copy_refuses_to_overwrite_and_undo_keeps_users_file(home):
    (home / "Desktop" / "budget.xlsx").write_text("template")
    (home / "Documents" / "budget.xlsx").write_text("real budget")

    msg = fc.copy_file(str(home / "Desktop"), "budget.xlsx", str(home / "Documents"))
    undo.undo_last()

    assert "already exists" in msg
    assert (home / "Documents" / "budget.xlsx").read_text() == "real budget"


def test_move_and_undo_still_work(home):
    (home / "Desktop" / "a.txt").write_text("x")
    assert "Moved" in fc.move_file(str(home / "Desktop"), "a.txt", str(home / "Documents"))
    undo.undo_last()
    assert (home / "Desktop" / "a.txt").read_text() == "x"


@pytest.mark.parametrize("original", [
    "Café crème".encode("cp1252"),              # non-UTF-8 text
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR",     # binary
    b"a,b\r\n1,2\r\n",                          # CRLF
])
def test_write_undo_restores_exact_bytes(home, original):
    target = home / "Documents" / "file.bin"
    target.write_bytes(original)

    fc.write_file(str(home / "Documents"), "file.bin", "oops")
    undo.undo_last()

    assert target.read_bytes() == original


def test_create_over_existing_undo_restores_exact_bytes(home):
    target = home / "Documents" / "notes.txt"
    target.write_bytes(b"line1\r\nline2\r\n")
    fc.create_file(str(home / "Documents"), "notes.txt", "new")
    undo.undo_last()
    assert target.read_bytes() == b"line1\r\nline2\r\n"


def test_find_skips_hidden_trees_and_accepts_bare_extension(home):
    for i in range(600):                         # a big ~/.cache
        (home / ".cache" / f"d{i}").mkdir(parents=True)
    (home / "Downloads" / "CV").mkdir()
    (home / "Downloads" / "CV" / "resume.pdf").write_text("pdf")

    assert "resume.pdf" in fc.find_files(name="resume", path=str(home))
    assert "resume.pdf" in fc.find_files(extension="pdf", path=str(home / "Downloads"))
