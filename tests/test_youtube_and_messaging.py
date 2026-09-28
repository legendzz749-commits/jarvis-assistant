"""Regression tests for YouTube summaries and messaging platform routing."""
from types import SimpleNamespace

import pytest

from actions import send_message, youtube_video as yt


class TranscriptApi12:
    """youtube-transcript-api 1.2+: instance API, snippet objects instead of dicts."""
    def list(self, video_id):
        transcript = SimpleNamespace(fetch=lambda: [SimpleNamespace(text="hello"),
                                                    SimpleNamespace(text="world")])
        return SimpleNamespace(find_manually_created_transcript=lambda langs: transcript)


def test_transcript_works_with_the_current_library(monkeypatch):
    monkeypatch.setattr(yt, "_TRANSCRIPT_OK", True)
    monkeypatch.setattr(yt, "YouTubeTranscriptApi", TranscriptApi12)
    assert yt._get_transcript("dQw4w9WgXcQ") == "hello world"


def test_summarize_uses_the_url_it_was_given(monkeypatch):
    monkeypatch.setattr(yt, "_TRANSCRIPT_OK", True)
    monkeypatch.setattr(yt, "_ask_for_url", lambda *_: pytest.fail("should not prompt"))
    monkeypatch.setattr(yt, "_get_transcript", lambda vid: "some words")
    monkeypatch.setattr(yt, "_summarize_with_gemini", lambda t, u: f"summary of {u}")

    out = yt._handle_summarize({"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}, None, None)

    assert "summary of" in out


@pytest.mark.parametrize("name,handler", [
    ("Signal", "_send_signal"), ("signal app", "_send_signal"),
    ("Instagram", "_send_instagram"), ("ig", "_send_instagram"),
    ("WhatsApp", "_send_whatsapp"), ("telegram", "_send_telegram"),
])
def test_each_platform_resolves_to_its_own_handler(name, handler):
    assert send_message._resolve_platform(name) is getattr(send_message, handler)


def test_message_is_not_typed_into_the_wrong_window(monkeypatch):
    keys = []
    monkeypatch.setattr(send_message, "_open_app", lambda _name: True)
    monkeypatch.setattr(send_message, "_focused_window_title", lambda: "notes.txt - Visual Studio Code")
    monkeypatch.setattr(send_message.pyautogui, "press", lambda *a: keys.append(a))
    monkeypatch.setattr(send_message.pyautogui, "hotkey", lambda *a: keys.append(a))
    monkeypatch.setattr(send_message.time, "sleep", lambda _s: None)

    out = send_message._desktop_send("WhatsApp", "Mum", "on my way")

    assert keys == []
    assert "did not type" in out


def test_linux_open_fails_when_no_desktop_entry_or_binary(monkeypatch):
    monkeypatch.setattr(send_message, "_get_os", lambda: "linux")
    monkeypatch.setattr(send_message.subprocess, "run",
                        lambda argv, **k: SimpleNamespace(returncode=1))
    # gtk-launch starts fine and then exits 1: no WhatsApp .desktop entry
    monkeypatch.setattr(send_message.subprocess, "Popen",
                        lambda argv, **k: SimpleNamespace(poll=lambda: 1))
    monkeypatch.setattr(send_message.time, "sleep", lambda _s: None)
    assert send_message._open_app("WhatsApp") is False


def test_paste_restores_the_users_clipboard(monkeypatch):
    board = {"v": "user's copied text"}
    monkeypatch.setattr(send_message.pyperclip, "paste", lambda: board["v"])
    monkeypatch.setattr(send_message.pyperclip, "copy", lambda t: board.__setitem__("v", t))
    monkeypatch.setattr(send_message.pyautogui, "hotkey", lambda *a: None)
    monkeypatch.setattr(send_message.time, "sleep", lambda _s: None)

    send_message._paste_text("hello")

    assert board["v"] == "user's copied text"


def test_video_titles_with_quotes_and_ampersands_decode(monkeypatch):
    html = ('"title":{"runs":[{"text":"Tom \\"The Rock\\" \\u0026 Friends"}]},'
            '"ownerChannelName":"Rock \\u0026 Roll TV","viewCount":"1234","lengthSeconds":"125"')
    monkeypatch.setattr(yt, "_REQUESTS_OK", True)
    monkeypatch.setattr(yt.requests, "get", lambda *a, **k: SimpleNamespace(text=html))
    info = yt._scrape_video_info("abc")
    assert info["title"] == 'Tom "The Rock" & Friends'
    assert info["channel"] == "Rock & Roll TV"


def test_trending_defaults_to_the_users_region(monkeypatch):
    import locale
    monkeypatch.setattr(locale, "getlocale", lambda *a: ("de_DE", "UTF-8"))
    assert yt._default_region() == "DE"
