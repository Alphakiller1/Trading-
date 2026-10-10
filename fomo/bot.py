"""fomo copy-signal alert bot (strategy v4). Alerts only: it never trades and never touches keys.

Signal (all must hold):
  * a "proven" wallet makes its FIRST buy on a pump.fun coin. Proven means: profitable on >=3 past coins,
    max buy <= $1k, median hold >= 20s, not blacklisted. Learned from data/positions.json (built by wallets.py).
  * coin market cap $5k-$200k, the full trade history is loadable, and the price is within +/-15% of the trigger
  * bundle filter: top-3 wallets bought <= 60% of buy USD in the coin's first 30 trades
  * the dev (creator) has not sold
Exit alerts:
  * before the leader sells: STOP at -30% from entry
  * leader sells -> SELL HALF; then TRAIL the rest 30% from its peak
  * TIME: 2 hours
Suggested size: $190-$250 (fomo's 0.5% fee tier). Act within ~30s of an alert; the edge fades after that.

Setup:
  pip install requests
  set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID (or DISCORD_WEBHOOK_URL) as environment variables
  python bot.py            # from fomo/data/, with positions.json present
Paper results are appended to paper_trades.csv either way.
"""
import os, sys, time, json, csv, math, threading, collections, statistics as st, datetime as dt
import requests
import concurrent.futures as cf

H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36",
     "Origin": "https://pump.fun", "Referer": "https://pump.fun/"}
B = "https://frontend-api-v3.pump.fun"
CH = "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"
MC_LO, MC_HI = 5_000, 200_000
CONC_MAX = 0.60
STOP, TRAIL, TMAX = 0.30, 0.30, 7200
FRESH_S = 120          # trigger must be at most this old
LAT = 15               # assumed human reaction time used for paper fills
SIZE = 250
S = requests.Session(); S.headers.update(H)
lock = threading.Lock()


# ---------- notifications ----------
def notify(text):
    print(time.strftime("%H:%M:%S"), text, flush=True)
    tok, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    hook = os.getenv("DISCORD_WEBHOOK_URL")
    try:
        if tok and chat:
            requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                          json={"chat_id": chat, "text": text, "disable_web_page_preview": True}, timeout=10)
        if hook:
            requests.post(hook, json={"content": text}, timeout=10)
    except Exception as e:
        print("notify failed:", e, flush=True)


# ---------- data ----------
def get(url, params=None):
    for i in range(3):
        try:
            r = S.get(url, params=params, timeout=10)
            if r.ok:
                return r.json()
            if r.status_code == 429:
                time.sleep(1.5 * (i + 1)); continue
        except Exception:
            pass
        time.sleep(1 + i)
    return None


def trades(mint, pages=1):
    """Newest-first trades. Returns (trades, complete_history)."""
    out, cur = [], None
    for _ in range(pages):
        p = dict(limit=100, program="pump", chainId=CH)
        if cur: p["cursor"] = cur
        d = get(f"https://swap-api.pump.fun/v2/coins/{mint}/trades", p)
        if not d: return out, False
        out += d["trades"]
        if not d["pagination"]["hasMore"]: return out, True
        cur = d["pagination"]["nextCursor"]
    return out, False


def sec(s): return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def proven_wallets(path="positions.json", blacklist="blacklist.txt"):
    pos = json.load(open(path))
    bl = set(l.strip() for l in open(blacklist)) if os.path.exists(blacklist) else set()
    acc = collections.defaultdict(lambda: [0, 0.0, 0.0, []])
    for p in pos:
        if p["dev"] or p["max_buy"] > 1000: continue
        a = acc[p["w"]]; a[0] += 1; a[1] += p["pnl"]; a[2] += p["buy_usd"]; a[3].append(p["hold"])
    return {w for w, a in acc.items() if w not in bl and a[0] >= 3 and a[2] > 0 and a[1] / a[2] > 0 and st.median(a[3]) >= 20}


# ---------- cost model for paper P&L ----------
SOL, K = 110.0, 20.27 * 1.066e9
def fee(u): return 0.10 if u < 5 else u * 0.02 if u < 47.5 else 0.95 if u < 190 else u * 0.005
def paper_pnl(size, entry_mc, exit_mc):
    x = (size - fee(size)) * 0.99 / SOL; vS = math.sqrt(entry_mc / 1e9 / SOL * K); vT = K / vS
    tok = vT - K / (vS + x); lift = ((vS + x) / vS) ** 2
    p = exit_mc / 1e9 * lift; vS2 = math.sqrt(p / SOL * K); vT2 = K / vS2
    u = (vS2 - K / (vT2 + tok)) * SOL * 0.99
    return u - fee(u) - size


# ---------- signal ----------
CACHE = {}   # mint -> dict(conc, devsold, buyers:set, last_slot, ok)

def check(coin, smart, now):
    """Incremental: full history is loaded once per coin; later passes only read the newest 100 trades."""
    mint = coin["mint"]; mc = coin.get("usd_market_cap") or 0
    if not (MC_LO <= mc <= MC_HI): return None
    recent, _ = trades(mint, pages=1)
    recent = sorted([t for t in recent if t.get("priceUsd")], key=lambda t: t["slotIndexId"])
    if not recent: return None
    st_ = CACHE.get(mint)
    if st_ is None:
        # only pay for the full history when a proven wallet has just bought
        if not any(t["type"] == "buy" and t["userAddress"] in smart and now - sec(t["timestamp"]) <= FRESH_S for t in recent):
            return None
        tr, full = trades(mint, pages=10)          # <=1000 trades, same universe as the backtest
        if not full:
            CACHE[mint] = dict(ok=False); return None
        tr = sorted([t for t in tr if t.get("priceUsd")], key=lambda t: t["slotIndexId"])
        eb = collections.Counter()
        for t in tr[:30]:
            if t["type"] == "buy": eb[t["userAddress"]] += float(t["amountUsd"] or 0)
        tot = sum(eb.values())
        conc = sum(v for _, v in eb.most_common(3)) / tot if tot else 1
        creator = coin.get("creator")
        st_ = CACHE[mint] = dict(ok=True, conc=conc, creator=creator, devsold=False, buyers=set(), last_slot="")
        new = tr
    else:
        if not st_["ok"]: return None
        new = [t for t in recent if t["slotIndexId"] > st_["last_slot"]]
    first = None
    for t in new:
        w = t["userAddress"]
        if w == st_["creator"] and t["type"] == "sell": st_["devsold"] = True
        if t["type"] == "buy":
            if first is None and w in smart and w not in st_["buyers"]: first = t
            st_["buyers"].add(w)
    st_["last_slot"] = max(st_["last_slot"], recent[-1]["slotIndexId"])
    if st_["devsold"] or st_["conc"] > CONC_MAX or not first: return None
    if now - sec(first["timestamp"]) > FRESH_S: return None
    trig = float(first["priceUsd"]) * 1e9; cur = float(recent[-1]["priceUsd"]) * 1e9
    if not (0.85 * trig <= cur <= 1.15 * trig): return None
    return dict(mint=mint, sym=coin.get("symbol"), leader=first["userAddress"], trig=trig, cur=cur,
                lead_usd=float(first["amountUsd"] or 0))


# ---------- position tracking ----------
def track(sig):
    m, sym, leader = sig["mint"], sig["sym"], sig["leader"]
    time.sleep(LAT)
    tr, _ = trades(m)
    if not tr: return
    entry = float(tr[0]["priceUsd"]) * 1e9
    t0 = time.time(); half_at = None; hi = entry; why = "TIME"; ex = entry
    while time.time() - t0 < TMAX:
        time.sleep(5)
        tr, _ = trades(m)
        tr = [t for t in tr if t.get("priceUsd")]
        if not tr: continue
        ex = float(tr[0]["priceUsd"]) * 1e9; hi = max(hi, ex)
        if half_at is None:
            if any(t["userAddress"] == leader and t["type"] == "sell" for t in tr):
                half_at = ex; hi = ex
                notify(f"SELL HALF {sym}: leader sold. mcap ${ex:,.0f} ({(ex/entry-1)*100:+.0f}%). Trail the rest: sell if it falls below ${hi*(1-TRAIL):,.0f}")
                continue
            if ex <= entry * (1 - STOP): why = "STOP"; break
        elif ex <= hi * (1 - TRAIL):
            why = "TRAIL"; break
    notify(f"SELL ALL {sym}: {why}. mcap ${ex:,.0f} ({(ex/entry-1)*100:+.0f}% vs entry ${entry:,.0f})")
    pnl = paper_pnl(SIZE / 2, entry, half_at) + paper_pnl(SIZE / 2, entry, ex) if half_at else paper_pnl(SIZE, entry, ex)
    with lock:
        new = not os.path.exists("paper_trades.csv")
        w = csv.writer(open("paper_trades.csv", "a"))
        if new: w.writerow(["utc", "sym", "mint", "leader", "entry_mc", "half_mc", "exit_mc", "why", "pnl_at_size", "size"])
        w.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), sym, m, leader, round(entry), round(half_at or 0), round(ex), why, round(pnl, 2), SIZE])
        if pnl <= -0.8 * SIZE: open("blacklist.txt", "a").write(leader + "\n")


def main():
    smart = proven_wallets()
    notify(f"bot started: {len(smart)} proven wallets loaded")
    alerted = set()
    while True:
        now = time.time(); coins = {}
        for off in range(0, 300, 50):
            for c in get(f"{B}/coins", dict(offset=off, limit=50, sort="last_trade_timestamp", order="DESC", includeNsfw="false")) or []:
                coins[c["mint"]] = c
        todo = [c for c in coins.values() if c["mint"] not in alerted]
        with cf.ThreadPoolExecutor(4) as ex:
            sigs = list(ex.map(lambda c: check(c, smart, now), todo))
        for sig in sigs:
            if sig:
                alerted.add(sig["mint"])
                notify(f"BUY {sig['sym']} ({sig['mint']})\nmcap ${sig['cur']:,.0f} (trigger ${sig['trig']:,.0f}, leader bought ${sig['lead_usd']:,.0f})\n"
                       f"size ${SIZE}. Skip if mcap > ${sig['trig']*1.15:,.0f}. Stop ${sig['cur']*(1-STOP):,.0f}")
                threading.Thread(target=track, args=(sig,), daemon=True).start()
        time.sleep(20)


if __name__ == "__main__":
    main()
