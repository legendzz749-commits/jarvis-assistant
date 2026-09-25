"""Regression tests for weather, web search budgets, CPU alerts and YouTube narration."""
import time
from types import SimpleNamespace

import pytest

from actions import system_monitor, weather_report, web_search
from core import gemini


def test_weather_returns_an_actual_forecast(monkeypatch):
    def fake_get(url, params=None, timeout=None):
        if "geocoding" in url:
            return SimpleNamespace(json=lambda: {"results": [
                {"name": "Izmir", "country": "Türkiye", "latitude": 38.4, "longitude": 27.1}]})
        return SimpleNamespace(json=lambda: {
            "current": {"temperature_2m": 24.2, "weather_code": 1, "wind_speed_10m": 12},
            "daily": {"weather_code": [1, 61, 3], "temperature_2m_min": [18, 17, 16],
                      "temperature_2m_max": [27, 22, 21],
                      "precipitation_probability_max": [5, 80, 20]}})
    monkeypatch.setattr(weather_report.requests, "get", fake_get)
    monkeypatch.setattr(weather_report.webbrowser, "open", lambda *_: pytest.fail("no browser"))

    today = weather_report.weather_action({"city": "Izmir"})
    tomorrow = weather_report.weather_action({"city": "Izmir", "time": "tomorrow"})

    assert "24°C" in today and "mainly clear" in today
    assert "light rain" in tomorrow and "80%" in tomorrow
    assert "time" in weather_report.TOOL["parameters"]["properties"]


def test_grounded_search_has_one_overall_budget(monkeypatch):
    monkeypatch.setattr(web_search, "_GROUNDED_BUDGET_S", 0.5)
    monkeypatch.setattr(web_search, "_gemini_available", lambda: True)
    monkeypatch.setattr(gemini, "call", lambda *a, **k: time.sleep(5))
    start = time.monotonic()
    with pytest.raises(RuntimeError):
        web_search._gemini_search("weather")
    assert time.monotonic() - start < 2


def test_quota_breaker_trips_when_every_grounded_model_is_cooling(monkeypatch):
    monkeypatch.setattr(web_search, "_gemini_available", lambda: True)
    monkeypatch.setattr(gemini, "call", lambda *a, **k: None)
    monkeypatch.setattr(gemini, "_cooling", lambda m: True)
    monkeypatch.setattr(web_search, "_quota_blocked_until", 0.0)
    with pytest.raises(RuntimeError):
        web_search._gemini_search("news")
    assert web_search._quota_blocked_until > time.monotonic()


def test_cpu_is_measured_between_checks_on_any_thread(monkeypatch):
    times = iter([SimpleNamespace(user=10, system=0, idle=90, _t=(10, 0, 90)),
                  SimpleNamespace(user=100, system=0, idle=100, _t=(100, 0, 100))])

    class T(tuple):
        pass

    def fake_times():
        t = next(times)
        obj = T(t._t)
        obj.idle = t.idle
        return obj
    monkeypatch.setattr(system_monitor.psutil, "cpu_times", fake_times)
    mon = system_monitor.SystemMonitor()
    assert mon._cpu_since_last() == 0.0
    assert mon._cpu_since_last() == pytest.approx(90.0)


def test_youtube_summary_is_not_injected_as_a_user_turn(monkeypatch):
    from actions import youtube_video as yt
    spoken = []
    monkeypatch.setattr(yt, "_TRANSCRIPT_OK", True)
    monkeypatch.setattr(yt, "_get_transcript", lambda vid: "words")
    monkeypatch.setattr(yt, "_summarize_with_gemini", lambda t, u: "the summary")
    out = yt._handle_summarize({"url": "https://youtu.be/dQw4w9WgXcQ"}, None, spoken.append)
    assert "the summary" in out and spoken == []
