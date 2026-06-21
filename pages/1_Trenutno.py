import streamlit as st
import requests
import warnings
import os
import json
from datetime import datetime, timedelta
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv
from config import load_config, save_config, get_coords, get_location_name, search_location, get_fallback_locations

load_dotenv()

warnings.filterwarnings("ignore", category=UserWarning, module="openai._compat")

# ────────────────────────────────────────────────────────────
# KONFIGURACIJA (lokacija + jezik)
# ────────────────────────────────────────────────────────────
cfg = load_config()
if "lang" not in st.session_state:
    st.session_state.lang = cfg.get("language", "sl")

lang = st.session_state.lang
LAT, LON = get_coords()
location_name = get_location_name()

# ────────────────────────────────────────────────────────────
# API SETUP + diskovni cache za kapitanovo napoved
# ────────────────────────────────────────────────────────────
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
if not OPENROUTER_API_KEY:
    try:
        OPENROUTER_API_KEY = st.secrets["OPENROUTER_API_KEY"]
    except:
        OPENROUTER_API_KEY = None

client = None
if OPENROUTER_API_KEY:
    client = OpenAI(
        api_key=OPENROUTER_API_KEY,
        base_url="https://openrouter.ai/api/v1"
    )
else:
    st.warning("⚠️ OPENROUTER_API_KEY ni nastavljen — Kapitanova napoved ne bo delovala.")

# Diskovni cache (shranjen na disk, delijo ga vsi uporabniki in preživi rerune)
FORECAST_CACHE_DIR = Path(__file__).parent / ".forecast_cache"

def _forecast_cache_path(lat: float, lon: float, lang: str, hour_key: str) -> Path:
    """Vrne pot do cache datoteke za dane parametre."""
    FORECAST_CACHE_DIR.mkdir(exist_ok=True)
    lat_s = f"{lat:.2f}"
    lon_s = f"{lon:.2f}"
    return FORECAST_CACHE_DIR / f"{lat_s}_{lon_s}_{lang}_{hour_key}.json"

def _get_cached_forecast(lat: float, lon: float, lang: str, hour_key: str):
    """Prebere napoved iz diskovnega cache-a, ce obstaja."""
    path = _forecast_cache_path(lat, lon, lang, hour_key)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return None

def _set_cached_forecast(lat: float, lon: float, lang: str, hour_key: str, forecast_text: str):
    """Shrani napoved v diskovni cache."""
    path = _forecast_cache_path(lat, lon, lang, hour_key)
    path.write_text(json.dumps(forecast_text, ensure_ascii=False), encoding="utf-8")
    for f in FORECAST_CACHE_DIR.glob("*.json"):
        if f.name == path.name:
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(data, str):
                mtime = f.stat().st_mtime
                if datetime.now().timestamp() - mtime > 3600:
                    f.unlink()
        except:
            try:
                f.unlink()
            except:
                pass

# ────────────────────────────────────────────────────────────
# JEZIK — besedila
# ────────────────────────────────────────────────────────────
TEXTS = {
    "sl": {"title": "Trenutno vreme", "updated": "Posodobljeno", "next_refresh": "Naslednja osvežitev približno ob", "temp_label": "🌡️ Temperatura", "humidity_label": "💧 Vlažnost", "precip_label": "☔ Padavine zdaj", "uv_label": "☀️ UV index", "sea_temp_label": "🌊 Temperatura morja", "waves_label": "🌊 Valovi", "wind_label": "🌬️ Veter", "wind_gusts_prefix": "sunki do", "no_alert": "Mirno vreme – vse pod kontrolo", "alert_prefix": "⚠️ ", "loc_label": "📍 Lokacija", "forecast_title": "🧭 Napoved za naslednjih 12 ur", "nav_next": "📊 10-dnevna napoved →"},
    "en": {"title": "Current weather", "updated": "Updated", "next_refresh": "Next refresh approx. at", "temp_label": "🌡️ Temperature", "humidity_label": "💧 Humidity", "precip_label": "☔ Precipitation now", "uv_label": "☀️ UV index", "sea_temp_label": "🌊 Sea temperature", "waves_label": "🌊 Waves", "wind_label": "🌬️ Wind", "wind_gusts_prefix": "gusts up to", "no_alert": "Calm weather – all under control", "alert_prefix": "⚠️ ", "loc_label": "📍 Location", "forecast_title": "🧭 Forecast for the next 12 hours", "nav_next": "📊 10-day forecast →"},
    "it": {"title": "Meteo attuale", "updated": "Aggiornato", "next_refresh": "Prossimo aggiornamento circa alle", "temp_label": "🌡️ Temperatura", "humidity_label": "💧 Umidità", "precip_label": "☔ Precipitazioni ora", "uv_label": "☀️ Indice UV", "sea_temp_label": "🌊 Temperatura del mare", "waves_label": "🌊 Onde", "wind_label": "🌬️ Vento", "wind_gusts_prefix": "raffiche fino a", "no_alert": "Tempo calmo – tutto sotto controllo", "alert_prefix": "⚠️ ", "loc_label": "📍 Località", "forecast_title": "🧭 Previsioni per le prossime 12 ore", "nav_next": "📊 Previsioni 10 giorni →"},
    "de": {"title": "Aktuelles Wetter", "updated": "Aktualisiert", "next_refresh": "Nächste Aktualisierung ca. um", "temp_label": "🌡️ Temperatur", "humidity_label": "💧 Luftfeuchtigkeit", "precip_label": "☔ Niederschlag jetzt", "uv_label": "☀️ UV-Index", "sea_temp_label": "🌊 Meerestemperatur", "waves_label": "🌊 Wellen", "wind_label": "🌬️ Wind", "wind_gusts_prefix": "Böen bis", "no_alert": "Ruhiges Wetter – alles unter Kontrolle", "alert_prefix": "⚠️ ", "loc_label": "📍 Standort", "forecast_title": "🧭 Vorhersage für die nächsten 12 Stunden", "nav_next": "📊 10-Tage-Vorhersage →"},
}

t = TEXTS[lang]

# ────────────────────────────────────────────────────────────
# POMOŽNE FUNKCIJE
# ────────────────────────────────────────────────────────────
def kmh_to_knots(kmh):
    return round(kmh / 1.852, 1) if kmh is not None else "N/A"

def feels_like_temp(temp, wind_kt):
    if not isinstance(temp, (int, float)) or wind_kt == "N/A" or wind_kt < 3 or temp > 12:
        return temp
    wind_mph = wind_kt * 1.15078
    chill = 13.12 + (0.6215 * temp) - (11.37 * (wind_mph ** 0.16)) + (0.3965 * temp * (wind_mph ** 0.16))
    return round(chill, 1)

def get_openmeteo_forecast():
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={LAT}&longitude={LON}&current=temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m,wind_gusts_10m,wind_direction_10m,uv_index&timezone=Europe/Ljubljana"
        return requests.get(url, timeout=10).json()
    except:
        return None

def get_openmeteo_marine():
    try:
        url = f"https://marine-api.open-meteo.com/v1/marine?latitude={LAT}&longitude={LON}&current=sea_surface_temperature&hourly=wave_height&forecast_days=2"
        return requests.get(url, timeout=10).json()
    except:
        return None

FORECAST_PROMPTS = {
    "sl": {
        "system": "Ti si izkušen, prijazen in rahlo hudomušen kapitan iz {loc}. Odgovarjaj izključno v slovenščini.",
        "user": "Kraj: {loc}. Trenutno: {temp}°C, občutek {feels}, veter {wind} kt {wdir}, valovi {waves}m, padavine {precip} mm, ura je {hour}:00 ({period}). Napiši kratko, uporabno in prijazno napoved za naslednjih 12 ur."
    },
    "en": {
        "system": "You are an experienced, friendly and slightly humorous captain from {loc}. Answer exclusively in English.",
        "user": "Location: {loc}. Currently: {temp}°C, feels like {feels}, wind {wind} kt {wdir}, waves {waves}m, precipitation {precip} mm, time is {hour}:00 ({period}). Write a short, useful and friendly forecast for the next 12 hours."
    },
    "it": {
        "system": "Sei un capitano esperto, amichevole e leggermente umoristico di {loc}. Rispondi esclusivamente in italiano.",
        "user": "Località: {loc}. Attualmente: {temp}°C, percepita {feels}, vento {wind} kt {wdir}, onde {waves}m, precipitazioni {precip} mm, ora sono le {hour}:00 ({period}). Scrivi una breve, utile e amichevole previsione per le prossime 12 ore."
    },
    "de": {
        "system": "Du bist ein erfahrener, freundlicher und leicht humorvoller Kapitän aus {loc}. Antworte ausschließlich auf Deutsch.",
        "user": "Ort: {loc}. Aktuell: {temp}°C, gefühlt {feels}, Wind {wind} kt {wdir}, Wellen {waves}m, Niederschlag {precip} mm, Uhrzeit {hour}:00 ({period}). Schreiben Sie eine kurze, nützliche und freundliche Vorhersage für die nächsten 12 Stunden."
    },
}

def generate_forecast(data, lang="sl"):
    if not client:
        return "Kapitan je na dopustu... 🏖️"
    now = datetime.now()
    hour_key = now.strftime("%Y-%m-%d_%H")
    cached = _get_cached_forecast(LAT, LON, lang, hour_key)
    if cached is not None:
        return cached
    p = FORECAST_PROMPTS.get(lang, FORECAST_PROMPTS["sl"])
    user_msg = p["user"].format(
        loc=location_name, temp=data["temp"], feels=data.get("feels_like", ""),
        wind=data["wind_speed_kt"], wdir=data["wind_dir_str"], waves=data["waves"],
        precip=data.get("precip", 0), hour=data.get("hour", 12), period=data.get("day_period", "dan"),
    )
    try:
        response = client.chat.completions.create(
            model="deepseek/deepseek-chat",
            messages=[
                {"role": "system", "content": p["system"].format(loc=location_name)},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.75, max_tokens=320
        )
        forecast_text = response.choices[0].message.content.strip()
        _set_cached_forecast(LAT, LON, lang, hour_key, forecast_text)
        return forecast_text
    except Exception:
        return "Kapitan je trenutno na radiu... poskusi čez minuto."

# ────────────────────────────────────────────────────────────
# CSS
# ────────────────────────────────────────────────────────────
st.markdown("""
<style>
    [data-testid="stSidebarNav"] { display: none; }
    .big-title { font-size: 32px !important; font-weight: bold; text-align: center; margin: 10px 0; }
    .metric-box { background: #f8f9fa; padding: 12px; border-radius: 10px; text-align: center; margin-bottom: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.06); }
    .metric-label { font-size: 14.5px !important; font-weight: bold; color: #444; }
    .metric-value { font-size: 26px !important; font-weight: bold; color: #0d6efd; }
    .forecast-box { background-color: #f0f8ff; padding: 18px; border-radius: 10px; margin: 15px auto; max-width: 96%; line-height: 1.6; border-left: 6px solid #0d6efd; font-size: 16px; }
    .update-time { text-align: center; color: #6b7280; font-size: 14px; margin-bottom: 4px; }
    .countdown { text-align: center; color: #9ca3af; font-size: 13px; margin-bottom: 20px; }
    a[data-testid="stSidebarNavLink"] { border-radius: 10px !important; transition: all 0.2s ease !important; }
    a[data-testid="stSidebarNavLink"]:hover { background: rgba(13, 110, 253, 0.1) !important; }
    a[data-testid="stSidebarNavLink"][aria-current="page"] { background: rgba(13, 110, 253, 0.15) !important; border-left: 4px solid #0d6efd !important; }
    a[data-testid="stSidebarNavLink"], a[data-testid="stSidebarNavLink"] * { font-size: 16px !important; font-weight: 600 !important; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important; }
    a[data-testid="stSidebarNavLink"][aria-current="page"], a[data-testid="stSidebarNavLink"][aria-current="page"] * { font-weight: 700 !important; }
    section[data-testid="stSidebar"] .stButton button[kind="primary"] { background-color: #A9DFBF !important; border-color: #92d5aa !important; color: #0B2512 !important; }
    section[data-testid="stSidebar"] .stButton button[kind="primary"]:hover { background-color: #95d5ac !important; border-color: #7ecb97 !important; color: #0B2512 !important; }
    section[data-testid="stSidebar"] .stButton button[kind="secondary"] { background-color: #F4F9F5 !important; border-color: #CBDED1 !important; color: #1E4620 !important; }
    section[data-testid="stSidebar"] .stButton button[kind="secondary"]:hover { background-color: #E8F3EC !important; border-color: #A9DFBF !important; color: #0B2512 !important; }
</style>
""", unsafe_allow_html=True)

st.markdown(f'<div class="big-title">🌊 {t["title"]} — {location_name}</div>', unsafe_allow_html=True)
# ── Navigacija med zavihki ──
if st.button(t["nav_next"], use_container_width=True, type="secondary"):
    st.switch_page("pages/2_Napoved.py")

# ────────────────────────────────────────────────────────────
# SIDEBAR — jezik + lokacija
# ────────────────────────────────────────────────────────────
LANG_NAMES = {"sl": "🇸🇮 SL", "en": "🇬🇧 EN", "it": "🇮🇹 IT", "de": "🇩🇪 DE"}

with st.sidebar:
    st.markdown("### 🌍 Jezik / Language")
    for lang_code, lang_label in LANG_NAMES.items():
        if st.button(lang_label, use_container_width=True,
                     type="secondary" if lang != lang_code else "primary"):
            st.session_state.lang = lang_code
            save_config(LAT, LON, location_name, lang_code)
            st.rerun()
    st.divider()
    with st.expander("📍 Spremeni lokacijo", expanded=False):
        search_q = st.text_input("🔍 Išči lokacijo", placeholder="Izola, Piran...", key="sidebar_search_1")
        if st.button("🔍 Poišči", key="side_search_btn_1", use_container_width=True, type="primary"):
            if search_q and len(search_q.strip()) >= 3:
                locs = search_location(search_q)
                if not locs:
                    locs = get_fallback_locations()
                st.session_state.side_results_1 = locs
            else:
                st.session_state.side_results_1 = []
        if "side_results_1" in st.session_state and st.session_state.side_results_1:
            st.markdown("<small>Izberi lokacijo:</small>", unsafe_allow_html=True)
            for idx, loc in enumerate(st.session_state.side_results_1):
                if st.button(loc["display"], key=f"side_loc_btn_1_{idx}", use_container_width=True):
                    cur_lang = st.session_state.get("lang", "sl")
                    save_config(loc["lat"], loc["lon"], loc["display"], cur_lang)
                    st.rerun()
    st.divider()
    st.caption("🌊 Vremenska postaja • 2025")

# ────────────────────────────────────────────────────────────
# Vreme
# ────────────────────────────────────────────────────────────
@st.fragment(run_every=900)
def prikazi_vreme():
    now = datetime.now()
    next_refresh = (now + timedelta(minutes=15)).strftime("%H:%M")
    forecast = get_openmeteo_forecast()
    marine = get_openmeteo_marine()

    if forecast and "current" in forecast:
        c = forecast["current"]
        temp = c.get("temperature_2m", "N/A")
        humidity = c.get("relative_humidity_2m", "N/A")
        precip = c.get("precipitation", 0)
        uv = c.get("uv_index", "N/A")
        wind_kmh = c.get("wind_speed_10m")
        gusts_kmh = c.get("wind_gusts_10m")
        wind_dir = c.get("wind_direction_10m")
        wind_kt = kmh_to_knots(wind_kmh)
        gusts_kt = kmh_to_knots(gusts_kmh)
        feels = feels_like_temp(temp, wind_kt)
        feels_str = f" (občutek {feels}°C)" if feels != temp else ""
        directions = ["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW"]
        wind_dir_str = directions[int((wind_dir + 11.25) / 22.5) % 16] if wind_dir is not None else "N"
        sea_temp = marine["current"].get("sea_surface_temperature", "N/A") if marine else "N/A"
        waves = round(marine["hourly"]["wave_height"][0], 1) if marine else "N/A"
        now_hour = now.hour
        day_period = "noč" if now_hour < 6 or now_hour >= 20 else "dan"
        data = {"temp": temp, "feels_like": feels_str, "humidity": humidity, "precip": precip, "uv": uv, "sea_temp": sea_temp, "waves": waves, "wind_speed_kt": wind_kt, "wind_gusts_kt": gusts_kt, "wind_dir_str": wind_dir_str, "hour": now_hour, "day_period": day_period}

        st.markdown(f'<div class="update-time">⏱️ {t["updated"]}: {now.strftime("%d.%m.%Y %H:%M")}</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="countdown">🔄 {t["next_refresh"]} {next_refresh}</div>', unsafe_allow_html=True)
        cols = st.columns(4)
        with cols[0]:
            st.markdown(f'<div class="metric-box"><div class="metric-label">{t["temp_label"]}</div><div class="metric-value">{temp}°C{feels_str}</div></div>', unsafe_allow_html=True)
            st.markdown(f'<div class="metric-box"><div class="metric-label">{t["humidity_label"]}</div><div class="metric-value">{humidity}%</div></div>', unsafe_allow_html=True)
        with cols[1]:
            st.markdown(f'<div class="metric-box"><div class="metric-label">{t["precip_label"]}</div><div class="metric-value">{precip} mm</div></div>', unsafe_allow_html=True)
            st.markdown(f'<div class="metric-box"><div class="metric-label">{t["uv_label"]}</div><div class="metric-value">{uv}</div></div>', unsafe_allow_html=True)
        with cols[2]:
            st.markdown(f'<div class="metric-box"><div class="metric-label">{t["sea_temp_label"]}</div><div class="metric-value">{sea_temp}°C</div></div>', unsafe_allow_html=True)
            st.markdown(f'<div class="metric-box"><div class="metric-label">{t["waves_label"]}</div><div class="metric-value">~{waves} m</div></div>', unsafe_allow_html=True)
        with cols[3]:
            gust_text = f"<br><small>({t['wind_gusts_prefix']} {gusts_kt} kt)</small>" if gusts_kt != "N/A" and gusts_kt > wind_kt + 2 else ""
            st.markdown(f'<div class="metric-box"><div class="metric-label">{t["wind_label"]}</div><div class="metric-value">{wind_kt} kt {wind_dir_str}{gust_text}</div></div>', unsafe_allow_html=True)
        alerts = []
        if gusts_kt != "N/A" and gusts_kt > 25: alerts.append(f"Močni sunki vetra ({gusts_kt} kt)")
        if waves != "N/A" and waves > 1.2: alerts.append(f"Visoki valovi ({waves} m)")
        if alerts:
            st.markdown(f'<div class="alert-box" style="background:#fee2e2;padding:12px;border-radius:10px;text-align:center;font-weight:600;color:#991b1b;">⚠️ {" • ".join(alerts)}</div>', unsafe_allow_html=True)
        else:
            st.markdown(f'<div class="ok-box" style="background:#dcfce7;padding:12px;border-radius:10px;text-align:center;font-weight:600;color:#166534;">✅ {t["no_alert"]}</div>', unsafe_allow_html=True)
        with st.spinner("Kapitan razmišlja... 🌊"):
            napoved = generate_forecast(data, lang)
            st.markdown(f'<div class="forecast-box">🧭 <b>{t["forecast_title"]}</b><br><br>{napoved}</div>', unsafe_allow_html=True)
    else:
        st.error("Napaka pri pridobivanju podatkov.")

prikazi_vreme()