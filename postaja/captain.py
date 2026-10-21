"""Kapitanova AI napoved: admin nastavitve, klic ponudnika in urni predpomnilnik na disku."""
import asyncio
import hashlib
import json
import logging
import time
from collections import deque

from .i18n import text
from .settings import ADMIN_CONFIG_PATH, CACHE_DIR, GEMINI_API_KEY, OPENROUTER_API_KEY, http

log = logging.getLogger(__name__)

DEFAULT_PROVIDER = "OpenRouter"
DEFAULT_MODEL = "deepseek/deepseek-v4-flash"

MODEL_CHOICES = {
    "DeepSeek V4 Flash (hiter + poceni)": ("OpenRouter", "deepseek/deepseek-v4-flash"),
    "Grok 4.3 (zabaven kapetanski stil)": ("OpenRouter", "x-ai/grok-4.3"),
    "Gemini 2.5 Flash (odličen kompromis)": ("OpenRouter", "google/gemini-2.5-flash"),
    "Claude Sonnet 5.5 (najboljša kvaliteta pisanja)": ("OpenRouter", "anthropic/claude-sonnet-5.5"),
    "Gemini Flash (rezerva - direktno)": ("Gemini", "gemini-3.5-flash"),
}

DEFAULT_PROMPTS = {
    "sl": "Ti si izkušen, piratsko zafrkljiv, a prijazen morski kapitan iz kraja {loc}. Odgovarjaj izključno v slovenščini. Če opaziš, da so valovi 'N/A', to pomeni, da si na suhem, daleč od morja (npr. v Ljubljani). V tem primeru bodi duhovit, potoži, kako pogrešaš vonj po soli in valove, ter ljudem namesto plovbe svetuj kopenski sprehod!",
    "en": "You are an experienced, witty, and friendly sea captain from {loc}. Answer exclusively in English. If you notice waves are 'N/A', it means you are stranded on dry land, far from the sea. Be humorous about it, complain how much you miss the salty air, and suggest a nice walk on land instead of sailing!",
    "it": "Sei un capitano di mare esperto, ironico e amichevole di {loc}. Rispondi esclusivamente in italiano. Se noti che le onde sono 'N/A', significa che sei sulla terraferma, lontano dal mare. Sii spiritoso, lamentati di quanto ti manchi l'aria salmastra e consiglia una bella passeggiata sulla terraferma invece di navigare!",
    "de": "Du bist ein erfahrener, humorvoller und freundlicher Seekapitän aus {loc}. Antworte ausschließlich auf Deutsch. Wenn die Wellen 'N/A' sind, bedeutet das, dass du gestrandet bist, weit weg vom Meer. Sei humorvoll, beschwere dich, wie sehr du die Seeluft vermisst, und empfehle einen Landspaziergang statt Segeln!",
}

USER_TEMPLATES = {
    "sl": """Kraj: {loc}. Trenutno: {temp}°C, občutek {feels}°C, veter {wind} kt {wdir}, valovi: {waves} m, padavine {precip} mm, ura je {hour}:00 ({period}).

Napoved po urah:
{hourly}

Opozorila: {alerts}

Napiši zelo jedrnato, uporabno, kapitansko in prijazno napoved za naslednjih 12 ur, največ 120 besed. Opiraj se na urno napoved: če so v njej padavine, nevihte, močnejši veter ali visoki valovi, jih obvezno omeni in povej, kdaj se pričakujejo. Ne izmišljuj si pojavov, ki jih v podatkih ni.""",
    "en": """Location: {loc}. Currently: {temp}°C, feels like {feels}°C, wind {wind} kt {wdir}, waves: {waves} m, precipitation {precip} mm, time is {hour}:00 ({period}).

Hourly forecast:
{hourly}

Alerts: {alerts}

Write a very concise, useful, captain-style forecast for the next 12 hours, at most 120 words. Base it on the hourly forecast: if it contains rain, thunderstorms, stronger wind or high waves, you must mention them and say when to expect them. Do not invent weather that is not in the data.""",
    "it": """Località: {loc}. Attualmente: {temp}°C, percepita {feels}°C, vento {wind} kt {wdir}, onde: {waves} m, precipitazioni {precip} mm, sono le {hour}:00 ({period}).

Previsione oraria:
{hourly}

Allerte: {alerts}

Scrivi una breve e concisa previsione in stile capitano per le prossime 12 ore, al massimo 120 parole. Basati sulla previsione oraria: se contiene precipitazioni, temporali, vento più forte o onde alte, devi menzionarli e dire quando sono attesi. Non inventare fenomeni che non sono nei dati.""",
    "de": """Ort: {loc}. Aktuell: {temp}°C, gefühlt {feels}°C, Wind {wind} kt {wdir}, Wellen: {waves} m, Niederschlag {precip} mm, Uhrzeit {hour}:00 ({period}).

Stündliche Vorhersage:
{hourly}

Warnungen: {alerts}

Schreibe eine sehr kurze Wettervorhersage im Kapitänsstil für die nächsten 12 Stunden, höchstens 120 Wörter. Stütze dich auf die stündliche Vorhersage: Wenn sie Niederschlag, Gewitter, stärkeren Wind oder hohe Wellen enthält, musst du sie erwähnen und sagen, wann sie zu erwarten sind. Erfinde kein Wetter, das nicht in den Daten steht.""",
}
PROMPT_VERSION = 3  # ob spremembi pozivov povečaj, da se stare predpomnjene napovedi ne uporabijo

# Varnostna meja; odgovor brez razmišljanja ima običajno 150-300 žetonov.
MAX_TOKENS = 1500
ANSWER_TIMEOUT = 45  # sekund za celoten klic modela; pod nginx mejo 60 s, da napako sporoči aplikacija, ne 504

# Varovalka pred izčrpanjem AI kreditov: največ toliko novih generiranj na uro (vse lokacije skupaj).
MAX_GENERATIONS_PER_HOUR = 120
_generations: deque[float] = deque()
_locks: dict[str, asyncio.Lock] = {}


def load_admin_config() -> dict:
    cfg = {}
    if ADMIN_CONFIG_PATH.exists():
        try:
            cfg = json.loads(ADMIN_CONFIG_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "ai_provider": cfg.get("ai_provider", DEFAULT_PROVIDER),
        "model": cfg.get("model", DEFAULT_MODEL),
        "prompts": {**DEFAULT_PROMPTS, **cfg.get("prompts", {})},
    }


def save_admin_config(cfg: dict) -> None:
    ADMIN_CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=4), encoding="utf-8")


def _prune_cache(keep: str) -> None:
    for f in CACHE_DIR.glob("*.txt"):
        if f.name != keep and time.time() - f.stat().st_mtime > 3600:
            try:
                f.unlink()
            except OSError:
                pass


async def _ask_openrouter(model: str, system: str, user: str) -> str:
    resp = await http.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"},
        json={
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.75, "max_tokens": MAX_TOKENS,
            # Brez razmišljanja: z njim je DeepSeek V4 Flash oktobra 2026 odgovarjal 5-15 s, včasih več kot
            # 45 s, in pri približno vsakem petem klicu porabil vse žetone za razmišljanje (prazen odgovor).
            # Brez njega odgovori v nekaj sekundah. Modeli brez razmišljanja parameter prezrejo.
            "reasoning": {"enabled": False},
        },
    )
    resp.raise_for_status()
    choice = resp.json()["choices"][0]
    if choice.get("finish_reason") == "length":
        log.warning("Model %s je dosegel omejitev dolžine; odrezanega odgovora ne prikažemo", model)
        return ""
    return (choice["message"].get("content") or "").strip()


async def _ask_gemini(model: str, system: str, user: str) -> str:
    resp = await http.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={"x-goog-api-key": GEMINI_API_KEY},
        json={
            "contents": [{"parts": [{"text": user}]}],
            "systemInstruction": {"parts": [{"text": system}]},
            "generationConfig": {"temperature": 0.75, "maxOutputTokens": MAX_TOKENS},
        },
    )
    resp.raise_for_status()
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()


def _hourly_table(hours: list[dict]) -> str:
    """Naslednje ure v strnjeni obliki za poziv (oznake so angleške, model odgovori v jeziku poziva)."""
    lines = []
    for h in hours:
        line = (f"{h['time']} | {h['temp']}°C | wind {h['wind_kt']} kt, gusts {h['gusts_kt']} kt {h['dir']} | "
                f"precipitation {h['precip']} mm ({h['prob']}%) | {h['sky']}")
        if h["waves"] is not None:
            line += f" | waves {h['waves']} m"
        lines.append(line)
    return "\n".join(lines)


async def forecast_text(data: dict, alerts: list[str], loc: str, lat: float, lon: float, lang: str) -> str:
    """Vrne kapitanovo napoved za tekočo uro; generira jo največ enkrat na lokacijo/jezik/model."""
    cfg = load_admin_config()
    provider, model = cfg["ai_provider"], cfg["model"]
    api_key = OPENROUTER_API_KEY if provider == "OpenRouter" else GEMINI_API_KEY
    if not api_key:
        return text(lang, "captain_no_key")

    hour_key = data["time"][:13]  # lokalna ura lokacije, npr. 2026-10-02T14
    digest = hashlib.sha1(f"{PROMPT_VERSION}|{provider}|{model}|{loc}".encode()).hexdigest()[:10]
    name = f"{lat:.2f}_{lon:.2f}_{lang}_{hour_key}_{digest}.txt"
    path = CACHE_DIR / name

    async with _locks.setdefault(name, asyncio.Lock()):
        try:
            if path.exists():
                return path.read_text(encoding="utf-8")

            now = time.monotonic()
            while _generations and now - _generations[0] > 3600:
                _generations.popleft()
            if len(_generations) >= MAX_GENERATIONS_PER_HOUR:
                return text(lang, "captain_busy")
            _generations.append(now)

            system = cfg["prompts"].get(lang, DEFAULT_PROMPTS["sl"]).replace("{loc}", loc)
            user = USER_TEMPLATES.get(lang, USER_TEMPLATES["sl"]).format(
                loc=loc, temp=data["temp"], feels=data["feels"],
                wind=data["wind_kt"], wdir=data["wind_dir"],
                waves=data["waves"] if data["waves"] is not None else "N/A",
                precip=data["precip_hour"], hour=int(data["time"][11:13]),
                period=text(lang, "period_day" if data["is_day"] else "period_night"),
                hourly=_hourly_table(data["hours"]), alerts="; ".join(alerts) or "-",
            )
            ask = _ask_openrouter if provider == "OpenRouter" else _ask_gemini
            async with asyncio.timeout(ANSWER_TIMEOUT):
                txt = await ask(model, system, user)
            if not txt:
                raise ValueError("prazen odgovor modela")

            CACHE_DIR.mkdir(exist_ok=True)
            path.write_text(txt, encoding="utf-8")
            _prune_cache(keep=name)
            return txt
        except Exception:
            log.exception("Kapitanova napoved ni uspela (%s, %s)", provider, model)
            return text(lang, "captain_error")
        finally:
            _locks.pop(name, None)
