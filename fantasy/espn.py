"""ESPN public fantasy data (no auth): % rostered across ESPN leagues, add-rate, weekly + ROS projections.
appliedTotal uses ESPN default PPR scoring — treat as relative value, not exact points for our league."""
import json

import httpx

from .cache import cached

URL = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{season}/segments/0/leaguedefaults/3"
POS = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "DEF"}
TEAMS = {0: "FA", 1: "ATL", 2: "BUF", 3: "CHI", 4: "CIN", 5: "CLE", 6: "DAL", 7: "DEN", 8: "DET", 9: "GB",
         10: "TEN", 11: "IND", 12: "KC", 13: "LV", 14: "LA", 15: "MIA", 16: "MIN", 17: "NE", 18: "NO",
         19: "NYG", 20: "NYJ", 21: "PHI", 22: "ARI", 23: "PIT", 24: "LAC", 25: "SF", 26: "SEA", 27: "TB",
         28: "WAS", 29: "CAR", 30: "JAX", 33: "BAL", 34: "HOU"}   # nflverse-style codes


@cached(3 * 3600)
def pool(season, week, limit=1000):
    flt = {"players": {"limit": limit, "sortPercOwned": {"sortAsc": False, "sortPriority": 1}}}
    r = httpx.get(URL.format(season=season), params={"view": "kona_player_info"},
                  headers={"X-Fantasy-Filter": json.dumps(flt)}, timeout=60)
    r.raise_for_status()
    out = []
    for rank, row in enumerate(r.json()["players"], 1):
        p = row["player"]
        pos = POS.get(p.get("defaultPositionId"))
        if not pos:
            continue
        o = p.get("ownership") or {}
        proj, actual = {}, {}
        for s in p.get("stats") or []:
            if s.get("seasonId") != season or s.get("statSplitTypeId") != 1:
                continue
            (proj if s.get("statSourceId") == 1 else actual)[s["scoringPeriodId"]] = round(s.get("appliedTotal") or 0, 1)
        ros_weeks = [proj[w] for w in sorted(proj) if w >= week]
        played = [actual[w] for w in sorted(actual) if w < week]
        out.append({"name": p["fullName"], "pos": pos, "team": TEAMS.get(p.get("proTeamId"), "?"),
                    "espn_own_rank": rank, "pct_owned": round(o.get("percentOwned", 0), 1),
                    "pct_change_7d": round(o.get("percentChange", 0), 2),
                    "pct_started": round(o.get("percentStarted", 0), 1),
                    "injury": p.get("injuryStatus"),
                    "proj_this_week": proj.get(week),
                    "proj_next_3": round(sum(proj.get(w, 0) for w in range(week, week + 3)), 1),
                    "proj_ros": round(sum(ros_weeks), 1), "ros_weeks": len(ros_weeks),
                    "last_3_actual": played[-3:]})
    return out
