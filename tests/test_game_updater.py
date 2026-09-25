"""Regression tests for the game updater's scheduled run and its update/install split."""
import subprocess
import sys
from pathlib import Path

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
