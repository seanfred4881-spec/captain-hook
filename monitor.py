import requests
import time
import os
import random

POLL_SECONDS = 60
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

URLS = [
    "https://partner-api.prizepicks.com/projections?per_page=250&single_stat=true&state_code=MA&game_mode=pickem",
    "https://api.prizepicks.com/projections?per_page=250&single_stat=true",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://app.prizepicks.com",
    "Referer": "https://app.prizepicks.com/",
}

session = requests.Session()
session.headers.update(HEADERS)

PROXY_URL = os.getenv("PROXY_URL")
if PROXY_URL:
    session.proxies = {"http": PROXY_URL, "https": PROXY_URL}

def fetch():
    last_err = None
    for url in URLS:
        try:
            r = session.get(url, timeout=20)
            if r.status_code == 403:
                print(f"Got 403 on {url[:40]}")
                last_err = "403"
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            print(f"Fetch fail: {e}")
            time.sleep(2)
    raise Exception(last_err or "All fetch failed")

def parse(data):
    cur = {}
    # Prizepicks puts player names in "included"
    players = {}
    for inc in data.get("included", []):
        if inc.get("type") == "new_player":
            players[inc["id"]] = inc["attributes"].get("name", "Unknown")

    for item in data.get("data", []):
        try:
            _id = item["id"]
            attrs = item["attributes"]
            rel = item.get("relationships", {}).get("new_player", {}).get("data", {})
            player_id = rel.get("id")
            name = players.get(player_id, "Unknown")

            cur[_id] = {
                "name": name,
                "desc": attrs.get("stat_display_name", ""),
                "line": attrs.get("line_score", 0)
            }
        except:
            continue
    return cur

def send(msg):
    if not WEBHOOK_URL:
        print(msg)
        return
    try:
        requests.post(WEBHOOK_URL, json={"content": msg}, timeout=10)
    except Exception as e:
        print(f"Webhook fail: {e}")

def main():
    print("Monitor started - Captain Hook 1554656337005125693")
    seen = None
    backoff = POLL_SECONDS
    while True:
        try:
            cur = parse(fetch())
            backoff = POLL_SECONDS
            if seen is None:
                print(f"Initial: {len(cur)} lines tracked")
                send(f"✅ Captain Hook live. Tracking {len(cur)} lines.")
            else:
                for _id, info in cur.items():
                    if _id not in seen:
                        send(f"🆕 NEW: {info['name']} - {info['desc']} {info['line']}")
                    elif info["line"] != seen[_id]["line"]:
                        send(f"📈 MOVE: {info['name']} {seen[_id]['line']} -> {info['line']}")
            seen = cur
        except Exception as e:
            print(f"Error: {e}")
            backoff = min(backoff * 2, 900)
        time.sleep(backoff)

if __name__ == "__main__":
    main()
