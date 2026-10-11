"""Sign in to fomo and X once, in a real Microsoft Edge window that YOU control.

    python tools/browser_login.py            # both
    python tools/browser_login.py --x        # X only
    python tools/browser_login.py --fomo     # fomo only

You type your own passwords/codes in the Edge window; this script never sees them.
It saves, under data/ (gitignored):
  - x_cookies.json   your X session cookies (auth_token, ct0), used read-only for coin search
  - settings.json    my_wallet = your fomo Solana wallet, read from fomo's login response
The Edge profile lives in data/edge-profile, so later runs stay signed in.
"""
import json, os, sys, time
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core import config  # noqa: E402

PROFILE = os.path.join(config.DATA, "edge-profile")
X_COOKIES = os.path.join(config.DATA, "x_cookies.json")
want_x = "--fomo" not in sys.argv
want_fomo = "--x" not in sys.argv
TIMEOUT_S = 30 * 60


def find_solana_wallets(obj, out):
    """Collect Solana addresses from Privy-style linked accounts in any JSON response."""
    if isinstance(obj, dict):
        ct = str(obj.get("chain_type") or obj.get("chainType") or obj.get("chain") or "").lower()
        addr = obj.get("address")
        if addr and isinstance(addr, str) and "solana" in ct and 32 <= len(addr) <= 44:
            out.add(addr)
        for v in obj.values():
            find_solana_wallets(v, out)
    elif isinstance(obj, list):
        for v in obj:
            find_solana_wallets(v, out)


wallets = set()
with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(PROFILE, channel="msedge", headless=False,
                                               viewport=None, args=["--start-maximized"])

    def on_response(r):
        if "privy" in r.url or "fomo.family" in r.url:
            try:
                if "json" in r.headers.get("content-type", ""):
                    find_solana_wallets(r.json(), wallets)
            except Exception:
                pass

    ctx.on("response", on_response)
    pages = ctx.pages
    if want_fomo:
        pg = pages[0] if pages else ctx.new_page()
        pg.goto("https://fomo.family")
    if want_x:
        px = ctx.new_page() if want_fomo else (pages[0] if pages else ctx.new_page())
        px.goto("https://x.com/login")
    print("Sign in inside the Edge window (fomo: click Login; X: your username/password/code).")
    print("This window closes by itself once both sessions are detected (30 min limit).", flush=True)

    x_done, fomo_done, t0 = not want_x, not want_fomo, time.time()
    while time.time() - t0 < TIMEOUT_S and not (x_done and fomo_done):
        time.sleep(3)
        try:
            if not x_done:
                ck = {c["name"]: c["value"] for c in ctx.cookies(["https://x.com"])}
                if ck.get("auth_token") and ck.get("ct0"):
                    json.dump({"auth_token": ck["auth_token"], "ct0": ck["ct0"]}, open(X_COOKIES, "w"))
                    x_done = True
                    print("X session saved.", flush=True)
            if not fomo_done and wallets:
                w = sorted(wallets)[0]
                config.save({"my_wallet": w})
                fomo_done = True
                print(f"fomo wallet saved: {w}", flush=True)
        except Exception as e:
            if "closed" in str(e).lower():
                break
    if not fomo_done and want_fomo:
        print("fomo wallet not detected. Paste it in the dashboard's Settings (fomo app: Deposit > Solana address).")
    if not x_done and want_x:
        print("X session not detected. Run again with --x after signing in.")
    try:
        ctx.close()
    except Exception:
        pass
