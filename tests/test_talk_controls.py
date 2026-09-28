"""Regression tests for push-to-talk after a restart and wake-word re-triggering."""
import json
import threading
import time

import numpy as np
import pytest

from core import wake_word


class StatefulModel:
    """Mimics openwakeword: the score stays high until reset() clears its buffers."""
    def __init__(self):
        self.primed = False

    def predict(self, frame):
        if frame.any():
            self.primed = True
        return {"hey_jarvis": 0.9 if self.primed else 0.0}

    def reset(self):
        self.primed = False


def test_wake_word_does_not_refire_on_silence_after_a_detection():
    fired = []
    det = wake_word.WakeWordDetector(on_detect=lambda: fired.append(1))
    det._model = StatefulModel()
    det._running = True
    thread = threading.Thread(target=det._loop, daemon=True)
    thread.start()

    det._queue.put(np.ones(1280, dtype=np.int16))       # "hey jarvis"
    time.sleep(0.2)
    det._queue.put(np.zeros(1280, dtype=np.int16))      # silence after going back to sleep
    time.sleep(0.2)
    det.stop()
    thread.join(1)

    assert fired == [1]


@pytest.mark.skipif(__import__("platform").system() == "Windows",
                    reason="Windows uses the global hook instead of a window shortcut")
def test_saved_push_to_talk_binds_the_chord_at_startup(qapp, config_file, pump):
    import ui
    config_file.write_text(json.dumps({"gemini_api_key": "k" * 20,
                                       "push_to_talk_enabled": True}))
    j = ui.JarvisUI("face.png")
    pump(50)
    try:
        assert getattr(j._win, "_ptt_sc", None) is not None
    finally:
        j._win.close()
