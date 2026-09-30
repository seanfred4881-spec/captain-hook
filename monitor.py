def main():
    print("Monitor started - Captain Hook")
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
