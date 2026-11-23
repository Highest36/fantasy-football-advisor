# Fantasy Football Advisor

A personal, single-user fantasy football assistant for my own Yahoo Fantasy NFL league.
It runs on my home server and is not a public service.

## What it does
- Reads my league's settings, roster, matchups, standings, and free agents from the
  **Yahoo Fantasy Sports API** (read-only, OAuth 2.0).
- Combines that with public NFL data (ESPN, Sleeper, nflverse, betting lines) to give
  start/sit, waiver, and trade advice.
- Exposes the data as an MCP tool server (`fantasy/server.py`) and a small LAN-only web UI
  (`fantasy/web.py`).

## Yahoo API usage
- Scope: Fantasy Sports **read**. No write actions (no roster moves or trades are submitted).
- Used only by me, for my own league. No data is shared, sold, or shown publicly.
- Requests are cached locally (`fantasy/cache.py`) to keep call volume low.

## Setup
```bash
python3.12 -m venv .venv && .venv/bin/pip install -e '.[web]'
cp .env.example .env   # fill in YAHOO_CLIENT_ID / YAHOO_CLIENT_SECRET
.venv/bin/python -m fantasy.cli auth    # one-time Yahoo OAuth
.venv/bin/python -m fantasy.cli smoke   # test all data sources
```
