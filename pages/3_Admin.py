import streamlit as st
import json
import requests
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Skrijemo stranski meni
st.markdown("""
<style>
    [data-testid="stSidebarNav"] { display: none; }
    .block-container { padding-top: 2rem !important; }
</style>
""", unsafe_allow_html=True)

# 1. NASTAVITEV GESLA
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "Kapetan2026")
CONFIG_PATH = Path("admin_config.json")

# Privzeti prompti
DEFAULT_PROMPTS = {
    "sl": "Ti si izkušen, piratsko zafrkljiv, a prijazen morski kapitan iz kraja {loc}. Odgovarjaj izključno v slovenščini. Če opaziš, da so valovi 'N/A', to pomeni, da si na suhem, daleč od morja (npr. v Ljubljani). V tem primeru bodi duhovit, potoži, kako pogrešaš vonj po soli in valove, ter ljudem namesto plovbe svetuj kopenski sprehod!",
    "en": "You are an experienced, witty, and friendly sea captain from {loc}. Answer exclusively in English. If you notice waves are 'N/A', it means you are stranded on dry land, far from the sea. Be humorous about it, complain how much you miss the salty air, and suggest a nice walk on land instead of sailing!",
    "it": "Sei un capitano di mare esperto, ironico e amichevole di {loc}. Rispondi exclusively in italiano. Se noti che le onde so 'N/A', significa che sei sulla terraferma, lontano od mare. Sii spiritoso, lamentati di quanto ti manchi l'aria salmastra e consiglia eno bella passeggiata sulla terraferma invece do navigare!",
    "de": "Du bist ein erfahrener, humorvoller und freundlicher Seekapitän aus {loc}. Antworte ausschließlich auf Deutsch. Wenn die Wellen 'N/A' sind, bedeutet das, da si gestrandet bist, weit weg vom Meer. Sei humorvoll, beschwe re dich, kako sehr du die Seuluft vermisst, und empfehle jeden Landspaziergang statt Segeln!"
}

def load_admin_config():
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {"ai_provider": "OpenRouter", "model": "deepseek/deepseek-v4-flash", "prompts": DEFAULT_PROMPTS}

def save_admin_config(config_data):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config_data, f, ensure_ascii=False, indent=4)

# Inicializacija
if "admin_authenticated" not in st.session_state:
    st.session_state.admin_authenticated = False

if not st.session_state.admin_authenticated:
    st.title("🔒 Vstop zaklenjen")
    geslo = st.text_input("Vnesi admin geslo:", type="password")
    if st.button("Prijava"):
        if geslo == ADMIN_PASSWORD:
            st.session_state.admin_authenticated = True
            st.success("Uspešno prijavljen!")
            st.rerun()
        else:
            st.error("Napačno geslo!")
    st.stop()

admin_cfg = load_admin_config()

st.title("⚓ Admin Konzola - Nadzorna plošča")

if st.button("🚪 Odjava"):
    st.session_state.admin_authenticated = False
    st.rerun()

st.markdown("---")

# ─── SECTION 1: IZBIRA AI MODELA ───
st.header("🤖 Izbira AI Modela za Kapetana")

MODEL_CHOICES = {
    "DeepSeek V4 Flash (hiter + poceni)": ("OpenRouter", "deepseek/deepseek-v4-flash"),
    "Grok 4.3 (zabaven kapetanski stil)": ("OpenRouter", "x-ai/grok-4.3"),
    "Gemini 2.5 Flash (odličen kompromis)": ("OpenRouter", "google/gemini-2.5-flash"),
    "Claude 4 Sonnet (najboljša kvaliteta pisanja)": ("OpenRouter", "anthropic/claude-4-sonnet"),
    "Gemini Flash (rezerva - direktno)": ("Gemini", "gemini-2.0-flash"),
}

trenutni_provider = admin_cfg.get("ai_provider", "OpenRouter")
trenutni_model = admin_cfg.get("model", "deepseek/deepseek-v4-flash")

current_label = next(
    (label for label, (prov, mod) in MODEL_CHOICES.items() 
     if prov == trenutni_provider and mod == trenutni_model),
    list(MODEL_CHOICES.keys())[0]
)

izbran_model = st.selectbox(
    "Izberi model:",
    options=list(MODEL_CHOICES.keys()),
    index=list(MODEL_CHOICES.keys()).index(current_label),
    help="Grok 4.3 je trenutno zelo primeren za kapetana (zabaven in duhovit)."
)

ai_provider, model_id = MODEL_CHOICES[izbran_model]

st.markdown("---")

# ─── SECTION 2: UREJANJE PROMPTOV ───
st.header("📝 Urejanje Kapetanovih promptov")
st.caption("Urejaš lahko 'System prompt', ki določa osebnost in obnašanje Kapetana.")

novi_prompts = {}
jeziki = {"sl": "🇸🇮 Slovenščina", "en": "🇬🇧 English", "it": "🇮🇹 Italiano", "de": "🇩🇪 Deutsch"}

for kod, ime in jeziki.items():
    trenutni_prompt = admin_cfg.get("prompts", {}).get(kod, DEFAULT_PROMPTS[kod])
    novi_prompts[kod] = st.text_area(f"Prompt za: {ime}", value=trenutni_prompt, height=100, key=f"prompt_{kod}")

st.markdown("<br>", unsafe_allow_html=True)

# GUMB ZA SHRANJEVANJE
if st.button("💾 Shrani vse nastavitve", type="primary", use_container_width=True):
    admin_cfg["ai_provider"] = ai_provider
    admin_cfg["model"] = model_id
    admin_cfg["prompts"] = novi_prompts
    save_admin_config(admin_cfg)
    st.success("✅ Nastavitve so uspešno shranjene v admin_config.json!")

st.markdown("---")

# ─── SECTION 3: TEST POVEZAV ───
st.header("🔌 Stanje API povezav")
col1, col2 = st.columns(2)

with col1:
    if st.button("Testiraj Open-Meteo", use_container_width=True):
        try:
            res = requests.get("https://api.open-meteo.com/v1/forecast?latitude=46.0569&longitude=14.5058&current_weather=true", timeout=5)
            if res.status_code == 200: 
                st.success(f"✅ Open-Meteo deluje! ({res.elapsed.total_seconds()}s)")
            else: 
                st.error(f"❌ Napaka: Status {res.status_code}")
        except Exception as e: 
            st.error(f"❌ Ni povezave: {str(e)}")

with col2:
    if st.button("Testiraj Trenutni AI Ponudnik", use_container_width=True):
        if ai_provider == "OpenRouter":
            api_key = os.getenv("OPENROUTER_API_KEY") or st.secrets.get("OPENROUTER_API_KEY")
            url = "https://openrouter.ai/api/v1/models"
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        else:
            api_key = os.getenv("GEMINI_API_KEY") or st.secrets.get("GEMINI_API_KEY")
            url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}" if api_key else ""
            headers = {}
            
        if not api_key or not url:
            st.warning("⚠️ API ključ za izbrani model ni nastavljen v .env!")
        else:
            try:
                res = requests.get(url, headers=headers, timeout=5)
                if res.status_code == 200: 
                    st.success("✅ Izbrani AI ponudnik se odziva pravilno!")
                else: 
                    st.error(f"❌ Napaka: Status {res.status_code}")
            except Exception as e: 
                st.error(f"❌ Napaka pri povezavi: {str(e)}")

st.markdown("<br>", unsafe_allow_html=True)

if st.button("⬅️ Nazaj na trenutno vreme", use_container_width=True):
    st.switch_page("pages/1_Trenutno.py")