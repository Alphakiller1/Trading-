# fomo meme-coin research: findings so far (2026-10-10)

Data: 294k pump.fun trades across 1,533 coins (pulled 2026-10-10); 7 days of on-chain launch and graduation timestamps (368k launches).
Costs modeled throughout:
- fomo fee tiers: 2% for $5–$47.50; flat $0.95 for $47.50–$190; 0.5% at $190+
- pump.fun fee: 1% per side
- constant-product slippage
- human reaction delay: 10 seconds unless stated

All "test" numbers come from coins that were held out from tuning.

## Base rates
- 78% of coins never pass a $10k market cap.
- Immediate round-trip cost (fees only; slippage cancels on a constant-product curve):

  | Trade size | $25 | $50 | $100 | $190+ |
  |---|---|---|---|---|
  | Round-trip cost | 5.9% | 5.8% | 3.9% | 3.0% |

- Random entries on coins between $5k and $80k: −0.3% with no costs and no delay. With costs and a 10-second delay: −11% to −14% per trade.
  **That is the bar every strategy has to clear.**

## Ruled out (negative after costs on the test set)
| Idea | Test-set ROI per trade |
|---|---|
| TWS rules as written (5s bars, 1% stop, 2% trail) | Profit came from 1 trade (+2,351%); −$1,281 without it. Negative with a 10-second delay |
| TWS EMA9/VWAP cross on 15s and 60s bars, any band | −5% to −17% |
| Buying fresh launches (first minute) | −11% to −30% |
| Graduation-zone momentum (crossing $45k–$55k) | −6% to −16% |
| Dip-buying after a sharp drop (20–40% within 30s) | −7% to −16% |
| **Buying after a dev dump** | **−19%, 13% win rate. Never do this.** |

## What carries information
- **Wallet skill persists.**
  - Small wallets (max buy ≤ $1k) that were profitable on half A of the coins made +15% pooled ROI on half B; 59% of them stayed profitable.
  - Wallets that lost on half A made −0.4% on half B.
- **Copy rule:** copy the first buy on a coin by any half-A-profitable wallet (median hold of at least 20 seconds, which screens out bots), and sell when that wallet sells. Result: **+2.0% to +3.7% per trade after costs**, at both $100 and $250 and with a 5–30 second delay (n = 134).
  - Fragile: −1.4% to −3.1% when the top 2% of winners are removed.
  - Stricter wallet filters made it worse, probably because the sample shrinks.
- Snapshots where the coin is active (3+ trades in the last minute) average about −3% versus −12% for random entries. Activity is a necessary filter, not an edge on its own.

## Time of day (7 days on-chain; graduation counts are relative, not true %)
| ET | Launches/hr | Graduations per 1k launches |
|---|---|---|
| 5–7 PM | ~2,700 | 37–43 (best) |
| Midnight–4 AM | ~1,500 | 38–41 (least competition) |
| 10 AM–4 PM | 2,200–2,900 | 29–34 |
| 7–8 AM | ~2,100 | 26–28 (worst) |

By weekday: Saturday is best (39) and Wednesday/Thursday worst (~30).

## Live test log
| Time (UTC) | Coin | Size | Signal | Result |
|---|---|---|---|---|
| 21:40 | GEPE | (not entered) | Leader had only 3 qualifying coins | −35% within 90 seconds, stop hit |
| 21:42 | Samsol | $25 | Leader bought $343 | Low −28%, exited around −12% by the 21:55 tick; leader still holding |

Lesson: weak leaders and tiny leader buys are noise. Live filters now require:
- the leader has 5–30 qualifying past coins with ROI ≥ 15% and a win rate ≥ 40%
- the leader's buy is ≥ $100
- the coin is ≥ 30 minutes old
- the dev hasn't sold
- positive net buying over the last 5 minutes, with 20 or more buyers
- price no more than 15% above the trigger

## Copy model v2: robustness check (each half of the coins reported separately)
Run with `copy2.py`. ROI per trade after costs at $100 with a 15-second delay. A rule only counts if it is positive on **both** halves.

| Variant | Half A | Half B |
|---|---|---|
| Baseline v1 (any half-A-profitable wallet, mirror exit, 30% stop) | +6.0% | −1.8% |
| Dev has not sold | +7.0% | −0.9% |
| 20% stop | +6.0% | −1.1% |
| Size $250 | +6.5% | −1.0% |
| Leader buy ≥ $100 | −3.8% | −5.4% |
| Leader has 5–30 coins | −3.9% | −5.6% |
| Coin age ≥ 30 min | −1.7% | −3.4% |
| 20+ buyers in last 5 min | −6.8% | −8.9% |
| Sell half at +30% or +50% | −1.7% | −3.9% / −1.9% |
| Trailing stop 25% | −4.2% | −4.0% |

Conclusions:
- **No variant is positive on both halves yet.** The v1 edge depends on a few big runners, and about 130 trades are too few to tell edge from luck.
- The "strict" live filters added after the GEPE loss were not supported by the data, so they were reverted.
- Cutting winners early (scale-outs, trailing stops) hurts. The profit comes from tail runners.
- Live signals are **paper only** until the expanded dataset confirms an edge.

## Copy model v3: bundle filter (first rule positive on both halves)
Run with `copy3.py`. **Bundle filter:** skip the coin if the top 3 wallets account for more than 60% of buy USD in its first 30 trades (a sniped or bundled launch).

Coins with complete trade histories only (618 of 812). ROI per trade after costs, 15-second delay:

| Rule | All | Half A | Half B | Without top 2% | n |
|---|---|---|---|---|---|
| Copy baseline | +8.3% | +19.9% | −3.8% | −0.5% | 51 |
| Early top-3 ≤ 70% | +10.8% | +25.6% | −5.7% | −1.1% | 38 |
| Early top-3 ≤ 60% | +19.3% | +33.9% | −1.4% | +3.8% | 29 |
| **Early top-3 ≤ 60% + dev not sold** | **+29.0%** | **+47.9%** | **+4.3%** | **+9.4%** | 23 |
| Same, $20 size | +27.3% | +46.5% | +2.3% | +7.4% | 23 |
| Same, 30-second delay | +30.7% | +50.3% | +5.2% | +14.9% | 23 |

Leader holding-time filters (median hold ≥ 60s up to ≥ 30 min) did **not** help.

Caveat: n = 23, with only 10 trades in half B. Promising, but not proven. The rule is now in the live scanner and paper trader (`paper.py`) to collect out-of-sample evidence.

## Paper trades (live, before the bundle filter)
| Coin | Result | Note |
|---|---|---|
| ZZZ | −38% | Leader sold within 30 seconds |
| TRUMP | −85% | Rug within 24 seconds; leader 9CtjtC also triggered PUMP (coordinated) |
| PUMP | −3% (stop flash) | Same leader as TRUMP |

## Social / narrative layer
X (Twitter) can't be read from this environment: it requires a login and no API key is available. Sources used instead: pump.fun coin metadata (twitter, website and telegram links), DexScreener's public API (paid profiles, boosts) and web search.

Coins launched 1–72h ago, how often each type reached a given peak market cap. Survivor-biased sample, so compare the rows rather than trusting the absolute numbers.

| Social type | → $30k | → $100k | → $200k |
|---|---|---|---|
| Website/Telegram | 37.9% | 32.2% | 27.6% |
| X profile | 25.6% | 16.1% | 12.7% |
| Linked to a tweet (news/event coin) | 16.2% | 8.2% | 4.5% |
| No socials | 10.7% | 8.0% | 6.8% |
| **Paid DexScreener profile** | 84.3% | 54.1% | 33.1% |
| DexScreener pair, no profile | 8.2% | 4.9% | 4.3% |

- News/event coins underperform as a group. Many copycats launch on the same tweet and split attention, so the edge is picking the leading coin for an event, not event coins in general.
- **The DexScreener profile result has look-ahead bias.** Devs often buy the profile after the coin pumps. The live scanner now records profile and boost status **at signal time**, so this can be tested honestly from paper trades.
- Copy trades by social type: tweet-linked −11% and X-profile +18% after removing the top 2% of winners. Each group has only 8–21 trades, so this is a hint, not a rule.

## Rug protection
- TRUMP and PUMP (live, same leader `9CtjtC…`) both rugged about 99% within 15 seconds of the signal.
- Leaders whose copied signal loses 80% or more are added to `blacklist.txt` automatically and never copied again.

## Unbiased launch cohort (live logger, first 30 min of every launch)
Source: `logger.py` and `cohort.py`. 225 launches with trade data.
- Reached $10k within 30 minutes: 3.9%. Reached $30k: 0.8%.
- Early buyer concentration, top-3 wallets' share of early buys:
  - 0–40%: 42.9% reached $10k
  - 40–60%: 11.5%
  - 80% or more: 5.8% (76% of all launches fall here)
- 40+ buyers in the first minute: 30.8% reached $10k, against 5.1% for 0–5 buyers.

## Early-quality-launch entry: fails
Source: `early_quality.py`. Rule: buy at 60–120 seconds if many buyers, low concentration and the dev hasn't sold.
- Result: **−19% to −26% per trade at $20**, worse than a random entry at 70 seconds (−7%).
- By the time the quality is visible, the price has already run. A signal can predict a high peak and still be unprofitable to buy.

## Copy + bundle filter, trade by trade ($20 each)
- 23 trades: **+$125.58 total**, 8 wins, median −$1.00.
- SPROUT (+457%) and HOTDOG (+228%) carry the result: +7.8% per trade without the best trade, **−2.7% without the best two**.
- Latency:

  | Delay | ROI per trade | Half B |
  |---|---|---|
  | 5s | +29.8% | positive |
  | 30s | +28.7% | positive |
  | 60s | +17.5% | −11% |
  | 90s | +19.5% | −5% |

- **Profile: lottery-like.** Many small losses and rare 3–5× runners. It needs many small trades, fast execution (≤ 30s) and no early profit-taking. It is not low-risk.

## Copy model v4: size and exit optimization
Run with `run_v4.py`. Bundle filter + dev not sold, market cap ≤ $200k, coins with complete histories.

**Trade size** (fees vs slippage):

| Size | ROI per trade | Without top 2% |
|---|---|---|
| $20 | +27.3% | +7.4% |
| $100 | +29.0% | +9.4% |
| **$190** | **+29.1%** | **+10.1%** |
| $250 | +28.6% | +10.0% |
| $500 | +26.7% | +9.7% |
| $1,000 | +24.0% | +9.1% |
| $2,000 | +20.6% | +8.2% |

Best: $190–$250 (fomo's 0.5% fee tier, little slippage). It still works at $1k–$2k.

**Exits:**

| Exit | ROI | Without top 2% | Half A | Half B |
|---|---|---|---|---|
| Mirror the leader (v3) | +29.0% | +9.4% | +47.9% | +4.3% |
| **Sell half when the leader sells, trail the rest 30%** | **+33.8%** | **+16.9%** | **+48.7%** | **+14.4%** |
| Half on leader sell, trail rest 50% | +30.8% | +9.7% | +51.5% | +4.0% |
| Half on leader sell, hold rest 2h | +27.5% | +11.2% | +45.2% | +4.5% |

**Leader selection:**
- Stricter filters hurt: leader ROI > 25% gave −12.0%, and leader runner share ≥ 20% gave −2.4%.
- Runner share ≥ 10% gave +34.7% but on only 17 trades.

**Adopted in `paper.py`:**
- size: $190–$250
- before the leader sells: stop at −30%
- when the leader sells: sell half and trail the rest 30% from its peak
- time limit: 2 hours

## Size tiers: $20–55 / $60–125 / $130–250
Run with `tiers.py`. 53 copy-signal trades (v4 exits, coins with complete histories, ≤ $200k).

**Predictability score (0–5)**, pre-specified, not fitted:
- +2 if the top-3 early-buyer share is ≤ 60% (+1 if ≤ 80%)
- +1 if the dev has not sold
- +1 if the leader has 5+ past coins
- +1 if the coin has real socials (website, Telegram or an X profile)

**ROI by score:**
- Only **score 5 is positive on both halves**: +35.1% (half A +47.2%, half B +21.2%), +9.2% without the top 2%.
- Scores 3–4 are mixed or negative.

**Volatility (5-minute price range before entry). Lower is not safer here:**

| Range | ROI per trade |
|---|---|
| Low (< 12%) | **−13.1%** (both halves negative: a calm coin is usually a dying coin) |
| Mid (12–32%) | **+36.2%** |
| High (≥ 32%) | +5.1% |

**Market cap:** nearly all signals fire under $15k (+15.7%). The $15k–$80k signals were negative, but n = 9.

**Tier rules (v2):**
- **Skip:** dev sold, volatility < 12%, or score ≤ 3. **Robust: −10% on both halves.**
- **T3 ($130–250):** score 5 and volatility 12–32%. In-sample +154%, but **n = 4, so not proven**.
- **T2 ($60–125):** score 5 and volatility ≥ 32%. +0.2% (n = 6).
- **T1 ($20–55):** score 4 (with volatility ≥ 12%). +22.6% (n = 10), half B −9.5%.

The skip rule is the reliable part. The tier boundaries were tuned on the same data and need paper-trade validation.

## Live results, 2026-10-10 evening (the honest scoreboard)
| Time (UTC) | Coin | Type | Signal mcap | Result within minutes |
|---|---|---|---|---|
| 21:40 | GEPE | copy signal | $18.6k | −35%, stop |
| 21:42 | Samsol | copy, $25 real | $13.7k | dipped −28%, exited about −12% |
| 22:02 | ZZZ | copy (paper) | $71.9k | −38%, leader sold within 30s |
| 22:06 | TRUMP | copy (paper) | $41.0k | −99% rug |
| 22:06 | PUMP | copy (paper) | $45.1k | −99% rug |
| 23:11 | OPENWORK | copy, score 4 | $4.8k | −36%, leader sold |
| 23:24 | pup | organic momentum, real $23 | $35.5k | **−48% in under 1 min** |

**7 of 7 live picks fell 25–99% within minutes.** The backtested copy edge (+29% per trade on 23 trades) did **not** show up live.

Likely reasons:
1. The backtest was too small and leaned on 2 runners.
2. At human speed, the copied wallets and dumpers exit before a manual trader can.
3. Prices gap through stops on thin bonding curves, so a −30% stop often fills at −40% to −99%.

**Conclusion: do not trade this strategy with real money.** Any continuation is paper-only, until at least 50 paper trades show a positive after-cost result.

## Walk-forward test: the copy edge was a look-ahead artifact
Run with `walkforward.py`. Wallet skill is measured using **only trades before cutoff T** (open positions marked at T); signals are traded only after T. Cutoff 19:55 UTC (later cutoffs leave no room for trades to finish before the data ends):

| Rule | n | ROI per trade | Median |
|---|---|---|---|
| v4 (bundle ≤ 60%, dev not sold) | 6 | −8.1% | −7.7% |
| No bundle filter | 18 | +4.0% | −7.1% |
| All copy signals | 45 | −3.5% | −11.4% |

- The coin-half split had a leak: all coins traded in the same window, so a wallet's skill came partly from how its same-period trades turned out. Once that leak is removed, the edge disappears. That matches the live record of 0 for 7.
- **What survives every test is the avoid list:** dev sold, bundled launch, volatility < 12%, and buying fresh launches after a run.
- **What's needed is multi-day data**, so walk-forward tests can use days of training and a separate test day. `collector.py` is built to run for days on a home PC.

## Open work
- (superseded by the walk-forward result) Re-test the copy rule on full coin histories, including the $80k–$200k band (focus is now coins under $200k; current data has no full-history signals above $80k).
- Improve exits on copies, for example scaling out at +30% or +50% instead of only mirroring the leader.
- Add time-of-day and copy-signal conditioning to the backtest.
- Alert bot, `bot.py`, combining the live scanner and exit watcher with Telegram or Discord output.
