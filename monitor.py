"""PrizePicks soccer 'Passes Attempted
Alerts (via Discord webhook) when:
    1. A NEW Passes Attempted line is po
    2. An existing line MOVES (bumped up
"""

import os
import time
import requests

WEBHOOK = os.environ["DISCORD_WEBHOOK_URL"]
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "60"))
LEAGUE_ID = os.getenv("LEAGUE_ID", "82")
PROXY = os.getenv("PROXY_URL")  # optional
PLAYER_FILTER = [p.strip().lower() for p in os.getenv("PLAYER_FILTER", "").split(",") if p.strip()]
URL = f"https://api.prizepicks.com/projections?league_id={LEAGUE_ID}&per_page=250&single_stat=true"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Origin": "https://app.prizepicks.com",
    "Referer": "https://app.prizepicks.com/"
}

def fetch():
    kwargs = {"headers": HEADERS, "timeout": 15}
    if PROXY:
        kwargs["proxies"] = {"http": PROXY, "https": PROXY}
    r = requests.get(URL, **kwargs)
    r.raise_for_status()
    return r.json()

def parse(data):
    players = {}
    for inc in data.get("included", []):
        if inc.get("type") == "new_player":
            a = inc["attributes"]
            players[inc["id"]] = f'{a.get("name")}'

    out = {}
    for p in data.get("data", []):
        a = p["attributes"]
        stat = (a.get("stat_type") or "").lower()
        if "pass" not in stat or "atte" not in stat:
            continue
        if a.get("odds_type", "standard") != "standard":
            continue
        pid = p["relationships"]["new_player"]["data"]["id"]
        name = players.get(pid, "Unknown")
        if PLAYER_FILTER and not any(f in name.lower() for f in PLAYER_FILTER):
            continue
        out[p["id"]] = {
            "name": name,
            "line": float(a["line_score"]),
            "start": a.get("start_time"),
            "desc": a.get("description", "Passes Attempted")
        }
    return out

def send(msg):
    requests.post(WEBHOOK, json={"content": msg}, timeout=10)

def main():
    print("Monitor started - Captain Hook 1554656337005125693")
    backoff = POLL_SECONDS

    # FIX: Load first board silently so it doesn't spam 8x on start
    try:
        seen = parse(fetch())
        print(f"Initial: {len(seen)} lines tracked")
    except Exception as e:
        print(f"Initial fetch failed: {e}")
        seen = {}
    
    while True:
        try:
            cur = parse(fetch())

            for _id, info in cur.items():
                if _id not in seen:
                    send(f"🆕 NEW: {info['name']} - {info['desc']} {info['line']}")
                elif cur[_id]["line"] != seen[_id]["line"]:
                    send(f"📈 MOVE: {info['name']} {seen[_id]['line']} -> {info['line']}")

            seen = cur
            time.sleep(POLL_SECONDS)

        except Exception as e:
            print(f"Error: {e}")
            time.sleep(backoff)

if __name__ == "__main__":
    main()
