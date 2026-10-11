# Trading

Research and tooling for trading strategies.

## Projects

### `fomo/`: meme-coin research for the fomo app (Solana, pump.fun coins ≤ $200k)

**Status (2026-10-10): no validated edge. Do not trade real money with these signals.** Full write-up: [`fomo/RESEARCH.md`](fomo/RESEARCH.md).

| Finding | Evidence |
|---|---|
| Costs: round trip 5.9% at $25, 3.9% at $100, 3.0% at $190+; random entries lose 11–14% at human speed | `backtest.py`, `strategies.py` |
| TWS EMA/VWAP momentum, launch sniping, dip-buying and graduation plays all lose after costs | `run_strats.py`, `dips.py`, `early_quality.py` |
| The copy-trade "edge" (+29% on a coin-half split) was look-ahead. **Walk-forward: −3.5% to −8%** | `copy2-4.py`, `walkforward.py` |
| Live: 7 of 7 picks fell 25–99% within minutes | RESEARCH.md scoreboard |
| **Robust avoid rules:** dev sold, bundled launch (top-3 early buyers > 60%), volatility < 12%, buying fresh launches after a run | `cohort.py`, `tiers.py`, `dips.py` |
| Peak/attention windows: 5–7 PM ET and midnight–4 AM ET; worst 7–8 AM ET | `chain_hours.py`, `hours.py` |
| **Small traders (every trade ≤ $1k, every day ≤ $5k): skill persists across days.** Strict past winners made +15.1% (CI +5.7% to +20.8%) on later days, but copying costs about 5–6 points per trade, which leaves roughly +5% that depends on a few big trades. Paper only | [`fomo/SMALL_TRADERS.md`](fomo/SMALL_TRADERS.md), `small_traders/` |

**Next step: collect multi-day data, then walk-forward everything.**

```bash
cd fomo/data
python ../collector.py                               # leave running for 5–7 days (Ctrl+C to stop; resumes)
python ../collector.py --export trades.json coins.json
python ../analyze.py && python ../wallets.py         # rebuild wallet positions
python ../walkforward.py                             # past-only skill -> future trades
```

A strategy graduates to paper trading (`bot.py`, alerts only) only if it's positive in walk-forward on held-out **days**, and to real money only after 50+ paper trades positive after costs.

### TWS momentum bot review (Interactive Brokers, Oct 2026)

Summary of the review of `master_strategy.py`:

- **Strategy:** a long-only scalp on low-priced, heavily traded stocks from IB's `HOT_BY_VOLUME` scanner. It runs on 5-second bars and enters when the 9-bar EMA crosses above a rolling 50-bar VWAP. That VWAP covers only about 4 minutes; it is not the day's VWAP.
- **Filters and entry:** the crossover bar needs at least 1.5× the volume of the previous 5 bars. The buy is a limit order at the last price plus 0.25%.
- **Exits:** a hard stop 1% below the signal price, plus a 2% trailing stop that takes over after about a 1% gain.
- **Paper results, Sep 30 – Oct 2:** 158 trades with an exit, a 17.7% win rate, +6.2% average win and −1.54% average loss, for about −$510 net.
- **Fix before going live:**
  1. Sell everything before the close.
  2. Measure the stop from the fill price, not the signal price.
  3. Exclude ETFs from the scanner.
  4. Rebuild the backtester to match the live rules: 5-second bars, rolling VWAP, trailing stop.
