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
                print("Got 403, trying next URL")
                last_err = "403 blocked"
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            print(f"Fail: {e}")
            time.sleep(2)

    if not PROXY_URL:
        print("Trying free proxy...")
        try:
            plist = requests.get("https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=10000&country=all", timeout=10).text.splitlines()
            if plist:
                proxy = random.choice(plist).strip()
                print(f"Trying proxy {proxy}")
                proxies = {"http": "http://" + proxy, "https": "http://" + proxy}
                r = requests.get(URLS[0], headers=HEADERS, proxies=proxies, timeout=15)
                r.raise_for_status()
                return r.json()
        except Exception as e:
            print(f"Proxy failed: {e}")

    raise Exception(last_err)

def parse(data):
    cur = {}
    for item in data.get("data", []):
        try:
            _id = item["id"]
            attrs = item["attributes"]
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
                send(f"Live. Tracking {len(cur)} lines.")
            else:
                for _id, info in cur.items():
                    if _id not in seen:
                        send(f"NEW: {info['name']} - {info['desc']} {info['line']}")
                    elif info["line"]!= seen[_id]["line"]:
                        send(f"MOVE: {info['name']} {seen[_id]['line']} -> {info['line']}")
            seen = cur
        except Exception as e:
            print(f"Error: {e}")
            backoff = min(backoff * 2, 900)
        time.sleep(backoff)

if __name__ == "__main__":
    main()
