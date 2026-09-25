"""Regression tests: app names from the model are matched exactly and never reach a shell."""
from types import SimpleNamespace

from actions import open_app


def test_aliases_match_whole_names_only():
    assert open_app._normalize("notepad++") == "notepad++"
    assert open_app._normalize("github desktop") == "github desktop"
    assert open_app._normalize("notepad") != "notepad"          # a real alias still resolves


def test_windows_launch_never_uses_a_shell(monkeypatch):
    launched = []
    monkeypatch.setattr(open_app.shutil, "which",
                        lambda name: r"C:\Windows\notepad.exe" if name.startswith("notepad") else None)
    monkeypatch.setattr(open_app.subprocess, "Popen",
                        lambda argv, **k: launched.append((argv, k.get("shell"))))
    monkeypatch.setattr(open_app.time, "sleep", lambda _s: None)

    open_app._launch_windows("notepad.exe & del important.txt")

    assert launched == [([r"C:\Windows\notepad.exe"], None)]


def test_linux_unknown_app_is_not_reported_as_opened(monkeypatch):
    monkeypatch.setattr(open_app.shutil, "which", lambda _n: None)
    monkeypatch.setattr(open_app.subprocess, "run",
                        lambda argv, **k: SimpleNamespace(returncode=4))   # xdg-open / gtk-launch fail
    assert open_app._launch_linux("nosuchapp") is False


def test_localized_names_reach_spotlight_intact(monkeypatch):
    import sys
    from actions import computer_control as cc
    typed, pasted = [], []
    fake = SimpleNamespace(PAUSE=0, press=lambda *a: None, hotkey=lambda *a: None,
                           write=lambda text, **k: typed.append(text))
    monkeypatch.setitem(sys.modules, "pyautogui", fake)
    monkeypatch.setattr(cc, "_paste_via_clipboard", lambda t: pasted.append(t) or True)
    monkeypatch.setattr(open_app.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1))
    monkeypatch.setattr(open_app.subprocess, "Popen", lambda *a, **k: (_ for _ in ()).throw(OSError()))
    monkeypatch.setattr(open_app.time, "sleep", lambda _s: None)
    open_app._launch_macos("Hesap Makinesi Öğrenci")
    assert pasted == ["Hesap Makinesi Öğrenci"] and typed == []
