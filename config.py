"""Upravljanje konfiguracije (lokacija + jezik) prek config.json + Nominatim iskanje."""
import json
import time
from pathlib import Path
import requests

CONFIG_PATH = Path(__file__).parent / "config.json"

# ────────────────────────────────────────────────────────────
# Države za iskanje
# ────────────────────────────────────────────────────────────
COUNTRY_CODES = "si,hr,it"

COUNTRY_NAMES = {
    "si": "Slovenija", "hr": "Hrvaška", "it": "Italija",
    "en_si": "Slovenia", "en_hr": "Croatia", "en_it": "Italy",
    "it_si": "Slovenia", "it_hr": "Croazia", "it_it": "Italia",
    "de_si": "Slowenien", "de_hr": "Kroatien", "de_it": "Italien",
}

COUNTRY_FLAGS = {"si": "🇸🇮", "hr": "🇭🇷", "it": "🇮🇹"}

# ────────────────────────────────────────────────────────────
# Privzeta lokacija (fallback, če Nominatim ne dela)
# ────────────────────────────────────────────────────────────
FALLBACK_LOCATIONS = [
    {"lat": 45.536, "lon": 13.660, "display": "Izola (Marina), Slovenija 🇸🇮", "country": "si"},
    {"lat": 45.578, "lon": 13.736, "display": "Ankaran, Slovenija 🇸🇮", "country": "si"},
    {"lat": 45.528, "lon": 13.568, "display": "Piran, Slovenija 🇸🇮", "country": "si"},
]

DEFAULT_LANG = "sl"


# ────────────────────────────────────────────────────────────
# Branje / pisanje config.json
# ────────────────────────────────────────────────────────────
def load_config() -> dict:
    """Prebere config.json ali vrže privzeto konfiguracijo."""
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            if "lat" not in cfg or "lon" not in cfg:
                cfg["lat"] = FALLBACK_LOCATIONS[0]["lat"]
                cfg["lon"] = FALLBACK_LOCATIONS[0]["lon"]
                cfg["location_name"] = FALLBACK_LOCATIONS[0]["display"]
            return cfg
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "lat": FALLBACK_LOCATIONS[0]["lat"],
        "lon": FALLBACK_LOCATIONS[0]["lon"],
        "location_name": FALLBACK_LOCATIONS[0]["display"],
        "language": DEFAULT_LANG,
    }


def save_config(lat: float, lon: float, location_name: str, language: str):
    """Shrani konfiguracijo v config.json."""
    cfg = {
        "lat": lat,
        "lon": lon,
        "location_name": location_name,
        "language": language,
    }
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def get_coords() -> tuple:
    """Vrne (lat, lon) iz configa."""
    cfg = load_config()
    return cfg.get("lat", FALLBACK_LOCATIONS[0]["lat"]), cfg.get("lon", FALLBACK_LOCATIONS[0]["lon"])


def _shorten_display(display: str) -> str:
    """Skrajša prikaz na 'kraj, država' (brez administrativnih enot in poštnih številk)."""
    parts = display.split(", ")
    if len(parts) < 2:
        return display
    city = parts[0]
    # Poišči državo od zadaj — preskoči poštne številke
    country = parts[-1]
    if country.strip().isdigit() and len(parts) >= 3:
        country = parts[-2]
    # Če je "država" še vedno administrativna enota, vzemi prvi del + zadnji del, ki ni številka
    if any(kw in country.lower() for kw in ["upravna", "unità", "občina", "comune", "municipality", "province", "provincia", "6000", "6001"]):
        # Poskusi najti del, ki vsebuje ime države
        for p in reversed(parts):
            p_stripped = p.strip()
            if p_stripped.isdigit():
                continue
            if any(kw in p_stripped.lower() for kw in ["slovenija", "slovenia", "hrvaška", "croatia", "hrvatska", "italija", "italia", "italy", "italien"]):
                country = p_stripped
                break
        else:
            # Če ne najdemo imena države, vzemi zadnji ne-številski del
            for p in reversed(parts):
                if not p.strip().isdigit():
                    country = p.strip()
                    break
    return f"{city}, {country}"


def get_location_name() -> str:
    """Vrne prikazno ime lokacije (skrajšano)."""
    cfg = load_config()
    raw = cfg.get("location_name", FALLBACK_LOCATIONS[0]["display"])
    return _shorten_display(raw)


# ────────────────────────────────────────────────────────────
# Open-Meteo Geocoding iskanje
# ────────────────────────────────────────────────────────────
def search_location(query: str, limit: int = 5) -> list[dict]:
    """
    Pošlje poizvedbo Open-Meteo Geocoding API-ju.
    Vrne seznam: [{"lat": ..., "lon": ..., "display": ..., "country": ...}, ...]
    Prazni seznam ob napaki.
    """
    if len(query.strip()) < 3:
        return []

    # Preberi jezik iz trenutne konfiguracije
    cfg = load_config()
    lang = cfg.get("language", "sl")
    
    url = "https://geocoding-api.open-meteo.com/v1/search"
    params = {
        "name": query.strip(),
        "count": 20,       # Vzamemo več zadetkov za filtriranje
        "language": lang,
    }

    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        results = []
        allowed_countries = {"SI", "HR", "IT"}
        country_flags = {"SI": "🇸🇮", "HR": "🇭🇷", "IT": "🇮🇹"}

        for item in data.get("results", []):
            country_code = item.get("country_code", "").upper()
            if country_code not in allowed_countries:
                continue
                
            lat = float(item.get("latitude", 0))
            lon = float(item.get("longitude", 0))
            name = item.get("name", "")
            country = item.get("country", "")
            
            flag = country_flags.get(country_code, "")
            display = f"{name}, {country} {flag}".strip()
            
            results.append({
                "lat": lat,
                "lon": lon,
                "display": display,
                "country": country_code.lower(),
            })

        return results[:limit]

    except Exception:
        return []


def _guess_country(display_name: str) -> str:
    """Poskusi uganiti kodo države iz display_name."""
    lower = display_name.lower()
    if "slovenia" in lower or "slovenija" in lower:
        return "si"
    if "croatia" in lower or "hrvatska" in lower:
        return "hr"
    if "italy" in lower or "italia" in lower or "italien" in lower:
        return "it"
    return "si"  # fallback


def get_fallback_locations() -> list[dict]:
    """Vrne privzete lokacije (ko Nominatim ne dela)."""
    return FALLBACK_LOCATIONS