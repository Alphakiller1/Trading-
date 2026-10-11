"""Solana RPC: watch wallets and turn their transactions into buys/sells.

fomo trades are gasless and settle in USDC, so a buy shows up as: owner's USDC goes down and the
owner's balance of a pump.fun token goes up, with someone else paying the fee. Parsing owner
token-balance deltas handles that and normal SOL-paid trades alike.
"""
import threading, time, requests
from . import config

QUOTES = {
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "USDC",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": "USDT",
    "So11111111111111111111111111111111111111112": "WSOL",
}
_gap = threading.Lock(); _last = [0.0]
health = {"last_ok": 0.0, "errors": 0}


def rpc(method, params, tries=4):
    url = config.load()["rpc_url"]
    for i in range(tries):
        with _gap:
            w = _last[0] + 0.25 - time.time()
            if w > 0:
                time.sleep(w)
            _last[0] = time.time()
        try:
            r = requests.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=20)
            if r.status_code == 429:
                time.sleep(2 * (i + 1)); continue
            d = r.json()
            if "error" in d:
                time.sleep(1 + i); continue
            health["last_ok"] = time.time()
            return d.get("result")
        except Exception:
            health["errors"] += 1
            time.sleep(1 + i)
    return None


def signatures(wallet, limit=15):
    return rpc("getSignaturesForAddress", [wallet, {"limit": limit}]) or []


def parse_trade(sig, wallet, sol_px, fresh=False):
    """Returns a trade dict, or None if the tx didn't change the wallet's meme-token balance.
    fresh=True: the tx was just pushed to us, so read it at 'confirmed' (1-2s) instead of waiting
    for 'finalized' (~13s), and retry briefly while the node catches up."""
    opts = {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 1, "commitment": "confirmed"}
    tx = None
    for i in range(6 if fresh else 1):
        tx = rpc("getTransaction", [sig, opts])
        if tx:
            break
        time.sleep(0.7)
    if not tx or not tx.get("meta") or tx["meta"].get("err"):
        return None
    m = tx["meta"]
    keys = [k["pubkey"] for k in tx["transaction"]["message"]["accountKeys"]]
    bal = {}
    for side, arr in ((0, m.get("preTokenBalances") or []), (1, m.get("postTokenBalances") or [])):
        for b in arr:
            if b.get("owner") == wallet:
                v = bal.setdefault(b["mint"], [0.0, 0.0])
                v[side] += float(b["uiTokenAmount"].get("uiAmount") or 0)
    deltas = {k: v[1] - v[0] for k, v in bal.items() if abs(v[1] - v[0]) > 1e-9}
    memes = {k: d for k, d in deltas.items() if k not in QUOTES}
    if not memes:
        return None
    mint = next((k for k in memes if k.endswith("pump")), max(memes, key=lambda k: abs(memes[k])))
    tok = memes[mint]
    quote_usd = 0.0
    for k, d in deltas.items():
        if QUOTES.get(k) in ("USDC", "USDT"):
            quote_usd += d
        elif QUOTES.get(k) == "WSOL":
            quote_usd += d * sol_px
    if wallet in keys:
        i = keys.index(wallet)
        sol_d = (m["postBalances"][i] - m["preBalances"][i]) / 1e9
        if abs(sol_d) > 0.002:            # ignore rent/fee dust
            quote_usd += sol_d * sol_px
    post = bal[mint][1]
    return dict(sig=sig, wallet=wallet, mint=mint, side="buy" if tok > 0 else "sell", tokens=abs(tok),
                usd=abs(quote_usd), ts=tx.get("blockTime") or time.time(), remaining=post,
                gasless=keys[0] != wallet)
