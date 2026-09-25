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
