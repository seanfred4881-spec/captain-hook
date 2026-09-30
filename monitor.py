import requests
import time
import os

POLL_SECONDS = 60
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

URLS = [
    "https://partner-api.prizepicks.com/projections?per_page=250&single_stat=true&state_code=MA&game_mode=pickem",
    "https://api.prizepicks.com/projections?per_page=250&single_stat=true",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Origin": "https://app.prizepicks.com",
    "Referer": "https://app.prizepicks.com/",
}

session = requests.Session()
session.headers.update(HEADERS)

def fetch():
    for url in URLS:
        r = session.get(url, timeout=20)
        print(f"FETCH {url[:50]} -> {r.status_code} len={len(r.text)}")
        if r.status_code == 200:
            return r.json()
    raise Exception("All URLs failed")

def parse(data):
    print(f"DEBUG keys: {list(data.keys())}")
    print(f"DEBUG data len: {len(data.get('data', []))}")
    print(f"DEBUG included len: {len(data.get('included', []))}")
    if data.get('data'):
        print(f"DEBUG first item: {str(data['data'][0])[:500]}")

    cur = {}
    players = {}
    for inc in data.get("included", []):
        if inc.get("type") == "new_player":
            players[inc["id"]] = inc["attributes"].get("name", "Unknown")

    for item in data.get("data", []):
        try:
            _id = item["id"]
            attrs = item["attributes"]
            rel = item.get("relationships", {}).get("new_player", {}).get("data", {})
            player_id = rel.get("id") if isinstance(rel, dict) else None
            name = players.get(player_id, "Unknown") if player_id else attrs.get("description", "Unknown")

            cur[_id] = {
                "name": name,
                "desc": attrs.get("stat_display_name", ""),
                "line": attrs.get("line_score", 0)
            }
        except Exception as e:
            print(f"parse error: {e}")
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
            print(f"Initial: {len(cur)} lines tracked")
            if seen is None:
                send(f"✅ Captain Hook live. Tracking {len(cur)} lines.")
            seen = cur
            backoff = POLL_SECONDS
        except Exception as e:
            print(f"Error: {e}")
            backoff = min(backoff * 2, 900)
        time.sleep(backoff)

if __name__ == "__main__":
    main()
