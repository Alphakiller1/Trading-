"""Multi-day pump.fun data collector (run on a home PC for days; the research needs walk-forward data).

What it records, rate-limit friendly (single thread, ~3 req/s, backs off on HTTP 429), resumable:
  * every launch it sees (created-timestamp listing, polled every 60s)
  * each coin's full trade tape at 2 hours after launch  -> data/raw/YYYY-MM-DD.jsonl
    (coins still active at 2h get one more capture at 24h  -> data/raw24/YYYY-MM-DD.jsonl)
  * every 5 min: a market snapshot of the 200 most recently traded coins -> data/snapshots/YYYY-MM-DD.jsonl

Usage:  cd fomo/data && python ../collector.py
Stop with Ctrl+C; pending captures are saved to pending.json and resumed on restart.
Convert to the backtest format with:  python ../collector.py --export trades.json coins.json
"""
import json, os, sys, time, requests

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36",
     "Origin": "https://pump.fun", "Referer": "https://pump.fun/"}
B = "https://frontend-api-v3.pump.fun"
CH = "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"
S = requests.Session(); S.headers.update(H)
MIN_GAP = 0.33            # seconds between requests (~3 req/s)
_last = [0.0]


def get(url, params=None):
    for i in range(6):
        wait = MIN_GAP - (time.time() - _last[0])
        if wait > 0: time.sleep(wait)
        _last[0] = time.time()
        try:
            r = S.get(url, params=params, timeout=15)
            if r.ok: return r.json()
            if r.status_code == 429: time.sleep(10 * (i + 1)); continue
            if r.status_code in (404, 400): return None
        except Exception:
            pass
        time.sleep(2 * (i + 1))
    return None


def tape(mint, max_pages=60):
    out, cur = [], None
    for _ in range(max_pages):
        p = dict(limit=100, program="pump", chainId=CH)
        if cur: p["cursor"] = cur
        d = get(f"https://swap-api.pump.fun/v2/coins/{mint}/trades", p)
        if not d: return out, False
        out += d["trades"]
        if not d["pagination"]["hasMore"]: return out, True
        cur = d["pagination"]["nextCursor"]
    return out, False


def append(folder, rec):
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, time.strftime("%Y-%m-%d", time.gmtime()) + ".jsonl"), "a") as f:
        f.write(json.dumps(rec) + "\n")


META = ("mint", "creator", "created_timestamp", "name", "symbol", "twitter", "telegram", "website", "description")


def run():
    pending = json.load(open("pending.json")) if os.path.exists("pending.json") else {}
    last_snap = 0
    while True:
        now = time.time()
        for off in (0, 50, 100):
            for c in get(f"{B}/coins", dict(offset=off, limit=50, sort="created_timestamp", order="DESC", includeNsfw="true")) or []:
                if c["mint"] not in pending and now - c["created_timestamp"] / 1000 < 3600:
                    pending[c["mint"]] = dict(meta={k: c.get(k) for k in META}, due=c["created_timestamp"] / 1000 + 7200, stage="2h")
        if now - last_snap >= 300:
            snap = []
            for off in range(0, 200, 50):
                for c in get(f"{B}/coins", dict(offset=off, limit=50, sort="last_trade_timestamp", order="DESC", includeNsfw="true")) or []:
                    snap.append({k: c.get(k) for k in ("mint", "usd_market_cap", "ath_market_cap", "complete", "reply_count", "created_timestamp")})
            append("snapshots", dict(t=now, coins=snap)); last_snap = now
        due = sorted((m for m, p in pending.items() if p["due"] <= now), key=lambda m: pending[m]["due"])[:20]
        for m in due:
            p = pending.pop(m)
            tr, full = tape(m)
            append("raw" if p["stage"] == "2h" else "raw24", dict(coin=p["meta"], stage=p["stage"], captured=time.time(), complete=full, trades=tr))
            if p["stage"] == "2h" and tr and time.time() - _ts(tr[0]["timestamp"]) < 1800:   # still trading in the last 30 min
                pending[m] = dict(meta=p["meta"], due=p["meta"]["created_timestamp"] / 1000 + 86400, stage="24h")
        json.dump(pending, open("pending.json", "w"))
        print(time.strftime("%H:%M:%S"), f"pending {len(pending)}, captured {len(due)}", flush=True)
        time.sleep(max(1, 60 - (time.time() - now)))


def _ts(s):
    import datetime as dt
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def export(trades_out, coins_out):
    """Merge raw captures (24h capture wins over 2h) into the {mint: trades} / {mint: coin} files the backtests read."""
    T, Cn = {}, {}
    for folder in ("raw", "raw24"):
        if not os.path.isdir(folder): continue
        for fn in sorted(os.listdir(folder)):
            for line in open(os.path.join(folder, fn)):
                r = json.loads(line); m = r["coin"]["mint"]
                T[m] = r["trades"]; Cn[m] = dict(r["coin"], program="pump")
    json.dump(T, open(trades_out, "w")); json.dump(Cn, open(coins_out, "w"))
    print(f"exported {len(T)} coins")


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "--export":
        export(sys.argv[2], sys.argv[3])
    else:
        try: run()
        except KeyboardInterrupt: print("stopped; pending saved")
