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

## Open work
- Re-test the copy rule on full coin histories (the re-download was paused when pump.fun rate-limited it).
- Improve exits on copies, for example scaling out at +30% or +50% instead of only mirroring the leader.
- Add time-of-day and copy-signal conditioning to the backtest.
- Alert bot, `bot.py`, combining the live scanner and exit watcher with Telegram or Discord output.
