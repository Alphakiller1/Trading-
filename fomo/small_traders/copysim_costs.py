"""Cost model shared by the copy simulations: fomo fee tiers, pump.fun fee, bonding-curve slippage."""

SOLUSD, K = 110.0, 30 * 1.073e9   # pump.fun curve: 30 virtual SOL x 1.073B virtual tokens
PUMP_FEE = 0.0125                  # conservative (sources say 1.0-1.25% per side)


def fomo_fee(usd):                 # same tiers as Trading-/fomo/backtest.py
    if usd < 5: return 0.10
    if usd < 47.5: return usd * 0.02
    if usd < 190: return 0.95
    return usd * 0.005


def buy_tokens(usd, px):           # constant-product fill at the curve state implied by px
    """Returns (tokens, lift): lift is how much our own buy raises the curve price, which the tape
    prices we later sell into do not include (same treatment as Trading-/fomo/strategies.py)."""
    x = (usd - fomo_fee(usd)) * (1 - PUMP_FEE) / SOLUSD
    vS = (px / SOLUSD * K) ** 0.5; vT = K / vS
    return vT - K / (vS + x), ((vS + x) / vS) ** 2


def sell_usd(tokens, px):
    vS = (px / SOLUSD * K) ** 0.5; vT = K / vS
    usd = (vS - K / (vT + tokens)) * SOLUSD * (1 - PUMP_FEE)
    return usd - fomo_fee(usd)
