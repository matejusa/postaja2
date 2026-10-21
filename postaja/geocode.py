"""Iskanje lokacij prek Open-Meteo Geocoding API (SI, HR, IT, NL)."""
import asyncio
import unicodedata
from itertools import chain, zip_longest

from .cache import cached
from .settings import http

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
SEARCH_TTL = 24 * 3600

# Vrstni red določa tudi prednost pri prepletanju zadetkov.
COUNTRY_FLAGS = {"SI": "🇸🇮", "HR": "🇭🇷", "IT": "🇮🇹", "NL": "🇳🇱"}
COUNTRY_NAMES = {
    "SI": {"sl": "Slovenija", "en": "Slovenia", "it": "Slovenia", "de": "Slowenien"},
    "HR": {"sl": "Hrvaška", "en": "Croatia", "it": "Croazia", "de": "Kroatien"},
    "IT": {"sl": "Italija", "en": "Italy", "it": "Italia", "de": "Italien"},
    "NL": {"sl": "Nizozemska", "en": "Netherlands", "it": "Paesi Bassi", "de": "Niederlande"},
}

FALLBACK_LOCATIONS = [
    {"lat": 45.536, "lon": 13.660, "display": "Izola (Marina), Slovenija 🇸🇮"},
    {"lat": 45.578, "lon": 13.736, "display": "Ankaran, Slovenija 🇸🇮"},
    {"lat": 45.528, "lon": 13.568, "display": "Piran, Slovenija 🇸🇮"},
]


def _plain(text: str) -> str:
    """Male črke brez strešic, da 'porec' najde 'Poreč'."""
    return "".join(ch for ch in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(ch))


async def _search_country(query: str, code: str) -> list[dict]:
    resp = await http.get(GEOCODING_URL, timeout=10,
                          params={"name": query, "count": 10, "language": "en", "countryCode": code})
    resp.raise_for_status()
    prefix = _plain(query)
    items = resp.json().get("results", [])
    # Najprej kraji, ki se začnejo z vpisanim besedilom, znotraj tega večji pred manjšimi.
    items.sort(key=lambda it: (not _plain(it.get("name", "")).startswith(prefix), -(it.get("population") or 0)))
    return [{
        "lat": float(it["latitude"]),
        "lon": float(it["longitude"]),
        "name": it.get("name", ""),
        "code": code,
        # Občina/regija samo za razločevanje enakih imen v seznamu zadetkov.
        "detail": ", ".join(dict.fromkeys(
            it[k] for k in ("admin2", "admin1") if it.get(k) and it[k] != it.get("name"))),
    } for it in items]


async def search_location(query: str, lang: str, limit: int = 8) -> list[dict]:
    """Išče po vsaki državi posebej (globalno iskanje pri kratkih vnosih zgreši manjše kraje)
    in zadetke prepleta, da nobena država ne preglasi ostalih."""
    query = query.strip()
    if len(query) < 3:
        return []

    async def fetch():
        per_country = await asyncio.gather(*(_search_country(query, code) for code in COUNTRY_FLAGS),
                                           return_exceptions=True)
        lists = [r for r in per_country if not isinstance(r, BaseException)]
        if not lists:
            raise RuntimeError("geokodiranje ni dosegljivo")
        seen, results = set(), []
        for loc in chain.from_iterable(zip_longest(*lists)):
            if loc and (loc["name"], loc["code"], loc["detail"]) not in seen:
                seen.add((loc["name"], loc["code"], loc["detail"]))
                results.append(loc)
        return results

    try:
        found = await cached(("geocode", _plain(query)), SEARCH_TTL, fetch)
    except Exception:
        return []
    # Imena krajev ostanejo izvirna (iskanje v slovenščini vrača "Občina Piran"), prevede se le država.
    return [{**loc, "display": f"{loc['name']}, {COUNTRY_NAMES[loc['code']][lang]} {COUNTRY_FLAGS[loc['code']]}"}
            for loc in found[:limit]]
