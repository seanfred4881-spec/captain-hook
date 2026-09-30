import requests, time, os

POLL_SECONDS = 60
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

URLS = [
    "https://partner-api.prizepicks.com/projections?per_page=1000&single_stat=true&game_mode=pickem",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Origin": "https://app.prizepicks.com",
    "Referer": "https://app.prizepicks.com/",
}
session = requests.Session()
session.headers.update(HEADERS)

def fetch():
    r = session.get(URLS[0], timeout=20)
    print(f"FETCH -> {r.status_code} len={len(r.text)}")
    j = r.json()
    print(f"FOUND {len(j.get('data',[]))}")
    return j

def parse(data):
    cur = {}
    players = {}
    for inc in data.get("included", []):
        if inc.get("type") == "new_player":
            players[inc["id"]] = inc["attributes"].get("name")
    for item in data.get("data", []):
        try:
            _id = item["id"]
            attrs = item["attributes"]
            rel = item.get("relationships", {}).get("new_player", {}).get("data", {})
            pid = rel.get("id") if isinstance(rel, dict) else None
            name = players.get(pid, attrs.get("description","Unknown"))
            cur[_id] = {"name": name, "desc": attrs.get("stat_display_name",""), "line": attrs.get("line_score",0)}
        except: continue
    return cur

def send(msg):
    print(f"DEBUG WEBHOOK_URL set? {bool(WEBHOOK_URL)} len={len(WEBHOOK_URL) if WEBHOOK_URL else 0}")
    if WEBHOOK_URL:
        print(f"DEBUG WEBHOOK start: {WEBHOOK_URL[:35]}...")
    if not WEBHOOK_URL:
        print(f"WOULD SEND (no webhook): {msg}")
        return
    try:
        resp = requests.post(WEBHOOK_URL, json={"content": msg}, timeout=10)
        print(f"DISCORD RESPONSE: {resp.status_code} - {resp.text[:200]}")
    except Exception as e:
        print(f"Webhook fail: {e}")

def main():
    print("Monitor started - Captain Hook 1554656337005125693")
    if not WEBHOOK_URL:
        print("!!! NO WEBHOOK_URL FOUND IN VARIABLES!!!")
    else:
        print(f"Webhook loaded: {WEBHOOK_URL[:35]}...")

    cur = parse(fetch())
    print(f"Initial: {len(cur)} lines tracked")
    send(f"✅ Captain Hook live. Tracking {len(cur)} lines. Test @ 07:23 AM")

    seen = cur
    while True:
        time.sleep(POLL_SECONDS)
        try:
            cur = parse(fetch())
            for _id, info in cur.items():
                if _id not in seen:
                    send(f"🆕 NEW: {info['name']} - {info['desc']} {info['line']}")
                elif info["line"]!= seen[_id]["line"]:
                    send(f"📈 MOVE: {info['name']} {seen[_id]['line']} -> {info['line']}")
            seen = cur
            print(f"Checked - still {len(cur)} lines")
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
