"""Sleeper public API: NFL state, player DB (injuries/depth), trending adds/drops."""
import httpx

from .cache import cached

BASE = "https://api.sleeper.app/v1"


def _get(path, **params):
    r = httpx.get(f"{BASE}{path}", params=params, timeout=30)
    r.raise_for_status()
    return r.json()


@cached(3600)
def state():
    return _get("/state/nfl")


@cached(12 * 3600)
def players():
    keep = ("full_name", "position", "team", "status", "injury_status", "injury_body_part",
            "injury_notes", "practice_participation", "depth_chart_position",
            "depth_chart_order", "years_exp", "age")
    return {pid: {k: p.get(k) for k in keep}
            for pid, p in _get("/players/nfl").items()
            if p.get("position") in ("QB", "RB", "WR", "TE", "K", "DEF")}


@cached(3600)
def trending(kind="add", hours=24, limit=25):
    db = players()
    out = []
    for row in _get(f"/players/nfl/trending/{kind}", lookback_hours=hours, limit=limit):
        p = db.get(row["player_id"], {})
        out.append({"sleeper_id": row["player_id"], "name": p.get("full_name") or row["player_id"],
                    "pos": p.get("position"), "team": p.get("team"), "count": row["count"],
                    "injury": p.get("injury_status")})
    return out


def injured(names=None):
    """Players with an injury designation, optionally restricted to a set of names."""
    wanted = {n.lower() for n in names} if names else None
    out = []
    for pid, p in players().items():
        if not p.get("injury_status") or not p.get("team"):
            continue
        if wanted and (p.get("full_name") or "").lower() not in wanted:
            continue
        out.append({"name": p["full_name"], "pos": p["position"], "team": p["team"],
                    "status": p["injury_status"], "body_part": p.get("injury_body_part"),
                    "practice": p.get("practice_participation"), "notes": p.get("injury_notes")})
    return out
