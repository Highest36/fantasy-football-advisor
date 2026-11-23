"""Push to a phone via Home Assistant (ephemeral token from the login flow — never persisted)."""
import os
import sys

import httpx

from . import config  # noqa: F401  (loads .env)

CLIENT = "http://fantasy-digest/"


def ha_token(base):
    with httpx.Client(base_url=base, timeout=20) as c:
        flow = c.post("/auth/login_flow", json={"client_id": CLIENT, "handler": ["homeassistant", None],
                                                "redirect_uri": CLIENT}).json()
        res = c.post(f"/auth/login_flow/{flow['flow_id']}",
                     json={"client_id": CLIENT, "username": os.environ["HA_USER"],
                           "password": os.environ["HA_PASS"]}).json()
        tok = c.post("/auth/token", data={"grant_type": "authorization_code", "code": res["result"],
                                          "client_id": CLIENT}).json()
        return tok["access_token"]


def push(title, message, url=None):
    base = os.environ["HA_URL"]
    r = httpx.post(f"{base}/api/services/notify/{os.environ['HA_NOTIFY']}",
                   headers={"Authorization": f"Bearer {ha_token(base)}"}, timeout=20,
                   json={"title": title, "message": message[:900],
                         "data": {"tag": "fantasy-digest", "group": "fantasy",
                                  **({"url": url, "clickAction": url} if url else {})}})
    r.raise_for_status()


if __name__ == "__main__":
    push(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
