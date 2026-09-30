import requests, time, os
from datetime import datetime
from collections import defaultdict

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
    players, leagues, games = {}, {}, {}
    for inc in data.get("included", []):
        if inc.get("type") == "new_player":
            players[inc["id"]] = inc["attributes"].get("name","Unknown")
        if inc.get("type") == "league":
            leagues[inc["id"]] = inc["attributes"].get("name","")
        if inc.get("type") == "game":
            attrs = inc["attributes"]
            # Try every possible name field
            name = attrs.get("name") or attrs.get("description") or attrs.get("label") or "Soccer Match"
            games[inc["id"]] = {
                "name": name,
                "start": attrs.get("start_time") or attrs.get("game_time") or attrs.get("starts_at") or ""
            }

    cur = {}
    for item in data.get("data", []):
        try:
            attrs = item["attributes"]
            stat = str(attrs.get("stat_display_name","")).lower()
            if "pass" not in stat or "attempt" not in stat:
                continue

            league_id = item.get("relationships",{}).get("league",{}).get("data",{}).get("id")
            league_name = leagues.get(league_id, "").upper()
            if "NFL" in league_name or "CFB" in league_name or "NCAAF" in league_name or "FOOTBALL" in league_name:
                continue

            game_id = item.get("relationships",{}).get("game",{}).get("data",{}).get("id")
            game_info = games.get(game_id, {"name": league_name.title() or "Soccer Match", "start": ""})

            _id = item["id"]
            pid = item.get("relationships",{}).get("new_player",{}).get("data",{}).get("id")

            cur[_id] = {
                "name": players.get(pid, attrs.get("description","Unknown")),
                "line": attrs.get("line_score",0),
                "league": league_name,
                "game_id": game_id,
                "game_name": game_info["name"],
                "game_start": game_info["start"]
            }
        except:
            continue
    return cur

def format_start_time(iso_str):
    if not iso_str:
        return "TBD"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z","+00:00"))
        return dt.strftime("%A, %B %d, %Y at %I:%M %p")
    except:
        return iso_str

def send_grouped_embeds(new_props):
    if not WEBHOOK_URL or not new_props:
        return

    grouped = defaultdict(list)
    for info in new_props:
        grouped[info["game_name"]].append(info)

    for game_name, props in grouped.items():
        start_str = format_start_time(props[0].get("game_start",""))
        lines_text = "\n".join([f"{p['name']} — Passes `{p['line']}`" for p in props])

        embed = {
            "title": "🚨 PrizePicks — SOCCER PASSES ARE UP",
            "description": f"**{game_name}**\n{lines_text}",
            "color": 3066993, # green
            "fields": [
                {
                    "name": "Starts",
                    "value": start_str,
                    "inline": False
                }
            ],
            "footer": {
                "text": f"PrizePicks • {len(props)} prop(s)"
            },
            "timestamp": datetime.utcnow().isoformat()
        }

        payload = {
            "username": "PrizePicks",
            "embeds": [embed]
        }
        requests.post(WEBHOOK_URL, json=payload, timeout=10)

def main():
    print("Captain Hook - SOCCER Passes Attempted ONLY - EMBED MODE V2")
    seen = parse(fetch())
    print(f"Initial tracking {len(seen)} SOCCER passes lines - NFL BLOCKED")
    if WEBHOOK_URL:
        requests.post(WEBHOOK_URL, json={"content": f"✅ Hook V2 live: Tracking {len(seen)} SOCCER Passes ONLY. Box format fixed."}, timeout=10)

    while True:
        time.sleep(60)
        try:
            cur = parse(fetch())
            new_to_send = []
            for _id, info in cur.items():
                if _id not in seen:
                    new_to_send.append(info)
                elif info["line"]!= seen[_id]["line"]:
                    # line bump
                    copy = info.copy()
                    copy["name"] = f"📈 {info['name']} {seen[_id]['line']} -> {info['line']}"
                    new_to_send.append(copy)

            if new_to_send:
                send_grouped_embeds(new_to_send)

            seen = cur
            print(f"Checked {len(cur)} soccer lines")
        except Exception as e:
            print(f"Error {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
