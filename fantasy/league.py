"""Manual league profile (stand-in until Yahoo approves Fantasy API access). Stored in league.json."""
import json

from .config import ROOT

FILE = ROOT / "league.json"
DEFAULT = {"league_size": None, "scoring": None, "roster_slots": None, "bench_spots": None,
           "waivers": {"type": None, "faab_budget": None, "faab_remaining": None, "priority": None,
                       "process_day_et": None},
           "playoff_weeks": None, "my_roster": [], "rostered_elsewhere": [], "confirmed_available": [],
           "notes": "", "updated": None}


def load():
    return {**DEFAULT, **json.loads(FILE.read_text())} if FILE.exists() else dict(DEFAULT)


def save(d):
    import datetime
    d["updated"] = datetime.datetime.now().isoformat(timespec="minutes")
    FILE.write_text(json.dumps(d, indent=2))
    return d


def rostered_total(d):
    """Players rostered league-wide (for the availability heuristic)."""
    size = d.get("league_size") or 12
    per_team = (sum((d.get("roster_slots") or {}).values()) if isinstance(d.get("roster_slots"), dict) else 9) \
        + (d.get("bench_spots") or 6)
    return size * per_team
