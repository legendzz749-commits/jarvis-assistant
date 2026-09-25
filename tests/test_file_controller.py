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


def test_rename_cannot_escape_to_another_folder(home):
    (home / "Documents" / "a.txt").write_text("x")
    for evil in ("../../evil.txt", str(home.parent / "evil.txt")):
        assert "plain name" in fc.rename_file(str(home / "Documents"), "a.txt", evil)
    assert (home / "Documents" / "a.txt").exists()


def test_undo_move_does_not_overwrite_a_new_file_at_the_origin(home):
    (home / "Desktop" / "a.txt").write_text("moved")
    fc.move_file(str(home / "Desktop"), "a.txt", str(home / "Documents"))
    (home / "Desktop" / "a.txt").write_text("new file")
    undo.undo_last()
    assert (home / "Desktop" / "a.txt").read_text() == "new file"
    assert (home / "Documents" / "a.txt").read_text() == "moved"


def test_copying_a_folder_into_itself_is_refused(home):
    (home / "Documents" / "proj").mkdir()
    (home / "Documents" / "proj" / "f.txt").write_text("x")
    msg = fc.copy_file(str(home / "Documents"), "proj", str(home / "Documents" / "proj" / "sub"))
    assert "into itself" in msg


def test_create_over_an_unreadable_file_is_not_undone_by_deleting_it(home, monkeypatch):
    target = home / "Documents" / "locked.log"
    target.write_text("x" * 100)

    def locked(self):
        raise PermissionError("locked by another program")
    real = fc.Path.read_bytes
    monkeypatch.setattr(fc.Path, "read_bytes", locked)
    fc.create_file(str(home / "Documents"), "locked.log", "new")
    monkeypatch.setattr(fc.Path, "read_bytes", real)
    undo.undo_last()
    assert target.exists()


def test_undo_delete_restores_from_the_linux_trash(home, monkeypatch):
    monkeypatch.setattr(fc, "_OS", "Linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))
    f = home / "Documents" / "notes.txt"
    f.write_text("keep me")
    trash = home / ".local" / "share" / "Trash"
    (trash / "files").mkdir(parents=True)
    (trash / "info").mkdir()
    f.rename(trash / "files" / "notes.txt")                    # what send2trash does
    (trash / "info" / "notes.txt.trashinfo").write_text(
        f"[Trash Info]\nPath={f}\nDeletionDate=2026-09-25T10:00:00\n")

    assert "restored" in fc._restore_from_trash(f)
    assert f.read_text() == "keep me"


def test_organize_keeps_going_and_stays_undoable_when_one_file_fails(home, monkeypatch):
    desk = home / "Desktop"
    (desk / "Images").mkdir()                                  # existed before
    (desk / "a.png").write_text("a")
    (desk / "b.pdf").write_text("b")
    (desk / "c.mp3").write_text("c")
    real_move = fc.shutil.move

    def flaky(src, dst):
        if src.endswith("b.pdf"):
            raise PermissionError("in use")
        return real_move(src, dst)
    monkeypatch.setattr(fc.shutil, "move", flaky)

    out = fc.organize_desktop()
    monkeypatch.setattr(fc.shutil, "move", real_move)
    undo.undo_last()

    assert "could not be moved" in out
    assert sorted(p.name for p in desk.iterdir() if p.is_file()) == ["a.png", "b.pdf", "c.mp3"]
    assert (desk / "Images").is_dir()                          # pre-existing folder kept


def test_write_tool_declares_append():
    assert "append" in fc.TOOL["parameters"]["properties"]


def test_localized_linux_desktop_is_found_from_user_dirs(home, monkeypatch):
    monkeypatch.setattr(fc, "_OS", "Linux")
    monkeypatch.delenv("XDG_DESKTOP_DIR", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    (home / "Masaüstü").mkdir()
    (home / ".config").mkdir()
    (home / ".config" / "user-dirs.dirs").write_text('XDG_DESKTOP_DIR="$HOME/Masaüstü"\n', encoding="utf-8")
    assert fc._get_desktop() == home / "Masaüstü"
    from actions import desktop
    assert desktop._get_desktop() == home / "Masaüstü"
