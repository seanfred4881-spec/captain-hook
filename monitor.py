import requests
import time
import os

POLL_SECONDS = 60
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
API_URL = "https://api.prizepicks.com/projections?per_page=250&single_stat=true"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Origin": "https://app.prizepicks.com",
    "Referer": "https://app.prizepicks.com/",
    "Accept-Language": "en-US,en;q=0.9",
}

session = requests.Session()
session.headers.update(HEADERS)

def fetch():
    r = session.get(API_URL, timeout=20)
    r.raise_for_status()
    return r.json()

def parse(data):
    cur = {}
    for item in data.get("data", []):
        try:
            _id = item["id"]
            attrs = item["attributes"]
            # this matches your original logic
            cur[_id] = {
                "name": attrs.get("new_player", {}).get("name", "Unknown"),
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
        print(f"Failed webhook: {e}")

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
