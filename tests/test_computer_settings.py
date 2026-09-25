"""Regression tests for volume, mute, hotkeys and typing in computer_settings."""
import ast
import sys
import types
from pathlib import Path

import pyautogui
import pyperclip
import pytest

from actions import computer_settings as cs


def test_every_hard_coded_key_is_one_pyautogui_knows():
    # pyautogui silently drops unknown key names, so a typo is a dead shortcut.
    tree = ast.parse(Path(cs.__file__).read_text(encoding="utf-8"))
    unknown = [
        (node.lineno, arg.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and node.func.attr in ("hotkey", "press")
        and getattr(node.func.value, "id", "") == "pyautogui"
        for arg in node.args
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
        and arg.value not in pyautogui.KEY_NAMES
    ]
    assert unknown == []


@pytest.fixture
def new_pycaw(monkeypatch):
    """pycaw >= 20251023: GetSpeakers() returns a wrapper with EndpointVolume, no Activate()."""
    calls = {}

    class Endpoint:
        def SetMasterVolumeLevelScalar(self, v, _ctx): calls["set"] = v
        def GetMasterVolumeLevelScalar(self): return 0.42

    pycaw_pkg = types.ModuleType("pycaw")
    pycaw_mod = types.ModuleType("pycaw.pycaw")
    pycaw_mod.AudioUtilities = types.SimpleNamespace(
        GetSpeakers=lambda: types.SimpleNamespace(EndpointVolume=Endpoint()))
    pycaw_mod.IAudioEndpointVolume = object
    comtypes = types.ModuleType("comtypes")
    comtypes.CLSCTX_ALL, comtypes.CoInitialize = 0, lambda: None
    monkeypatch.setitem(sys.modules, "pycaw", pycaw_pkg)
    monkeypatch.setitem(sys.modules, "pycaw.pycaw", pycaw_mod)
    monkeypatch.setitem(sys.modules, "comtypes", comtypes)
    monkeypatch.setattr(cs, "_OS", "Windows")
    monkeypatch.setattr(cs.pyautogui, "press", lambda *_: None)
    return calls


def test_windows_volume_works_with_current_pycaw(new_pycaw):
    cs.volume_set(30)
    assert new_pycaw["set"] == pytest.approx(0.30)
    assert cs.volume_get() == 42


def test_unmute_on_macos_actually_unmutes(monkeypatch):
    scripts = []
    monkeypatch.setattr(cs, "_OS", "Darwin")
    monkeypatch.setattr(cs.subprocess, "run", lambda argv, **k: scripts.append(argv[-1]))

    cs.ACTION_MAP["unmute"]()
    cs.ACTION_MAP["mute"]()

    assert scripts == ["set volume without output muted", "set volume with output muted"]


def test_type_text_falls_back_when_no_clipboard_backend(monkeypatch):
    typed = []

    def no_backend(_text):
        raise pyperclip.PyperclipException("could not find a copy/paste mechanism")
    monkeypatch.setattr(cs.pyperclip, "copy", no_backend)
    monkeypatch.setattr(cs.pyautogui, "write", lambda text, **k: typed.append(text))

    cs.type_text("hello world")

    assert typed == ["hello world"]


def test_smart_type_falls_back_when_no_clipboard_backend(monkeypatch):
    from actions import computer_control as cc
    typed = []

    def no_backend(_text):
        raise pyperclip.PyperclipException("could not find a copy/paste mechanism")
    monkeypatch.setattr(cc.pyperclip, "copy", no_backend)
    monkeypatch.setattr(cc.pyautogui, "typewrite", lambda text, **k: typed.append(text))

    cc._smart_type("a sentence that is longer than twenty characters", clear_first=False)

    assert typed == ["a sentence that is longer than twenty characters"]
