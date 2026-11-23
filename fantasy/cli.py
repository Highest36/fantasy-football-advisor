"""python -m fantasy.cli auth | code <CODE> | smoke"""
import json
import sys
import warnings

warnings.filterwarnings("ignore")

from . import server, yahoo  # noqa: E402


def show(label, fn):
    try:
        v = fn()
        print(f"== {label}: OK\n{json.dumps(v, default=str)[:700]}\n")
        return True
    except Exception as e:
        print(f"== {label}: FAIL {type(e).__name__}: {e}\n")
        return False


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "smoke"
    if cmd == "auth":
        print(yahoo.auth_url())
    elif cmd == "code":
        yahoo.exchange_code(sys.argv[2])
        print("token saved; leagues:", yahoo.my_leagues())
    elif cmd == "smoke":
        checks = [("nfl_state", server.nfl_state),
                  ("game_environment", server.game_environment),
                  ("trending", lambda: server.trending(limit=5)),
                  ("defense_vs_position RB", lambda: server.defense_vs_position("RB")[:5]),
                  ("player_detail", lambda: server.player_detail("Ja'Marr Chase", 2)),
                  ("league_settings", server.league_settings),
                  ("my_roster", server.my_roster),
                  ("free_agents RB", lambda: server.free_agents("RB", 5)),
                  ("matchups", server.matchups),
                  ("standings", server.standings)]
        ok = sum(show(n, f) for n, f in checks)
        print(f"{ok}/{len(checks)} passed")
        sys.exit(0 if ok == len(checks) else 1)


if __name__ == "__main__":
    main()
