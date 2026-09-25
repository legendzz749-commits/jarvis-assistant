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
