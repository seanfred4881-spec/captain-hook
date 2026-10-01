import json
import os
import time
import urllib.request

url = os.getenv("DISCORD_WEBHOOK_URL", "")
if not url:
    print("DISCORD_WEBHOOK_URL is not set")
else:
    req = urllib.request.Request(
        url,
        data=json.dumps({"content": "✅ Sportbooks scanner webhook test OK"}).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "sportbook-scanner/1.0"},
    )
    try:
        urllib.request.urlopen(req, timeout=10)
        print("Sent test message")
    except Exception as e:
        print("Failed:", e)

while True:
    time.sleep(3600)
