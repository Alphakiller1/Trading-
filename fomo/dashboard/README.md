# FOMO Command: local trading dashboard

A local dashboard for the small-leader follow strategy in [`../SMALL_TRADERS.md`](../SMALL_TRADERS.md). It never places trades. It watches wallets on-chain, scores signals, paper-trades, logs your real trades, and alerts you.

**Start:** double-click `run_dashboard.bat`, or run `python server.py` and open http://127.0.0.1:8777.

**Hosted interface:** https://alphakiller1.github.io/Trading-/ shows the same dashboard and connects to the engine on your PC. Your data never leaves your machine; the page shows "engine offline" until `server.py` is running. If the browser asks to let the site reach devices on your local network, click Allow.

## What each view does

| View | What it does |
|---|---|
| **Command** | Live signals, open positions with live P&L, the alert stream, and today's numbers: P&L, entries against the cap, kill-switch state, and paper-gate progress |
| **Signals** | Every leader first-buy, with a verdict: GO, CAUTION or SKIP, and the reasons |
| **Trade log** | Real and paper trades, an equity curve, win rate, and ROI without the best 2 trades. Notes on every trade |
| **Intelligence** | Coin X-ray (paste any token address), market clock by ET hour, round-trip cost by trade size, your edge report, the research numbers, the rules |
| **Leaders** | Wallets that pass the leader rule. Re-scored daily from closed positions only. You can add your own |
| **Settings** | Sizing and risk limits, your fomo wallet, Discord webhook, RPC URL, X cookies |

## How it works

- **Wallet watching.** It polls each enabled leader wallet and your fomo wallet through Solana RPC (`core/chain.py`).
  - fomo trades are gasless and settle in USDC, so a trade is detected from the change in the wallet's token balances.
  - These are version 1 transactions, which the RPC request has to allow explicitly.
- **Signals.** A leader's **first** buy in a coin gets scored (`core/intel.py`). It is a SKIP when any of these is true:
  - the dev sold
  - the launch was bundled (the top 3 wallets took more than 60% of early buys)
  - the 5-minute range is under 12%
  - fewer than 3 real trades in the last minute
  - the coin is under 1 minute old
  - the market cap is over your limit

  Unknowns and weaker signals make it a CAUTION. Each signal gets X mentions if X is connected.
- **Paper trading.** Every GO signal opens a paper trade after `entry_delay_s`, priced with fomo's fees, pump.fun's fee and bonding-curve slippage. It closes when the leader sells (after the exit delay), at the 2-hour time stop, or at the −50% disaster stop.
- **Your real trades.** They import from your wallet's on-chain history the first time the wallet is set, then log live. Exit alerts fire when a leader you copied sells, and at the time and disaster stops.
- **Kill switch.** It trips after 4 losses in a row, or once the day's losses reach 15% of the daily cap. Then paper entries stop and you get a RISK alert.
- **Prices.** pump.fun's coin endpoint keeps a stale market cap after a coin graduates, so graduated coins are priced from DexScreener.

## Alerts

- **Desktop.** Click "Enable alerts" once in the browser. You get a notification and a sound for each alert.
- **Phone.** Put a Discord webhook in Settings, then use "Send test alert" to check it.

## X (Twitter)

Signals show recent X mentions, searched in a headless Edge with your own X session (library clients like twikit broke when X changed its request signing):
1. In your normal Edge, open x.com and press F12.
2. Go to Application → Cookies → https://x.com.
3. Copy `auth_token` and `ct0` into Settings.

The cookies are saved to `data/x_cookies.json`, which is gitignored. Searches are read-only, at most 1 every 15 seconds, and cached for 5 minutes. Scraping is against X's terms and can limit the account it runs on.

## Data

Everything runtime lives in `data/`, which is gitignored: settings, `fomo.db` (SQLite), the Edge profile, and X cookies. Delete `fomo.db` to start fresh.
