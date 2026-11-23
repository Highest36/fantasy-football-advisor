"""LAN-only web front end. Data views call the same functions as the MCP tools; Claude jobs
(ask / digest) run on the host through a forced-command SSH key (runner.sh)."""
import ipaddress
import json
import os
import threading
import time
import uuid
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

import paramiko  # noqa: E402
from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402

from . import espn, league, nflverse, server  # noqa: E402
from .config import ROOT  # noqa: E402

app = FastAPI(title="fantasy")
STATIC = Path(__file__).parent / "static"
JOBS = ROOT / "web" / "jobs"
SSH = ROOT / "web" / "ssh"
HOST = os.getenv("FANTASY_SSH_HOST", "127.0.0.1")
SSH_USER = os.getenv("FANTASY_SSH_USER", "fantasy")
ALLOWED = [ipaddress.ip_network(n.strip()) for n in
           os.getenv("FANTASY_ALLOWED_NETS", "192.168.0.0/16,10.0.0.0/8,127.0.0.0/8,172.16.0.0/12").split(",")]
_claude = threading.Semaphore(1)   # small box — one claude run at a time


@app.middleware("http")
async def lan_only(request: Request, call_next):
    peer = request.client.host if request.client else "0.0.0.0"
    ip = peer
    if ipaddress.ip_address(peer) in ipaddress.ip_network("172.16.0.0/12"):   # via reverse proxy
        ip = request.headers.get("x-real-ip") or request.headers.get("x-forwarded-for", peer).split(",")[0].strip()
    try:
        ok = any(ipaddress.ip_address(ip) in n for n in ALLOWED)
    except ValueError:
        ok = False
    if not ok:
        return JSONResponse({"error": "LAN only"}, status_code=403)
    return await call_next(request)


def _k(n):
    return nflverse.norm_name(n)


def _pname(p):
    return p["name"] if isinstance(p, dict) else p


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/overview")
def overview():
    d = league.load()
    week, season = server._week(), server._season()
    names = [_pname(p) for p in d["my_roster"]]
    market = {_k(m["name"]): m for m in server.player_market(names) if "error" not in m}
    inj = {_k(i["name"]): i for i in server.injuries(names)}
    byes = server.bye_weeks()
    games = server.game_environment(week)
    gmap = {}
    for g in games:
        for side, opp, at in ((g["home"], g["away"], "vs"), (g["away"], g["home"], "@")):
            gmap[side] = {"opp": f"{at} {opp}", "kickoff_utc": g["kickoff_utc"], "line": g["line"],
                          "total": g["total"], "implied": (g.get("implied") or {}).get(side)}
    roster = []
    for p in d["my_roster"]:
        p = p if isinstance(p, dict) else {"name": p}
        m = market.get(_k(p["name"]), {})
        team = p.get("team") or m.get("team")
        i = inj.get(_k(p["name"]))
        roster.append({**p, "team": team, "pos": p.get("pos") or m.get("pos"),
                       "bye": byes.get(team, p.get("bye")), "game": gmap.get(team),
                       "injury": (i or {}).get("status"), "injury_detail": (i or {}).get("body_part"),
                       "proj_this_week": m.get("proj_this_week"), "proj_next_3": m.get("proj_next_3"),
                       "ros_ppg": round(m["proj_ros"] / m["ros_weeks"], 1) if m.get("ros_weeks") else None,
                       "pct_owned": m.get("pct_owned"), "last_3": m.get("last_3_actual")})
    upcoming_byes = {w: [r["name"] for r in roster if r["bye"] == w] for w in range(week, week + 4)}
    return {"week": week, "season": season, "profile": d, "roster": roster,
            "upcoming_byes": {w: v for w, v in upcoming_byes.items() if v}}


@app.get("/api/waivers")
def waivers(position: str | None = None, max_owned: float = 60, count: int = 25):
    return server.waiver_candidates(position or None, max_owned, count)


@app.get("/api/player")
def player(name: str):
    return server.player_detail(name, 4)


@app.get("/api/games")
def games(week: int | None = None):
    return server.game_environment(week)


@app.get("/api/defense")
def defense(position: str):
    return server.defense_vs_position(position)


# ---------- profile editing ----------
@app.get("/api/profile")
def get_profile():
    return league.load()


@app.post("/api/profile")
async def set_profile(request: Request):
    body = await request.json()
    allowed = set(league.DEFAULT) | {"team_name", "ir_spots", "pending_claims"}
    bad = set(body) - allowed
    if bad:
        raise HTTPException(400, f"unknown keys: {sorted(bad)}")
    return server.update_league_profile(body)


def _lookup(name):
    pool = {_k(p["name"]): p for p in espn.pool(server._season(), server._week())}
    return pool.get(_k(name), {})


@app.post("/api/roster/add")
async def roster_add(request: Request):
    b = await request.json()
    d = league.load()
    if any(_k(_pname(p)) == _k(b["name"]) for p in d["my_roster"]):
        raise HTTPException(400, "already on roster")
    m = _lookup(b["name"])
    entry = {"name": m.get("name", b["name"]), "pos": b.get("pos") or m.get("pos"),
             "team": b.get("team") or m.get("team"), "slot": b.get("slot") or "BN"}
    d["my_roster"].append(entry)
    _drop_from_lists(d, entry["name"])
    return league.save(d)


@app.post("/api/roster/remove")
async def roster_remove(request: Request):
    b = await request.json()
    d = league.load()
    d["my_roster"] = [p for p in d["my_roster"] if _k(_pname(p)) != _k(b["name"])]
    return league.save(d)


@app.post("/api/roster/slot")
async def roster_slot(request: Request):
    b = await request.json()
    d = league.load()
    for p in d["my_roster"]:
        if isinstance(p, dict) and _k(p["name"]) == _k(b["name"]):
            p["slot"] = b["slot"]
    return league.save(d)


def _drop_from_lists(d, name):
    for key in ("rostered_elsewhere", "confirmed_available"):
        d[key] = [n for n in d.get(key, []) if _k(n) != _k(name)]


@app.post("/api/mark")
async def mark(request: Request):
    """status: taken | available | clear"""
    b = await request.json()
    d = league.load()
    _drop_from_lists(d, b["name"])
    if b["status"] == "taken":
        d["rostered_elsewhere"].append(b["name"])
    elif b["status"] == "available":
        d["confirmed_available"].append(b["name"])
    return league.save(d)


@app.post("/api/claims/resolve")
async def resolve_claim(request: Request):
    b = await request.json()
    d = league.load()
    claims = d.get("pending_claims") or []
    c = next((c for c in claims if _k(c["add"]) == _k(b["add"])), None)
    if not c:
        raise HTTPException(404, "no such claim")
    claims.remove(c)
    if b.get("won"):
        if c.get("drop"):
            d["my_roster"] = [p for p in d["my_roster"] if _k(_pname(p)) != _k(c["drop"])]
        m = _lookup(c["add"])
        d["my_roster"].append({"name": m.get("name", c["add"]), "pos": m.get("pos"), "team": m.get("team"), "slot": "BN"})
        _drop_from_lists(d, c["add"])
    else:
        d.setdefault("rostered_elsewhere", []).append(c["add"])
    d["pending_claims"] = claims
    return league.save(d)


@app.post("/api/claims/add")
async def add_claim(request: Request):
    b = await request.json()
    d = league.load()
    d.setdefault("pending_claims", []).append({"add": b["add"], "drop": b.get("drop"),
                                               "submitted": time.strftime("%Y-%m-%d")})
    return league.save(d)


# ---------- reports ----------
@app.get("/api/reports")
def reports():
    files = sorted((ROOT / "reports").glob("*.md"), reverse=True)
    return [{"name": f.name, "size": f.stat().st_size} for f in files[:60]]


@app.get("/api/reports/{name}")
def report(name: str):
    f = (ROOT / "reports" / name).resolve()
    if f.parent != (ROOT / "reports").resolve() or f.suffix != ".md" or not f.exists():
        raise HTTPException(404)
    return {"name": name, "content": f.read_text()}


# ---------- claude jobs over ssh ----------
def _ssh(command, stdin_text=None, timeout=900):
    c = paramiko.SSHClient()
    c.load_host_keys(str(SSH / "known_hosts"))
    c.set_missing_host_key_policy(paramiko.RejectPolicy())
    c.connect(HOST, username=SSH_USER, key_filename=str(SSH / "id_ed25519"),
              look_for_keys=False, allow_agent=False, timeout=15)
    try:
        stdin, stdout, stderr = c.exec_command(command, timeout=timeout)
        if stdin_text is not None:
            stdin.write(stdin_text)
            stdin.channel.shutdown_write()
        out = stdout.read().decode()
        return stdout.channel.recv_exit_status(), out
    finally:
        c.close()


def _save_job(job):
    (JOBS / f"{job['id']}.json").write_text(json.dumps(job))


def _run_job(job, command, stdin_text):
    job["status"] = "queued"
    _save_job(job)
    with _claude:
        job["status"], job["started"] = "running", time.time()
        _save_job(job)
        try:
            rc, out = _ssh(command, stdin_text)
            if job["kind"] == "ask":
                try:
                    r = json.loads(out)
                    job.update(result=r.get("result"), session_id=r.get("session_id"),
                               cost_usd=r.get("total_cost_usd"),
                               status="error" if r.get("is_error") else "done")
                except json.JSONDecodeError:
                    job.update(status="error", result=out[-2000:] or f"no output (rc={rc})")
            else:
                job.update(status="done" if rc == 0 else "error", result=out[-2000:])
        except Exception as e:
            job.update(status="error", result=f"{type(e).__name__}: {e}")
        job["finished"] = time.time()
        _save_job(job)


def _start(kind, command, stdin_text=None, **meta):
    job = {"id": uuid.uuid4().hex[:12], "kind": kind, "created": time.time(), **meta}
    _save_job(job)
    threading.Thread(target=_run_job, args=(job, command, stdin_text), daemon=True).start()
    return job


@app.post("/api/ask")
async def ask(request: Request):
    b = await request.json()
    q = (b.get("question") or "").strip()
    if not q:
        raise HTTPException(400, "empty question")
    sid = b.get("session_id") or ""
    return _start("ask", f"ask {sid}".strip(), q[:4000], question=q[:4000], parent_session=sid or None)


@app.post("/api/digest/{kind}")
def digest(kind: str):
    if kind not in ("waivers", "sunday", "tnf"):
        raise HTTPException(400, "bad kind")
    return _start("digest", f"digest {kind}", digest=kind)


@app.get("/api/jobs/{job_id}")
def job(job_id: str):
    f = JOBS / f"{job_id}.json"
    if not job_id.isalnum() or not f.exists():
        raise HTTPException(404)
    return json.loads(f.read_text())


@app.get("/api/jobs")
def jobs(kind: str | None = None, limit: int = 30):
    out = []
    for f in sorted(JOBS.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True):
        j = json.loads(f.read_text())
        if not kind or j["kind"] == kind:
            out.append(j)
        if len(out) >= limit:
            break
    return out


@app.get("/healthz")
def healthz():
    return {"ok": True}
