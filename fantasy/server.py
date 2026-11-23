"""MCP server exposing Yahoo league + free NFL data sources as tools."""
import warnings

warnings.filterwarnings("ignore")
import logging  # noqa: E402

logging.getLogger("httpx").setLevel(logging.WARNING)

from mcp.server.mcpserver import MCPServer  # noqa: E402

from . import espn, league, nflverse, odds, sleeper, yahoo  # noqa: E402
from .config import ROOT  # noqa: E402

mcp = MCPServer("fantasy", instructions=(ROOT / "PLAYBOOK.md").read_text())


def _season():
    return int(sleeper.state()["season"])


def _week():
    return int(sleeper.state()["week"])


def _fmt():
    try:
        return yahoo.league_settings()["scoring_format"]
    except Exception:
        return league.load().get("scoring") or "half"


YAHOO_DOWN = ("Yahoo Fantasy API is blocked (403 - app awaiting Yahoo approval). "
              "Using the manual league profile instead; see league_profile.")


@mcp.tool()
def nfl_state() -> dict:
    """Current NFL season and week (per Sleeper)."""
    return sleeper.state()


@mcp.tool()
def league_settings() -> dict:
    """My Yahoo league: scoring rules (PPR/half/std + modifiers), roster slots, waiver type/FAAB,
    trade deadline, playoff start week, current week, my team key."""
    try:
        return yahoo.league_settings()
    except yahoo.YahooAuthError:
        raise
    except Exception:
        return {"note": YAHOO_DOWN, **league.load()}


@mcp.tool()
def my_roster(week: int | None = None) -> dict:
    """My roster for a week: each player's slot, eligibility, Yahoo status/injury, bye, points/projection.
    Falls back to the manual league profile while Yahoo access is pending."""
    try:
        return yahoo.roster(week=week)
    except Exception:
        d = league.load()
        return {"note": YAHOO_DOWN, "players": d["my_roster"], "profile_updated": d["updated"]}


@mcp.tool()
def team_roster(team_key: str, week: int | None = None) -> dict:
    """Any team's roster (use all_rosters or standings to find team keys)."""
    return yahoo.roster(team=team_key, week=week)


@mcp.tool()
def all_rosters() -> list:
    """Every team's roster - for trade-partner fit (who's thin/deep at each position)."""
    return [yahoo.roster(team=t["team_key"]) for t in yahoo.standings()]


@mcp.tool()
def matchups(week: int | None = None) -> list:
    """League scoreboard: every matchup's points, Yahoo projected points, win probability."""
    return yahoo.scoreboard(week)


@mcp.tool()
def standings() -> list:
    """League standings: rank, record, points for."""
    return yahoo.standings()


@mcp.tool()
def free_agents(position: str | None = None, count: int = 25) -> list:
    """Available players (FA + waivers) in my league sorted by Yahoo actual rank.
    position: QB, RB, WR, TE, K, DEF, or W/R/T. Includes % owned."""
    return yahoo.free_agents(position, count)


@mcp.tool()
def recent_transactions(count: int = 25) -> list:
    """Recent league adds/drops/trades."""
    return yahoo.transactions(count)


@mcp.tool()
def player_detail(name: str, last_n_weeks: int = 4) -> dict:
    """Usage trend for one NFL player (this season): weekly fantasy pts in my scoring, targets,
    target share, air-yards share, WOPR, carries, snap %, plus next 3 opponents and Sleeper injury info."""
    out = nflverse.player_usage(name, _season(), last_n_weeks, _fmt())
    inj = sleeper.injured([out.get("name", name)])
    out["injury"] = inj[0] if inj else None
    return out


@mcp.tool()
def trending(kind: str = "add", hours: int = 24, limit: int = 25) -> list:
    """Sleeper-wide trending adds or drops (kind='add'|'drop') - a proxy for waiver-wire buzz."""
    return sleeper.trending(kind, hours, limit)


@mcp.tool()
def injuries(names: list[str] | None = None) -> list:
    """Sleeper injury designations (Q/D/O/IR) + practice participation, optionally for given names."""
    return sleeper.injured(names)


@mcp.tool()
def game_environment(week: int | None = None) -> list:
    """Week's games: Vegas line, total, implied team totals, kickoff (UTC), indoor, weather."""
    return odds.game_environment(week or _week(), _season())


@mcp.tool()
def defense_vs_position(position: str, last_n_weeks: int | None = None) -> list:
    """Fantasy points allowed per game by each NFL defense to a position, in my league's scoring.
    rank_easiest=1 is the softest matchup."""
    return nflverse.defense_vs_position(position, _season(), _fmt(), last_n_weeks)


def _key(n):
    return nflverse.norm_name(n)


@mcp.tool()
def league_profile() -> dict:
    """Manual league profile: league size, scoring, roster slots, waiver/FAAB rules, my roster,
    players known rostered by other teams, players confirmed available. Empty fields = ask the user."""
    return league.load()


@mcp.tool()
def update_league_profile(changes: dict) -> dict:
    """Merge changes into the league profile and save. Keys: league_size, scoring (ppr|half|std),
    roster_slots (dict e.g. {"QB":1,"RB":2,"WR":2,"TE":1,"W/R/T":1,"K":1,"DEF":1}), bench_spots,
    waivers {type: faab|rolling|reverse_standings, faab_budget, faab_remaining, priority, process_day_et},
    playoff_weeks, my_roster (list of {"name","pos","team","slot"}), rostered_elsewhere (names),
    confirmed_available (names), notes. List keys are REPLACED - send the whole list."""
    d = league.load()
    for k, v in changes.items():
        if isinstance(v, dict) and isinstance(d.get(k), dict):
            d[k] = {**d[k], **v}
        else:
            d[k] = v
    return league.save(d)


@mcp.tool()
def waiver_candidates(position: str | None = None, max_pct_owned: float = 60, count: int = 15) -> list:
    """Likely-available waiver targets ranked by ESPN rest-of-season projection. Excludes my roster and
    players known rostered elsewhere. availability: confirmed / likely / maybe (based on ESPN % rostered
    vs. how many players this league rosters). Includes 7-day add-rate, Sleeper trending adds, injury,
    this-week / next-3 / ROS projections (ESPN PPR scale - use for relative value). Then verify the top
    names with player_detail before recommending, and have the user confirm availability."""
    d = league.load()
    mine = {_key(p["name"] if isinstance(p, dict) else p) for p in d["my_roster"]}
    taken = {_key(n) for n in d["rostered_elsewhere"]}
    confirmed = {_key(n) for n in d["confirmed_available"]}
    cutoff = league.rostered_total(d)
    trend = {_key(t["name"]): t["count"] for t in sleeper.trending("add", 48, 100)}
    week = _week()
    out = []
    for p in espn.pool(_season(), week):
        k = _key(p["name"])
        if k in mine or k in taken or (position and p["pos"] != position.upper()):
            continue
        if k in confirmed:
            avail = "confirmed"
        elif p["pct_owned"] > max_pct_owned:
            continue
        else:
            avail = "likely" if p["espn_own_rank"] > cutoff or p["pct_owned"] < 35 else "maybe"
        if not p["ros_weeks"]:
            continue
        out.append({**p, "availability": avail, "ros_ppg": round(p["proj_ros"] / p["ros_weeks"], 1),
                    "sleeper_adds_48h": trend.get(k, 0)})
    out.sort(key=lambda x: (x["availability"] != "confirmed", -x["ros_ppg"]))
    if position:
        return out[:count]
    quota = {"RB": 5, "WR": 5, "TE": 3, "QB": 3, "DEF": 2, "K": 1}   # QBs would otherwise crowd the list
    return [p for pos, n in quota.items() for p in [x for x in out if x["pos"] == pos][:n]]


@mcp.tool()
def player_market(names: list[str]) -> list:
    """ESPN % rostered, add-rate and this-week/next-3/ROS projections for specific players
    (e.g. my roster, to find drop candidates or compare trade pieces)."""
    pool = {_key(p["name"]): p for p in espn.pool(_season(), _week())}
    return [pool.get(_key(n), {"name": n, "error": "not in ESPN top-1000 pool"}) for n in names]


@mcp.tool()
def bye_weeks() -> dict:
    """Bye week for every NFL team this season."""
    return nflverse.byes(_season())


if __name__ == "__main__":
    mcp.run()
