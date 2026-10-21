# Vremenska postaja (FastAPI) – podatki za namestitev na Neoserv

Različica: **2026.10.21** · paket: `postaja-2026.10.21.tar.gz` (SHA-256 je v datoteki `.sha256` ob paketu)

Prvi del odgovarja na osem vprašanj seje za strežnik, drugi del so predlagani koraki.

## Odgovori

### 1. Koda

- Dostava je **tar paket**, ne git. Paket vsebuje samo mapo `postaja/` (Python koda, predloge, statika, ta navodila). Na strežniku ni `git clone`, `pull`, `reset` ali `checkout`.
- Koda je v gitu (veja `main`), na strežnik pa gre kot paket; istovetnost paketa zagotavlja SHA-256.
- Vsebina: popolna zamenjava Streamlit aplikacije. Tri strani (`/trenutno`, `/napoved`, `/lokacija`), admin konzola (`/admin`), kapitanova AI napoved, graf brez zunanjih knjižnic.
- Zrelost: lastnik je aplikacijo preizkusil lokalno (Windows, Python 3.14). Na Pythonu 3.12 ni bila zagnana; preverjena je le skladnja. Prvi pravi preizkus na 3.12 je korak 5 spodaj.
- Primerjava s stanjem strežnika (varnostna kopija 3. 10. 2026): razlike med strežnikom in GitHubom so obvoznice za piškotke (`time.sleep`, `set_cookies_on_arrival`, `return_page`, `peskovnik.py`), prevodi imen držav pri iskanju in `.streamlit/config.toml`. Nova aplikacija obvoznic ne potrebuje; vrnitev na isto stran po menjavi jezika in prevedena imena držav ima vgrajena. Iz starih datotek se ne prenaša nič kode.

### 2. Zagon

```
/var/www/vreme.vzemi.si/venv-postaja/bin/uvicorn postaja.main:app --host 127.0.0.1 --port 8503
```

- delovna mapa: `/var/www/vreme.vzemi.si` (starš mape `postaja/`)
- **1 worker** (obvezno: predpomnilnik in omejitev AI klicev sta v pomnilniku procesa)
- vrata 8503 so predlog; ustreza katerakoli prosta
- systemd enota je priložena: `postaja/deploy/postaja.service`

### 3. Odvisnosti

- `postaja/requirements.txt`: 22 paketov, vsi pripeti z `==`, vključno s posrednimi.
- Preverjeno s `pip install --dry-run --only-binary=:all:` za `manylinux2014_x86_64`, CPython 3.12: za vse obstajajo wheel paketi, **prevajanja ni**. Prevedena sta samo `pydantic-core` in `markupsafe`, oba z gotovim wheelom za cp312. Predpostavka: strežnik je x86_64.
- Varovalka pri namestitvi: `pip install --only-binary=:all: -r postaja/requirements.txt` (raje odpove, kot da bi prevajal).
- Node in frontend build nista potrebna. Statika (`style.css`, `app.js`, `chart.js`) je ročno napisana in v paketu.

### 4. Konfiguracija in skrivnosti

Bere se `/var/www/vreme.vzemi.si/.env` (z `python-dotenv`; `EnvironmentFile` v systemd ni potreben).

| Spremenljivka | Potrebna | Pomen |
|---|---|---|
| `OPENROUTER_API_KEY` | da (že obstaja) | kapitanova napoved prek OpenRouter |
| `GEMINI_API_KEY` | ne (že obstaja) | samo če se v adminu izbere neposredni Gemini |
| `ADMIN_PASSWORD` | da, **nova** | geslo za `/admin`; brez nje je admin onemogočen |
| `SECRET_KEY` | da, **nova** | podpis admin seje; naključen niz |
| `HTTPS_ONLY` | da, **nova**, vrednost `1` | piškotki z oznako `Secure` |

- Privzetega ali trdo kodiranega gesla ni. Geslo izbere in vpiše lastnik; staro privzeto geslo naj se ne uporabi ponovno, ker je v git zgodovini.
- Brez AI ključev aplikacija deluje, kapitan pa izpiše, da ključev nima.
- `st.secrets` / `secrets.toml` se ne uporablja.

### 5. Podatki in stanje

- Baze ni. Uporabnikove nastavitve (lokacija, jezik) so v piškotkih brskalnika; imena piškotkov so enaka kot pri Streamlitu.
- `admin_config.json` (model in kapitanovi prompti): aplikacija ga **bere in piše** v `/var/www/vreme.vzemi.si/admin_config.json`. Obstoječa datoteka na strežniku ostane in velja naprej; iz paketa se ne prepiše.
- `.forecast_cache/`: aplikacija jo sama ustvari v `/var/www/vreme.vzemi.si/` in vanjo piše majhne besedilne datoteke (kapitanove napovedi), starejše od ene ure sproti briše.
- Pravice: `www-data` mora smeti pisati v `admin_config.json` in ustvariti `.forecast_cache/`.
- `config.json` se ne uporablja več in se ne prenaša.

### 6. Zdravje

```bash
curl -s http://127.0.0.1:8503/health
```

Pričakovano: `{"status":"ok","version":"2026.10.21"}`. Pot ne kliče zunanjih storitev. Polnejši preizkus je v koraku 5.

### 7. Zamenjava

Strinjam se s predlogom: nova aplikacija najprej na svojih vratih, dokazljivo delujoča; nato preklop v nginx; stari Streamlit se po uspešnem preklopu **ustavi** in ostane nameščen kot vrnitev.

### 8. Pomnilnik

- Izmerjeno lokalno po več zahtevah: okoli 70 MB na proces.
- Ocena za strežnik: 60–100 MB. Predpomnilnik je omejen na 2000 vnosov, zato ne raste brez meje.
- Obremenitev je vhodno-izhodna (klici Open-Meteo in AI ponudnika); večjega računanja ali gradnje ni. Presežek 1 GB zaradi te aplikacije ni pričakovan.
- Med vzporednim delovanjem obeh aplikacij (koraki 4–6) je poraba za ta čas večja za omenjenih 60–100 MB.

## Predlagani koraki

### 1. Prenos in razpakiranje

Paket in `.sha256` se preneseta v `/tmp` na strežniku, nato:

```bash
cd /tmp && sha256sum -c postaja-2026.10.21.tar.gz.sha256
sudo tar -xzf /tmp/postaja-2026.10.21.tar.gz -C /var/www/vreme.vzemi.si
sudo chown -R www-data:www-data /var/www/vreme.vzemi.si/postaja
```

### 2. Ločeno Python okolje

```bash
cd /var/www/vreme.vzemi.si
sudo -u www-data python3 -m venv venv-postaja
sudo -u www-data venv-postaja/bin/pip install --only-binary=:all: -r postaja/requirements.txt
```

### 3. `.env` in pravice

V `.env` se dodajo `ADMIN_PASSWORD`, `SECRET_KEY`, `HTTPS_ONLY=1` (glej točko 4). Naključen niz:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Preverjanje pravic (oba ukaza morata izpisati `OK`):

```bash
sudo -u www-data test -w /var/www/vreme.vzemi.si && echo OK
sudo -u www-data test -w /var/www/vreme.vzemi.si/admin_config.json && echo OK
```

### 4. Storitev

```bash
ss -ltn | grep ':8503 '
```

Ukaz ne sme izpisati ničesar (vrata prosta). Nato:

```bash
sudo cp /var/www/vreme.vzemi.si/postaja/deploy/postaja.service /etc/systemd/system/postaja.service
sudo systemctl daemon-reload
sudo systemctl enable --now postaja.service
systemctl status postaja.service --no-pager
```

### 5. Preizkus pred preklopom

```bash
curl -s http://127.0.0.1:8503/health
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8503/lokacija
curl -s -b "lat=45.536; lon=13.66; loc=Izola" http://127.0.0.1:8503/partials/trenutno | grep -c metric-value
curl -s -m 90 -b "lat=45.536; lon=13.66; loc=Izola" http://127.0.0.1:8503/partials/kapitan
```

Pričakovano: zdravje `ok`, `200`, število `7`, kapitanovo besedilo (traja 5–10 s). Ob težavah:

```bash
journalctl -u postaja.service -n 50 --no-pager
```

### 6. Preklop v nginx

V `/etc/nginx/sites-available/vreme` se v vseh vrsticah `proxy_pass` vrata 8502 zamenjajo z 8503. Streamlitove websocket nastavitve lahko ostanejo; ne motijo.

```bash
sudo cp /etc/nginx/sites-available/vreme /etc/nginx/sites-available/vreme.pred-preklopom
sudo sed -i 's/127\.0\.0\.1:8502/127.0.0.1:8503/g; s/localhost:8502/localhost:8503/g' /etc/nginx/sites-available/vreme
sudo nginx -t && sudo systemctl reload nginx
```

Nato v brskalniku: https://vreme.vzemi.si (trenutno vreme, 10 dni, menjava lokacije in jezika, `/admin`).

### 7. Ustavitev Streamlita

Po uspešnem preizkusu:

```bash
sudo systemctl disable --now vreme.service
```

### Vrnitev nazaj

```bash
sudo systemctl enable --now vreme.service
sudo cp /etc/nginx/sites-available/vreme.pred-preklopom /etc/nginx/sites-available/vreme
sudo nginx -t && sudo systemctl reload nginx
```

### Kasnejše posodobitve

Nov paket se razpakira čez obstoječo mapo (korak 1), nato:

```bash
sudo systemctl restart postaja.service
```
