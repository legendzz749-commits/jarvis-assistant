"""Regression tests for desktop organize/clean/wallpaper and the topic monitor."""
import pytest

from actions import background_monitor as bm
from actions import desktop
from core import undo


@pytest.fixture
def desk(tmp_path, monkeypatch):
    d = tmp_path / "Desktop"
    d.mkdir()
    monkeypatch.setattr(desktop, "_get_desktop", lambda: d)
    undo.clear()
    yield d
    undo.clear()


def test_organize_is_undoable_and_survives_a_locked_file(desk, monkeypatch):
    for name in ("a.png", "b.pdf", "c.mp3"):
        (desk / name).write_text(name)
    real = desktop.shutil.move

    def flaky(src, dst):
        if src.endswith("b.pdf"):
            raise PermissionError("in use")
        return real(src, dst)
    monkeypatch.setattr(desktop.shutil, "move", flaky)

    out = desktop.organize_desktop()
    monkeypatch.setattr(desktop.shutil, "move", real)
    undo.undo_last()

    assert "could not be moved" in out
    assert sorted(p.name for p in desk.iterdir()) == ["a.png", "b.pdf", "c.mp3"]


def test_clean_desktop_can_be_undone(desk):
    (desk / "notes.txt").write_text("x")
    desktop.clean_desktop()
    undo.undo_last()
    assert (desk / "notes.txt").read_text() == "x"
    assert [p.name for p in desk.iterdir()] == ["notes.txt"]


def test_generated_code_can_use_the_shutil_shim(tmp_path):
    src = tmp_path / "a.txt"
    src.write_text("x")
    out = desktop._execute_generated_code(
        f"shutil.copy2({str(src)!r}, {str(tmp_path / 'b.txt')!r})\nprint('ok')")
    assert (tmp_path / "b.txt").exists(), out


def test_wallpaper_download_is_kept_and_bounded(tmp_path, monkeypatch):
    import io
    import urllib.request
    monkeypatch.setattr(desktop.Path, "home", classmethod(lambda cls: tmp_path))
    set_to = []
    monkeypatch.setattr(desktop, "set_wallpaper", lambda p: set_to.append(p) or "Wallpaper set")
    timeouts = []

    def fake_urlopen(url, timeout=None):
        timeouts.append(timeout)
        return io.BytesIO(b"\x89PNG fake")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    desktop.set_wallpaper_from_url("https://example.com/a.png")

    assert timeouts == [15]
    assert desktop.Path(set_to[0]).exists()           # the OS re-reads this file later


def test_non_latin_topics_get_distinct_keys():
    assert bm._slug("Galatasaray") != bm._slug("Москва") != bm._slug("東京")
    assert bm._slug("Москва") and bm._slug("東京")


def test_failed_or_web_page_results_are_not_announced_or_marked_checked(monkeypatch):
    saved = {}
    monitors = {"ai": {"topic": "AI"}}
    monkeypatch.setattr(bm, "_load", lambda: {k: dict(v) for k, v in monitors.items()})
    monkeypatch.setattr(bm, "_save", lambda m: saved.update(m))
    import actions.web_search as ws
    monkeypatch.setattr(ws, "_ddg_news", lambda q, max_results=5: [{"title": "Some homepage", "url": "x"}])

    assert bm.check_all() == []
    assert "last_check" not in saved.get("ai", {})


def test_check_does_not_resurrect_a_monitor_removed_meanwhile(monkeypatch):
    store = {"ai": {"topic": "AI"}, "f1": {"topic": "F1"}}
    saved = {}

    def load():
        return {k: dict(v) for k, v in store.items()}

    def news(q, max_results=5):
        store.pop("f1", None)                          # user removes F1 during the check
        return [{"title": f"{q} headline", "source": "Reuters"}]
    monkeypatch.setattr(bm, "_load", load)
    monkeypatch.setattr(bm, "_save", lambda m: saved.update(m))
    import actions.web_search as ws
    monkeypatch.setattr(ws, "_ddg_news", news)

    bm.check_all()
    assert "f1" not in saved
