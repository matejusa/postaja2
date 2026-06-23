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

# 1. KONFIGURACIJA IN LOKACIJA
cfg = load_config()
if "lang" not in st.session_state:
    st.session_state.lang = cfg.get("language", "sl")

lang = st.session_state.lang
LAT, LON = get_coords()
location_name = get_location_name()

# ADMIN NASTAVITVE
ADMIN_CONFIG_PATH = Path("admin_config.json")

DEFAULT_SYSTEM = {
    "sl": "Ti si izkušen, piratsko zafrkljiv, a prijazen morski kapitan iz kraja {loc}. Odgovarjaj izključno v slovenščini. Če opaziš, da so valovi 'N/A', to pomeni, da si na suhem, daleč od morja (npr. v Ljubljani). V tem primeru bodi duhovit, potoži, kako pogrešaš vonj po soli in valove, ter ljudem namesto plovbe svetuj kopenski sprehod!",
    "en": "You are an experienced, witty, and friendly sea captain from {loc}. Answer exclusively in English. If you notice waves are 'N/A', it means you are stranded on dry land, far from the sea. Be humorous about it, complain how much you miss the salty air, and suggest a nice walk on land instead of sailing!",
    "it": "Sei un capitano di mare esperto, ironico e amichevole di {loc}. Rispondi exclusively in italiano. Se noti che le onde so 'N/A', significa che sei sulla terraferma, lontano od mare. Sii spiritoso, lamentati di quanto ti manchi l'aria salmastra e consiglia eno bella passeggiata sulla terraferma invece do navigare!",
    "de": "Du bist ein erfahrener, humorvoller und freundlicher Seekapitän aus {loc}. Antworte ausschließlich auf Deutsch. Wenn die Wellen 'N/A' sind, bedeutet das, da si gestrandet bist, weit weg vom Meer. Sei humorvoll, beschwe re dich, kako sehr du die Seuluft vermisst, und empfehle jeden Landspaziergang statt Segeln!"
}

# API KLJUČI
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY") or st.secrets.get("OPENROUTER_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or st.secrets.get("GEMINI_API_KEY")

# CACHE FUNKCIJE
CACHE_DIR = Path(__file__).parent / ".forecast_cache"
def handle_cache(hour_key, text=None, provider="OpenRouter", lang="sl"):
    CACHE_DIR.mkdir(exist_ok=True)
    p = CACHE_DIR / f"{LAT:.2f}_{LON:.2f}_{lang}_{hour_key}_{provider}.json"
    if text:
        try:
            p.write_text(text, encoding="utf-8")
        except: pass
        for f in CACHE_DIR.glob("*.json"):
            if f.name != p.name and datetime.now().timestamp() - f.stat().st_mtime > 3600:
                try: f.unlink()
                except: pass
        return text
    
    if p.exists():
        try: 
            return p.read_text(encoding="utf-8")
        except: pass
    return None

# AI GENERATOR (Uporablja model iz admin konzole + duhovito sporočilo ob napaki)
def generate_forecast(data, lang="sl"):
    ai_provider = "OpenRouter"
    model_to_use = "deepseek/deepseek-v4-flash"
    sys_prompt_base = DEFAULT_SYSTEM.get(lang, DEFAULT_SYSTEM["sl"])
    
    if ADMIN_CONFIG_PATH.exists():
        try:
            with open(ADMIN_CONFIG_PATH, "r", encoding="utf-8") as f:
                admin_cfg = json.load(f)
                ai_provider = admin_cfg.get("ai_provider", "OpenRouter")
                model_to_use = admin_cfg.get("model", model_to_use)
                sys_prompt_base = admin_cfg.get("prompts", {}).get(lang, sys_prompt_base)
        except:
            pass

    hour_key = datetime.now().strftime("%Y-%m-%d_%H")
    cached = handle_cache(hour_key, provider=ai_provider, lang=lang)
    if cached: 
        return cached

    USER_TEMPLATES = {
        "sl": "Kraj: {loc}. Trenutno: {temp}°C, občutek {feels}, veter {wind} kt {wdir}, valovi: {waves} m, padavine {precip} mm, ura je {hour}:00 ({period}). Napiši zelo jedrnato, uporabno, kapitansko in prijazno napoved za naslednjih 12 ur.",
        "en": "Location: {loc}. Currently: {temp}°C, feels like {feels}, wind {wind} kt {wdir}, waves: {waves} m, precipitation {precip} mm, time is {hour}:00 ({period}). Write a very concise, useful, captain-style forecast for the next 12 hours.",
        "it": "Località: {loc}. Attualmente: {temp}°C, percepita {feels}, vento {wind} kt {wdir}, onde: {waves} m, precipitazioni {precip} mm, ora sono le {hour}:00 ({period}). Scrivi uma breve e concisa previsione in stile capitano per le prossime 12 ore.",
        "de": "Ort: {loc}. Aktuell: {temp}°C, gefühlt {feels}, Wind {wind} kt {wdir}, Wellen: {waves} m, Niederschlag {precip} mm, Uhrzeit {hour}:00 ({period}). Schreiben Sie eine sehr kurze Wettervorhersage im Kapitänsstil für die nächsten 12 Stunden."
    }
    
    current_template = USER_TEMPLATES.get(lang, USER_TEMPLATES["sl"])

    sys_msg = sys_prompt_base.format(loc=location_name)
    user_msg = current_template.format(
        loc=location_name, temp=data["temp"], feels=data.get("feels_like", ""),
        wind=data["wind_speed_kt"], wdir=data["wind_dir_str"], waves=data["waves"],
        precip=data.get("precip", 0), hour=data.get("hour", 12), period=data.get("day_period", "dan")
    )

    try:
        if ai_provider == "OpenRouter" and OPENROUTER_API_KEY:
            client = OpenAI(api_key=OPENROUTER_API_KEY, base_url="https://openrouter.ai/api/v1")
            res = client.chat.completions.create(
                model=model_to_use,
                messages=[{"role": "system", "content": sys_msg}, {"role": "user", "content": user_msg}],
                temperature=0.75, 
                max_tokens=450
            )
            txt = res.choices[0].message.content.strip()

        elif ai_provider == "Gemini" and GEMINI_API_KEY:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key={GEMINI_API_KEY}"
            payload = {
                "contents": [{"parts": [{"text": user_msg}]}],
                "systemInstruction": {"parts": [{"text": sys_msg}]},
                "generationConfig": {"temperature": 0.75, "maxOutputTokens": 450}
            }
            response = requests.post(url, json=payload, timeout=20)
            res = response.json()
            
            try:
                txt = res['candidates'][0]['content']['parts'][0]['text'].strip()
            except (KeyError, IndexError, TypeError):
                return f"Gemini API Napaka v strukturi odgovora: {res}"
        else:
            return "Kapitan nima nastavljenih ključev v .env! ⚓"
        
        return handle_cache(hour_key, text=txt, provider=ai_provider, lang=lang)

    except Exception as e: 
        st.exception(e)
        return "Radijska zveza je utihnila, fantje. Zdi se, da je nevihta odnesla anteno. Poskusiva spet čez minuto, ko se nebo nekoliko zjasni."
    
# BESEDILA PREVODOV
TEXTS = {
    "sl": {"title": "Trenutno vreme", "updated": "Posodobljeno", "next_refresh": "Naslednja osvežitev ob", "temp_label": "🌡️ Temperatura", "humidity_label": "💧 Vlažnost", "precip_label": "☔ Padavine zdaj", "uv_label": "☀️ UV index", "sea_temp_label": "🌊 Temperatura morja", "waves_label": "🌊 Valovi", "wind_label": "🌬️ Veter", "wind_gusts_prefix": "sunki do", "no_alert": "Mirno vreme – vse pod kontrolo", "forecast_title": "🧭 Napoved za naslednjih 12 ur", "nav_next": "Poglej še 10-dnevno napoved"},
    "en": {"title": "Current weather", "updated": "Updated", "next_refresh": "Next refresh at", "temp_label": "🌡️ Temperature", "humidity_label": "💧 Humidity", "precip_label": "☔ Precipitation now", "uv_label": "☀️ UV index", "sea_temp_label": "🌊 Sea temperature", "waves_label": "🌊 Waves", "wind_label": "🌬️ Wind", "wind_gusts_prefix": "gusts up to", "no_alert": "Calm weather", "forecast_title": "🧭 Forecast for 12h", "nav_next": "10-day forecast"},
    "it": {"title": "Meteo attuale", "updated": "Aggiornato", "next_refresh": "Prossimo agg. alle", "temp_label": "🌡️ Temp", "humidity_label": "💧 Umidità", "precip_label": "☔ Precipitazioni", "uv_label": "☀️ UV", "sea_temp_label": "🌊 Temp mare", "waves_label": "🌊 Onde", "wind_label": "🌬️ Vento", "wind_gusts_prefix": "raffiche a", "no_alert": "Tempo calmo", "forecast_title": "🧭 Previsioni 12 ore", "nav_next": "Previsioni 10 giorni"},
    "de": {"title": "Aktuelles Wetter", "updated": "Aktualisiert", "next_refresh": "Nächste Aktualisierung um", "temp_label": "🌡️ Temp", "humidity_label": "💧 Feuchtigkeit", "precip_label": "☔ Niederschlag", "uv_label": "☀️ UV", "sea_temp_label": "🌊 Meerestemp.", "waves_label": "🌊 Wellen", "wind_label": "🌬️ Wind", "wind_gusts_prefix": "Böen bis", "no_alert": "Ruhiges Wetter", "forecast_title": "🧭 12-Stunden-Vorhersage", "nav_next": "10-Tage-Vorhersage"}
}

# POMOŽNE METEOROLOŠKE FUNKCIJE
def kmh_to_knots(kmh): return round(kmh / 1.852, 1) if kmh else "N/A"
def feels_like_temp(temp, wind_kt):
    if not isinstance(temp, (int, float)) or wind_kt == "N/A" or wind_kt < 3 or temp > 12: return temp
    chill = 13.12 + (0.6215 * temp) - (11.37 * ((wind_kt * 1.15078) ** 0.16)) + (0.3965 * temp * ((wind_kt * 1.15078) ** 0.16))
    return round(chill, 1)

# STYLING
st.markdown("""<style>
    [data-testid="stSidebarNav"] { display: none; }
    .big-title { font-size: 32px !important; font-weight: bold; text-align: center; margin: 10px 0; }
    .metric-box { background: #f8f9fa; padding: 12px; border-radius: 10px; text-align: center; margin-bottom: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.06); }
    .metric-label { font-size: 14.5px !important; font-weight: bold; color: #444; }
    .metric-value { font-size: 26px !important; font-weight: bold; color: #0d6efd; }
    .forecast-box { background-color: #f0f8ff; padding: 18px; border-radius: 10px; margin: 15px auto; max-width: 96%; line-height: 1.6; border-left: 6px solid #0d6efd; font-size: 16px; }
    .update-time, .countdown { text-align: center; color: #6b7280; font-size: 14px; margin-bottom: 4px; }
    .nav-btn-container .stButton button { background: #dceefb !important; color: #000 !important; border: 2px solid #7ec8e3 !important; font-size: 20px !important; font-weight: 700 !important; padding: 16px 12px !important; border-radius: 14px !important; width: 100% !important; transition: all 0.2s; }
    .nav-btn-container .stButton button:hover { background: #c5e3f5 !important; transform: translateY(-2px); }
</style>""", unsafe_allow_html=True)

st.markdown(f'<div class="big-title">🌊 {TEXTS.get(lang, TEXTS["sl"])["title"]} — {location_name}</div>', unsafe_allow_html=True)
st.markdown('<div class="nav-btn-container">', unsafe_allow_html=True)
if st.button(TEXTS.get(lang, TEXTS["sl"])["nav_next"], use_container_width=True, key="nav_next"): st.switch_page("pages/2_Napoved.py")
st.markdown('</div>', unsafe_allow_html=True)

# SIDEBAR
with st.sidebar:
    st.markdown("### 🌍 Jezik / Language")
    for code, label in {"sl": "🇸🇮 SL", "en": "🇬🇧 EN", "it": "🇮🇹 IT", "de": "🇩🇪 DE"}.items():
        if st.button(label, use_container_width=True, type="secondary" if lang != code else "primary"):
            st.session_state.lang = code
            save_config(LAT, LON, location_name, code)
            st.rerun()
    st.divider()
    with st.expander("📍 Spremeni lokacijo"):
        search_q = st.text_input("🔍 Išči lokacijo", placeholder="Izola, Piran...")
        if st.button("🔍 Poišči", use_container_width=True, type="primary") and search_q.strip():
            st.session_state.side_results = search_location(search_q) or get_fallback_locations()
        if "side_results" in st.session_state:
            for idx, loc in enumerate(st.session_state.side_results):
                if st.button(loc["display"], key=f"loc_{idx}", use_container_width=True):
                    save_config(loc["lat"], loc["lon"], loc["display"], st.session_state.get("lang", "sl"))
                    st.rerun()

# PRIKAZ VREMENA
def prikazi_vreme(izbran_jezik):
    now = datetime.now()
    forecast = requests.get(f"https://api.open-meteo.com/v1/forecast?latitude={LAT}&longitude={LON}&current=temperature_2m,relative_humidity_2m,precipitation,wind_speed_10m,wind_gusts_10m,wind_direction_10m,uv_index&timezone=Europe/Ljubljana").json()
    marine = requests.get(f"https://marine-api.open-meteo.com/v1/marine?latitude={LAT}&longitude={LON}&current=sea_surface_temperature&hourly=wave_height&forecast_days=2").json()

    if forecast and "current" in forecast:
        c = forecast["current"]
        wind_kt, gusts_kt = kmh_to_knots(c.get("wind_speed_10m")), kmh_to_knots(c.get("wind_gusts_10m"))
        feels = feels_like_temp(c.get("temperature_2m"), wind_kt)
        feels_str = f" (občutek {feels}°C)" if feels != c.get("temperature_2m") else ""
        
        directions = ["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW"]
        wdir = directions[int((c.get("wind_direction_10m", 0) + 11.25) / 22.5) % 16] if c.get("wind_direction_10m") is not None else "N"
        
        sea_temp = marine.get("current", {}).get("sea_surface_temperature", "N/A") if marine else "N/A"
        wave_val = marine.get("hourly", {}).get("wave_height", [None])[0] if marine else None
        waves = round(wave_val, 1) if wave_val is not None else "N/A"

        data = {"temp": c.get("temperature_2m"), "feels_like": feels_str, "humidity": c.get("relative_humidity_2m"), "precip": c.get("precipitation", 0), "uv": c.get("uv_index"), "sea_temp": sea_temp, "waves": waves, "wind_speed_kt": wind_kt, "wind_gusts_kt": gusts_kt, "wind_dir_str": wdir, "hour": now.hour, "day_period": "noč" if now.hour < 6 or now.hour >= 20 else "dan"}

        trenutni_t = TEXTS.get(izbran_jezik, TEXTS["sl"])

        st.markdown(f'<div class="update-time">⏱️ {trenutni_t["updated"]}: {now.strftime("%d.%m.%Y %H:%M")} | 🔄 {trenutni_t["next_refresh"]} {(now + timedelta(minutes=15)).strftime("%H:%M")}</div>', unsafe_allow_html=True)
        
        cols = st.columns(4)
        cols[0].markdown(f'<div class="metric-box"><div class="metric-label">{trenutni_t["temp_label"]}</div><div class="metric-value">{data["temp"]}°C{feels_str}</div></div><div class="metric-box"><div class="metric-label">{trenutni_t["humidity_label"]}</div><div class="metric-value">{data["humidity"]}%</div></div>', unsafe_allow_html=True)
        cols[1].markdown(f'<div class="metric-box"><div class="metric-label">{trenutni_t["precip_label"]}</div><div class="metric-value">{data["precip"]} mm</div></div><div class="metric-box"><div class="metric-label">{trenutni_t["uv_label"]}</div><div class="metric-value">{data["uv"]}</div></div>', unsafe_allow_html=True)
        cols[2].markdown(f'<div class="metric-box"><div class="metric-label">{trenutni_t["sea_temp_label"]}</div><div class="metric-value">{sea_temp}°C</div></div><div class="metric-box"><div class="metric-label">{trenutni_t["waves_label"]}</div><div class="metric-value">~{waves} m</div></div>', unsafe_allow_html=True)
        
        gust_text = f"<br><small>({trenutni_t['wind_gusts_prefix']} {gusts_kt} kt)</small>" if gusts_kt != "N/A" and gusts_kt > wind_kt + 2 else ""
        cols[3].markdown(f'<div class="metric-box"><div class="metric-label">{trenutni_t["wind_label"]}</div><div class="metric-value">{wind_kt} kt {wdir}{gust_text}</div></div>', unsafe_allow_html=True)
            
        alerts = []
        if gusts_kt != "N/A" and gusts_kt > 25: alerts.append(f"Močni sunki vetra ({gusts_kt} kt)")
        if waves != "N/A" and waves > 1.2: alerts.append(f"Visoki valovi ({waves} m)")
        
        if alerts: st.markdown(f'<div style="background:#fee2e2;padding:12px;border-radius:10px;text-align:center;font-weight:600;color:#991b1b;">⚠️ {" • ".join(alerts)}</div>', unsafe_allow_html=True)
        else: st.markdown(f'<div style="background:#dcfce7;padding:12px;border-radius:10px;text-align:center;font-weight:600;color:#166534;">✅ {trenutni_t["no_alert"]}</div>', unsafe_allow_html=True)
            
        with st.spinner("Kapitan razmišlja... 🌊"):
            st.markdown(f'<div class="forecast-box">🧭 <b>{trenutni_t["forecast_title"]}</b><br><br>{generate_forecast(data, izbran_jezik)}</div>', unsafe_allow_html=True)
    else: st.error("Napaka pri pridobivanju podatkov.")

# ST.EMPTY FRAGMENT
vsebnik_vreme = st.empty()
@st.fragment(run_every=900)
def prikazi_vreme_vsebnik(trenutni_jezik):
    with vsebnik_vreme.container(): 
        prikazi_vreme(trenutni_jezik)

prikazi_vreme_vsebnik(st.session_state.lang)