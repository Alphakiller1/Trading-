# Small-trader study and the "small-leader follow" strategy (2026-10-11)

Question: on fomo, for pump.fun coins under $80k market cap, can you profit by following the best **small** traders: wallets that never put more than $1k into a trade and never trade more than $5k in a day?

Builds on [`RESEARCH.md`](RESEARCH.md), which found no validated edge and a copy-trade result that disappeared out of sample. That study had one day of trades, so it could not test whether a wallet's skill lasts from one day to the next. This one can: pump.fun's public portfolio endpoint returns each wallet's positions going back months.

**Status: still no proven edge for a copier. Paper trade only.** What's new is evidence that small-trader skill persists across days. The size of that edge is about the same as the cost of copying it.

Code and outputs: [`small_traders/`](small_traders/).

## Data

- **Coins:** the 363 most actively traded pump.fun coins between $6k and $80k (latest 500 trades each), plus 76 of the newest launches.
- **Wallets:** 9,443 traded those coins. 4,000 passed a first screen (no trade above $1k, median trade at least $10), and I pulled each one's full position history.
- **After the size rules:**

  | Group | Wallets |
  |---|---|
  | Had sub-$80k pump.fun positions (and ≤ 1,000 positions in total) | 1,381 |
  | Skipped: more than 1,000 positions (mostly bots) | 565 |
  | Removed: launch snipers (median entry market cap < $4.5k; no human can copy these in time) | 81 |
  | **Meet both size rules: every position ≤ $1k and every day ≤ $5k** | **364** |

- **Positions:** 89,681 positions in sub-$80k coins, from March 2024 to October 2026, mostly since August 2026.
- **Cost model:** same as `RESEARCH.md`, except the pump.fun fee is 1.25% per side to be conservative (sources say 1–1.25%). Round-trip cost, including fomo's fee tiers and bonding-curve slippage:

  | Size | $25 | $100 | $190+ |
  |---|---|---|---|
  | Round-trip cost | 6.3% | 4.4% | 3.5% |

## Walk-forward test: does small-trader skill last into the next day?

**Method.** For each test day D:
- A wallet's track record uses only positions it **closed before D** (last 14 days).
- It is then scored on positions it closed **on D**.
- Nothing after D feeds the selection.
- Dating: pump.fun rarely records an open time. A position is dated by its last trade, which I checked equals the wallet's final sell on the tape (median difference 0 seconds).

These are the **leaders' own** returns, before any cost of copying them.

| Leader group (chosen before day D) | Positions | ROI | Without top 2% | Median | Win % |
|---|---|---|---|---|---|
| All small wallets (baseline) | 83,472 | +0.1% | −7.0% | −10.2% | 32.6% |
| Profitable before (ROI > 0, 10+ closed) | 36,699 | +5.4% | −1.6% | −5.3% | 36.9% |
| **Strict: ROI > 20%, win rate ≥ 40%, 10+ closed** | 1,424 | **+15.1%** | **+5.9%** | −4.3% | 44.5% |
| Losers before (ROI ≤ 0, 10+ closed) | 40,939 | −6.1% | −12.5% | −16.0% | 29.1% |

**Skill does persist.** Past winners beat the baseline and past losers stay worse.

95% confidence intervals, resampled by wallet:

| Group | 95% CI | Wallets |
|---|---|---|
| Profitable before | +3.8% to +7.0% | 162 |
| Strict | +5.7% to +20.8% | 34 |
| Baseline | −1.8% to +1.8% | 313 |

### The strict group, examined
- Without its 3 best-earning wallets: +6.5%. One wallet accounts for 21% of its positions.
- By period:

  | Period | Positions | Wallets | ROI | Without top 2% | Median |
  |---|---|---|---|---|---|
  | Apr–Aug 2026 | 613 | 15 | +21.1% | +8.3% | −7.3% |
  | Sep–Oct 2026 | 684 | 21 | +10.7% | +6.2% | −0.4% |

- Slices. I found these by slicing the data, so they're hypotheses, not rules:

  | Slice | ROI | Without top 2% |
  |---|---|---|
  | Entry market cap under $10k | +20.5% | +11.1% |
  | Entry market cap $10k–$80k | +4.6% | about −4% to 0% |
  | Leader position $50–$190 | +21.6% | +12.2% |
  | Leader position under $50 | +3.7% | −3.0% |

- How they trade (Sep–Oct):
  - median entry market cap $9.1k (middle half $5.1k–$21.5k)
  - median position **$36** (middle half $14–$85)
  - about 5 positions per active day
- What sets them apart is **more small wins**: 36% of their positions end between 0% and +50%, against 26% for all small wallets. Their share of big runners is about the same. They take profits quickly.

### The broader "profitable before" group is not enough
+5.4% falls to −1.6% without its top 2% of trades. A copier pays 3.5–6.3% in costs before any delay, so this group can't be copied profitably.

## What copying actually costs (replay on today's tapes)

I replayed copies of every listed wallet's first buy on 2026-10-11 using the real trade tapes:
- the copier enters 5–60 seconds after the leader
- the copier exits the same delay after the leader's first sell
- all costs are charged

| Group (selected on data before today) | Copier ROI (5s delay, $100) | Leader's own | Copier ROI ($190) |
|---|---|---|---|
| All small wallets (224 copies) | −6.9% | −1.1% | −6.1% |
| Profitable before (56 copies) | −10.5% | −4.3% | −9.6% |

- **The copier lands about 5–6 points behind the leader per trade at $100–$190.** Most of that is fees; delay drift adds 1–2 points. Delays from 5 to 60 seconds made little difference.
- It was a weak day for the leaders, and the strict group fired only twice. One partial day isn't a verdict.
- Rough estimate for the strict group in Sep–Oct: leader +10.7%, minus 5–6 points, is about **+5% per trade**. Without the best 2% of trades it's about 0%, and the median trade loses. That is a thin, tail-dependent edge on 21 wallets.
- The decisive test, replaying all 684 strict-group positions on their full tapes (`copy_wf.py`), was blocked: pump.fun's Cloudflare layer throttled this session. The script is paced and resumable, so run it from home.

## Strategy: small-leader follow (paper only until it passes the gate below)

### 1. Leader list
Rebuild it every day with `small_traders/leaders.py`, using closed positions only:
- every position ≤ $1k and every day ≤ $5k, across the wallet's whole history
- median entry market cap ≥ $4.5k (no launch snipers)
- last 14 days: 10+ closed sub-$80k pump.fun positions, ROI > 20%, win rate ≥ 40%
- drop wallets on `datasets/blacklist.txt`

On 2026-10-11 only **5 wallets** qualified (`small_traders/results/leaders_2026-10-11.csv`). Three of them enter around $4.9k market cap, seconds after launch, which may be too fast to follow on fomo.

### 2. Entry
Trigger: a listed leader's **first** buy in a coin under $80k. Only enter if fomo can fill within about 30 seconds.

Skip the coin if any of these is true. These are the avoid rules that held up in every test in `RESEARCH.md`:
- the dev has sold
- the top 3 wallets hold more than 60% of buy USD in the first 30 trades (bundled launch)
- the 5-minute price range is under 12% (a dying coin)
- the coin is a fresh launch that has already run
- there were fewer than 3 trades in the last minute

### 3. Size
- **$100–$190 per trade.** Below $190, fomo's $0.95 minimum fee raises your cost. Never more than $1k.
- At most $5k of buys per day and 10 entries per day.
- One position per coin. **No re-entry** after a loss on that coin that day. (The TWS bot's re-entry loop is the same failure.)

### 4. Exit
- Sell everything within 30 seconds of the leader's first sell.
- Two-hour time limit.
- Disaster stop at −50%. Stops on thin curves fill far below the trigger, so they limit damage but are not precise.
- Don't take early profits. In `RESEARCH.md` the profit came from runners.

### 5. Kill switch
Stop for the day after 4 losing trades in a row, or when the day's losses reach 15% of that day's buy budget.

### 6. Gate to real money
1. **50+ paper trades**, positive after costs both with and without the best 2 trades.
2. Then 50 real trades at $25–$50.
3. Then scale to $100–$190.

The 7-of-7 live losses in `RESEARCH.md` are why this gate exists.

## What carries over from the TWS momentum bot

- **The signal doesn't carry over.** The EMA9 / rolling-VWAP crossover with volume confirmation lost money on pump.fun at every bar size tested (`RESEARCH.md`).
- **The risk structure does:**
  - a fixed size cap per trade
  - one position per symbol
  - a time limit instead of holding overnight (the TWS bot's DAY-order gap)
  - no automatic re-entry after a stop
  - a hard daily stop
- **The "volume confirmation" idea** maps to the activity filter: 3+ trades in the last minute. That separates live coins from dying ones, but it is a filter, not an edge.

## Tools for the social (Twitter/X) layer

- **[`d60/twikit`](https://github.com/d60/twikit)** (~4.7k stars) and **[`vladkens/twscrape`](https://github.com/vladkens/twscrape)** (~2.9k stars):
  - both maintained as of 2026-10-11
  - both need a logged-in X account, and scraping breaks X's terms and can get that account suspended
  - use a separate account and keep its cookies in a local `.env`, never in this repo
- **[`GMGNAI/gmgn-skills`](https://github.com/GMGNAI/gmgn-skills)** (GMGN's official CLI):
  - wallet stats, Smart Money and KOL trade feeds, and per-coin bundler, sniper and insider ratios
  - needs a free personal API key from gmgn.ai/ai
  - I used only its public demo key, for one read-only lookup: wallet `7MgKaK…` showed +9.9% realized over 30 days on $18.5k bought, a 46% win rate over 490 coins, and 8 coins created by the wallet itself
  - its swap and order commands can trade from your wallet, so leave trading disabled
- **Avoid the small "memecoin Twitter bot" repos** with 0–5 stars. Crypto bot repos are a common way to spread wallet-draining malware.
- **What social data has shown so far** (`RESEARCH.md`): tweet-linked "news coins" underperform, because copycats split the attention. A paid DexScreener profile looks strong only because devs buy it *after* a pump (look-ahead). Any X signal has to be recorded at signal time and tested walk-forward.

## Caveats

1. **Survivorship.** Wallets were found because they traded today. Wallets that went broke and quit are missing, which lifts every group. The gaps between groups (winners, baseline, losers) are the more reliable finding than the levels.
2. **The leaders' ROI is pump.fun's portfolio PnL.** It may or may not net out the fees the leader paid in their own app.
3. **The strict group is 34 wallets** (21 in Sep–Oct), and its result depends partly on a few wallets.
4. **The copier replay covers one partial day**, and the full replay is still pending.

## To reproduce

```bash
cd fomo/small_traders
python seed2.py          # active sub-$80k coins and their latest trades
python wallets_fetch.py  # full position histories for small-size wallets
python walkforward_days.py
python copysim.py 190    # copier replay on today's tapes
python copy_wf.py        # full replay of strict-group positions (slow: paced for pump.fun's rate limit)
python leaders.py        # today's leader list
```
