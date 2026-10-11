"""Hold plan: how long to stay in, from tools/hold_fit.py's replays of real leader signals.

Picks the replay group that matches the signal (positive model EV first, then its verdict), then the
best of a FIXED set of plans that span the typical peak window (5-10 min timers, take-profit with a
5-10 min cap) by trimmed mean. A fixed set stops noisy samples from picking 1-2 minute "plans" that
only minimize exposure (when every exit loses after fees, the shortest one always loses least).
Stops are not used inside the window: coins typically dip 10-16% before they peak.
"""
import json, os, re
from . import config

PATH = os.path.join(config.ROOT, "model", "hold_table.json")
_t = {"mtime": 0, "data": None}


def _load():
    try:
        m = os.path.getmtime(PATH)
        if m != _t["mtime"]:
            _t.update(mtime=m, data=json.load(open(PATH)))
    except Exception:
        _t["data"] = None
    return _t["data"]


CANDIDATES = ("time_5m", "time_10m", "tp25_5m", "tp25_10m", "tp50_10m")


def _deployable(rule):
    return rule in CANDIDATES


def plan(verdict, ev_pos=False):
    d = _load()
    if not d:
        return None
    if verdict == "SKIP":
        return dict(enter=False, text="Don't enter: the coin fails the avoid rules.")
    g = d["groups"]
    name = "positive_EV" if ev_pos and "positive_EV" in g else ("not_SKIP" if "not_SKIP" in g else "all")
    grp = g.get(name)
    if not grp:
        return None
    rules = {k: v for k, v in grp["rules"].items() if v and _deployable(k)}
    best = max(rules, key=lambda k: rules[k]["trim"])
    m = re.fullmatch(r"(?:time_(\d+)m)|(?:tp(\d+)(?:_sl(\d+))?_(\d+)m)", best)
    if m.group(1):
        window, tp, sl = int(m.group(1)), None, None
    else:
        tp, sl, window = int(m.group(2)), (int(m.group(3)) if m.group(3) else None), int(m.group(4))
    r = rules[best]
    pk = grp["peak_min"]
    text = (f"Hold up to {window} min" + (f"; take profit at +{tp}%" if tp else "") + (f"; stop at -{sl}%" if sl else "; no stop inside the window")
            + f". Coins like this peaked around {pk['median']} min (middle half {pk['p25']}-{pk['p75']}), "
              f"usually after a {abs(grp['dip_before_peak_median']):.0%} dip. Beyond 15 min the replays bled. "
              f"This plan's replay result after fees at ${d['size']:.0f}: {r['mean']:+.1%} mean, {r['median']:+.1%} median, "
              f"{r['win']:.0%} wins (n={r['n']}).")
    return dict(enter=True, group=name, rule=best, window_min=window, take_profit_pct=tp, stop_pct=sl,
                peak_median_min=pk["median"], dip_median=grp["dip_before_peak_median"], expected_mean=r["mean"],
                expected_median=r["median"], win=r["win"], n=r["n"], replays=d["signals"], size=d["size"], text=text)
