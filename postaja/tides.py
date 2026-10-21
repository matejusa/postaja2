"""Gladina morja za graf plimovanja: napoved iz Open-Meteo, razstavljena na plimovanje in vremensko odstopanje.

Vir daje samo skupno gladino (plimovanje + zračni tlak + modelska višina morja). Plimovanje ločimo z
drsečim 25-urnim povprečjem: povprečje je počasni (vremenski) del, ostanek je astronomsko plimovanje.
Odstopanje je izraženo glede na povprečno gladino zadnjih treh mesecev na isti točki modela.
"""
import asyncio
import math
from datetime import datetime, timedelta, timezone

from . import weather
from .cache import cached
from .settings import http

MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
SERIES_TTL = 1800
BASELINE_TTL = 24 * 3600
BASELINE_DAYS = 92
HALF_WINDOW = 12   # ur na vsako stran: 25-urno okno izravna poldnevno in dnevno plimovanje
DAYS = 10

# Tržaški zaliv: jugo gladino dviga, burja jo znižuje, zato tu dodamo pas teh dveh vetrov.
GULF_OF_TRIESTE = {"lat": (45.42, 45.83), "lon": (13.35, 13.92)}
BURJA_FROM = (25, 95)    # smer, iz katere piha (stopinje): SSV do V
JUGO_FROM = (105, 190)   # VJV do J
MIN_WIND_KT = 7          # šibkejših sapic ne štejemo za jugo ali burjo

J2000 = datetime(2000, 1, 1, 12, tzinfo=timezone.utc)


def in_gulf_of_trieste(lat: float, lon: float) -> bool:
    box = GULF_OF_TRIESTE
    return box["lat"][0] <= lat <= box["lat"][1] and box["lon"][0] <= lon <= box["lon"][1]


def moon_elongation(when: datetime) -> float:
    """Kot Luna–Sonce v stopinjah (0 = mlaj, 90 = prvi krajec, 180 = ščip, 270 = zadnji krajec).
    Poenostavljeni formuli iz Astronomical Almanac, natančnost okoli 0,3° (dobra ura)."""
    d = (when - J2000).total_seconds() / 86400
    t = d / 36525
    sin = lambda deg: math.sin(math.radians(deg))
    g = 357.528 + 0.9856003 * d
    sun = 280.460 + 0.9856474 * d + 1.915 * sin(g) + 0.020 * sin(2 * g)
    moon = (218.32 + 481267.881 * t
            + 6.29 * sin(135.0 + 477198.87 * t) - 1.27 * sin(259.3 - 413335.36 * t)
            + 0.66 * sin(235.7 + 890534.22 * t) + 0.21 * sin(269.9 + 954397.74 * t)
            - 0.19 * sin(357.5 + 35999.05 * t) - 0.11 * sin(186.5 + 966404.03 * t))
    return (moon - sun) % 360


def moon_phases(start_utc: datetime, hours: int) -> list[dict]:
    """Lunine mene v obdobju: ura od začetka (h) in mena (p: 0 mlaj, 1 prvi krajec, 2 ščip, 3 zadnji krajec)."""
    found = []
    previous = moon_elongation(start_utc)
    for h in range(1, hours + 1):
        current = moon_elongation(start_utc + timedelta(hours=h))
        if current // 90 != previous // 90:
            found.append({"h": h, "p": int(current // 90)})
        previous = current
    return found


async def _get(params: dict) -> dict:
    resp = await http.get(MARINE_URL, params={"timezone": "auto", **params})
    resp.raise_for_status()
    return resp.json()


async def _baseline(lat: float, lon: float) -> float | None:
    """Povprečna gladina zadnjih treh mesecev (plimovanje se v tem času izpovpreči)."""
    async def fetch():
        raw = await _get({"latitude": lat, "longitude": lon, "hourly": "sea_level_height_msl",
                          "past_days": BASELINE_DAYS, "forecast_days": 1})
        values = [v for v in raw["hourly"]["sea_level_height_msl"] if v is not None]
        return sum(values) / len(values) if len(values) > 14 * 24 else None
    return await cached(("tide-baseline", round(lat, 3), round(lon, 3)), BASELINE_TTL, fetch)


async def available(lat: float, lon: float) -> bool:
    """Ali ima lokacija podatke o gladini. Ob napaki vira velja "ne", dokler vnos v predpomnilniku ne poteče."""
    async def fetch():
        try:
            async with asyncio.timeout(4):
                return await _baseline(lat, lon) is not None
        except Exception:
            return False
    return await cached(("tide-available", round(lat, 3), round(lon, 3)), 600, fetch)


def _wind_class(deg) -> str | None:
    if deg is None:
        return None
    if BURJA_FROM[0] <= deg < BURJA_FROM[1]:
        return "burja"
    if JUGO_FROM[0] <= deg < JUGO_FROM[1]:
        return "jugo"
    return None


async def chart(lat: float, lon: float) -> dict | None:
    """Podatki za graf gladine od danes 00:00 po krajevnem času; None, če lokacija nima morskih podatkov."""
    async def fetch():
        base = await _baseline(lat, lon)
        if base is None:
            return None
        raw = await _get({"latitude": lat, "longitude": lon, "hourly": "sea_level_height_msl",
                          "current": "sea_level_height_msl", "past_days": 1, "forecast_days": DAYS + 1})
        times, values = raw["hourly"]["time"], raw["hourly"]["sea_level_height_msl"]
        now = raw["current"]["time"]
        start = times.index(now[:10] + "T00:00")

        level, astro = [], []
        for i in range(start, min(start + DAYS * 24, len(times))):
            window = values[i - HALF_WINDOW:i + HALF_WINDOW + 1]
            if i < HALF_WINDOW or len(window) < 2 * HALF_WINDOW + 1 or None in window:
                break  # konec napovedi: brez polnega okna plimovanja ni mogoče ločiti
            slow = sum(window) / len(window)
            level.append(round((values[i] - base) * 100))
            astro.append(round((values[i] - slow) * 100))
        if len(level) < 48:
            return None

        offset = timedelta(seconds=raw.get("utc_offset_seconds", 0))
        start_local = datetime.fromisoformat(times[start])
        return {
            "start": times[start][:10],
            "level": level,   # napovedana gladina, cm glede na trimesečno povprečje
            "astro": astro,   # astronomsko plimovanje, cm okoli ničle
            # Začetek grafa kot trenutek UTC: brskalnik iz njega in svoje ure izračuna, kje je "zdaj".
            "start_ts": int((start_local - offset).replace(tzinfo=timezone.utc).timestamp()),
            "moons": moon_phases((start_local - offset).replace(tzinfo=timezone.utc), DAYS * 24),
        }

    data = await cached(("tide", round(lat, 3), round(lon, 3)), SERIES_TTL, fetch)
    if data is None or not in_gulf_of_trieste(lat, lon):
        return data

    # Pas juga in burje iz vetrovne napovedi, ki jo aplikacija že ima (hitrost v vozlih, 0 = drug veter).
    try:
        forecast = await weather.forecast(lat, lon)
    except Exception:
        return data
    by_hour = {(day["date"], h["hour"]): h for day in forecast["days"] for h in day["hours"]}
    first = datetime.fromisoformat(data["start"])
    jugo, burja = [], []
    for i in range(len(data["level"])):
        moment = first + timedelta(hours=i)
        hour = by_hour.get((moment.date().isoformat(), moment.hour))
        kind = _wind_class(hour["deg"]) if hour else None
        speed = (hour["wind_kt"] or 0) if hour else 0
        if speed < MIN_WIND_KT:
            kind = None
        jugo.append(speed if kind == "jugo" else 0)
        burja.append(speed if kind == "burja" else 0)
    return {**data, "wind": {"jugo": jugo, "burja": burja}}
