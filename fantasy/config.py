import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "cache"
CACHE_DIR.mkdir(exist_ok=True)
load_dotenv(ROOT / ".env")

YAHOO_CLIENT_ID = os.getenv("YAHOO_CLIENT_ID", "")
YAHOO_CLIENT_SECRET = os.getenv("YAHOO_CLIENT_SECRET", "")
YAHOO_LEAGUE_KEY = os.getenv("YAHOO_LEAGUE_KEY", "")   # e.g. 461.l.123456 (auto-discovered if blank)
YAHOO_TEAM_KEY = os.getenv("YAHOO_TEAM_KEY", "")
TOKEN_FILE = ROOT / "token.json"

# nflreadpy reads these at import time
os.environ.setdefault("NFLREADPY_CACHE", "filesystem")
os.environ.setdefault("NFLREADPY_CACHE_DIR", str(CACHE_DIR / "nflverse"))
os.environ.setdefault("NFLREADPY_CACHE_DURATION", str(6 * 3600))
