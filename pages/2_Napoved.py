import streamlit as st
import requests
import pandas as pd
import json
from datetime import datetime
from pathlib import Path
from config import load_config, save_config, get_coords, get_location_name, search_location, get_fallback_locations

# ════════════════════════════════════════════════════════════
# KONFIGURACIJA (lokacija + jezik)
# ════════════════════════════════════════════════════════════
cfg = load_config()
if "lang" not in st.session_state:
    st.session_state.lang = cfg.get("language", "sl")

lang = st.session_state.lang
LAT, LON = get_coords()
location_name = get_location_name()

# ════════════════════════════════════════════════════════════
# JEZIK
# ════════════════════════════════════════════════════════════
TEXTS = {
    "sl": {"page_title": "10-dnevna napoved", "table_title": "📋 Napoved po urah", "caption": "🔄 Podatki se osvežijo vsakih 30 minut • Vir: Open-Meteo", "error_no_data": "Ni podatkov za prikaz.", "error_api": "Napaka pri API klicu", "build_error": "Napaka: zgradi React projekt v Grafi/dist/", "dnevi": ["Pon", "Tor", "Sre", "Čet", "Pet", "Sob", "Ned"], "dnevi_full": ["Ponedeljek", "Torek", "Sreda", "Četrtek", "Petek", "Sobota", "Nedelja"], "h_ura": "Ura", "h_temp": "Temp", "h_padavine": "Padavine", "h_verj": "Verj.", "h_veter": "Veter / Sunki", "h_uv": "UV Max", "loc_label": "📍 Lokacija", "nav_prev": "Poglej še trenutno vreme"},
    "en": {"page_title": "10-day forecast", "table_title": "📋 Hourly forecast", "caption": "🔄 Data refreshes every 30 minutes • Source: Open-Meteo", "error_no_data": "No data available.", "error_api": "API call error", "build_error": "Error: build React project in Grafi/dist/", "dnevi": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], "dnevi_full": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"], "h_ura": "Hour", "h_temp": "Temp", "h_padavine": "Precip.", "h_verj": "Prob.", "h_veter": "Wind / Gusts", "h_uv": "UV Max", "loc_label": "📍 Location", "nav_prev": "See also current weather"},
    "it": {"page_title": "Previsioni 10 giorni", "table_title": "📋 Previsioni orarie", "caption": "🔄 Dati aggiornati ogni 30 minuti • Fonte: Open-Meteo", "error_no_data": "Nessun dato disponibile.", "error_api": "Errore chiamata API", "build_error": "Errore: compila il progetto React in Grafi/dist/", "dnevi": ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"], "dnevi_full": ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"], "h_ura": "Ora", "h_temp": "Temp", "h_padavine": "Precip.", "h_verj": "Prob.", "h_veter": "Vento / Raffiche", "h_uv": "UV Max", "loc_label": "📍 Località", "nav_prev": "Vedi anche meteo attuale"},
    "de": {"page_title": "10-Tage-Vorhersage", "table_title": "📋 Stündliche Vorhersage", "caption": "🔄 Daten werden alle 30 Minuten aktualisiert • Quelle: Open-Meteo", "error_no_data": "Keine Daten verfügbar.", "error_api": "API-Fehler", "build_error": "Fehler: React-Projekt in Grafi/dist/ erstellen", "dnevi": ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"], "dnevi_full": ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"], "h_ura": "Std.", "h_temp": "Temp", "h_padavine": "Nied.", "h_verj": "Wahr.", "h_veter": "Wind / Böen", "h_uv": "UV Max", "loc_label": "📍 Standort", "nav_prev": "Siehe auch aktuelles Wetter"},
}

t = TEXTS[lang]
DNEVI = t["dnevi"]
DNEVI_FULL = t["dnevi_full"]

# ════════════════════════════════════════════════════════════
# KONSTANTE
# ════════════════════════════════════════════════════════════
DIST_DIR = Path(__file__).parent.parent / "Grafi" / "dist"

WMO_ICONS = {0: "☀️", 1: "🌤️", 2: "⛅", 3: "☁️", 45: "🌫️", 48: "🌫️", 51: "🌦️", 53: "🌦️", 55: "🌦️", 56: "🌦️", 57: "🌦️", 61: "🌧️", 63: "🌧️", 65: "🌧️", 66: "🌧️", 67: "🌧️", 71: "❄️", 73: "❄️", 75: "❄️", 77: "❄️", 80: "🌦️", 81: "🌦️", 82: "🌦️", 85: "❄️", 86: "❄️", 95: "⛈️", 96: "⛈️", 99: "⛈️"}

def kmh_to_knots(kmh):
    return int(round(kmh / 1.852)) if kmh is not None else 0

def wmo_to_icon(code):
    return WMO_ICONS.get(code, "❓")

def degrees_to_direction(deg):
    if deg is None: return "❓"
    directions = [
        ("N", "⬇️"), ("NE", "↙️"), ("E", "⬅️"), ("SE", "↖️"),
        ("S", "⬆️"), ("SW", "↗️"), ("W", "➡️"), ("NW", "↘️")
    ]
    idx = int((deg + 22.5) % 360 / 45)
    return f"{directions[idx][1]} {directions[idx][0]}"

def get_temp_color(temp):
    if temp < 15: return "#2563eb"
    elif temp < 25: return "#16a34a"
    elif temp < 32: return "#ea580c"
    elif temp < 36: return "#dc2626"
    else: return "#8b00ff"

def get_uv_color(uv):
    if uv is None or uv < 0.1: return "#64748b"
    if uv < 3: return "#16a34a"
    elif uv < 8: return "#eab308"
    else: return "#dc2626"

def dan_str(datum_str: str) -> str:
    d = datetime.strptime(datum_str, "%Y-%m-%d")
    return f"{DNEVI[d.weekday()]} {d.day}.{d.month}."

def dan_full(datum_str: str) -> str:
    d = datetime.strptime(datum_str, "%Y-%m-%d")
    return f"{DNEVI_FULL[d.weekday()]} {d.day}.{d.month}."

# ════════════════════════════════════════════════════════════
# API KLIC
# ════════════════════════════════════════════════════════════
@st.cache_data(ttl=1800, show_spinner=False)
def get_forecast(lat, lon):
    try:
        url = (f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,wind_speed_10m_max,wind_gusts_10m_max,wind_direction_10m_dominant,weather_code,uv_index_max&hourly=temperature_2m,precipitation,precipitation_probability,wind_speed_10m,wind_direction_10m,weather_code,wind_gusts_10m&timezone=Europe/Ljubljana&forecast_days=10")
        return requests.get(url, timeout=15).json()
    except Exception as e:
        st.error(f"{t['error_api']}: {e}")
        return None

# ════════════════════════════════════════════════════════════
# IZGRADNJA HTML Z REACT GRAFOM
# ════════════════════════════════════════════════════════════
def build_chart_html(forecast_data: dict) -> str:
    daily = forecast_data["daily"]
    hourly = forecast_data["hourly"]
    weather_data = []
    for i in range(len(daily["time"])):
        start = i * 24
        d = datetime.strptime(daily["time"][i], "%Y-%m-%d")
        dan_ime = DNEVI[d.weekday()]
        datum_str = f"{d.day}.{d.month}."
        for ura in [0, 4, 8, 12, 16, 20]:
            h = start + ura
            if h >= len(hourly["time"]): continue
            temp = hourly["temperature_2m"][h] if h < len(hourly["temperature_2m"]) else 0
            veter = kmh_to_knots(hourly["wind_gusts_10m"][h]) if h < len(hourly["wind_gusts_10m"]) else 0
            smer = hourly["wind_direction_10m"][h] if h < len(hourly["wind_direction_10m"]) else 0
            padavine = 0
            for dh in range(4):
                if h + dh < len(hourly["precipitation"]): padavine += max(0, hourly["precipitation"][h + dh])
            padavine = round(padavine, 1)
            ikona_koda = hourly["weather_code"][h] if h < len(hourly["weather_code"]) else 0
            weather_data.append({"xLabel": f"{datum_str}_{ura}", "datum": datum_str, "dan": dan_ime, "ura": ura, "temp": temp, "veter": veter, "smer": smer, "padavine": padavine, "ikona": wmo_to_icon(ikona_koda)})
    js_files = list(DIST_DIR.glob("assets/index-*.js"))
    css_files = list(DIST_DIR.glob("assets/index-*.css"))
    if not js_files or not css_files: return f"<p>{t['build_error']}</p>"
    html_path = DIST_DIR / "index.html"
    base_html = html_path.read_text(encoding="utf-8")
    js_content = js_files[0].read_text(encoding="utf-8")
    css_content = css_files[0].read_text(encoding="utf-8")
    js_name = js_files[0].name
    css_name = css_files[0].name
    data_json = json.dumps(weather_data, ensure_ascii=False)
    LEGEND_TEXTS = {"sl": {"temp": "🌡️ Temperatura", "wind": "💨 Sunki vetra"}, "en": {"temp": "🌡️ Temperature", "wind": "💨 Wind gusts"}, "it": {"temp": "🌡️ Temperatura", "wind": "💨 Raffiche"}, "de": {"temp": "🌡️ Temperatur", "wind": "💨 Böen"}}
    lt = LEGEND_TEXTS.get(lang, LEGEND_TEXTS["sl"])
    resp_css = """<style>#root{border-inline:none!important}html,body{margin:0;padding:0;overflow-x:auto}#weather-chart{max-width:none!important;width:100%!important}@media(max-width:992px){#weather-chart{min-width:300vw!important}}</style>"""
    final = base_html.replace(f'<link rel="stylesheet" crossorigin href="/assets/{css_name}">', f"<style>{css_content}</style>").replace(f'<script type="module" crossorigin src="/assets/{js_name}"></script>', f"{resp_css}<script>window.__WEATHER_DATA__={data_json};</script><script>window.__CHART_TEXTS__={json.dumps(lt, ensure_ascii=False)};</script><script type=\"module\">{js_content}</script>")
    return final

# ════════════════════════════════════════════════════════════
# UI
# ════════════════════════════════════════════════════════════
big_title = location_name
st.markdown(f'<div class="big-title">{big_title}</div>', unsafe_allow_html=True)
st.markdown('<div class="nav-btn-container">', unsafe_allow_html=True)
if st.button(t["nav_prev"], use_container_width=True, type="secondary", key="nav_prev"):
    st.switch_page("pages/1_Trenutno.py")
st.markdown('</div>', unsafe_allow_html=True)

st.markdown("""
<style>
    [data-testid="stSidebarNav"] { display: none; }
    .big-title { font-size: 26px !important; font-weight: bold; text-align: center; margin: -8px 0 0 0; padding: 0; line-height: 1.2; }
    .main > .block-container { padding-top: 0.5rem !important; }
    a[data-testid="stSidebarNavLink"] { border-radius: 10px !important; transition: all 0.2s ease !important; }
    a[data-testid="stSidebarNavLink"]:hover { background: rgba(13, 110, 253, 0.1) !important; }
    a[data-testid="stSidebarNavLink"][aria-current="page"] { background: rgba(13, 110, 253, 0.15) !important; border-left: 4px solid #0d6efd !important; }
    a[data-testid="stSidebarNavLink"], a[data-testid="stSidebarNavLink"] * { font-size: 16px !important; font-weight: 600 !important; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important; }
    a[data-testid="stSidebarNavLink"][aria-current="page"], a[data-testid="stSidebarNavLink"][aria-current="page"] * { font-weight: 700 !important; }
    section[data-testid="stSidebar"] .stButton button[kind="primary"] { background-color: #A9DFBF !important; border-color: #92d5aa !important; color: #0B2512 !important; }
    section[data-testid="stSidebar"] .stButton button[kind="primary"]:hover { background-color: #95d5ac !important; border-color: #7ecb97 !important; color: #0B2512 !important; }
    section[data-testid="stSidebar"] .stButton button[kind="secondary"] { background-color: #F4F9F5 !important; border-color: #CBDED1 !important; color: #1E4620 !important; }
    section[data-testid="stSidebar"] .stButton button[kind="secondary"]:hover { background-color: #E8F3EC !important; border-color: #A9DFBF !important; color: #0B2512 !important; }
    .nav-btn-container .stButton button {
        background: #dceefb !important;
        color: #000000 !important;
        border: 2px solid #7ec8e3 !important;
        font-size: 20px !important;
        font-weight: 700 !important;
        padding: 16px 12px !important;
        border-radius: 14px !important;
        box-shadow: 0 4px 14px rgba(126, 200, 227, 0.35) !important;
        transition: all 0.2s ease !important;
        margin: 10px 0 !important;
        width: 100% !important;
    }
    .nav-btn-container .stButton button:hover {
        background: #c5e3f5 !important;
        border-color: #5ab0d4 !important;
        box-shadow: 0 6px 20px rgba(90, 176, 212, 0.45) !important;
        transform: translateY(-2px) !important;
    }
</style>
""", unsafe_allow_html=True)

# ── SIDEBAR — jezik + lokacija ──
LANG_NAMES = {"sl": "🇸🇮 SL", "en": "🇬🇧 EN", "it": "🇮🇹 IT", "de": "🇩🇪 DE"}
with st.sidebar:
    st.markdown("### 🌍 Jezik / Language")
    for lang_code, lang_label in LANG_NAMES.items():
        if st.button(lang_label, use_container_width=True, type="secondary" if lang != lang_code else "primary"):
            st.session_state.lang = lang_code
            save_config(LAT, LON, location_name, lang_code)
            st.rerun()
    st.divider()
    with st.expander("📍 Spremeni lokacijo", expanded=False):
        search_q = st.text_input("🔍 Išči lokacijo", placeholder="Izola, Piran...", key="sidebar_search_2")
        if st.button("🔍 Poišči", key="side_search_btn_2", use_container_width=True, type="primary"):
            if search_q and len(search_q.strip()) >= 3:
                locs = search_location(search_q)
                if not locs: locs = get_fallback_locations()
                st.session_state.side_results_2 = locs
            else: st.session_state.side_results_2 = []
        if "side_results_2" in st.session_state and st.session_state.side_results_2:
            st.markdown("<small>Izberi lokacijo:</small>", unsafe_allow_html=True)
            for idx, loc in enumerate(st.session_state.side_results_2):
                if st.button(loc["display"], key=f"side_loc_btn_2_{idx}", use_container_width=True):
                    cur_lang = st.session_state.get("lang", "sl")
                    save_config(loc["lat"], loc["lon"], loc["display"], cur_lang)
                    st.rerun()
    st.divider()
    st.caption("🌊 Vremenska postaja • 2025")

data = get_forecast(LAT, LON)
if not data or "daily" not in data:
    st.error(t["error_no_data"])
    st.stop()

html = build_chart_html(data)
st.components.v1.html(html, height=550, scrolling=True)
st.divider()
st.subheader(t["table_title"])

# Funkcije za barvanje
def degrees_to_direction(deg):
    if deg is None: return "❓"
    directions = [
        ("N", "⬇️"), ("NE", "↙️"), ("E", "⬅️"), ("SE", "↖️"),
        ("S", "⬆️"), ("SW", "↗️"), ("W", "➡️"), ("NW", "↘️")
    ]
    idx = int((deg + 22.5) % 360 / 45)
    return f"{directions[idx][1]} {directions[idx][0]}"

def get_temp_color(temp):
    if temp < 15: return "#2563eb"
    elif temp < 25: return "#16a34a"
    elif temp < 32: return "#ea580c"
    elif temp < 36: return "#dc2626"
    else: return "#8b00ff"

def get_uv_color(uv):
    if uv is None or uv < 0.1: return "#64748b"
    if uv < 3: return "#16a34a"
    elif uv < 8: return "#eab308"
    else: return "#dc2626"

# --- PRENOVLJENA ZANKA ZA TABELO ---
daily = data["daily"]
hourly = data["hourly"]
ST_DNI_URNO = 3
ure_v_dnevu = [0, 6, 12, 18]
table_rows = ""

for dan_idx in range(len(daily["time"])):
    ime_dneva = dan_full(daily["time"][dan_idx])
    table_rows += f"""<tr class="day-header"><td colspan="6">{ime_dneva}</td></tr>"""
    ure = range(24) if dan_idx < ST_DNI_URNO else ure_v_dnevu
    
    for ura in ure:
        h = dan_idx * 24 + ura
        if h >= len(hourly["time"]): continue
        
        ica = "🌙" if (ura < 6 or ura >= 20) else wmo_to_icon(hourly["weather_code"][h])
        tmp = hourly["temperature_2m"][h]
        pad = round(hourly["precipitation"][h] or 0, 1)
        prob = hourly["precipitation_probability"][h]
        vet = kmh_to_knots(hourly["wind_speed_10m"][h])
        sunki = kmh_to_knots(hourly["wind_gusts_10m"][h]) if "wind_gusts_10m" in hourly else "-"
        
        smer_deg = hourly["wind_direction_10m"][h] if "wind_direction_10m" in hourly else None
        smer_str = degrees_to_direction(smer_deg)
        
        wind_str = f"{vet} / {sunki} kt {smer_str}" if sunki != "-" else f"{vet} kt {smer_str}"
        
        padavine_skupaj = f"{pad} mm ({prob}%)" if pad > 0 else f"- ({prob}%)"
        
        t_color = get_temp_color(tmp)
        
        # UV samo podnevi
        if 6 <= ura <= 18:
            uv = daily["uv_index_max"][dan_idx]
            uv_color = get_uv_color(uv)
            uv_str = f'<span style="color: {uv_color};">{uv}</span>'
        else:
            uv_str = "—"
        
        nocni = "class=\"night\"" if ura < 6 or ura >= 20 else ""
        table_rows += f"""<tr {nocni}>
            <td class="ura">{ura:02d}:00</td>
            <td class="icon">{ica}</td>
            <td class="temp" style="color: {t_color};">{tmp}°</td>
            <td class="precip">{padavine_skupaj}</td>
            <td class="wind">{wind_str}</td>
            <td class="uv">{uv_str}</td>
        </tr>"""

# Posodobljen HTML in CSS
table_html = f"""<div style="overflow-x:auto;-webkit-overflow-scrolling:touch;">
<table cellspacing="0">
<thead><tr>
    <th>{t['h_ura']}</th>
    <th style="width:36px;"></th>
    <th>{t['h_temp']}</th>
    <th>{t['h_padavine']} (% verj.)</th>
    <th>{t['h_veter']}</th>
    <th>{t['h_uv']}</th>
</tr></thead>
<tbody>{table_rows}</tbody></table></div>
<style>
    table{{width:100%;border-collapse:collapse;font-family:sans-serif;font-size:14px;background:#f8f9fa;border-radius:10px;overflow:hidden;box-shadow:0 2px 5px rgba(0,0,0,0.06)}}
    thead tr{{background:#0d6efd;color:#fff}}
    th{{padding:10px 8px;text-align:center;font-weight:700;font-size:12px;letter-spacing:0.3px}}
    td{{padding:7px 8px;text-align:center;border-bottom:1px solid #e9ecef;font-size:14px;color:#333}}
    td:first-child{{text-align:left;padding-left:14px}}
    .day-header td{{background:#e8f4fd;color:#000;font-weight:700;font-size:15px;text-align:left;padding:10px 14px;border-bottom:2px solid #0d6efd}}
    .night td{{background:#f1f3f5}}
    .ura{{font-weight:600;color:#0d6efd;font-size:13px}}
    .icon{{font-size:18px}}
    .temp{{font-weight:700;font-size:16px}}
    .precip{{color:#2563eb; font-weight:600}}
    .wind{{color:#1e3a8a; font-weight:600}}
    @media(max-width:480px){{
        table{{font-size:11px}}
        td{{padding:6px 4px;font-size:11px}}
        th{{padding:8px 4px;font-size:9px}}
        .temp{{font-size:12px}}
        .icon{{font-size:14px}}
    }}
</style>"""
st.markdown(table_html, unsafe_allow_html=True)
st.caption(t["caption"])