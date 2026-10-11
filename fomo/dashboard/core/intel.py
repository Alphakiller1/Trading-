"""Coin X-ray: the avoid rules from fomo/RESEARCH.md + SMALL_TRADERS.md, turned into a verdict.

SKIP rules held up in every test (dev sold, bundled launch, dead-calm coin, inactive coin,
fresh launch). CAUTION flags things the research couldn't confirm or that underperformed.
"""
import time, collections
from . import pump, config


def xray(mint, leader=None, leader_usd=None):
    cfg = config.load()
    now = time.time()
    c = pump.coin(mint, max_age=5) or {}
    young = c.get("created_timestamp") and now - c["created_timestamp"] / 1000 < 1800
    tr, from_start = pump.trades(mint, pages=8 if young else 3)   # young coins: reach the launch trades
    m = {}
    m["symbol"] = c.get("symbol") or "?"
    m["name"] = c.get("name") or ""
    m["image"] = c.get("image_uri")
    m["mcap"] = pump.mcap(mint, max_age=5)
    m["ath"] = float(c["ath_market_cap"]) if c.get("ath_market_cap") else None
    m["age_min"] = round((now - c["created_timestamp"] / 1000) / 60, 1) if c.get("created_timestamp") else None
    m["graduated"] = bool(c.get("complete"))
    m["banned"] = bool(c.get("is_banned"))
    m["creator"] = c.get("creator")
    m["twitter"], m["website"], m["telegram"] = c.get("twitter"), c.get("website"), c.get("telegram")
    m["replies"] = c.get("reply_count")
    m["volume_1h"] = c.get("volume_1h_usd")
    m["trades_seen"] = len(tr)
    m["data_partial"] = not tr

    real = [t for t in tr if t["usd"] >= 1.0]            # drop micro-buy bot spam
    m["dust_share"] = round(1 - len(real) / len(tr), 2) if tr else None
    last60 = [t for t in real if now - t["t"] <= 60]
    last5 = [t for t in real if now - t["t"] <= 300]
    m["trades_60s"] = len(last60)
    m["buyers_5m"] = len({t["w"] for t in last5 if t["side"] == "buy"})
    m["sellers_5m"] = len({t["w"] for t in last5 if t["side"] == "sell"})
    m["net_flow_5m"] = round(sum(t["usd"] if t["side"] == "buy" else -t["usd"] for t in last5), 2)
    px5 = [t["px"] for t in last5]
    m["range_5m"] = round(max(px5) / min(px5) - 1, 3) if len(px5) >= 5 and min(px5) > 0 else None
    cr = m["creator"]
    dev = [t for t in tr if t["w"] == cr]
    m["dev_sold"] = True if any(t["side"] == "sell" for t in dev) else (False if (dev or from_start) else None)
    if from_start and tr:
        first = [t for t in tr[:30] if t["side"] == "buy"]
        tot = sum(t["usd"] for t in first)
        by = collections.Counter()
        for t in first:
            by[t["w"]] += t["usd"]
        m["top3_early"] = round(sum(v for _, v in by.most_common(3)) / tot, 2) if tot else None
    else:
        m["top3_early"] = None
    m["leader_usd"] = leader_usd

    hard, soft = [], []
    if m["banned"]: hard.append("Coin is banned on pump.fun")
    if m["mcap"] and m["mcap"] >= cfg["max_mcap_usd"]: hard.append(f"Market cap ${m['mcap']:,.0f} is above your ${cfg['max_mcap_usd']:,.0f} limit")
    if m["dev_sold"] is True: hard.append("Dev has sold (buying after a dev dump averaged -19%)")
    if m["top3_early"] is not None and m["top3_early"] > 0.60: hard.append(f"Bundled launch: top 3 wallets took {m['top3_early']:.0%} of early buys")
    if m["range_5m"] is not None and m["range_5m"] < 0.12: hard.append(f"5-min range only {m['range_5m']:.0%} (calm coins lost -13%)")
    if tr and m["trades_60s"] < 3: hard.append(f"Inactive: {m['trades_60s']} real trades in the last minute")
    if m["age_min"] is not None and m["age_min"] < 1: hard.append("Fresh launch (< 1 min): early entries lost at app speed")
    if m["data_partial"]: soft.append("Trade data unavailable right now (pump.fun throttle): checks incomplete")
    if m["dev_sold"] is None: soft.append("Dev activity unknown (history too long to scan)")
    if m["top3_early"] is None and not m["data_partial"]: soft.append("Launch concentration unknown")
    if m["graduated"]: soft.append("Graduated off the bonding curve: outside the tested range")
    tw = m["twitter"] or ""
    if "/status/" in tw: soft.append("Tweet-linked news coin (copycats split attention; underperformed)")
    if not (m["website"] or m["telegram"] or (tw and "/status/" not in tw)): soft.append("No real socials")
    if leader_usd is not None and leader_usd < 20: soft.append(f"Leader bought only ${leader_usd:.0f}")
    if m["dust_share"] and m["dust_share"] > 0.5: soft.append(f"{m['dust_share']:.0%} of trades are bot dust (fake activity)")

    score = 0
    if m["top3_early"] is not None:
        score += 2 if m["top3_early"] <= 0.60 else (1 if m["top3_early"] <= 0.80 else 0)
    if m["dev_sold"] is False: score += 1
    if leader and (leader.get("closed_14d") or 0) >= 5: score += 1
    if m["website"] or m["telegram"] or (tw and "/status/" not in tw): score += 1
    verdict = "SKIP" if hard else ("CAUTION" if soft else "GO")
    return dict(mint=mint, verdict=verdict, score=score, hard=hard, soft=soft, m=m, ts=now)
