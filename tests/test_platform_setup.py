"""Regression tests for macOS push-to-talk, wake-word install, action isolation and Linux setup."""
import sys
from types import SimpleNamespace

from core import action_loader, hotkey, wake_word


def test_macos_chord_is_physical_control_not_command(monkeypatch):
    monkeypatch.setattr(hotkey, "_OS", "Darwin")
    assert hotkey.qt_sequence() == "Meta+Space"      # Qt's "Ctrl" is ⌘ on macOS
    monkeypatch.setattr(hotkey, "_OS", "Linux")
    assert hotkey.qt_sequence() == "Ctrl+Space"


def test_wake_word_installs_a_version_this_code_can_use(monkeypatch):
    calls = []
    monkeypatch.setattr(wake_word, "is_installed", lambda: False)
    monkeypatch.setattr(wake_word.subprocess, "run",
                        lambda argv, **k: calls.append(argv) or SimpleNamespace(returncode=0))

    wake_word.install_and_download(logger=lambda *_: None)

    first = calls[0]
    assert "--no-deps" in first and "openwakeword>=0.6,<0.7" in first
    assert any("onnxruntime>=1.10,<2" in c for c in calls[1])


def test_an_action_that_exits_on_import_cannot_kill_discovery(tmp_path):
    (tmp_path / "needs_tk.py").write_text(
        "import sys\nsys.exit('NOTE: You must install tkinter on Linux')\n")
    (tmp_path / "fine.py").write_text(
        "def run(parameters):\n    return 'ok'\n"
        "TOOL = {'name': 'fine', 'description': 'ok', 'handler': run,\n"
        "        'parameters': {'type': 'OBJECT', 'properties': {}}}\n")

    registry = action_loader.discover_actions(tmp_path, logger=lambda *_: None)

    assert "fine" in registry.names()


def test_linux_setup_names_the_missing_system_libraries(monkeypatch, capsys):
    import ctypes.util
    import setup
    monkeypatch.setattr(ctypes.util, "find_library", lambda _name: None)
    monkeypatch.setitem(sys.modules, "tkinter", None)          # import fails

    setup._check_linux_libraries()

    out = capsys.readouterr().out
    assert "python3-tk libportaudio2 libxcb-cursor0" in out


def test_setup_explains_an_externally_managed_python(tmp_path, monkeypatch, capsys):
    import sysconfig

    import pytest
    import setup
    (tmp_path / "EXTERNALLY-MANAGED").write_text("[externally-managed]")
    monkeypatch.setattr(sysconfig, "get_path", lambda name: str(tmp_path))
    monkeypatch.setattr(sys, "prefix", sys.base_prefix)            # not in a venv
    with pytest.raises(SystemExit):
        setup._check_environment()
    assert "venv" in capsys.readouterr().out
