"""Market pulse: a light scan of the live sub-$80k pump.fun market, every 20 minutes.

Measures what the strategy cares about right now: launch pace vs the 7-day baseline for this ET
hour, how many coins are actually trading in each market-cap zone, how many of the most active
ones pass the avoid rules (and why the rest fail), and today's leader signals. Paced for
pump.fun's rate limit (~70 requests per scan).
"""
import collections, datetime as dt, json, os, statistics, threading, time
from zoneinfo import ZoneInfo
from . import config, pump, intel, store

ET = ZoneInfo("America/New_York")
PATH = os.path.join(config.DATA, "market_scan.json")
HIST = os.path.join(config.DATA, "market_history.jsonl")
last = {"data": None}
_lock = threading.Lock()


def _zone(m):
    return "< $10k" if m < 10000 else "$10k-25k" if m < 25000 else "$25k-45k" if m < 45000 else "$45k-80k"


def scan(hourly=None, n_xray=10):
    if not _lock.acquire(blocking=False):
        return last["data"]
    try:
        now = time.time()
        et = dt.datetime.now(ET)
        # 1) launch pace from the newest launches
        launched = []
        for off in range(0, 300, 50):
            d = pump.get(f"{pump.FE}/coins", dict(offset=off, limit=50, sort="created_timestamp", order="DESC", includeNsfw="true")) or []
            launched += d
        ts = sorted(c["created_timestamp"] / 1000 for c in launched if c.get("created_timestamp"))
        pace = (len(ts) - 1) / ((ts[-1] - ts[0]) / 3600) if len(ts) > 10 and ts[-1] > ts[0] else None
        base = next((h for h in (hourly or []) if h["et"] == et.hour), None)
        # 2) the live tradeable market
        active = {}
        for off in range(0, 200, 50):
            for c in pump.get(f"{pump.FE}/coins", dict(offset=off, limit=50, sort="last_trade_timestamp", order="DESC", includeNsfw="true")) or []:
                m = c.get("usd_market_cap") or 0
                if c.get("program") == "pump" and not c.get("complete") and 3000 <= m < 80000:
                    active[c["mint"]] = c
        zones = collections.Counter(_zone(c["usd_market_cap"]) for c in active.values())
        # 3) X-ray the most active tradeable coins (recently traded, $5k-$60k)
        pick = sorted((c for c in active.values() if 5000 <= c["usd_market_cap"] < 60000),
                      key=lambda c: -(c.get("last_trade_timestamp") or 0))[:n_xray]
        xr, reasons, partial = [], collections.Counter(), 0
        for c in pick:
            x = None
            for attempt in range(2):
                wait = pump.health["throttled_until"] - time.time()
                if wait > 0:
                    time.sleep(min(wait + 1, 120))      # pump.fun throttle: wait it out instead of scoring blanks
                try:
                    x = intel.xray(c["mint"])
                except Exception:
                    x = None
                if x and not x["m"].get("data_partial"):
                    break
            if not x or x["m"].get("data_partial"):
                partial += 1                            # unreadable coins are left out of the stats
                continue
            for r in x["hard"]:
                reasons[r.split(":")[0].split("(")[0].strip()[:48]] += 1
            m = x["m"]
            xr.append(dict(mint=c["mint"], symbol=m.get("symbol"), mcap=m.get("mcap"), verdict=x["verdict"],
                           age_min=m.get("age_min"), trades_60s=m.get("trades_60s"), net_flow_5m=m.get("net_flow_5m"),
                           range_5m=m.get("range_5m"), why=(x["hard"] + x["soft"])[:2]))
        vc = collections.Counter(r["verdict"] for r in xr)
        # 4) today's leader signals
        day0 = dt.datetime(et.year, et.month, et.day, tzinfo=ET).timestamp()
        sig = store.q("SELECT verdict, intel FROM signals WHERE side='buy' AND verdict!='ADD' AND ts>=?", (day0,))
        evs = []
        for s in sig:
            try:
                mv = (json.loads(s["intel"] or "{}") or {}).get("model")
                if mv:
                    evs.append(mv["copier_ev"])
            except Exception:
                pass
        sv = collections.Counter(s["verdict"] for s in sig)
        tradeable = (vc["GO"] + vc["CAUTION"]) / len(xr) if xr else None
        rel = (pace / base["launches"] - 1) if pace and base else None
        mood = ("Hot" if (rel or 0) > 0.15 and (tradeable or 0) >= 0.4 else
                "Cold" if (rel or 0) < -0.2 or (tradeable is not None and tradeable < 0.2) else "Normal")
        out = dict(at=now, et=et.strftime("%a %H:%M ET"), mood=mood,
                   launches_per_hr=round(pace) if pace else None, baseline_per_hr=base["launches"] if base else None,
                   pace_vs_baseline=rel, grads_per_1k_baseline=base["per1k"] if base else None,
                   active=len(active), active_of=200, zones={z: zones.get(z, 0) for z in ("< $10k", "$10k-25k", "$25k-45k", "$45k-80k")},
                   xray=dict(n=len(xr), unreadable=partial, go=vc["GO"], caution=vc["CAUTION"], skip=vc["SKIP"], tradeable=tradeable,
                             top_fail=reasons.most_common(4), coins=xr),
                   signals=dict(n=len(sig), go=sv["GO"], caution=sv["CAUTION"], skip=sv["SKIP"],
                                ev_pos=sum(e > 0 for e in evs), ev_median=statistics.median(evs) if evs else None),
                   sol=pump.sol_price())
        json.dump(out, open(PATH, "w"))
        with open(HIST, "a") as f:
            f.write(json.dumps({k: out[k] for k in ("at", "mood", "launches_per_hr", "active", "pace_vs_baseline")} | {"tradeable": tradeable}) + "\n")
        last["data"] = out
        return out
    finally:
        _lock.release()


def latest():
    if last["data"] is None and os.path.exists(PATH):
        try:
            last["data"] = json.load(open(PATH))
        except Exception:
            pass
    return last["data"]


def loop(hourly):
    while True:
        try:
            scan(hourly)
        except Exception as e:
            store.alert("info", "MARKET", "Market scan failed", str(e)[:200])
        time.sleep(20 * 60)
