"""Vremenski podatki iz Open-Meteo s skupnim predpomnilnikom za vse obiskovalce."""
import asyncio
from datetime import date

from .cache import cached
from .settings import http

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"

CURRENT_TTL = 600    # 10 min
HOURS_AHEAD = 12     # obzorje za opozorila in kapitanovo napoved
STORM_CODES = (95, 96, 99)
FORECAST_TTL = 1800  # 30 min

WMO_ICONS = {0: "☀️", 1: "🌤️", 2: "⛅", 3: "☁️", 45: "🌫️", 48: "🌫️", 51: "🌦️", 53: "🌦️", 55: "🌦️", 56: "🌦️", 57: "🌦️", 61: "🌧️", 63: "🌧️", 65: "🌧️", 66: "🌧️", 67: "🌧️", 71: "❄️", 73: "❄️", 75: "❄️", 77: "❄️", 80: "🌦️", 81: "🌦️", 82: "🌦️", 85: "❄️", 86: "❄️", 95: "⛈️", 96: "⛈️", 99: "⛈️"}
# Kratek opis vremena za kapitanov poziv (model ga sam prevede v jezik odgovora).
WMO_TEXT = {0: "clear", 1: "mostly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "fog", 51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 56: "freezing drizzle", 57: "freezing drizzle", 61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain", 67: "freezing rain", 71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains", 80: "light showers", 81: "showers", 82: "violent showers", 85: "snow showers", 86: "snow showers", 95: "thunderstorm", 96: "thunderstorm with hail", 99: "thunderstorm with hail"}
COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]

async def _get(url: str, params: dict) -> dict:
    resp = await http.get(url, params=params)
    resp.raise_for_status()
    return resp.json()


def knots(kmh, digits=1):
    if kmh is None:
        return None
    kt = round(kmh / 1.852, digits)
    return int(kt) if digits == 0 else kt


def compass(deg) -> str:
    if deg is None:
        return ""
    return COMPASS[int((deg + 11.25) / 22.5) % 16]


def icon(code, is_day=True) -> str:
    if not is_day and code in (0, 1):
        return "🌙"
    return WMO_ICONS.get(code, "❓")


def _during(values: list, i: int):
    """Open-Meteo urne vsote in maksimume (padavine, verjetnost padavin, sunki) pripiše KONCU ure:
    vrednost ob 14:00 velja za 13–14. Vrstica za uro H pa naj pove, kaj se zgodi med H in H+1,
    zato vzamemo vrednost naslednje ure."""
    return values[min(i + 1, len(values) - 1)]


def _outlook(gusts_now, waves_now, hours: list[dict]) -> dict:
    """Vrhovi v naslednjih urah. Čas je "now" (že zdaj), "HH:MM" ali None (dogodka ni)."""
    def when(i):
        return "now" if i == 0 else hours[i]["time"]

    def peak(key, now_value):
        best, at = now_value, "now"
        for i, hour in enumerate(hours):
            if hour[key] is not None and (best is None or hour[key] > best):
                best, at = hour[key], when(i)
        return best, at

    gust, gust_at = peak("gusts_kt", gusts_now)
    wave, wave_at = peak("waves", waves_now)
    rainy = [i for i, hour in enumerate(hours) if hour["precip"] >= 0.1]
    stormy = [i for i, hour in enumerate(hours) if hour["code"] in STORM_CODES]
    return {
        "gust": gust, "gust_at": gust_at, "wave": wave, "wave_at": wave_at,
        "rain_total": round(sum(hour["precip"] for hour in hours), 1),
        "rain_peak": max((hour["precip"] for hour in hours), default=0),
        "rain_from": when(rainy[0]) if rainy else None,
        "storm_from": when(stormy[0]) if stormy else None,
    }


async def current(lat: float, lon: float) -> dict:
    """Trenutno vreme + morje + naslednjih 12 ur. Morski podatki so None, če lokacija ni ob morju."""
    async def fetch():
        coords = {"latitude": lat, "longitude": lon, "timezone": "auto", "forecast_hours": HOURS_AHEAD + 1}
        forecast, marine = await asyncio.gather(
            _get(FORECAST_URL, {
                **coords,
                "current": "temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,wind_speed_10m,wind_gusts_10m,wind_direction_10m,uv_index,is_day",
                "hourly": "temperature_2m,precipitation,precipitation_probability,wind_speed_10m,wind_gusts_10m,wind_direction_10m,weather_code",
            }),
            _get(MARINE_URL, {**coords, "current": "sea_surface_temperature,wave_height", "hourly": "wave_height"}),
            return_exceptions=True,
        )
        if isinstance(forecast, BaseException):
            raise forecast
        c = forecast["current"]
        if isinstance(marine, BaseException):
            marine = {}
        m = marine.get("current") or {}
        waves = m.get("wave_height")
        mh = marine.get("hourly") or {}
        wave_at = dict(zip(mh.get("time", []), mh.get("wave_height", [])))
        h = forecast["hourly"]
        hours = [{
            "time": stamp[11:16],
            "temp": h["temperature_2m"][i],
            "precip": _during(h["precipitation"], i) or 0,
            "prob": _during(h["precipitation_probability"], i),
            "wind_kt": knots(h["wind_speed_10m"][i], 0),
            "gusts_kt": knots(_during(h["wind_gusts_10m"], i), 0),
            "dir": compass(h["wind_direction_10m"][i]),
            "code": h["weather_code"][i],
            "sky": WMO_TEXT.get(h["weather_code"][i], "?"),
            "waves": wave_at.get(stamp),
        } for i, stamp in enumerate(h["time"][:HOURS_AHEAD])]  # zadnja ura služi samo za _during
        gusts_now = knots(c.get("wind_gusts_10m"))
        return {
            "hours": hours,
            "outlook": _outlook(gusts_now, waves, hours),
            "time": c["time"],
            "is_day": bool(c.get("is_day", 1)),
            "temp": c.get("temperature_2m"),
            "feels": c.get("apparent_temperature"),
            "humidity": c.get("relative_humidity_2m"),
            "precip": c.get("precipitation") or 0,            # zadnjih 15 minut
            "precip_hour": round(hours[0]["precip"], 1),      # napoved za tekočo uro
            "uv": round(c["uv_index"], 1) if c.get("uv_index") is not None else None,
            "wind_kt": knots(c.get("wind_speed_10m")),
            "gusts_kt": gusts_now,
            "wind_deg": c.get("wind_direction_10m"),
            "wind_dir": compass(c.get("wind_direction_10m")),
            "sea_temp": m.get("sea_surface_temperature"),
            "waves": round(waves, 1) if waves is not None else None,
        }
    return await cached(("current", round(lat, 3), round(lon, 3)), CURRENT_TTL, fetch)


async def forecast(lat: float, lon: float) -> dict:
    """10-dnevna napoved: dnevi z urnimi vrsticami + točke za graf (na 4 ure)."""
    async def fetch():
        raw = await _get(FORECAST_URL, {
            "latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 10,
            # Open-Meteo ob zahtevi s "current" v urne vrednosti vključi kratkoročni 15-minutni model.
            # Zahtevamo ga tudi tu, da 10-dnevna stran za iste ure kaže enake številke kot stran Trenutno.
            "current": "temperature_2m",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,wind_gusts_10m_max,weather_code,uv_index_max",
            "hourly": "temperature_2m,precipitation,precipitation_probability,wind_speed_10m,wind_gusts_10m,wind_direction_10m,weather_code,is_day",
        })
        d, h = raw["daily"], raw["hourly"]
        days, by_date = [], {}
        for i, iso in enumerate(d["time"]):
            dt = date.fromisoformat(iso)
            day = {
                "date": iso, "weekday": dt.weekday(), "label": f"{dt.day}.{dt.month}.",
                "icon": icon(d["weather_code"][i]),
                "tmax": d["temperature_2m_max"][i], "tmin": d["temperature_2m_min"][i],
                "precip": d["precipitation_sum"][i] or 0,
                "gusts_kt": knots(d["wind_gusts_10m_max"][i], 0),
                "uv": d["uv_index_max"][i],
                "hours": [],
            }
            days.append(day)
            by_date[iso] = (i, day)

        points = []
        for i, stamp in enumerate(h["time"]):
            if stamp[:10] not in by_date or h["temperature_2m"][i] is None:
                continue
            day_idx, day = by_date[stamp[:10]]
            hour = int(stamp[11:13])
            ico = icon(h["weather_code"][i], bool(h["is_day"][i]))
            gust = knots(_during(h["wind_gusts_10m"], i), 0)
            day["hours"].append({
                "hour": hour, "icon": ico, "night": not h["is_day"][i],
                "temp": h["temperature_2m"][i],
                "precip": round(_during(h["precipitation"], i) or 0, 1),
                "prob": _during(h["precipitation_probability"], i),
                "wind_kt": knots(h["wind_speed_10m"][i], 0), "gusts_kt": gust,
                "deg": h["wind_direction_10m"][i], "dir": compass(h["wind_direction_10m"][i]),
            })
            if hour % 4 == 0:
                rain = sum(max(0, p or 0) for p in h["precipitation"][i + 1:i + 5])  # štiri ure od te ure naprej
                points.append({
                    "d": day_idx, "h": hour, "temp": h["temperature_2m"][i], "gust": gust or 0,
                    "deg": h["wind_direction_10m"][i], "rain": round(rain, 1), "icon": ico,
                })
        return {"days": days, "points": points}
    return await cached(("forecast", round(lat, 3), round(lon, 3)), FORECAST_TTL, fetch)
