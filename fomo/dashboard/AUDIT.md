# FOMO Command: audit and verification (2026-10-11)

Run `python tools/verify.py` with the engine running to reproduce the matrix. It writes `data/verify_report.md`. Refit the model with `python tools/model_fit.py`.

## Verification matrix: 36 PASS, 1 WARN, 0 FAIL

| Area | What was proven |
|---|---|
| Data | pump.fun, swap API, Solana RPC and DexScreener all reachable. Graduated coins are priced from DexScreener: pump.fun's figure was stale ($815k vs $759k) |
| Parser | Your wallet's on-chain USDC ($51.99) equals fomo's cash figure, so it is your fomo trading wallet. **37 of 37 fomo swaps** were parsed from 38 transactions (fomo's own swapCount is 37). The trade log reconciles: P&L = proceeds − cost on all 17 closed trades |
| Costs | fomo's fee tier matches an observed fill: **1.98%** on a $20 order vs 2.00% in the model. Round trip: $25 6.3%, $100 4.4%, $190+ 3.5% |
| Rules | Unit tests on `intel.judge`: dev sold, bundled launch, dead-calm coin, inactive coin, fresh launch and over-cap market cap each → SKIP. Concentrated holders → CAUTION. A clean coin → GO. Unknowns alone no longer force CAUTION |
| Risk | Unit tests on `engine.risk_from`: the loss streak, daily loss limit, entry cap and buy cap all trip correctly. A winning day stays armed |
| Model | The EV table is fitted on 73,933 positions. **Out-of-sample rank correlation +0.72.** GO requires positive EV at your size |
| Live | The engine is watching. **Median 33s** from a leader's block to your alert. Alert de-duplication survives restarts |
| UI | Local and GitHub Pages both serve. CORS allows only your Pages site. X shows `ready` once a session is saved (this was the WARN: it read `off` until the first search) |

## Findings and fixes

1. **CAUTION mostly meant "data missing."** Almost every signal carried "dev activity unknown" and "launch concentration unknown," because busy coins can't be paged back to their launch.
   - **Fix:** two live on-chain facts, each one RPC call: whether the dev still holds tokens, and the top-3 holders' share outside the bonding curve.
   - Unknowns are now dim info lines and don't set the verdict.
2. **The verdict ignored who was buying and how much.**
   - **Fix:** a walk-forward EV model (`tools/model_fit.py` → `model/ev_table.json`, served by `core/model.py`).
   - **Data:** 73,933 positions from 364 small wallets.
   - **Each position's features:** the leader's prior-14-day class (from positions closed *before* that day), the coin's entry market cap, and the leader's position size.
   - **Validation:** fitted before Oct 1, tested on Oct 1–10. Rank correlation **+0.72** across 34 cells. The top quarter of cells by fit made **+2.2%** per trade out of sample, against **−5.1%** for all cells (leader-side).
   - **What predicts a good copy:** the leader's conviction (a $25+ buy), an early entry (under $10k market cap), and a leader who isn't a recent loser:

     | Cell | Out-of-sample result | Trades | Win rate |
     |---|---|---|---|
     | Strict leader, under $10k, $100+ buy | +14.7% | 59 | 59% |
     | Recent small winner, under $10k, $100+ buy | +11.6% | 482 | 47% |
     | Strict leader, under $10k, $25–100 buy | +8.1% | 80 | 60% |

   - **What loses:** buys under $25 (strict under $10k: −10.5%), new wallets, recent losers, and entries at $25k–$80k.
   - **Engine change:** GO now requires `copier EV = shrunk cell mean − (round trip at your size + 1.5% delay drift) > 0`. Cells with little data are shrunk toward a −5% prior.
3. **The leader rule watched the wrong wallets.** Strict-only watching missed the best large cell (recent small winners making $100+ buys).
   - **Fix:** watch every small, profitable, non-bot wallet (10+ closed trades in 14 days, positive ROI, median trade ≥ $10), and let the model pick which buys to copy.
4. **Sizing didn't match the account.** Settings assumed $190 trades and a $5k day with a $50 bankroll, so the EV math and the kill switch were meaningless.
   - **Fix:** $25 trades, a $250 daily buy cap, and a $25 daily loss limit (10% of the cap). Change these in Settings as the balance grows.
5. **Exit alerts repeated after every restart.** Fixed: de-duplication now checks the alert history.

## The $50 → $300 by Tuesday check

Monte Carlo with 20,000 runs and 40 trades. Per-trade outcomes come from the **out-of-sample October** data. Each trade is charged the copy penalty at its actual size.

| Trades taken | Sizing | Reach $300 | End under $10 | Median finish | Average finish |
|---|---|---|---|---|---|
| Model GO signals only | $25 each | 0.8% | 24.9% | $71 | $82 |
| Model GO signals only | **half the balance** | **12.2%** | **8.8%** | $45 | $94 |
| Model GO signals only | all-in | 24.6% | 49.2% | $11 | $118 |
| Every leader signal | any | 0.0–1.5% | 94–98% | ~$4 | ~$7–9 |
| Your own 17 trades, replayed | half the balance | 2.1% | 4.4% | $41 | — |

**Reading it:**
- The model turns a near-certain loss (94% bust copying everything) into a positive average.
- **Tripling or 6×-ing $50 in two days is still a long shot at any sizing.** The more you bet per trade, the better the odds of reaching $300, and the more likely the account ends near zero.
- **Caveats:**
  - These are leader-side results minus an estimated penalty, not your fills.
  - The wallet set is survivorship-biased: it only includes wallets still active today.
  - 40 GO signals by Tuesday is an assumption, not a certainty.
