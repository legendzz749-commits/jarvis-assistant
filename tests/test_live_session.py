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


def test_quiz_results_survive_sleep_and_reconnect():
    live = _live(_wake_enabled=True, _awake=False, _loop=object(), session=None,
                 _pending_texts=[], _last_user_speech=0.0)
    live.ui.muted = True
    live._on_text_command("[QUIZ_DONE] topic=history | auto-marked 4/5 correct")
    assert live._awake is True
    assert live._pending_texts == ["[QUIZ_DONE] topic=history | auto-marked 4/5 correct"]


def test_a_slow_tool_does_not_stop_the_receive_loop():
    sent = []

    class FakeSession:
        async def send_tool_response(self, function_responses):
            sent.append(function_responses)

    session = FakeSession()
    live = _live(session=session, _tool_tasks=set(), _pending_vision=None)
    live._flush_pending_vision = lambda: asyncio.sleep(0)

    async def slow_tool(fc):
        await asyncio.sleep(0.3)
        return fc.name

    live._execute_tool = slow_tool
    tool_call = SimpleNamespace(function_calls=[SimpleNamespace(name="dev_agent")])

    async def run():
        start = asyncio.get_running_loop().time()
        task = asyncio.create_task(live._answer_tool_call(tool_call, session))
        await asyncio.sleep(0)                      # the loop is free right away
        assert asyncio.get_running_loop().time() - start < 0.1 and not sent
        await task
    asyncio.run(run())
    assert sent == [["dev_agent"]]


def test_phone_mic_is_not_streamed_while_asleep():
    import threading

    async def run():
        q = asyncio.Queue()
        out = asyncio.Queue()
        live = _live(_wake_enabled=True, _awake=False, _speaking_lock=threading.Lock(),
                     _is_speaking=False, out_queue=out, _phone_active=False,
                     _dashboard=SimpleNamespace(_phone_audio_queue=q))
        live.ui.muted = False
        await q.put({"data": b"\x00" * 320, "mime_type": "audio/pcm"})
        task = asyncio.create_task(live._relay_phone_audio())
        await asyncio.sleep(0.1)
        task.cancel()
        return out.qsize()
    assert asyncio.run(run()) == 0


def test_prompt_editor_notes_are_not_sent_to_the_model():
    prompt = main._load_system_prompt()
    assert "Edit the wording" not in prompt and "[SELF]" in prompt


def test_idle_state_matches_the_real_mic_gate():
    live = _live(_wake_enabled=False, _awake=True, _ptt_enabled=True, _ptt_held=False)
    assert live._idle_state() == "SLEEPING"
    live._ptt_enabled = False
    assert live._idle_state() == "LISTENING"
    live._wake_enabled, live._awake = True, False
    assert live._idle_state() == "SLEEPING"


def test_full_uplink_drops_the_oldest_block_instead_of_raising():
    async def run():
        live = _live(out_queue=asyncio.Queue(maxsize=2))
        for i in range(5):
            live._enqueue_mic({"n": i})
        return [live.out_queue.get_nowait()["n"] for _ in range(2)]
    assert asyncio.run(run()) == [3, 4]


def test_network_errors_are_recognised_on_every_os():
    import socket
    group = BaseExceptionGroup("tg", [ConnectionResetError(104, "Connection reset by peer")])
    assert main._is_network_error(group)
    assert main._is_network_error(socket.gaierror(-2, "Name or service not known"))
    assert not main._is_network_error(ValueError("bad config"))


def _run_turns(turns):
    """Feed transcript turns through _receive_audio; return (log, mouthed)."""
    import pytest
    log, mouthed = [], []

    class Done(Exception):
        pass

    def responses():
        for chunks, user in turns:
            for u in user:
                yield SimpleNamespace(data=None, tool_call=None, server_content=SimpleNamespace(
                    output_transcription=None, input_transcription=SimpleNamespace(text=u),
                    turn_complete=False))
            for c in chunks:
                yield SimpleNamespace(data=None, tool_call=None, server_content=SimpleNamespace(
                    output_transcription=SimpleNamespace(text=c), input_transcription=None,
                    turn_complete=False))
            yield SimpleNamespace(data=None, tool_call=None, server_content=SimpleNamespace(
                output_transcription=None, input_transcription=None, turn_complete=True))

    class FakeSession:
        async def receive(self):
            for r in responses():
                yield r
            raise Done

    live = _live(session=FakeSession(), _last_out_logged="", _session_log=[], _dashboard=None,
                 _asst_name="JARVIS", _vision_close_pending=False, _last_user_speech=0.0,
                 _resume_handle=None)
    live.ui.write_log = log.append
    live._visemes = SimpleNamespace(reset=lambda: None, feed_text=mouthed.append)
    with pytest.raises(Done):
        asyncio.run(live._receive_audio())
    return log, mouthed


def test_a_resent_tail_is_neither_logged_nor_mouthed_twice():
    log, mouthed = _run_turns([
        (["Let me check the forecast", "for Izmir."], ["weather in izmir"]),
        (["check the forecast", "for Izmir.", "It is sunny."], []),   # tail re-sent after the tool
    ])
    assert log == ["You: weather in izmir", "JARVIS: Let me check the forecast for Izmir.",
                   "JARVIS: It is sunny."]
    assert mouthed == ["Let me check the forecast", "for Izmir.", "It is sunny."]


def test_repeated_phrases_inside_an_answer_are_kept():
    log, mouthed = _run_turns([
        (["Step one: open the settings panel.", "Then", "Then", "open the settings panel."], ["how"]),
    ])
    assert mouthed == ["Step one: open the settings panel.", "Then", "Then", "open the settings panel."]
    assert log[-1] == "JARVIS: Step one: open the settings panel. Then Then open the settings panel."


def test_the_same_answer_to_a_new_question_is_spoken():
    log, mouthed = _run_turns([
        (["It is sunny in Izmir today."], ["weather?"]),
        (["It is sunny in Izmir today."], ["and now?"]),
    ])
    assert mouthed == ["It is sunny in Izmir today."] * 2
    assert log.count("JARVIS: It is sunny in Izmir today.") == 2


def test_shutdown_lets_the_goodbye_finish_and_asks_for_it_once(monkeypatch):
    import os
    sent, exited = [], []

    class FakeSession:
        async def send_client_content(self, **k):
            sent.append(k)

    live = _live(session=FakeSession(), _is_speaking=False, _session_log=[])
    monkeypatch.setattr(os, "_exit", lambda code: exited.append(asyncio.get_running_loop().time()))

    async def run():
        clock = asyncio.get_running_loop().time
        reply = await live._execute_tool(SimpleNamespace(name="shutdown_jarvis", args={}, id="1"))
        await asyncio.sleep(0.1)
        live._generating = True                      # the goodbye streams in...
        await asyncio.sleep(1.9)
        live._generating = False                     # ...and has finished playing
        done = clock()
        while not exited and clock() - done < 3:
            await asyncio.sleep(0.05)
        return reply, done
    reply, done = asyncio.run(run())
    assert "goodbye" in reply.response["result"].lower() and sent == []
    assert exited and exited[0] >= done


def test_a_fresh_start_request_survives_a_later_keep_request():
    import pytest
    live = _live(_reconnect_event=None, _reconnect_keep=True)
    live.request_reconnect(keep_context=False, reason="voice")
    live.request_reconnect(keep_context=True, reason="audio device")

    async def fire():
        live._reconnect_event = asyncio.Event()
        live._reconnect_event.set()
        await live._watch_reconnect()
    with pytest.raises(main._ReconnectSignal) as sig:
        asyncio.run(fire())
    assert sig.value.keep_context is False
    assert live._reconnect_keep is True               # consumed: the next request starts clean
