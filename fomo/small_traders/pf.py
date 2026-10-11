"""Shared pump.fun public-API helpers for the memecoin research (read-only)."""
import time, json, os, requests

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36",
     "Origin": "https://pump.fun", "Referer": "https://pump.fun/"}
FE = "https://frontend-api-v3.pump.fun"
SW = "https://swap-api.pump.fun"
CHAIN = "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"
S = requests.Session(); S.headers.update(H)


MIN_GAP = 1.5          # seconds between requests: Cloudflare 429s the session above ~1-2 req/s
_last = [0.0]


def get(url, params=None, tries=8):
    for i in range(tries):
        wait = _last[0] + MIN_GAP - time.time()
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        try:
            r = S.get(url, params=params, timeout=15)
            if r.status_code == 429:
                time.sleep(60); continue   # Cloudflare edge throttle (HTML body)
            if r.status_code >= 500:
                time.sleep(2 * (i + 1)); continue
            if r.ok:
                return r.json()
            return None
        except Exception:
            time.sleep(2 * (i + 1))
    return None


def list_coins(sort, max_offset=2000):
    out = []
    for off in range(0, max_offset, 50):
        d = get(f"{FE}/coins", dict(offset=off, limit=50, sort=sort, order="DESC", includeNsfw="true"))
        if not d:
            break
        out += d
    return out


def coin_trades(mint, max_pages=40):
    """Full trade tape, newest first from the API; returned oldest-first."""
    trades, cursor, failed = [], None, False
    for _ in range(max_pages):
        p = dict(limit=100, program="pump", chainId=CHAIN)
        if cursor:
            p["cursor"] = cursor
        d = get(f"{SW}/v2/coins/{mint}/trades", p)
        if not d:
            failed = True   # a page never came back: the tape is incomplete, not finished
            break
        trades += d.get("trades", [])
        pg = d.get("pagination", {})
        if not pg.get("hasMore"):
            break
        cursor = pg.get("nextCursor")
    slim = [dict(ts=t["timestamp"], w=t["userAddress"], side=t["type"], usd=float(t["amountUsd"]),
                 sol=float(t["amountSol"] or 0), px=float(t["priceUsd"]), tx=t["tx"]) for t in trades
            if t.get("amountUsd") is not None and t.get("priceUsd") is not None]
    slim.reverse()
    return slim, failed or len(trades) >= max_pages * 100


def portfolio(wallet, pages=5):
    pos = []
    for pg in range(pages):
        d = get(f"{FE}/user-portfolio/{wallet}", dict(filter="all", page=pg, pageSize=100, sortBy="PNL"))
        if not d or not d.get("positions"):
            break
        for p in d["positions"]:
            p.pop("callout", None)
            c = p.get("coin") or {}
            pos.append({k: p.get(k) for k in ("coinMint", "chainId", "isExited", "pnlUsd", "pnlPercentage", "costBasisUsd",
                                              "amountBoughtUsd", "amountBought", "realizedPnlUsd", "valueUsd", "openedAt", "updatedAt",
                                              "hasTransfers", "likelyLost", "hasUntrustedUsdBasis", "potentialSpam")}
                       | {"mcap_now": c.get("marketCapUsd"), "program": c.get("program"), "symbol": c.get("symbol")})
        if len(d["positions"]) < 100:
            break
    return pos


def summary(wallet, period):
    return get(f"{FE}/portfolio-summary", dict(user=wallet, period=period))
