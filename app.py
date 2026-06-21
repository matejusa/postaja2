import streamlit as st
from config import load_config, save_config, search_location, get_fallback_locations

# ── ČE LOKACIJA ŽE OBSTAJA → PRESKOČI ONBOARDING ──
cfg = load_config()
if cfg.get("lat") is not None and cfg.get("lon") is not None:
    st.switch_page("pages/1_Trenutno.py")

st.set_page_config(
    page_title="Vremenska postaja",
    layout="wide",
    page_icon="🌊"
)

# ── Slovar prevodov ──
L = {
    "sl": {
        "title": "🌊 Vremenska postaja",
        "label_lokacija": "1. 📍 Vnesi lokacijo",
        "label_potrdi": "2. ✅ Potrdi",
        "label_izberi": "3. 📍 Izberi lokacijo",
        "btn_potrdi": "Potrdi",
        "btn_spremeni": "✏️ Spremeni",
        "placeholder": "npr. Izola, Piran, Portorož...",
        "caption": "💡 Vnesite lokacijo in pritisnite Potrdi",
        "searching_for": "Iskanje:",
    },
    "en": {
        "title": "🌊 Weather Station",
        "label_lokacija": "1. 📍 Enter location",
        "label_potrdi": "2. ✅ Confirm",
        "label_izberi": "3. 📍 Select location",
        "btn_potrdi": "Confirm",
        "btn_spremeni": "✏️ Change",
        "placeholder": "e.g. Izola, Piran, Portorož...",
        "caption": "💡 Enter a location and press Confirm",
        "searching_for": "Searching for:",
    },
    "it": {
        "title": "🌊 Stazione Meteo",
        "label_lokacija": "1. 📍 Inserisci località",
        "label_potrdi": "2. ✅ Conferma",
        "label_izberi": "3. 📍 Seleziona località",
        "btn_potrdi": "Conferma",
        "btn_spremeni": "✏️ Cambia",
        "placeholder": "es. Izola, Piran, Portorož...",
        "caption": "💡 Inserisci località e premi Conferma",
        "searching_for": "Ricerca:",
    },
    "de": {
        "title": "🌊 Wetterstation",
        "label_lokacija": "1. 📍 Ort eingeben",
        "label_potrdi": "2. ✅ Bestätigen",
        "label_izberi": "3. 📍 Ort auswählen",
        "btn_potrdi": "Bestätigen",
        "btn_spremeni": "✏️ Ändern",
        "placeholder": "z.B. Izola, Piran, Portorož...",
        "caption": "💡 Ort eingeben und Bestätigen drücken",
        "searching_for": "Suche nach:",
    },
}

# Inicializacija stanja
if "confirmed_results" not in st.session_state:
    st.session_state.confirmed_results = []
    st.session_state.confirmed_search_query = ""
if "lang_selected" not in st.session_state:
    st.session_state.lang_selected = "sl"
    st.session_state.lang = "sl"

lang = st.session_state.lang_selected
T = L.get(lang, L["sl"])

# Stil po meri (Nove barve in +50% večji font)
st.markdown("""
<style>
    [data-testid="stSidebarNav"] { display: none; }
    .main > div { padding-top: 0 !important; }
    .block-container { padding-top: 2rem !important; padding-bottom: 0.5rem !important; }
    .onboarding-box {
        max-width: 340px; margin: 0 auto; padding: 0 10px;
        text-align: center;
    }
    .onboarding-title {
        font-size: 28px !important; font-weight: bold; margin: 0 0 14px 0;
    }
    .section-label {
        font-size: 17px !important; font-weight: 700; color: #333;
        margin-bottom: 8px;
    }
    .lang-row {
        max-width: 340px; margin: 0 auto 12px auto;
    }
    .stCaption {
        font-size: 18px !important; color: #666;
    }

    /* ── NOVE VELIKOSTI GUMBOV (50% večji font in višji gumbi) ── */
    .stButton button[kind="primary"],
    .stButton button[kind="secondary"] {
        font-size: 32px !important;      /* Masiven, jasno berljiv font */
        font-weight: 700 !important;
        height: 72px !important;         /* Povišano, da font ne gleda ven */
        border-radius: 14px !important;
        padding: 4px 10px !important;
    }
    div[data-testid="stTextInput"] input {
        font-size: 27px !important;
        padding: 16px 18px !important;
        min-height: 58px !important;
    }
    .results-heading {
        font-size: 20px !important; font-weight: 700; color: #1E4620;
        margin: 4px 0 12px 0;
    }

    /* Izjema za majhen servisni gumb "Spremeni" */
    div[data-testid="stHorizontalBlock"] button {
        font-size: 16px !important;
        height: 38px !important;
        padding: 0 10px !important;
        border-radius: 8px !important;
    }

    /* ── NOVE BARVE (Premium Sage Green + Črn/Temen font) ── */
    /* Primarni gumb (Potrdi, Prva lokacija) */
    .stButton button[kind="primary"] {
        background-color: #A9DFBF !important; /* Nežna pastelno zelena */
        border-color: #92d5aa !important;
        color: #0B2512 !important;            /* Globoka, skoraj črna gozdna barva */
    }
    .stButton button[kind="primary"]:hover {
        background-color: #95d5ac !important; /* Malo temnejša ob lebdenju */
        border-color: #7ecb97 !important;
        color: #0B2512 !important;
    }
    
    /* Sekundarni gumbi (Jeziki, ostale lokacije) */
    .stButton button[kind="secondary"] {
        background-color: #F4F9F5 !important; /* Zelo nežno zelenkasto ozadje */
        border-color: #CBDED1 !important;
        color: #1E4620 !important;            /* Temno zelena za odličen kontrast */
    }
    .stButton button[kind="secondary"]:hover {
        background-color: #E8F3EC !important;
        border-color: #A9DFBF !important;
        color: #0B2512 !important;
    }
</style>
""", unsafe_allow_html=True)

# Ogrodje aplikacije
st.markdown('<div class="onboarding-box">', unsafe_allow_html=True)
st.markdown(f'<div class="onboarding-title">{T["title"]}</div>', unsafe_allow_html=True)

# ── LOGIKA PRIKAZA: Če rezultati ŠE NISO potrjeni ──
if not st.session_state.confirmed_results:

    # ── 1. Izberi jezik ──
    st.markdown('<div class="lang-row">', unsafe_allow_html=True)
    langs = [
        ("sl", "🇸🇮 Slovenščina"),
        ("en", "🇬🇧 English"),
        ("it", "🇮🇹 Italiano"),
        ("de", "🇩🇪 Deutsch"),
    ]
    col1, col2 = st.columns(2)
    for col, (code, label) in zip([col1, col2], langs[:2]):
        with col:
            is_sel = st.session_state.lang_selected == code
            if st.button(label, key=f"lang_{code}", use_container_width=True, type="primary" if is_sel else "secondary"):
                st.session_state.lang_selected = code
                st.session_state.lang = code
                st.rerun()

    col1, col2 = st.columns(2)
    for col, (code, label) in zip([col1, col2], langs[2:]):
        with col:
            is_sel = st.session_state.lang_selected == code
            if st.button(label, key=f"lang_{code}", use_container_width=True, type="primary" if is_sel else "secondary"):
                st.session_state.lang_selected = code
                st.session_state.lang = code
                st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

    # ── 2. Vnesi lokacijo ──
    st.markdown(f'<div class="section-label">{T["label_lokacija"]}</div>', unsafe_allow_html=True)
    search_query = st.text_input(
        "",
        placeholder=T["placeholder"],
        key="onboarding_search",
        label_visibility="collapsed",
    )
    st.markdown('<div style="height:4px;"></div>', unsafe_allow_html=True)

    # ── 3. Potrdi ──
    st.markdown(f'<div class="section-label">{T["label_potrdi"]}</div>', unsafe_allow_html=True)
    confirmed = st.button(T["btn_potrdi"], key="confirm_search", use_container_width=True, type="primary")

    if confirmed:
        if search_query and len(search_query.strip()) >= 3:
            results = search_location(search_query)
            if not results:
                results = get_fallback_locations()
            st.session_state.confirmed_results = results
            st.session_state.confirmed_search_query = search_query
            st.rerun()
        else:
            st.session_state.confirmed_results = []
            st.session_state.confirmed_search_query = ""
            
    st.markdown('<div style="text-align:center; max-width:340px; margin:0 auto;">', unsafe_allow_html=True)
    st.caption(T["caption"])
    st.markdown('</div>', unsafe_allow_html=True)

# ── LOGIKA PRIKAZA: Če SO rezultati že potrjeni ──
else:
    col_txt, col_btn = st.columns([2, 1])
    with col_txt:
        st.markdown(
            f'<div style="line-height:38px; font-size:16px; text-align:left; color:#333;">'
            f'{T["searching_for"]} <b>"{st.session_state.confirmed_search_query}"</b>'
            f'</div>', 
            unsafe_allow_html=True
        )
    with col_btn:
        if st.button(T["btn_spremeni"], key="reset_search", use_container_width=True, type="secondary"):
            st.session_state.confirmed_results = []
            st.session_state.confirmed_search_query = ""
            st.rerun()

    st.markdown('<hr style="margin: 8px 0 16px 0; border:0; border-top:1px solid #ddd;">', unsafe_allow_html=True)

    # ── 4. Rezultati na samem vrhu zaslona ──
    st.markdown(f'<div class="results-heading">{T["label_izberi"]}</div>', unsafe_allow_html=True)
    
    for idx, loc in enumerate(st.session_state.confirmed_results):
        if st.button(loc["display"], key=f"onb_loc_btn_{idx}", use_container_width=True, type="primary" if idx == 0 else "secondary"):
            save_config(loc["lat"], loc["lon"], loc["display"], st.session_state.lang_selected)
            st.session_state.lang = st.session_state.lang_selected
            st.switch_page("pages/1_Trenutno.py")

st.markdown('</div>', unsafe_allow_html=True)