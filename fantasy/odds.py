"""ESPN scoreboard: schedule, spreads, totals -> implied team points."""
import httpx

from .cache import cached

ESPN_TO_NFLVERSE = {"LAR": "LA", "WSH": "WAS"}
URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"


@cached(3600)
def game_environment(week, season):
    d = httpx.get(URL, params={"week": week, "seasontype": 2, "dates": season}, timeout=30).json()
    games = []
    for ev in d.get("events", []):
        c = ev["competitions"][0]
        teams = {t["homeAway"]: ESPN_TO_NFLVERSE.get(a := t["team"]["abbreviation"], a)
                 for t in c["competitors"]}
        odds = (c.get("odds") or [{}])[0]
        total = odds.get("overUnder")
        details = odds.get("details") or ""
        home_spread = None
        if details.upper() == "EVEN":
            home_spread = 0.0
        elif details:
            fav, line = details.rsplit(" ", 1)
            fav = ESPN_TO_NFLVERSE.get(fav, fav)
            line = abs(float(line))
            home_spread = -line if fav == teams["home"] else line
        g = {"game": ev["shortName"], "kickoff_utc": ev["date"], "status": c["status"]["type"]["name"],
             "home": teams["home"], "away": teams["away"], "line": details or None, "total": total,
             "indoor": c.get("venue", {}).get("indoor"),
             "weather": (ev.get("weather") or {}).get("displayValue")}
        if total is not None and home_spread is not None:
            g["implied"] = {teams["home"]: round((total - home_spread) / 2, 1),
                            teams["away"]: round((total + home_spread) / 2, 1)}
        games.append(g)
    return games
