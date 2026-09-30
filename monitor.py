import requests
import time
import os
import random

POLL_SECONDS = 60
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

# Try partner API first, it's less blocked
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
    "Sec-Ch-Ua": '"Not/A)Brand";v="8", "Chromium";v="126", "Google Chrome";v="126"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
}

session = requests.Session()
session.headers.update(HEADERS)

# Optional: add a proxy if you have one. 
# In Railway -> Variables -> Add PROXY_URL = http://user:pass@ip:port
PROXY_URL = os.getenv("PROXY_URL")
if PROXY_URL:
    session.proxies = {"http": PROXY_URL, "https": PROXY_URL}
    print(f"Using proxy: {PROXY_URL[:20]}...")

def fetch():
    last_err = None
    for url in URLS:
        try:
            r = session.get(url, timeout=20)
            if r.status_code == 403:
                print(f"403 on
