"""Today's leader list for the small-leader follow strategy (paper trading only).

A wallet qualifies when, using ONLY positions it has fully closed in the last 14 days:
  - every position it ever took was <= $1k and no day's buys exceeded $5k (whole history)
  - it is not a launch sniper (median entry market cap >= $4.5k)
  - it closed >= 10 pump.fun positions entered under $80k, with ROI > 20% and win rate >= 40%
Run walkforward_days.py's inputs first (seed2.py, then wallets_fetch.py) to refresh portfolios/.
Writes leaders.csv.
"""
import csv, datetime as dt
import walkforward_days as wf

now = dt.datetime.now(dt.timezone.utc)
out = []
for w, wd in wf.wallets.items():
    if not wd["small"]:
        continue
    tr = [r for r in wd["rows"] if r["exited"] and r["u"] and now - dt.timedelta(days=14) <= r["u"] < now]
    if len(tr) < 10:
        continue
    roi = wf.roi(tr)
    win = sum(r["pnl"] > 0 for r in tr) / len(tr)
    if roi > 0.20 and win >= 0.40:
        out.append(dict(wallet=w, closed_14d=len(tr), roi_14d=round(roi, 3), win_rate=round(win, 3),
                        median_size_usd=round(sorted(r["bought"] for r in tr)[len(tr) // 2], 2),
                        median_entry_mcap=round(sorted(r["mcap"] for r in tr)[len(tr) // 2])))
out.sort(key=lambda x: -x["roi_14d"])
with open("leaders.csv", "w", newline="") as f:
    wr = csv.DictWriter(f, fieldnames=list(out[0]) if out else ["wallet"])
    wr.writeheader(); wr.writerows(out)
print(f"\n{len(out)} leaders qualify as of {now:%Y-%m-%d %H:%M} UTC -> leaders.csv")
for x in out[:25]:
    print(f"  {x['wallet']}  closed {x['closed_14d']:3d}  ROI {x['roi_14d']:+.0%}  win {x['win_rate']:.0%}  "
          f"size ${x['median_size_usd']:.0f}  entry mcap ${x['median_entry_mcap']:,}")
