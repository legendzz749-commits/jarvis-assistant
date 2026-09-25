"""Regression tests for the game updater's scheduled run and its update/install split."""
import subprocess
import sys
from pathlib import Path

import pytest

from actions import game_updater as gu

ROOT = Path(__file__).resolve().parent.parent


def test_scheduled_script_run_can_import_its_dependencies(tmp_path):
    # Exactly how cron/schtasks/launchd start it: the file path, not a module.
    probe = ("import runpy, sys; sys.argv=['game_updater.py'];"
             f"runpy.run_path({str(ROOT / 'actions' / 'game_updater.py')!r}, run_name='probe')")
    r = subprocess.run([sys.executable, "-c", probe], cwd=tmp_path,
                       capture_output=True, text=True, timeout=60)
    assert "No module named 'config'" not in r.stderr, r.stderr


def test_update_of_a_game_not_in_steam_never_installs_something(monkeypatch, tmp_path):
    installed = []
    monkeypatch.setattr(gu, "_find_steam_path", lambda: tmp_path)
    monkeypatch.setattr(gu, "_get_steam_games", lambda _p: [{"name": "Portal 2"}])
    monkeypatch.setattr(gu, "_install_steam_game", lambda *a, **k: installed.append(k) or "installing")
    monkeypatch.setattr(gu, "is_linux", lambda: True)

    out = gu.game_updater({"action": "update", "platform": "both", "game_name": "Fortnite"})

    assert installed == []
    assert "not installed" in out


def test_known_ids_do_not_map_to_the_wrong_games():
    assert "fortnite" not in gu._KNOWN_APPIDS
    assert "minecraft" not in gu._KNOWN_APPIDS


def test_paused_or_queued_download_is_not_finished():
    assert gu._update_finished(4)                  # installed, nothing pending
    assert not gu._update_finished(4 | 2 | 512)    # paused mid-update
    assert not gu._update_finished(4 | 2)          # queued
    assert not gu._update_finished(4 | 2 | 1024)   # downloading


def test_symlinked_steam_root_does_not_list_every_game_twice(tmp_path):
    real = tmp_path / "real_steam"
    (real / "steamapps").mkdir(parents=True)
    (real / "steamapps" / "libraryfolders.vdf").write_text(f'"path"  "{real}"')
    link = tmp_path / "dot_steam"
    link.symlink_to(real)
    assert len(gu._get_steam_libraries(link)) == 1


def test_similar_names_do_not_resolve_to_a_different_known_game(monkeypatch):
    monkeypatch.setattr(gu, "_find_steam_path", lambda: None)
    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: (_ for _ in ()).throw(OSError("offline")))
    result = gu._search_steam_appid("elden ring nightreign")
    assert not result or result[1] != "ELDEN RING"


def test_auto_shutdown_waits_for_a_human(monkeypatch):
    from core import confirm
    started = []
    shown = []
    confirm.bind(lambda t, d: shown.append(t), lambda: None)
    monkeypatch.setattr(gu, "_watch_and_shutdown", lambda **k: started.append(1))
    try:
        reply = gu._arm_auto_shutdown(Path("/nonexistent"))
        assert "CONFIRMATION_PENDING" in reply and started == [] and shown
    finally:
        confirm.resolve(False)
        monkeypatch.setattr(confirm, "_show_cb", None)


@pytest.mark.parametrize("title,ok", [
    ("Steam", True), ("Sign in to Steam", True),
    ("ELDEN RING on Steam - Google Chrome", False), ("Steam - Mozilla Firefox", False),
    ("Steamworks SDK readme.txt - Notepad", False),
])
def test_only_steams_own_windows_are_automated(title, ok):
    assert gu._is_steam_window(title) is ok


def test_install_by_app_id_alone_is_accepted(monkeypatch, tmp_path):
    installed = []
    monkeypatch.setattr(gu, "_find_steam_path", lambda: tmp_path)
    monkeypatch.setattr(gu, "_install_steam_game", lambda p, **k: installed.append(k) or "Installing.")
    out = gu.game_updater({"action": "install", "platform": "steam", "app_id": "1245620"})
    assert installed and installed[0]["app_id"] == "1245620" and "Installing" in out


def test_flatpak_steam_is_found(tmp_path, monkeypatch):
    monkeypatch.setattr(gu.Path, "home", classmethod(lambda cls: tmp_path))
    flat = tmp_path / ".var/app/com.valvesoftware.Steam/.local/share/Steam"
    flat.mkdir(parents=True)
    assert gu._find_steam_linux() == flat


def test_result_is_not_also_spoken_as_a_user_turn(monkeypatch, tmp_path):
    spoken = []
    monkeypatch.setattr(gu, "_find_steam_path", lambda: tmp_path)
    monkeypatch.setattr(gu, "_update_steam_games", lambda p, **k: "All up to date.")
    monkeypatch.setattr(gu, "is_linux", lambda: True)
    gu.game_updater({"action": "update", "platform": "both"}, speak=spoken.append)
    assert spoken == []
