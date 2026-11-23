"""nflverse: weekly usage, snap share, defense-vs-position, schedule."""
import re

from . import config  # noqa: F401  (sets NFLREADPY_* env before import)
import nflreadpy as nfl
import polars as pl

SLEEPER_TO_NFLVERSE = {"LAR": "LA", "WSH": "WAS", "JAC": "JAX"}


def norm_name(n):
    n = re.sub(r"[.'\-]", "", (n or "").lower())
    return re.sub(r"\s+(jr|sr|ii|iii|iv|v)$", "", n).strip()


def points_col(fmt):
    if fmt == "ppr":
        return pl.col("fantasy_points_ppr")
    if fmt == "half":
        return pl.col("fantasy_points") + 0.5 * pl.col("receptions")
    return pl.col("fantasy_points")


def stats(season):
    return nfl.load_player_stats([season]).filter(pl.col("season_type") == "REG")


def schedule(season):
    return nfl.load_schedules([season]).filter(pl.col("game_type") == "REG")


def find_player(name, season):
    s = stats(season)
    key = norm_name(name)
    hit = s.filter(pl.col("player_display_name").map_elements(norm_name, return_dtype=pl.Utf8) == key)
    if hit.is_empty():
        hit = s.filter(pl.col("player_display_name").str.to_lowercase().str.contains(key.split()[-1]))
    return hit


def player_usage(name, season, last_n=4, fmt="half"):
    rows = find_player(name, season)
    if rows.is_empty():
        return {"error": f"no {season} stats for {name!r}"}
    pid = rows["player_id"].mode()[0]
    rows = rows.filter(pl.col("player_id") == pid).sort("week")
    ids = nfl.load_ff_playerids().filter(pl.col("gsis_id") == pid)
    pfr = ids["pfr_id"][0] if not ids.is_empty() else None
    snaps = {}
    if pfr:
        sc = nfl.load_snap_counts([season]).filter(pl.col("pfr_player_id") == pfr)
        snaps = dict(zip(sc["week"].to_list(), sc["offense_pct"].to_list()))
    weekly = []
    for r in rows.with_columns(pts=points_col(fmt)).tail(last_n).iter_rows(named=True):
        weekly.append({k: r[k] for k in ("week", "opponent_team", "pts", "targets", "receptions",
                                         "receiving_yards", "carries", "rushing_yards", "attempts",
                                         "passing_yards", "passing_tds", "rushing_tds", "receiving_tds",
                                         "target_share", "air_yards_share", "wopr")}
                      | {"snap_pct": snaps.get(r["week"])})
    for w in weekly:
        for k, v in w.items():
            if isinstance(v, float):
                w[k] = round(v, 3)
    last = rows.tail(1).row(0, named=True)
    team = last["team"]
    season_pts = rows.select(points_col(fmt)).to_series()
    return {"name": last["player_display_name"], "pos": last["position"], "team": team,
            "games": rows.height, "season_ppg": round(season_pts.mean(), 2),
            f"last_{last_n}": weekly, "upcoming": upcoming(team, season, last["week"] + 1, 3),
            "scoring": fmt, "gsis_id": pid}


def upcoming(team, season, from_week, n=3):
    sc = schedule(season).filter(((pl.col("home_team") == team) | (pl.col("away_team") == team))
                                 & (pl.col("week") >= from_week)).sort("week").head(n)
    return [{"week": r["week"], "opp": r["away_team"] if r["home_team"] == team else "@" + r["home_team"],
             "gameday": r["gameday"]} for r in sc.iter_rows(named=True)]


def byes(season):
    sc = schedule(season)
    teams = set(sc["home_team"]) | set(sc["away_team"])
    out = {}
    for t in teams:
        played = set(sc.filter((pl.col("home_team") == t) | (pl.col("away_team") == t))["week"])
        missing = sorted(set(range(1, 19)) - played)
        out[t] = missing[0] if missing else None
    return out


def defense_vs_position(pos, season, fmt="half", last_n_weeks=None):
    s = stats(season).filter(pl.col("position") == pos.upper())
    if last_n_weeks:
        s = s.filter(pl.col("week") > s["week"].max() - last_n_weeks)
    g = (s.with_columns(pts=points_col(fmt))
         .group_by(["opponent_team", "week"]).agg(pl.col("pts").sum())
         .group_by("opponent_team").agg(pl.col("pts").mean().round(2).alias("pts_allowed_pg"),
                                       pl.len().alias("games"))
         .sort("pts_allowed_pg", descending=True))
    return [{"defense": r["opponent_team"], "rank_easiest": i + 1, **{k: r[k] for k in ("pts_allowed_pg", "games")}}
            for i, r in enumerate(g.iter_rows(named=True))]
