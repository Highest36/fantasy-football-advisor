"""Tiny SQLite JSON cache with per-call TTL."""
import json
import sqlite3
import time
from functools import wraps

from .config import CACHE_DIR

_db = sqlite3.connect(CACHE_DIR / "cache.db", check_same_thread=False)
_db.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, ts REAL, v TEXT)")


def get(key, ttl):
    row = _db.execute("SELECT ts, v FROM kv WHERE k=?", (key,)).fetchone()
    if row and time.time() - row[0] < ttl:
        return json.loads(row[1])
    return None


def put(key, value):
    _db.execute("REPLACE INTO kv VALUES (?,?,?)", (key, time.time(), json.dumps(value)))
    _db.commit()


def cached(ttl):
    def deco(fn):
        @wraps(fn)
        def inner(*args, **kwargs):
            key = f"{fn.__module__}.{fn.__name__}:{json.dumps([args, kwargs], default=str)}"
            hit = get(key, ttl)
            if hit is not None:
                return hit
            val = fn(*args, **kwargs)
            put(key, val)
            return val
        return inner
    return deco
