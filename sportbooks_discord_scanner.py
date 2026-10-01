"""
Sportbooks latency scanner: paper-trading / measurement skeleton.

Flow: book lock + odds move -> SIGNAL -> snapshot prediction-market price at
fixed offsets (to measure real staleness) -> if still stale, PAPER entry ->
exit on target / stop / timeout. Everything is logged to JSONL.

LIVE EXECUTION IS NOT IMPLEMENTED. Run in paper mode for weeks and check
whether the edge exists in your own data before considering it.

Run the demo:  python sportbooks_scanner.py --sim
Discord:       export DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
"""
import argparse
import asyncio
import json
import os
import time
import urllib.request
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional, Protocol

# ----------------------------------------------------------------- config

@dataclass
class Config:
    lock_window_s: float = 2.0        # both books must lock within this window
    min_prob_move: float = 0.10       # implied-prob jump that marks a goal (not a corner/VAR)
    odds_lookback_s: float = 5.0      # odds move must be this recent before the lock
    confirm_delay_s: float = 10.0     # wait before checking staleness
    stale_move_c: float = 2.0         # "stale" = moved < this many cents
    max_entry_c: float = 90.0         # don't buy above this
    target_c: float = 10.0            # take profit (cents above entry)
    stop_c: float = 6.0               # stop loss (cents below entry)
    max_hold_s: float = 90.0          # time stop
    fee_c: float = 1.0                # round-trip fee/slippage guess, cents
    snapshot_offsets_s: tuple = (0, 1, 2, 3, 5, 8, 10, 15, 30)
    log_path: str = "discord_scanner_log.jsonl"
    discord_webhook: str = field(default_factory=lambda: os.getenv("DISCORD_WEBHOOK_URL", ""))
    live: bool = False                # keep False

# ------------------------------------------------------------- data types

@dataclass
class BookEvent:
    ts: float
    book: str            # "DK" | "FD"
    event_id: str
    team: str            # side the odds refer to
    status: str          # "OPEN" | "LOCKED"
    odds: Optional[int]  # American odds, None if unavailable
    sport: str = "soccer"

@dataclass
class Quote:
    ts: float
    bid_c: float
    ask_c: float
    @property
    def mid(self): return (self.bid_c + self.ask_c) / 2

class BookFeed(Protocol):
    def events(self) -> AsyncIterator[BookEvent]: ...

class MarketFeed(Protocol):
    async def quote(self, market_id: str) -> Quote: ...

# ---------------------------------------------------------------- helpers

def implied(american: int) -> float:
    return -american / (-american + 100) if american < 0 else 100 / (american + 100)

def log(cfg: Config, kind: str, **data):
    row = {"t": time.time(), "kind": kind, **data}
    with open(cfg.log_path, "a") as f:
        f.write(json.dumps(row) + "\n")

def notify(cfg: Config, text: str):
    """Post to the #sportbook-scanner Discord channel via webhook."""
    print(text)
    if not cfg.discord_webhook:
        return
    try:
        req = urllib.request.Request(
            cfg.discord_webhook,
            data=json.dumps({"content": text[:1990]}).encode(),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "sportbook-scanner/1.0",  # Discord rejects the default urllib UA
            },
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:  # never let Discord kill the scanner
        print("discord error:", e)

# --------------------------------------------------------- signal detector

class SignalDetector:
    """Lock alone is NOT a signal. Soccer requires a recent odds jump on both
    books before the lock. UFC (no odds jump needed) is flagged low confidence."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.hist: dict = {}   # (event, book) -> list[(ts, prob)]
        self.locks: dict = {}  # (event, team) -> {book: ts}
        self.fired: set = set()

    def on_event(self, e: BookEvent) -> Optional[dict]:
        key = (e.event_id, e.book)
        if e.odds is not None:
            self.hist.setdefault(key, []).append((e.ts, implied(e.odds)))
            self.hist[key] = [(t, p) for t, p in self.hist[key] if e.ts - t < 60]

        if e.status != "LOCKED":
            self.locks.pop((e.event_id, e.team), None)
            return None

        lk = self.locks.setdefault((e.event_id, e.team), {})
        lk[e.book] = e.ts
        if len(lk) < 2 or max(lk.values()) - min(lk.values()) > self.cfg.lock_window_s:
            return None
        if (e.event_id, e.team) in self.fired:
            return None

        if e.sport == "soccer":
            if not all(self._jumped(e.event_id, b, e.ts) for b in lk):
                log(self.cfg, "lock_no_jump", event=e.event_id, team=e.team)
                return None  # corner / VAR / injury style suspension
            confidence = "high"
        else:
            confidence = "low"  # UFC: lock-only

        self.fired.add((e.event_id, e.team))
        return {"event_id": e.event_id, "team": e.team, "sport": e.sport,
                "confidence": confidence, "ts": e.ts}

    def _jumped(self, event_id, book, now) -> bool:
        pts = [(t, p) for t, p in self.hist.get((event_id, book), [])
               if now - t <= self.cfg.odds_lookback_s]
        return len(pts) >= 2 and pts[-1][1] - pts[0][1] >= self.cfg.min_prob_move

# --------------------------------------------------------------- trade loop

async def handle_signal(cfg: Config, sig: dict, market: MarketFeed, market_id: str):
    team = sig["team"]
    log(cfg, "signal", **sig)
    notify(cfg, f"⚡ PASS: {team} ({sig['sport']}, {sig['confidence']} conf): books LOCKED")

    t0 = time.time()
    q0 = await market.quote(market_id)
    snaps = [{"off": 0, "mid": q0.mid, "ask": q0.ask_c}]

    # Measurement: record how the price actually moves after the signal.
    entry_quote, paper_open = None, False
    for off in cfg.snapshot_offsets_s[1:]:
        await asyncio.sleep(max(0, t0 + off - time.time()))
        q = await market.quote(market_id)
        snaps.append({"off": off, "mid": q.mid, "ask": q.ask_c})

        if not paper_open and off >= cfg.confirm_delay_s:
            moved = abs(q.mid - q0.mid)
            if moved < cfg.stale_move_c and q.ask_c <= cfg.max_entry_c:
                entry_quote, paper_open = q, True
                notify(cfg, f"PLAY (paper): BUY {team} {q.ask_c:.0f}c")
                log(cfg, "paper_entry", team=team, price=q.ask_c, snaps=snaps)
                break
            log(cfg, "no_entry", team=team, moved=moved, ask=q.ask_c, snaps=snaps)
            return

    if not paper_open:
        log(cfg, "no_entry", team=team, reason="no_confirm_window", snaps=snaps)
        return

    # Exit: target / stop / time.
    entry = entry_quote.ask_c
    t_in = time.time()
    while True:
        await asyncio.sleep(1)
        q = await market.quote(market_id)
        held = time.time() - t_in
        if q.bid_c >= entry + cfg.target_c:
            reason = "target"
        elif q.bid_c <= entry - cfg.stop_c:
            reason = "stop"
        elif held >= cfg.max_hold_s:
            reason = "time"
        else:
            continue
        pnl = q.bid_c - entry - cfg.fee_c
        notify(cfg, f"SELL ({reason}): {q.bid_c:.0f}c ({pnl:+.1f}c net of fees)")
        log(cfg, "paper_exit", team=team, reason=reason, entry=entry,
            exit=q.bid_c, pnl_c=pnl, held_s=held)
        return

async def run(cfg: Config, books: BookFeed, market: MarketFeed, market_ids: dict):
    """market_ids: {(event_id, team): 'KALSHI-OR-POLY-ID'}"""
    det = SignalDetector(cfg)
    async for e in books.events():
        log(cfg, "book_event", **e.__dict__)
        sig = det.on_event(e)
        mid = market_ids.get((e.event_id, e.team))
        if sig and mid:
            asyncio.create_task(handle_signal(cfg, sig, market, mid))

# ------------------------------------------------------- simulated feeds

class SimBooks:
    async def events(self):
        t = time.time
        yield BookEvent(t(), "DK", "m1", "Arsenal", "OPEN", -350)
        yield BookEvent(t(), "FD", "m1", "Arsenal", "OPEN", -340)
        await asyncio.sleep(1)
        yield BookEvent(t(), "DK", "m1", "Arsenal", "OPEN", -800)
        yield BookEvent(t(), "FD", "m1", "Arsenal", "OPEN", -750)
        yield BookEvent(t(), "DK", "m1", "Arsenal", "LOCKED", -800)
        await asyncio.sleep(0.4)
        yield BookEvent(t(), "FD", "m1", "Arsenal", "LOCKED", -750)
        await asyncio.sleep(120)  # keep the loop alive for the trade

class SimMarket:
    def __init__(self): self.start = time.time()
    async def quote(self, market_id):
        el = time.time() - self.start
        mid = 62 if el < 14 else 78  # reprices ~14s in
        return Quote(time.time(), mid - 1, mid + 1)

# ------------------------------------------------------ real feed stubs

class OddsFeed:
    """TODO: wrap a licensed odds provider (OpticOdds, Sportradar, etc.)
    and yield BookEvent objects. Do not scrape sportsbooks."""
    async def events(self):
        raise NotImplementedError
        yield

class KalshiMarket:
    """TODO: use Kalshi's official API for order book quotes (bid/ask in cents)."""
    async def quote(self, market_id): raise NotImplementedError

class PolymarketMarket:
    """TODO: use Polymarket's CLOB API for best bid/ask; convert to cents."""
    async def quote(self, market_id): raise NotImplementedError

# ------------------------------------------------------------------- main

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sim", action="store_true", help="run with simulated feeds")
    args = ap.parse_args()
    cfg = Config()
    if cfg.live:
        raise SystemExit("Live execution is intentionally not implemented.")
    if args.sim:
        asyncio.run(run(cfg, SimBooks(), SimMarket(), {("m1", "Arsenal"): "SIM-ARS"}))
    else:
        raise SystemExit("Wire up OddsFeed + a market feed first, or use --sim.")
