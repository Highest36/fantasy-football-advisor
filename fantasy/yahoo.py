"""Thin Yahoo Fantasy Sports v2 client (OAuth2, format=json) + response normalizer."""
import json
import os
import time
from urllib.parse import parse_qs, urlparse
from urllib.parse import urlencode

import httpx

from . import config
from .cache import cached

AUTH_URL = "https://api.login.yahoo.com/oauth2/request_auth"
TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"
API = "https://fantasysports.yahooapis.com/fantasy/v2"
REDIRECT = os.getenv("YAHOO_REDIRECT", "oob")


class YahooAuthError(RuntimeError):
    pass


# ---------- OAuth ----------
def auth_url():
    return f"{AUTH_URL}?{urlencode({'client_id': config.YAHOO_CLIENT_ID, 'redirect_uri': REDIRECT, 'response_type': 'code'})}"


def _token_request(data):
    r = httpx.post(TOKEN_URL, data={**data, "redirect_uri": REDIRECT},
                   auth=(config.YAHOO_CLIENT_ID, config.YAHOO_CLIENT_SECRET), timeout=30)
    if r.status_code != 200:
        raise YahooAuthError(f"token endpoint {r.status_code}: {r.text[:300]}")
    tok = r.json()
    tok["obtained_at"] = time.time()
    config.TOKEN_FILE.write_text(json.dumps(tok))
    config.TOKEN_FILE.chmod(0o600)
    return tok


def exchange_code(code):
    """Accepts the bare code (oob) or the full redirected URL (pasted from the address bar)."""
    code = code.strip()
    if code.startswith("http"):
        code = parse_qs(urlparse(code).query)["code"][0]
    return _token_request({"grant_type": "authorization_code", "code": code})


def _access_token():
    if not config.TOKEN_FILE.exists():
        raise YahooAuthError("not authorized yet - run: python -m fantasy.cli auth")
    tok = json.loads(config.TOKEN_FILE.read_text())
    if time.time() > tok["obtained_at"] + tok.get("expires_in", 3600) - 120:
        old_refresh = tok["refresh_token"]
        tok = _token_request({"grant_type": "refresh_token", "refresh_token": old_refresh})
        tok.setdefault("refresh_token", old_refresh)
        config.TOKEN_FILE.write_text(json.dumps(tok))
    return tok["access_token"]


def get(path):
    r = httpx.get(f"{API}/{path}", params={"format": "json"},
                  headers={"Authorization": f"Bearer {_access_token()}"}, timeout=30)
    if r.status_code == 401:
        raise YahooAuthError(f"401 from Yahoo: {r.text[:300]}")
    r.raise_for_status()
    return norm(r.json()["fantasy_content"])


# ---------- normalizer ----------
def norm(x):
    """Collapse Yahoo's {"0": {...}, "count": n} maps into lists and its
    list-of-fragment-dicts into single dicts (when keys don't collide)."""
    if isinstance(x, dict):
        keys = [k for k in x if k != "count"]
        if keys and all(k.isdigit() for k in keys):
            out = []
            for k in sorted(keys, key=int):
                v = norm(x[k])
                out.append(next(iter(v.values())) if isinstance(v, dict) and len(v) == 1 else v)
            return out
        return {k: norm(v) for k, v in x.items()}
    if isinstance(x, list):
        items = [norm(i) for i in x]
        if items and all(isinstance(i, (dict, list)) for i in items):
            merged, ok = {}, True
            for i in items:
                parts = i if isinstance(i, list) else [i]
                for p in parts:
                    if not isinstance(p, dict) or merged.keys() & p.keys():
                        ok = False
                        break
                    merged.update(p)
                if not ok:
                    break
            if ok:
                return merged
        return items
    return x


# ---------- discovery ----------
@cached(86400)
def my_leagues():
    d = get("users;use_login=1/games;game_keys=nfl/teams")
    teams = d["users"][0]["games"][0]["teams"]
    return [{"team_key": t["team_key"], "team_name": t["name"],
             "league_key": t["team_key"].rsplit(".t.", 1)[0]} for t in teams]


def league_key():
    if config.YAHOO_LEAGUE_KEY:
        return config.YAHOO_LEAGUE_KEY
    lg = my_leagues()
    if len(lg) != 1:
        raise RuntimeError(f"multiple/zero NFL leagues, set YAHOO_LEAGUE_KEY in .env: {lg}")
    return lg[0]["league_key"]


def team_key():
    if config.YAHOO_TEAM_KEY:
        return config.YAHOO_TEAM_KEY
    lk = league_key()
    return next(t["team_key"] for t in my_leagues() if t["league_key"] == lk)


# ---------- league data ----------
def _player(p):
    sel = p.get("selected_position") or {}
    if isinstance(sel, list):
        sel = next((s for s in sel if "position" in s), {})
    elig = p.get("eligible_positions") or []
    out = {"name": (p.get("name") or {}).get("full"), "player_key": p.get("player_key"),
           "team": p.get("editorial_team_abbr"), "pos": p.get("display_position"),
           "eligible": [e.get("position") for e in elig] if isinstance(elig, list) else elig,
           "slot": sel.get("position"), "status": p.get("status"), "injury": p.get("injury_note"),
           "bye": (p.get("bye_weeks") or {}).get("week"),
           "pct_owned": (p.get("percent_owned") or {}).get("value"),
           "points": (p.get("player_points") or {}).get("total"),
           "projected": (p.get("player_projected_points") or {}).get("total")}
    return {k: v for k, v in out.items() if v not in (None, "", [])}


@cached(6 * 3600)
def league_settings():
    d = get(f"league/{league_key()}/settings")["league"]
    s = d["settings"]
    stat_names = {c["stat"]["stat_id"]: c["stat"]["display_name"]
                  for c in s.get("stat_categories", {}).get("stats", [])} if isinstance(s.get("stat_categories"), dict) else {}
    mods = {}
    for m in (s.get("stat_modifiers") or {}).get("stats", []):
        st = m.get("stat", m)
        mods[stat_names.get(st["stat_id"], st["stat_id"])] = float(st["value"])
    rec = mods.get("Rec", 0)
    return {"league": d.get("name"), "league_key": d.get("league_key"), "num_teams": d.get("num_teams"),
            "current_week": d.get("current_week"), "end_week": d.get("end_week"),
            "scoring_format": "ppr" if rec >= 1 else "half" if rec >= 0.5 else "std",
            "scoring": mods,
            "roster_positions": [(r["roster_position"]["position"], r["roster_position"]["count"])
                                 for r in s.get("roster_positions", [])] if isinstance(s.get("roster_positions"), list) else s.get("roster_positions"),
            "waiver_type": s.get("waiver_type"), "uses_faab": s.get("uses_faab"),
            "trade_end_date": s.get("trade_end_date"), "playoff_start_week": s.get("playoff_start_week"),
            "num_playoff_teams": s.get("num_playoff_teams"), "my_team_key": team_key()}


@cached(600)
def roster(team=None, week=None):
    tk = team or team_key()
    wk = f";week={week}" if week else ""
    t = get(f"team/{tk}/roster{wk}/players/stats;type=week{wk}")["team"]
    faab = t.get("faab_balance")
    return {"team": t.get("name"), "team_key": tk, "faab_balance": faab,
            "players": [_player(p) for p in t["roster"]["players"]]}


@cached(600)
def free_agents(position=None, count=25, start=0):
    pos = f";position={position}" if position else ""
    d = get(f"league/{league_key()}/players;status=A{pos};sort=AR;count={count};start={start}"
            f"/percent_owned")["league"]
    return [_player(p) for p in d.get("players", [])]


@cached(600)
def scoreboard(week=None):
    wk = f";week={week}" if week else ""
    d = get(f"league/{league_key()}/scoreboard{wk}")["league"]
    out = []
    for m in d["scoreboard"]["matchups"]:
        out.append({"week": m.get("week"), "status": m.get("status"),
                    "teams": [{"name": t.get("name"), "team_key": t.get("team_key"),
                               "points": (t.get("team_points") or {}).get("total"),
                               "projected": (t.get("team_projected_points") or {}).get("total"),
                               "win_probability": t.get("win_probability")}
                              for t in m["teams"]]})
    return out


@cached(600)
def standings():
    d = get(f"league/{league_key()}/standings")["league"]
    return [{"name": t.get("name"), "team_key": t.get("team_key"),
             "rank": (t.get("team_standings") or {}).get("rank"),
             "record": (t.get("team_standings") or {}).get("outcome_totals"),
             "points_for": (t.get("team_standings") or {}).get("points_for")}
            for t in d["standings"]["teams"]]


@cached(600)
def transactions(count=25):
    d = get(f"league/{league_key()}/transactions;count={count}")["league"]
    return d.get("transactions")
