import requests
import time
import os

POLL_SECONDS = 60
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
PROXY_URL = os.getenv("PROXY_URL")

# No state_code - that's what was returning 0
URLS = [
    "https://partner-api.prizepicks.com/projections?per_page=1000&single_stat=true&game_mode=pickem",
    "https://api.prizepicks.com/projections?per_page=1000&single_stat=true",
    "https://api.prizepicks.com/projections?per_page=500&single_stat=true&game_mode=pickem",
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
if PROXY_URL:
    session.proxies = {"http": PROXY_URL, "https": PROXY_URL}

def fetch():
    for url in URLS:
        try:
            r = session.get(url, timeout=20)
            print(f"FETCH {url[:55]} -> {r.status_code} len={len(r.text)}")
            if r.status_code!= 200:
                continue
            j = r.json()
            # Only return if it actually has data
            if len(j.get('data', [])) > 0:
                print(f"FOUND {len(j.get('data', []))} projections")
                return j
            else:
                print(f"EMPTY board, trying next URL - body: {r.text[:200]}")
        except Exception as e:
            print(f"FAIL {url[:40]} -> {e}")
    raise Exception("All boards empty - PrizePicks blocking Railway IP")

def parse(data):
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
            pid = rel.get("id") if isinstance(rel, dict) else None

            if pid and pid in players:
                name = players[pid]
            else:
                name = attrs.get("description", "Unknown")

            cur[_id] = {
                "name": name,
                "desc": attrs.get("stat_display_name", attrs.get("stat_type", "")),
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
    while True:
        try:
            cur = parse(fetch())
            print(f"Initial: {len(cur)} lines tracked")
            if seen is None:
                send(f"✅ Captain Hook live. Tracking {len(cur)} lines.")
            else:
                for _id, info in cur.items():
                    if _id not in seen:
                        send(f"🆕 NEW: {info['name']} - {info['desc']} {info['line']}")
                    elif info["line"]!= seen[_id]["line"]:
                        send(f"📈 MOVE: {info['name']} {seen[_id]['line']} -> {info['line']}")
            seen = cur
        except Exception as e:
            print(f"Error: {e}")
            send(f"⚠️ Error: {e}")
        time.sleep(POLL_SECONDS)

if __name__ == "__main__":
    main()
