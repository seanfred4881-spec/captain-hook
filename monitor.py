"""PrizePicks soccer 'Passes Attempted' alerts.
Alerts (via Discord webhook) when:
  1. A NEW Passes Attempted line is posted ("dropped")
  2. An existing line MOVES (bumped up or down)
"""
import os
import time
import requests
WEBHOOK = os.environ["DISCORD_WEBHOOK_URL"]
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "60"))
LEAGUE_ID = os.getenv("LEAGUE_ID", "82")  # 82 = soccer (verify if it stops working)
PROXY = os.getenv("PROXY_URL")  # optional, see README
PLAYER_FILTER = [p.strip().lower() for p in os.getenv("PLAYERS", "").split(",") if p.strip()]
URL = "https://api.prizepicks.com/projections"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": "https://app.prizepicks.com/",
    "Origin": "https://app.prizepicks.com",
}
def notify(msg: str):
    try:
        requests.post(WEBHOOK, json={"content": msg}, timeout=10)
    except Exception as e:
        print("notify failed:", e)
def fetch():
    params = {"league_id": LEAGUE_ID, "per_page": 250, "single_stat": "true"}
    proxies = {"http": PROXY, "https": PROXY} if PROXY else None
    r = requests.get(URL, params=params, headers=HEADERS, proxies=proxies, timeout=20)
    r.raise_for_status()
    return r.json()
def parse(data):
    players = {}
    for inc in data.get("included", []):
        if inc.get("type") == "new_player":
            a = inc["attributes"]
            players[inc["id"]] = f'{a.get("display_name")} ({a.get("team", "?")})'
  out = {}
    for p in data.get("data", []):
        a = p["attributes"]
        stat = (a.get("stat_type") or a.get("stat_display_name") or "").lower()
        if "pass" not in stat or "attempt" not in stat:
            continue
        if a.get("odds_type", "standard") != "standard":
            continue  # skip demons/goblins
        pid = p["relationships"]["new_player"]["data"]["id"]
        name = players.get(pid, "Unknown")
        if PLAYER_FILTER and not any(f in name.lower() for f in PLAYER_FILTER):
            continue
        out[p["id"]] = {
            "name": name,
            "line": float(a["line_score"]),
            "start": a.get("start_time", ""),
            "desc": a.get("description", ""),
        }
        return out
def main():
    seen = None
    backoff = POLL_SECONDS
    print("Monitor started")
    while True:
        try:
            current = parse(fetch())
            backoff = POLL_SECONDS
            if seen is None:
                print(f"Seeded with {len(current)} lines (no alerts on first run)")
                notify(f"✅ PrizePicks monitor is live. Tracking {len(current)} soccer Passes Attempted lines.")
            else:
                for pid, cur in current.items():
                    old = seen.get(pid)
                    if old is None:
                        notify(f"🆕 **New line dropped**\n{cur['name']} vs {cur['desc']}\n"
                               f"Passes Attempted: **{cur['line']}**")
                    elif cur["line"] != old["line"]:
                        arrow = "⬆️ Bumped up" if cur["line"] > old["line"] else "⬇️ Dropped"
                        notify(f"{arrow}\n{cur['name']} vs {cur['desc']}\n"
                               f"Passes Attempted: {old['line']} → **{cur['line']}**")
            seen = current
        except requests.HTTPError as e:
            code = e.response.status_code
            print("HTTP error", code)
            if code in (403, 429):
                backoff = min(backoff * 2, 900)
                if code == 403:
                    print("Blocked by PrizePicks - see README about PROXY_URL")
        except Exception as e:
            print("error:", e)
        time.sleep(backoff)
if __name__ == "__main__":
    main()
