"""Regression tests for JarvisLive session state (main.py), driven without audio or network."""
import asyncio
from types import SimpleNamespace

import main


def _live(**state):
    """A JarvisLive with just the state these code paths touch."""
    live = object.__new__(main.JarvisLive)
    ui = SimpleNamespace(muted=False, set_state=lambda *_: None,
                         write_log=lambda *_: None)
    live.__dict__.update(ui=ui, audio_in_queue=None, _turn_done_event=None,
                         _visemes=SimpleNamespace(reset=lambda: None),
                         _play_cursor=0.0, _interrupted=False, _generating=False,
                         _action_registry=SimpleNamespace(scheduling=lambda _n: None),
                         _plugin_registry=SimpleNamespace(scheduling=lambda _n: None))
    live.set_speaking = lambda _v: None
    live.speak_error = lambda *_: None
    live.__dict__.update(state)
    return live


def test_interrupt_while_idle_does_not_swallow_the_next_reply():
    live = _live()
    live.interrupt()                     # stray Esc with nothing being generated
    assert live._interrupted is False


def test_interrupt_during_generation_still_discards_that_reply():
    live = _live(_generating=True)
    live.interrupt()
    assert live._interrupted is True


def test_failed_capture_does_not_leave_vision_busy(monkeypatch):
    def no_screen():
        raise OSError("screen grab failed")
    monkeypatch.setattr(main, "_capture_screen", no_screen)
    live = _live(_vision_busy=False, _vision_last_time=-1e9, _vision_cam_active=False)

    fc = SimpleNamespace(name="screen_process", id="1", args={"angle": "screen"})
    asyncio.run(live._execute_tool(fc))

    assert live._vision_busy is False


def test_taskgroup_failure_text_names_the_real_error():
    group = BaseExceptionGroup("unhandled errors in a TaskGroup (1 sub-exception)",
                               [ConnectionError("API key not valid. Please pass a valid API key.")])
    text = main._leaf_errors_text(group)
    assert "API key not valid" in text
    assert "unhandled" not in text               # the wrapper read as a rejected "handle"


def test_prompt_clock_does_not_depend_on_am_pm():
    import inspect
    src = inspect.getsource(main.JarvisLive._build_config)
    assert "%p" not in src and "%H:%M" in src


def test_missing_microphone_keeps_the_session(monkeypatch):
    logs = []
    live = _live()
    live.ui.write_log = logs.append

    def no_mic(*a, **k):
        raise main.sd.PortAudioError("no input device")
    monkeypatch.setattr(main.sd, "InputStream", no_mic)
    monkeypatch.setattr(main, "get_input_device", lambda: "")

    async def run():
        task = asyncio.ensure_future(live._listen_audio())
        await asyncio.sleep(0.3)
        assert not task.done(), task.exception() if task.done() else None
        task.cancel()
    asyncio.run(run())
    assert any("microphone" in m.lower() for m in logs)
