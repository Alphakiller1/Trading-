# Prompt: fomo hands-on research + strategy + bot (for ChatGPT agent mode with browser)

Copy everything below the line into ChatGPT (agent mode, so it can use its own browser).

---

You are a quantitative crypto trading researcher. Use your browser for real, hands-on research. Base every conclusion on what you can actually see or download, not on general knowledge. Cite the URL and the time for every number you report. When something can't be verified, label it **UNVERIFIED**.

## Context

I trade Solana meme coins in the **fomo app** (https://fomo.family, a social trading app; web app plus iOS and Android). My account handle is **ChaseLytics**. Login is Apple or Google sign-in only, so if you need to be logged in, stop and ask me to log in for you in your browser session. Never ask for my passwords or seed phrases, and never place a real trade without my explicit "yes" for that exact trade.

My results are tracked in the GitHub repo **Alphakiller1/Trading-** (`fomo/` folder). It already contains Python scripts that pull pump.fun trade data and backtest a momentum signal.

**My constraints**
- Markets: coins with a **market cap under $80,000**. Most of these are pump.fun bonding-curve coins; graduation happens at roughly $69k–$90k.
- Trade size: **$25–$250 per trade**. Use larger sizes on calmer coins and smaller sizes on more volatile coins.
- I want to model my rules on **top traders who trade under $5k per day and under $1k per trade**, not on whales.
- I want the **lowest risk possible**. I understand nothing here is guaranteed. Tell me plainly if the data shows no edge after costs.

**The strategy I'm adapting (from my Interactive Brokers stock bot)**
- Universe: the hottest stocks by volume.
- Signal on 5-second bars: the 9-bar EMA crosses above a rolling 50-bar VWAP. The crossover bar needs at least 1.5× the average volume of the prior 5 bars.
- Entry: limit buy at the last price plus 0.25%, cancelled if not filled within 30 seconds.
- Exits: a hard stop 1% below the signal price, plus a 2% trailing stop that activates after about a 1% gain.
- Paper results: 158 trades, 17.7% win rate, +6.2% average win, −1.54% average loss, net negative. The strategy depends on a few big runners.
- Known flaws: the stop is measured from the signal price instead of the fill; it re-enters the same symbol repeatedly; there's no daily loss limit; it holds positions overnight.

**Known facts (verify them, don't trust them)**
- fomo spot fee (reported, **UNVERIFIED**): flat $0.10 under $5; 2% from $5 to $47.50; flat $0.95 from $47.50 to $190; 0.5% at $190 and up. Gas is reportedly sponsored.
- fomo spot reportedly has **no limit, stop-loss or take-profit orders** (perps do). Confirm this in the app's buy and sell screens.
- pump.fun bonding-curve fee is about 1% per side. Slippage is large at small market caps: a $200 buy into a $10k-cap coin moves the price several percent.
- Public pump.fun endpoints that worked as of 2026-10-10 (no login needed):
  - `https://frontend-api-v3.pump.fun/coins?offset=0&limit=50&sort=created_timestamp|last_trade_timestamp|market_cap&order=DESC&includeNsfw=true`
  - `https://swap-api.pump.fun/v2/coins/{mint}/trades?limit=100&program=pump&chainId=solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp&cursor={nextCursor}`, the full trade tape with wallet, side, USD amount and price
  - `https://frontend-api-v3.pump.fun/pnl-leaderboard?period=daily|weekly|monthly&sort=combined&limit=100`
  - `https://frontend-api-v3.pump.fun/portfolio-summary?user={wallet}&period=1d|1w|all`, with PnL, realized PnL and total buy spend
  - `https://frontend-api-v3.pump.fun/user-portfolio/{wallet}?filter=all&page=0&pageSize=100&sortBy=PNL`, per-coin positions
  - Market cap ≈ `priceUsd × 1e9` (1B supply).

## Tasks

### 1. Hands-on fomo audit (in the browser)
- Open fomo.family and its web app. Document exactly what a trader can do on **spot** Solana meme coins:
  - order types, sell options (%, partial), any auto-sell, TP/SL or alerts
  - slippage settings, priority or MEV settings
  - the fee shown on a $25, $100 and $250 order (read it from the confirmation screen; don't submit)
- Document fomo's social features: leaderboards, trader profiles, the "following" feed, notifications. Check whether trader profiles show trade history, trade sizes and PnL, and how quickly a followed trader's trade shows up.
- Find whether fomo has a public API or any automation route. If none exists, say so; the bot will then be an **alert bot** while I place trades manually.

### 2. Find traders who fit my profile
- From the fomo leaderboard and profiles, and from pump.fun's leaderboard and `portfolio-summary`, collect at least 30 candidate wallets or handles.
- Keep only traders who meet all of these:
  - median trade at or below $250 (max $1k)
  - daily buy spend at or below $5k
  - most of their entries below an $80k market cap
  - positive realized PnL over at least 1 week, with 20 or more trades
- Exclude:
  - the coin's creator (dev)
  - bots: more than 200 trades a day, or round trips under 10 seconds
  - bundlers and snipers buying in the first block
- For each kept trader, produce a table from their actual trades:
  - entry market cap; coin age at entry
  - hold time; exit multiple
  - win rate; average win and average loss
  - trades per day; size
  - whether they scale out
- Identify the **common, repeatable pattern** across the profitable ones. Contrast it with unprofitable small traders, as a control group.

### 3. Design the strategy
Merge the TWS momentum logic with what the profitable small traders actually do. Then adapt it to fomo's realities: manual exits with no stop orders, the fee tiers, and slippage. Specify every rule numerically:
- **Coin filters:** market-cap band, age, holder count, dev holdings, top-10 holder %, bundle %, volume and buy/sell ratio, socials.
- **Entry trigger:** the EMA/VWAP cross adapted to a timeframe a human can execute (likely 15s–1m bars), plus any confirming signals.
- **Sizing:** $25–$250 scaled inversely to recent volatility. Include the formula. Show the fee and slippage break-even move at $25, $50, $100, $190 and $250.
- **Exits:** stop measured from the fill; scale-out levels; trailing rule; time stop. Size each one so it's realistic to do by hand.
- **Risk:** max open positions, daily loss limit, no re-entry on the same coin after a stop, and trading hours.

### 4. Backtest honestly
Use the pump.fun trade tapes above, or the scripts in Alphakiller1/Trading-/fomo if you can run code.
- Include all costs, and execution delay: 3–10 seconds for manual trading.
- Split by coin into train and test sets; report the **test-set** results.
- Report:
  - number of trades; win rate
  - average and median return per trade after costs
  - max drawdown; worst day
  - results by market-cap band and trade size

If the edge is zero or negative after costs, say so clearly and recommend what (if anything) would change that.

### 5. Build the bot
Write a Python bot, `fomo/bot.py`, that:
- polls pump.fun's public endpoints, or uses a websocket if you find a public one;
- applies the coin filters and the entry trigger;
- sends me alerts (Telegram or Discord webhook) with:
  - coin, market cap, suggested size, entry price
  - stop and target levels in both price and market cap
  - a direct fomo link to the coin, if fomo has deep links (find out)
- tracks open alerts and sends **exit alerts** when a stop, target, trailing or time rule triggers;
- has a **paper-trading mode** that logs simulated fills with full costs to CSV, plus a daily summary;
- has no private keys and no auto-trading unless fomo offers an official API. If you think auto-trading through another route (for example a Solana wallet plus Jupiter) is worth it, describe it separately with its risks. Don't build it.

## Deliverables
1. `fomo/FOMO_AUDIT.md`: the hands-on findings from step 1, with screenshots described and URLs cited.
2. `fomo/TRADERS.md`: the trader table and the common pattern from step 2.
3. `fomo/STRATEGY.md`: the exact rules from step 3 plus the backtest results from step 4, including the negative ones.
4. `fomo/bot.py` + `fomo/requirements.txt` + setup instructions.
5. A short summary covering what works, what doesn't, and the realistic expected result per 100 trades at my sizes.

Work step by step. Show me your findings after step 2 before designing the strategy.
