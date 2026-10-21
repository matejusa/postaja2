"""Nastavitve iz okolja (.env v korenu projekta)."""
import os
import secrets
from pathlib import Path

import httpx
from dotenv import load_dotenv

VERSION = "2026.10.21"
ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
# Brez privzetega gesla: če ADMIN_PASSWORD ni nastavljen, je admin konzola onemogočena.
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
# Brez SECRET_KEY se admin seje razveljavijo ob vsakem ponovnem zagonu.
SECRET_KEY = os.getenv("SECRET_KEY") or secrets.token_hex(32)
# Na strežniku za HTTPS nastavi HTTPS_ONLY=1, da brskalnik piškotke pošilja samo po šifrirani povezavi.
HTTPS_ONLY = os.getenv("HTTPS_ONLY", "") == "1"

ADMIN_CONFIG_PATH = ROOT / "admin_config.json"
CACHE_DIR = ROOT / ".forecast_cache"

# Skupni HTTP odjemalec za vse zunanje klice (zapre se ob zaustavitvi aplikacije).
http = httpx.AsyncClient(timeout=15)
