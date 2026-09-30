import requests, time, os

WEBHOOK_URL = os.getenv("WEBHOOK_URL")
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Origin": "https://app.prizepicks.com",
    "Referer": "https://app.prizepicks.com/",
}
session = requests.Session()
session.headers.update(HEADERS)

URL = "https://partner-api.prizepicks.com/projections?per_page=1000&single_stat=true&game_mode=pickem"

def fetch():
    r = session.get(URL, timeout=20)
    return r.json()

def parse(data):
    players, leagues = {}, {}
    for inc in data.get("included", []):
        if inc.get("type") == "new_player":
            players[inc["id"]] = inc["attributes"].get("name","Unknown")
        if inc.get("type") == "league":
            leagues[inc["id"]] = inc["attributes"].get("name","")

    cur = {}
    for item in data.get("data", []):
        try:
            attrs = item["attributes"]
            stat = str(attrs.get("stat_display_name","")).lower()
            if "pass" not in stat or "attempt" not in stat:
                continue

            league_id = item.get("relationships",{}).get("league",{}).get("data",{}).get("id")
            league_name = leagues.get(league_id, "UNK")

            _id = item["id"]
            pid = item.get("relationships",{}).get("new_player",{}).get("data",{}).get("id")
            cur[_id] = {
                "name": players.get(pid, attrs.get("description","Unknown")),
                "line": attrs.get("line_score",0),
                "league": league_name
            }
        except: continue
    return cur

def send(msg):
    if WEBHOOK_URL:
        requests.post(WEBHOOK_URL, json={"content": msg}, timeout=10)

def main():
    print("Captain Hook - Passes Attempted w/ League Tag")
    seen = parse(fetch())
    print(f"Initial tracking {len(seen)} passes lines")
    send(f"✅ Hook live: Tracking {len(seen)} Passes Attempted lines [NFL + SOCCER]. Will show league tag.")

    while True:
        time.sleep(60)
        try:
            cur = parse(fetch())
            for _id, info in cur.items():
                if _id not in seen:
                    send(f"🆕 NEW: {info['name']} {info['line']} Passes Attempted [{info['league']}]")
                elif info["line"] != seen[_id]["line"]:
                    send(f"📈 BUMP: {info['name']} {seen[_id]['line']} -> {info['line']} Passes Attempted [{info['league']}]")
            seen = cur
            print(f"Checked {len(cur)} passes lines")
        except Exception as e:
            print(f"Error {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
