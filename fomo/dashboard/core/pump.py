"""pump.fun public API (read-only) + the fee/slippage model from fomo/small_traders."""
import threading, time, requests

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36",
     "Origin": "https://pump.fun", "Referer": "https://pump.fun/"}
FE = "https://frontend-api-v3.pump.fun"
SW = "https://swap-api.pump.fun"
CHAIN = "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"
S = requests.Session(); S.headers.update(H)

MIN_GAP = 1.0                      # pump.fun's Cloudflare layer throttles bursts (HTML 429)
_gap_lock = threading.Lock(); _last = [0.0]
health = {"throttled_until": 0.0, "last_ok": 0.0, "errors": 0}


def get(url, params=None, tries=3):
    if time.time() < health["throttled_until"]:
        return None
    for i in range(tries):
        with _gap_lock:
            wait = _last[0] + MIN_GAP - time.time()
            if wait > 0:
                time.sleep(wait)
            _last[0] = time.time()
        try:
            r = S.get(url, params=params, timeout=12)
            if r.status_code == 429:
                health["throttled_until"] = time.time() + 90
                health["errors"] += 1
                return None
            if r.status_code >= 500:
                time.sleep(1.5 * (i + 1)); continue
            if r.ok:
                health["last_ok"] = time.time()
                return r.json()
            return None
        except Exception:
            health["errors"] += 1
            time.sleep(1.5 * (i + 1))
    return None


_sol = {"px": 110.0, "t": 0}


def sol_price():
    if time.time() - _sol["t"] > 60:
        d = get(f"{FE}/sol-price")
        if d and d.get("solPrice"):
            _sol.update(px=float(d["solPrice"]), t=time.time())
    return _sol["px"]


_coin_cache = {}


def coin(mint, max_age=8):
    c = _coin_cache.get(mint)
    if c and time.time() - c[0] < max_age:
        return c[1]
    d = get(f"{FE}/coins-v3/{mint}")
    if d and isinstance(d, dict) and d.get("mint"):
        _coin_cache[mint] = (time.time(), d)
        return d
    return c[1] if c else None


_dex_cache = {}


def dex_mcap(mint, max_age=8):
    """Market cap from DexScreener. pump.fun's coin endpoint keeps the stale bonding-curve value
    after a coin graduates (e.g. $4.4k shown for a $533k coin), so graduated coins price here."""
    c = _dex_cache.get(mint)
    if c and time.time() - c[0] < max_age:
        return c[1]
    try:
        r = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{mint}", timeout=10)
        pairs = (r.json() or {}).get("pairs") or []
        pairs = [x for x in pairs if x.get("chainId") == "solana"]
        if not pairs:
            return None
        best = max(pairs, key=lambda x: (x.get("liquidity") or {}).get("usd") or 0)
        v = best.get("marketCap") or best.get("fdv")
        v = float(v) if v else None
        _dex_cache[mint] = (time.time(), v)
        return v
    except Exception:
        return None


def mcap(mint, max_age=8):
    d = coin(mint, max_age)
    if d and d.get("complete"):
        return dex_mcap(mint, max_age) or (float(d["usd_market_cap"]) if d.get("usd_market_cap") else None)
    return float(d["usd_market_cap"]) if d and d.get("usd_market_cap") else None


def trades(mint, pages=2):
    """Latest trades, oldest first. Returns (trades, reached_start)."""
    out, cursor, start = [], None, False
    for _ in range(pages):
        p = dict(limit=100, program="pump", chainId=CHAIN)
        if cursor:
            p["cursor"] = cursor
        d = get(f"{SW}/v2/coins/{mint}/trades", p)
        if not d:
            break
        out += d.get("trades", [])
        pg = d.get("pagination", {})
        if not pg.get("hasMore"):
            start = True
            break
        cursor = pg.get("nextCursor")
    rows = []
    for t in out:
        if t.get("amountUsd") is None or t.get("priceUsd") is None:
            continue
        rows.append(dict(t=_ts(t["timestamp"]), w=t["userAddress"], side=t["type"],
                         usd=float(t["amountUsd"]), px=float(t["priceUsd"])))
    rows.reverse()
    return rows, start


def portfolio(wallet, pages=10):
    pos = []
    for pg in range(pages):
        d = get(f"{FE}/user-portfolio/{wallet}", dict(filter="all", page=pg, pageSize=100, sortBy="PNL"))
        if not d or not d.get("positions"):
            break
        pos += d["positions"]
        if len(d["positions"]) < 100:
            break
    return pos


def portfolio_summary(wallet, period="1w"):
    return get(f"{FE}/portfolio-summary", dict(user=wallet, period=period))


def _ts(s):
    import datetime as dt
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


# ---- costs: fomo fee tiers + pump.fun fee + constant-product slippage ----
K = 30 * 1.073e9
PUMP_FEE = 0.0125


def fomo_fee(usd):
    if usd < 5: return 0.10
    if usd < 47.5: return usd * 0.02
    if usd < 190: return 0.95
    return usd * 0.005


def buy_fill(usd, px, sol=None):
    """(tokens, lift) for a buy of `usd` at token price `px` (USD)."""
    sol = sol or sol_price()
    x = (usd - fomo_fee(usd)) * (1 - PUMP_FEE) / sol
    vS = (px / sol * K) ** 0.5; vT = K / vS
    return vT - K / (vS + x), ((vS + x) / vS) ** 2


def sell_value(tokens, px, lift=1.0, sol=None):
    sol = sol or sol_price()
    p = px * lift
    vS = (p / sol * K) ** 0.5; vT = K / vS
    usd = (vS - K / (vT + tokens)) * sol * (1 - PUMP_FEE)
    return usd - fomo_fee(usd)


def round_trip_cost(usd, mcap_usd=20000):
    px = mcap_usd / 1e9
    tok, lift = buy_fill(usd, px)
    return 1 - sell_value(tok, px, lift) / usd
