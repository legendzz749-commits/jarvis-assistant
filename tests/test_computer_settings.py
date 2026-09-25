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


@pytest.mark.parametrize("text,wrong", [
    ("restart the browser", "restart"),
    ("unlock the screen", "lock_screen"),
    ("kill 3 processes", "volume_set"),
])
def test_descriptions_do_not_resolve_to_the_wrong_action(text, wrong):
    assert cs._detect_action(text)["action"] != wrong


def test_volume_number_still_resolves():
    assert cs._detect_action("set the volume to 30") == {"action": "volume_set", "value": 30}


def test_undo_of_mute_restores_the_mute_state(monkeypatch):
    from core import undo
    undo.clear()
    state = {"muted": False}
    monkeypatch.setattr(cs, "_mute_get", lambda: state["muted"])
    monkeypatch.setattr(cs, "_set_mute", lambda m: state.__setitem__("muted", m))
    cs.computer_settings({"action": "mute"})
    assert state["muted"] is True
    undo.undo_last()
    assert state["muted"] is False


def test_xrandr_fallback_sets_a_real_value(monkeypatch):
    calls = []

    def fake_run(argv, **k):
        calls.append(argv)
        return types.SimpleNamespace(stdout="HDMI-1 connected primary\n\tBrightness: 0.80\n", returncode=0)
    monkeypatch.setattr(cs.subprocess, "run", fake_run)
    cs._xrandr_brightness_step(-0.1)
    assert calls[-1] == ["xrandr", "--output", "HDMI-1", "--brightness", "0.70"]


def test_move_without_coordinates_never_parks_in_the_failsafe_corner(monkeypatch):
    from actions import computer_control as cc
    moved = []
    monkeypatch.setattr(cc, "_move", lambda x, y: moved.append((x, y)) or "moved")
    monkeypatch.setattr(cc.pyautogui, "size", lambda: (1920, 1080))
    assert "needs" in cc.computer_control({"action": "move"})
    cc.computer_control({"action": "move", "x": 0, "y": 0})
    assert moved == [(1, 1)]


def test_user_data_never_invents_values(monkeypatch):
    from actions import computer_control as cc
    monkeypatch.setattr(cc, "_user_profile", lambda: {})
    assert cc.computer_control({"action": "user_data", "field": "email"}).startswith("NOT_IN_MEMORY")


def test_non_ascii_text_is_pasted_not_dropped(monkeypatch):
    from actions import computer_control as cc
    typed, pasted = [], []
    monkeypatch.setattr(cc, "_copy_to_clipboard", lambda t: pasted.append(t) or True)
    monkeypatch.setattr(cc.pyautogui, "typewrite", lambda t, **k: typed.append(t))
    monkeypatch.setattr(cc.pyautogui, "hotkey", lambda *a: None)
    monkeypatch.setattr(cc.time, "sleep", lambda _s: None)
    cc._type("Günaydın")
    assert pasted == ["Günaydın"] and typed == []


@pytest.mark.parametrize("typo,action", [("fullscren", "full_screen"), ("volumeup", "volume_up")])
def test_typos_still_resolve(typo, action):
    assert cs.ACTION_MAP[cs._detect_action(typo)["action"]] is cs.ACTION_MAP[action]


@pytest.mark.parametrize("os_name,expected", [("Windows", 600), ("Linux", 5), ("Darwin", 5)])
def test_scroll_moves_the_same_number_of_notches_on_every_os(monkeypatch, os_name, expected):
    scrolled = []
    monkeypatch.setattr(cs, "_OS", os_name)
    monkeypatch.setattr(cs.pyautogui, "scroll", scrolled.append)
    cs.computer_settings({"action": "scroll_down"})
    assert scrolled == [-expected]


def test_dark_mode_undo_restores_the_exact_previous_scheme(monkeypatch):
    from core import undo
    undo.clear()
    scheme = {"v": "'prefer-light'"}
    monkeypatch.setattr(cs, "_OS", "Linux")

    def fake_run(argv, **k):
        if argv[:2] == ["gsettings", "get"]:
            return types.SimpleNamespace(stdout=scheme["v"] + "\n", returncode=0)
        if argv[:2] == ["gsettings", "set"]:
            scheme["v"] = argv[-1] if argv[-1].startswith("'") else f"'{argv[-1]}'"
        return types.SimpleNamespace(stdout="", returncode=0)
    monkeypatch.setattr(cs.subprocess, "run", fake_run)

    cs.computer_settings({"action": "dark_mode"})
    assert scheme["v"] == "'prefer-dark'"
    undo.undo_last()
    assert scheme["v"] == "'prefer-light'"


def test_screen_find_sends_logical_size_on_retina(monkeypatch):
    from PIL import Image
    from actions import computer_control as cc
    from core import gemini
    sent = []
    monkeypatch.setattr(cc, "_get_api_key", lambda: "test-key")
    monkeypatch.setattr(cc.pyautogui, "size", lambda: (1440, 900))
    monkeypatch.setattr(cc.pyautogui, "screenshot", lambda: Image.new("RGB", (2880, 1800)))
    def fake_call(contents, **k):
        sent.append(Image.open(__import__("io").BytesIO(contents[0].inline_data.data)).size)
        return types.SimpleNamespace(text="700,450")
    monkeypatch.setattr(gemini, "call", fake_call)
    assert cc._screen_find("the OK button") == (700, 450)
    assert sent == [(1440, 900)]
