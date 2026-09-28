import webbrowser
from urllib.parse import quote_plus

import requests

# WMO weather interpretation codes (Open-Meteo), grouped the way people say them.
_WMO = {0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
        45: "fog", 48: "freezing fog", 51: "light drizzle", 53: "drizzle",
        55: "heavy drizzle", 56: "freezing drizzle", 57: "freezing drizzle",
        61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain",
        67: "freezing rain", 71: "light snow", 73: "snow", 75: "heavy snow",
        77: "snow grains", 80: "rain showers", 81: "rain showers",
        82: "violent rain showers", 85: "snow showers", 86: "heavy snow showers",
        95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with hail"}


def _forecast(city: str, when: str) -> str | None:
    """A spoken-length forecast from Open-Meteo (free, no API key), or None.

    The tool used to only open a Google search in the browser and return
    "Showing the weather", so the model had no weather to say — it guessed."""
    geo = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                       params={"name": city, "count": 1}, timeout=8).json()
    place = (geo.get("results") or [None])[0]
    if not place:
        return None
    fc = requests.get("https://api.open-meteo.com/v1/forecast", params={
        "latitude": place["latitude"], "longitude": place["longitude"],
        "current": "temperature_2m,weather_code,wind_speed_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                 "precipitation_probability_max",
        "timezone": "auto", "forecast_days": 3,
    }, timeout=8).json()
    d = fc["daily"]
    name = f"{place['name']}, {place.get('country', '')}".strip(", ")

    def day(i: int, label: str) -> str:
        return (f"{label}: {_WMO.get(d['weather_code'][i], 'mixed')}, "
                f"{d['temperature_2m_min'][i]:.0f}–{d['temperature_2m_max'][i]:.0f}°C, "
                f"{d['precipitation_probability_max'][i] or 0}% chance of rain")

    if when.lower() in ("today", "now", ""):
        cur = fc["current"]
        return (f"{name} now: {cur['temperature_2m']:.0f}°C, "
                f"{_WMO.get(cur['weather_code'], 'mixed')}, wind {cur['wind_speed_10m']:.0f} km/h. "
                + day(0, "Today"))
    if when.lower() == "tomorrow":
        return f"{name}. " + day(1, "Tomorrow")
    return f"{name}. " + "; ".join(day(i, lbl) for i, lbl in
                                   enumerate(("Today", "Tomorrow", "Day after")))


def weather_action(
    parameters: dict,
    player=None,
    session_memory=None,
) -> str:
    city     = parameters.get("city")
    when     = parameters.get("time", "today")  

    if not city or not isinstance(city, str) or not city.strip():
        msg = "Sir, the city is missing for the weather report."
        _log(msg, player)
        return msg

    city = city.strip()
    when = (when or "today").strip()

    search_query  = f"weather in {city} {when}"
    url           = f"https://www.google.com/search?q={quote_plus(search_query)}"

    try:
        report = _forecast(city, when)
    except Exception as e:
        print(f"[Weather] Forecast lookup failed ({e}) — opening the browser instead")
        report = None
    if report:
        _log(report, player)
        return report

    try:
        opened = webbrowser.open(url)
        if not opened:
            raise RuntimeError("webbrowser.open returned False")
    except Exception as e:
        msg = f"Sir, I couldn't open the browser for the weather report: {e}"
        _log(msg, player)
        return msg

    msg = f"Showing the weather for {city}, {when}, sir."
    _log(msg, player)

    if session_memory:
        try:
            session_memory.set_last_search(query=search_query, response=msg)
        except Exception:
            pass

    return msg


def _log(message: str, player=None) -> None:
    print(f"[Weather] {message}")
    if player:
        try:
            player.write_log(f"JARVIS: {message}")
        except Exception:
            pass


# ── Tool declaration (auto-discovered by core/action_loader.py) ──────────────
TOOL = {
    "name": "weather_report",
    "description": "Gives the weather report to user",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "city": {
                "type": "STRING",
                "description": "City name"
            },
            "time": {
                "type": "STRING",
                "description": "today (default), tomorrow, or the next few days"
            }
        },
        "required": [
            "city"
        ]
    },
    "handler": weather_action,
}
