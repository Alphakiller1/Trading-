# Trading

Research and tooling for trading strategies.

## Projects

### `fomo/`: meme-coin strategy for the fomo app (Solana, sub-$80k market caps)

Goal: adapt the TWS momentum bot logic (below) to low-cap Solana meme coins traded on [fomo](https://fomo.family).
The rules come from two sources:

1. **What profitable small traders actually do.** Wallets sized under $1k per trade and under $5k per day, on coins below an $80k market cap.
2. **A backtest of the TWS signal on real pump.fun trade data**, with realistic costs: fomo fees, pump.fun fees and bonding-curve slippage.

Trade size: **$25–$250 per trade**. Use larger sizes on calmer coins and smaller sizes on more volatile ones.

| Script | What it does |
|---|---|
| `collect.py` | Pulls recent pump.fun coins and their full trade tapes from pump.fun's public APIs into `data/` |
| `analyze.py` | Market overview: trades below $80k market cap, buy-size distribution, coin peak market caps |
| `wallets.py` | Rebuilds every wallet's position per coin (entry market cap, hold time, PnL) and finds small-size wallets |
| `profiles.py` | Pulls 1-day and 1-week PnL and buy spend for candidate wallets (for the $5k/day filter) |
| `backtest.py` | The TWS signal on trade tapes, with fomo fee tiers, 1% pump.fun fee and constant-product slippage |
| `sweep.py` | Parameter sweep with a train/test split by coin, to avoid overfitting |

Run order, from `fomo/data/`:

```bash
cd fomo/data
python ../collect.py          # ~30-60 min
python ../analyze.py
python ../wallets.py
python ../profiles.py
PYTHONPATH=.. python ../backtest.py
PYTHONPATH=.. python ../sweep.py
```

#### Cost model (check the current fees in the app)
- fomo spot fee (reported tiers): flat $0.10 under $5; 2% from $5 to $47.50; flat $0.95 from $47.50 to $190; 0.5% at $190 and above
- pump.fun bonding curve: about 1% per side
- Slippage: constant-product bonding curve (virtual reserves taken from the coin's data)

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
