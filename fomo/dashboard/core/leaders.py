"""Leader list: small wallets (every position <= $1k, every day <= $5k, not launch snipers) that
closed 10+ sub-$80k pump.fun positions in the last 14 days with ROI > 20% and win rate >= 40%.
Same rule that held up in the day-level walk-forward (fomo/SMALL_TRADERS.md).
"""
import collections, csv, datetime as dt, glob, json, os, statistics, threading, time
from . import config, pump, store, chain

UNIVERSE = os.path.join(config.FOMO_DIR, "datasets", "small_wallet_universe.json")
RESULTS = os.path.join(config.FOMO_DIR, "small_traders", "results")
SOL_CHAIN = 1399811149
job = {"running": False, "done": 0, "total": 0, "started": 0.0, "finished": 0.0, "qualified": 0, "msg": ""}


def _ts(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def score_wallet(positions, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    rows, day_spend, max_pos = [], collections.Counter(), 0.0
    for p in positions:
        if p.get("chainId") != SOL_CHAIN:
            continue
        bought, qty = p.get("amountBoughtUsd") or 0, p.get("amountBought") or 0
        u = _ts(p.get("updatedAt")); o = _ts(p.get("openedAt")) or u
        if bought <= 0 or qty <= 0 or o is None:
            continue
        day_spend[o.date()] += bought
        max_pos = max(max_pos, bought)
        if p.get("hasTransfers") or p.get("hasUntrustedUsdBasis") or p.get("potentialSpam"):
            continue
        prog = (p.get("coin") or {}).get("program")
        if prog != "pump" and not str(p["coinMint"]).endswith("pump"):
            continue
        mc = bought / qty * 1e9
        if mc >= 80000:
            continue
        rows.append(dict(u=u, exited=bool(p.get("isExited")), bought=bought, pnl=p.get("pnlUsd") or 0.0, mcap=mc))
    if not rows:
        return None
    small = max_pos <= 1000 and max(day_spend.values()) <= 5000
    sniper = statistics.median(r["mcap"] for r in rows) < 4500
    tr = [r for r in rows if r["exited"] and r["u"] and now - dt.timedelta(days=14) <= r["u"] < now]
    b = sum(r["bought"] for r in tr)
    roi = sum(r["pnl"] for r in tr) / b if b else 0.0
    win = sum(r["pnl"] > 0 for r in tr) / len(tr) if tr else 0.0
    last = max((r["u"] for r in rows if r["u"]), default=None)
    return dict(small=small, sniper=sniper, closed_14d=len(tr), roi_14d=roi, win_rate=win,
                median_size=statistics.median(r["bought"] for r in tr) if tr else None,
                median_mcap=statistics.median(r["mcap"] for r in tr) if tr else None,
                last_trade_at=last.timestamp() if last else None,
                qualified=small and not sniper and len(tr) >= 10 and roi > 0.20 and win >= 0.40
                and statistics.median(r["bought"] for r in tr) >= 10)   # sub-$10 "traders" are bots


def seed_from_results():
    """First run: load the newest leaders_*.csv from the research so the dashboard starts with a list."""
    if store.one("SELECT COUNT(*) n FROM leaders")["n"]:
        return
    files = sorted(glob.glob(os.path.join(RESULTS, "leaders_*.csv")))
    if not files:
        return
    for r in csv.DictReader(open(files[-1])):
        store.insert("leaders", dict(wallet=r["wallet"], closed_14d=int(r["closed_14d"]), roi_14d=float(r["roi_14d"]),
                                     win_rate=float(r["win_rate"]), median_size=float(r["median_size_usd"]),
                                     median_mcap=float(r["median_entry_mcap"]), enabled=1, source="research",
                                     updated_at=os.path.getmtime(files[-1])))


def refresh_async():
    if job["running"]:
        return False
    threading.Thread(target=_refresh, daemon=True).start()
    return True


def _refresh():
    uni = json.load(open(UNIVERSE))["wallets"]
    extra = [r["wallet"] for r in store.q("SELECT wallet FROM leaders WHERE source='manual'")]
    wallets = list(dict.fromkeys(uni + extra))
    job.update(running=True, done=0, total=len(wallets), started=time.time(), qualified=0, msg="Scoring wallets")
    q = 0
    for w in wallets:
        try:
            pos = pump.portfolio(w)
            s = score_wallet(pos) if pos else None
            cur = store.one("SELECT * FROM leaders WHERE wallet=?", (w,))
            if s and s["qualified"]:
                q += 1
                row = {k: s[k] for k in ("closed_14d", "roi_14d", "win_rate", "median_size", "median_mcap", "last_trade_at")}
                row["updated_at"] = time.time()
                if cur:
                    store.update("leaders", "wallet", w, row | {"source": cur["source"] if cur["source"] == "manual" else "auto"})
                else:
                    store.insert("leaders", row | {"wallet": w, "enabled": 1, "source": "auto"})
            elif cur and cur["source"] != "manual":
                store.update("leaders", "wallet", w, {"source": "lapsed", "enabled": 0, "updated_at": time.time(),
                                                      **({"closed_14d": s["closed_14d"], "roi_14d": s["roi_14d"],
                                                          "win_rate": s["win_rate"]} if s else {})})
        except Exception as e:
            job["msg"] = f"error on {w[:6]}: {e}"
        job["done"] += 1
        job["qualified"] = q
    job.update(running=False, finished=time.time(), msg=f"{q} wallets qualify")
    store.alert("info", "LEADERS", f"Leader list refreshed: {q} qualify", f"Scored {len(wallets)} small wallets")


imp = {"running": False, "done": 0, "total": 0, "added": 0, "msg": ""}


def import_async(cands):
    """Score outside wallets (e.g. fomo's leaderboard) with the same leader rule; add qualifiers."""
    if imp["running"]:
        return False
    threading.Thread(target=_import, args=(cands,), daemon=True).start()
    return True


def _import(cands):
    imp.update(running=True, done=0, total=len(cands), added=0, msg="Scoring imported wallets")
    added = 0
    for c in cands:
        w = c["wallet"]
        try:
            pos = pump.portfolio(w)
            s = score_wallet(pos) if pos else None
            if s and s["qualified"]:
                row = {k: s[k] for k in ("closed_14d", "roi_14d", "win_rate", "median_size", "median_mcap", "last_trade_at")}
                row.update(updated_at=time.time(), label=c.get("label"), note=c.get("note"))
                if store.one("SELECT 1 x FROM leaders WHERE wallet=?", (w,)):
                    store.update("leaders", "wallet", w, row)
                else:
                    store.insert("leaders", row | {"wallet": w, "enabled": 1, "source": "fomo"})
                added += 1
        except Exception as e:
            imp["msg"] = f"error on {w[:6]}: {e}"
        imp["done"] += 1
        imp["added"] = added
    imp.update(running=False, msg=f"{added} of {len(cands)} fomo traders qualify")
    store.alert("info", "LEADERS", f"fomo leaderboard import: {added} of {len(cands)} qualify", "Added to Leaders with source 'fomo'.")


def score_chain(wallet, max_sigs=150, now=None):
    """Leader rule from the wallet's own on-chain trades (for fomo traders, whose trades pump.fun's
    portfolio index doesn't see). Round trips = buys then a sell to ~zero balance, per coin."""
    now = now or time.time()
    sigs = [s for s in (chain.rpc("getSignaturesForAddress", [wallet, {"limit": max_sigs}]) or []) if not s.get("err")]
    sol = pump.sol_price()
    trades = [t for t in (chain.parse_trade(s["signature"], wallet, sol) for s in reversed(sigs)) if t]
    if not trades:
        return None
    opn, rts, day_buys, max_buy = {}, [], collections.Counter(), 0.0
    for t in trades:
        if t["side"] == "buy":
            o = opn.setdefault(t["mint"], dict(cost=0.0, proc=0.0, t0=t["ts"]))
            o["cost"] += t["usd"]; max_buy = max(max_buy, t["usd"])
            day_buys[dt.datetime.fromtimestamp(t["ts"]).date()] += t["usd"]
        elif t["mint"] in opn:
            o = opn[t["mint"]]; o["proc"] += t["usd"]
            if t["remaining"] <= 1e-6:
                o["t1"] = t["ts"]; rts.append(o); del opn[t["mint"]]
    recent = [r for r in rts if r["t1"] >= now - 14 * 86400 and r["cost"] > 0]
    cost = sum(r["cost"] for r in recent)
    roi = (sum(r["proc"] for r in recent) - cost) / cost if cost else 0.0
    win = sum(r["proc"] > r["cost"] for r in recent) / len(recent) if recent else 0.0
    med = statistics.median(r["cost"] for r in recent) if recent else 0.0
    small = max_buy <= 1000 and (max(day_buys.values()) if day_buys else 0) <= 5000
    return dict(closed_14d=len(recent), roi_14d=roi, win_rate=win, median_size=med, median_mcap=None,
                last_trade_at=trades[-1]["ts"], small=small, n_trades=len(trades),
                qualified=small and len(recent) >= 10 and roi > 0.20 and win >= 0.40 and med >= 10)


def import_chain_async(cands):
    if imp["running"]:
        return False
    threading.Thread(target=_import_chain, args=(cands,), daemon=True).start()
    return True


def _import_chain(cands):
    imp.update(running=True, done=0, total=len(cands), added=0, msg="Scoring fomo traders on-chain")
    added = 0
    for c in cands:
        try:
            s = score_chain(c["wallet"])
            if s and s["qualified"]:
                row = {k: s[k] for k in ("closed_14d", "roi_14d", "win_rate", "median_size", "median_mcap", "last_trade_at")}
                row.update(updated_at=time.time(), label=c.get("label"), note=c.get("note"))
                if store.one("SELECT 1 x FROM leaders WHERE wallet=?", (c["wallet"],)):
                    store.update("leaders", "wallet", c["wallet"], row)
                else:
                    store.insert("leaders", row | {"wallet": c["wallet"], "enabled": 1, "source": "fomo"})
                added += 1
        except Exception as e:
            imp["msg"] = f"error on {c['wallet'][:6]}: {e}"
        imp["done"] += 1; imp["added"] = added
    imp.update(running=False, msg=f"{added} of {len(cands)} fomo traders qualify (on-chain)")
    store.alert("info", "LEADERS", f"fomo traders scored on-chain: {added} of {len(cands)} qualify", "Added to Leaders with source 'fomo'.")
