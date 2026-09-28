"""Regression tests for the avatar mesh/rig, lip-sync fallback and the echo guard."""
import subprocess
import sys
from pathlib import Path

import numpy as np

from core import avatar_mesh, echo, viseme

ROOT = Path(__file__).resolve().parent.parent


def test_mouth_corners_move_together():
    head = avatar_mesh.build_head()
    left, right = 78, 308          # inner-lip corners (lips_in[0], lips_in[10])
    assert abs(head["jaw"][left] - head["jaw"][right]) < 0.05


def test_damaged_mesh_raises_instead_of_hanging():
    probe = ("import sys, numpy as np; sys.path.insert(0, %r)\n"
             "from core import avatar_mesh\n"
             "faces = np.array([[0, 1, 2], [3, 4, 5]])   # two separate border loops\n"
             "try:\n    avatar_mesh._boundary_loop(faces)\nexcept ValueError:\n    print('fell back')\n") % str(ROOT)
    r = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=20)
    assert "fell back" in r.stdout


def test_band_energies_accept_sounddevice_blocks():
    rng = np.random.default_rng(0)
    mono = rng.integers(-3000, 3000, 1024).astype(np.int16)
    np.testing.assert_allclose(echo.band_energies(mono.reshape(-1, 1), 16000),
                               echo.band_energies(mono, 16000), rtol=1e-5)


def test_mouth_is_not_held_shut_after_the_transcript_runs_out():
    vs = viseme.VisemeStream()
    vs.feed_text("m")                                   # a lip closure
    loud = [(0.9, 0.8, 0.0)] * 200                      # (level, open, wide) — loud speech
    out = vs.frames(loud, 0.02)
    assert max(o for _lvl, o, _w in out[-20:]) > 0.3


def test_greek_ou_is_a_rounded_u():
    shapes = [v for v, _w in viseme.text_to_visemes("ουρανός")]
    assert shapes[0] == "U"


def test_confirmation_banner_is_removed_when_it_expires(monkeypatch):
    from core import confirm
    hidden = []
    monkeypatch.setattr(confirm, "TIMEOUT_SECONDS", 0.1)
    confirm.bind(lambda t, d: None, lambda: hidden.append(1))
    try:
        confirm.request("x", "Shut down", "", lambda: "done")
        import time
        time.sleep(0.4)
        assert hidden and confirm.pending_title() in ("", None)
    finally:
        monkeypatch.setattr(confirm, "_show_cb", None)


def test_saved_device_does_not_match_a_different_long_name(monkeypatch):
    import sounddevice as sd
    from core import audio_devices as ad
    devices = [{"name": "Microphone", "max_input_channels": 1, "max_output_channels": 0, "hostapi": 0},
               # both share the first 24 characters "Speakers (2- Realtek USB"
               {"name": "Speakers (2- Realtek USB Headset Earphone)"[:31], "max_input_channels": 0,
                "max_output_channels": 2, "hostapi": 0},
               {"name": "Speakers (2- Realtek USB Audio Device)"[:31], "max_input_channels": 0,
                "max_output_channels": 2, "hostapi": 0}]
    monkeypatch.setattr(sd, "query_devices", lambda *a, **k: devices)
    monkeypatch.setattr(sd, "query_hostapis", lambda *a, **k: [{"name": "MME"}])
    monkeypatch.setattr(ad, "list_devices", lambda kind: [])
    monkeypatch.setattr(ad, "_usable", lambda idx, kind: True)
    # saved from DirectSound with its full name; MME shows it cut to 31 characters
    assert ad.resolve("Speakers (2- Realtek USB Audio Device)", "output") == 2


def test_ligatures_and_fullwidth_letters_reach_the_mouth():
    assert viseme.to_latin("ﬁ") == "f" and viseme.to_latin("ａ") == "a"


def test_reset_from_another_thread_cannot_break_frame_generation():
    import threading
    from collections import deque
    stream = viseme.VisemeStream()
    resets = []

    class RacyDeque(deque):
        """Lands a GUI-thread reset (Esc) between the emptiness check and popleft."""
        def __bool__(self):
            nonempty = len(self) > 0
            if nonempty and not resets:
                t = threading.Thread(target=stream.reset)
                resets.append(t)
                t.start()
                t.join(0.2)          # with the lock, reset waits for frames() instead
            return nonempty

    stream._q = RacyDeque(viseme.text_to_visemes("mama papa"))
    stream.frames([(0.8, 0.5, 0.0)] * 5, 1.0)
    resets[0].join()


def test_wake_word_readiness_does_not_import_openwakeword(tmp_path, monkeypatch):
    import importlib.util
    import types
    from core import wake_word
    pkg = tmp_path / "openwakeword"
    models = pkg / "resources" / "models"
    models.mkdir(parents=True)
    for f in (f"{wake_word.WAKE_MODEL}_v0.1.onnx", "melspectrogram.onnx", "embedding_model.onnx"):
        (models / f).write_bytes(b"")
    (pkg / "__init__.py").write_text("raise RuntimeError('heavy import')")
    spec = types.SimpleNamespace(submodule_search_locations=[str(pkg)])
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: spec if name == "openwakeword" else None)
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delitem(sys.modules, "openwakeword", raising=False)
    assert wake_word.is_ready()


def test_device_list_waits_for_the_running_prefetch(monkeypatch):
    import time
    from core import audio_devices
    calls = []

    def slow_query():
        calls.append(1)
        time.sleep(0.3)
        return {"input": ["Mic"], "output": ["Speakers"]}
    monkeypatch.setattr(audio_devices, "_query", slow_query)
    monkeypatch.setattr(audio_devices, "_cache", None)
    audio_devices.prefetch()
    time.sleep(0.05)                                     # prefetch is mid-probe
    assert audio_devices.list_devices("input") == ["Mic"]
    assert len(calls) == 1


def test_brows_drift_apart_while_speaking_and_settle_in_silence():
    import random
    from core import avatar
    random.seed(7)
    a = avatar.HoloAvatar()
    L, R = avatar_mesh.LANDMARKS["brow_l"], avatar_mesh.LANDMARKS["brow_r"]
    widest = 0.0
    for _ in range(1200):                                # 20 s of speech at 60 Hz
        a.step(1 / 60, 0.6, speaking=True, state="SPEAKING")
        a._pose()
        lift = a._v[:, 1] - a._v0[:, 1]
        widest = max(widest, abs(lift[L].mean() - lift[R].mean()))
    assert widest > 0.005
    for _ in range(600):
        a.step(1 / 60, 0.0, speaking=False, state="LISTENING")
    assert abs(a._skew) < 0.01
