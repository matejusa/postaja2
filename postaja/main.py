"""Vremenska postaja – FastAPI aplikacija (zagon: uvicorn postaja.main:app)."""
import asyncio
import hmac
import logging
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote, unquote

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape
from starlette.middleware.sessions import SessionMiddleware

from . import captain, tides, weather
from .geocode import FALLBACK_LOCATIONS, search_location
from .i18n import DEFAULT_LANG, LANGS, TEXTS
from .settings import ADMIN_PASSWORD, GEMINI_API_KEY, HTTPS_ONLY, OPENROUTER_API_KEY, SECRET_KEY, VERSION, http

log = logging.getLogger(__name__)
BASE = Path(__file__).parent
COOKIE_MAX_AGE = 365 * 24 * 3600
# Pragovi opozoril; veljajo za trenutno stanje in naslednjih 12 ur.
GUST_ALERT_KT = 25
WAVE_ALERT_M = 1.2
RAIN_NOTE_MM = 0.5          # skupaj v 12 urah: rumeno obvestilo
HEAVY_RAIN_MM = 15          # skupaj v 12 urah: rdeče opozorilo
HEAVY_RAIN_HOURLY_MM = 5    # v eni uri: rdeče opozorilo


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await http.aclose()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, same_site="lax", max_age=8 * 3600, https_only=HTTPS_ONLY)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")


# ── Jinja filtri ──
def _rich(txt: str) -> Markup:
    """Kapitanovo besedilo: varno ubežano, z **krepko** in prelomi vrstic."""
    out = str(escape(txt))
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"^#+\s*", "", out, flags=re.M)
    return Markup(out.replace("\n", "<br>"))


def _stamp(iso: str) -> str:
    """2026-10-02T14:15 → 2.10.2026 14:15"""
    y, m, d = iso[:10].split("-")
    return f"{int(d)}.{int(m)}.{y} {iso[11:16]}"


def _temp_class(temp) -> str:
    if temp is None:
        return ""
    for limit, name in ((15, "t-cold"), (25, "t-mild"), (32, "t-warm"), (36, "t-hot")):
        if temp < limit:
            return name
    return "t-extreme"


def _deg(temp) -> str:
    return "—" if temp is None else f"{round(temp)}°"


templates.env.filters.update(rich=_rich, stamp=_stamp, temp_class=_temp_class, deg=_deg)
templates.env.globals["LANGS"] = LANGS
# Različica v naslovu statičnih datotek: po posodobitvi brskalniki ne uporabijo starih kopij iz predpomnilnika.
templates.env.globals["VERSION"] = VERSION


# ── Uporabnikove nastavitve živijo izključno v piškotkih ──
@dataclass
class Prefs:
    lang: str
    lat: float | None = None
    lon: float | None = None
    loc: str = ""

    @property
    def has_location(self) -> bool:
        return self.lat is not None


def get_prefs(request: Request) -> Prefs:
    c = request.cookies
    lang = c.get("lang") if c.get("lang") in LANGS else DEFAULT_LANG
    try:
        lat, lon = float(c["lat"]), float(c["lon"])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError
    except (KeyError, ValueError):
        return Prefs(lang)
    return Prefs(lang, lat, lon, unquote(c.get("loc", ""))[:80])


def set_cookie(response: Response, key: str, value: str) -> None:
    response.set_cookie(key, value, max_age=COOKIE_MAX_AGE, samesite="lax", httponly=True, secure=HTTPS_ONLY)


def render(request: Request, name: str, prefs: Prefs, **ctx) -> HTMLResponse:
    return templates.TemplateResponse(request, name, {"prefs": prefs, "t": TEXTS[prefs.lang], **ctx})


async def render_page(request: Request, name: str, prefs: Prefs, **ctx) -> HTMLResponse:
    """Cela stran z navigacijo: zavihek Plima se pokaže samo lokacijam z morskimi podatki."""
    has_tide = prefs.has_location and await tides.available(prefs.lat, prefs.lon)
    return render(request, name, prefs, has_tide=has_tide, **ctx)


def safe_next(target: str) -> str:
    if target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return "/"


def find_alerts(data: dict, t: dict) -> tuple[str, list[str]]:
    """Vrne raven ("warn", "note" ali "ok") in besedila opozoril za zdaj in naslednjih 12 ur."""
    o = data["outlook"]

    def when(at: str, word: str = "around") -> str:
        return t["now"] if at == "now" else f"{t[word]} {at}"

    severe, notes = [], []
    if o["storm_from"]:
        severe.append(f"{t['alert_storm']} ({when(o['storm_from'], 'from')})")
    if o["gust"] is not None and o["gust"] > GUST_ALERT_KT:
        severe.append(f"{t['alert_gusts']} {t['up_to']} {round(o['gust'])} kt ({when(o['gust_at'])})")
    if o["wave"] is not None and o["wave"] > WAVE_ALERT_M:
        severe.append(f"{t['alert_waves']} {t['up_to']} {round(o['wave'], 1)} m ({when(o['wave_at'])})")
    if o["rain_total"] >= RAIN_NOTE_MM and o["rain_from"]:
        heavy = o["rain_total"] >= HEAVY_RAIN_MM or o["rain_peak"] >= HEAVY_RAIN_HOURLY_MM
        text = (f"{t['alert_heavy_rain' if heavy else 'alert_rain']} {when(o['rain_from'], 'from')}, "
                f"{t['total']} {o['rain_total']} mm {t['next_12h']}")
        (severe if heavy else notes).append(text)
    return ("warn" if severe else "note" if notes else "ok"), severe + notes


async def current_context(prefs: Prefs) -> dict:
    try:
        data = await weather.current(prefs.lat, prefs.lon)
    except Exception:
        log.exception("Open-Meteo (trenutno) ni dosegljiv")
        return {"data": None}
    level, alerts = find_alerts(data, TEXTS[prefs.lang])
    return {"data": data, "level": level, "alerts": alerts}


# ── Strani ──
@app.api_route("/health", methods=["GET", "HEAD"])
async def health():
    return {"status": "ok", "version": VERSION}


@app.api_route("/", methods=["GET", "HEAD"])
async def index(request: Request):
    return RedirectResponse("/trenutno" if get_prefs(request).has_location else "/lokacija", 303)


async def location_context(q: str, lang: str) -> dict:
    q = q.strip()
    searched = len(q) >= 3
    results = await search_location(q, lang) if searched else []
    return {"q": q, "searched": searched, "results": results, "suggestions": FALLBACK_LOCATIONS}


@app.get("/lokacija")
async def location_page(request: Request, q: str = ""):
    prefs = get_prefs(request)
    return await render_page(request, "lokacija.html", prefs, **await location_context(q, prefs.lang))


@app.get("/partials/lokacije")
async def location_partial(request: Request, q: str = ""):
    """Zadetki med tipkanjem (klic iz app.js)."""
    prefs = get_prefs(request)
    return render(request, "_lokacije.html", prefs, **await location_context(q, prefs.lang))


@app.post("/lokacija")
async def location_set(lat: float = Form(...), lon: float = Form(...), display: str = Form(...)):
    response = RedirectResponse("/trenutno", 303)
    set_cookie(response, "lat", str(lat))
    set_cookie(response, "lon", str(lon))
    set_cookie(response, "loc", quote(display[:80]))
    return response


@app.post("/jezik")
async def language_set(lang: str = Form(...), next: str = Form("/")):
    response = RedirectResponse(safe_next(next), 303)
    if lang in LANGS:
        set_cookie(response, "lang", lang)
    return response


@app.get("/trenutno")
async def current_page(request: Request):
    prefs = get_prefs(request)
    if not prefs.has_location:
        return RedirectResponse("/lokacija", 303)
    return await render_page(request, "trenutno.html", prefs, **await current_context(prefs))


@app.get("/partials/trenutno")
async def current_partial(request: Request):
    prefs = get_prefs(request)
    if not prefs.has_location:
        return Response(status_code=403)
    return render(request, "_trenutno.html", prefs, **await current_context(prefs))


@app.get("/partials/kapitan")
async def captain_partial(request: Request):
    prefs = get_prefs(request)
    if not prefs.has_location:
        return Response(status_code=403)
    try:
        data = await weather.current(prefs.lat, prefs.lon)
    except Exception:
        return Response(status_code=502)
    _, alerts = find_alerts(data, TEXTS[prefs.lang])
    txt = await captain.forecast_text(data, alerts, prefs.loc, prefs.lat, prefs.lon, prefs.lang)
    return render(request, "_kapitan.html", prefs, forecast=txt)


@app.get("/napoved")
async def forecast_page(request: Request):
    prefs = get_prefs(request)
    if not prefs.has_location:
        return RedirectResponse("/lokacija", 303)
    try:
        data = await weather.forecast(prefs.lat, prefs.lon)
    except Exception:
        log.exception("Open-Meteo (napoved) ni dosegljiv")
        return await render_page(request, "napoved.html", prefs, days=None)
    t = TEXTS[prefs.lang]
    chart = {
        "points": data["points"],
        "days": [{"name": t["days"][d["weekday"]], "date": d["label"]} for d in data["days"]],
    }
    return await render_page(request, "napoved.html", prefs, days=data["days"], chart=chart)


@app.get("/plima")
async def tide_page(request: Request):
    prefs = get_prefs(request)
    if not prefs.has_location:
        return RedirectResponse("/lokacija", 303)
    try:
        tide = await tides.chart(prefs.lat, prefs.lon)
    except Exception:
        log.exception("Open-Meteo (gladina morja) ni dosegljiv")
        tide = None
    if tide:
        t = TEXTS[prefs.lang]
        first = date.fromisoformat(tide["start"])
        dates = [first + timedelta(days=i) for i in range(tides.DAYS)]
        tide = {**tide, "days": [{"name": t["days"][d.weekday()], "date": f"{d.day}.{d.month}."} for d in dates], "t": {
            "level": t["tide_level"], "astro": t["tide_astro"], "dev": t["tide_dev"],
            "jugo": t["tide_jugo"], "burja": t["tide_burja"], "moons": t["tide_moons"], "now": t["now"]}}
    return await render_page(request, "plima.html", prefs, tide=tide)


@app.get("/sidro")
async def anchor_page(request: Request):
    """Straža sidra teče v celoti v brskalniku (static/sidro.js); strežnik da samo stran in prevode."""
    prefs = get_prefs(request)
    if not prefs.has_location:
        return RedirectResponse("/lokacija", 303)
    texts = {key[len("anchor_"):]: value for key, value in TEXTS[prefs.lang].items() if key.startswith("anchor_")}
    return await render_page(request, "sidro.html", prefs, texts=texts)


# ── Admin ──
def is_admin(request: Request) -> bool:
    return bool(ADMIN_PASSWORD) and request.session.get("admin") is True


@app.get("/admin")
async def admin_page(request: Request):
    prefs = get_prefs(request)
    if not is_admin(request):
        return await render_page(request, "admin_login.html", prefs, enabled=bool(ADMIN_PASSWORD),
                      flash=request.session.pop("flash", None))
    cfg = captain.load_admin_config()
    current = next((label for label, choice in captain.MODEL_CHOICES.items()
                    if choice == (cfg["ai_provider"], cfg["model"])), None)
    return await render_page(request, "admin.html", prefs, cfg=cfg, choices=captain.MODEL_CHOICES, current=current,
                  flash=request.session.pop("flash", None))


@app.post("/admin/login")
async def admin_login(request: Request, password: str = Form(...)):
    if ADMIN_PASSWORD and hmac.compare_digest(password.encode(), ADMIN_PASSWORD.encode()):
        request.session["admin"] = True
    else:
        await asyncio.sleep(1)
        request.session["flash"] = "❌ Napačno geslo!"
    return RedirectResponse("/admin", 303)


@app.post("/admin/logout")
async def admin_logout(request: Request):
    request.session.clear()
    return RedirectResponse("/admin", 303)


@app.post("/admin/save")
async def admin_save(request: Request):
    if not is_admin(request):
        return RedirectResponse("/admin", 303)
    form = await request.form()
    cfg = captain.load_admin_config()
    if form.get("choice") in captain.MODEL_CHOICES:
        cfg["ai_provider"], cfg["model"] = captain.MODEL_CHOICES[form["choice"]]
    for code in LANGS:
        prompt = str(form.get(f"prompt_{code}", "")).strip()
        if prompt:
            cfg["prompts"][code] = prompt
    captain.save_admin_config(cfg)
    request.session["flash"] = "✅ Nastavitve so shranjene."
    return RedirectResponse("/admin", 303)


@app.post("/admin/test")
async def admin_test(request: Request, what: str = Form(...)):
    if not is_admin(request):
        return RedirectResponse("/admin", 303)
    if what == "meteo":
        name, url, headers = "Open-Meteo", "https://api.open-meteo.com/v1/forecast?latitude=46.0569&longitude=14.5058&current=temperature_2m", {}
    elif captain.load_admin_config()["ai_provider"] == "OpenRouter":
        name, url, headers = "OpenRouter", "https://openrouter.ai/api/v1/key", {"Authorization": f"Bearer {OPENROUTER_API_KEY}"}
        if not OPENROUTER_API_KEY:
            url = ""
    else:
        name, url, headers = "Gemini", "https://generativelanguage.googleapis.com/v1beta/models", {"x-goog-api-key": GEMINI_API_KEY}
        if not GEMINI_API_KEY:
            url = ""
    if not url:
        request.session["flash"] = f"⚠️ {name}: API ključ ni nastavljen v .env!"
    else:
        try:
            resp = await http.get(url, headers=headers, timeout=5)
            ok = resp.status_code == 200
            request.session["flash"] = (f"✅ {name} deluje ({resp.elapsed.total_seconds():.2f} s)" if ok
                                        else f"❌ {name}: status {resp.status_code}")
        except Exception as e:
            request.session["flash"] = f"❌ {name}: ni povezave ({type(e).__name__})"
    return RedirectResponse("/admin", 303)
