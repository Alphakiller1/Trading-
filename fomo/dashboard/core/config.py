"""Settings for the fomo dashboard. Stored in data/settings.json (gitignored)."""
import json, os, threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
FOMO_DIR = os.path.dirname(ROOT)
os.makedirs(DATA, exist_ok=True)
PATH = os.path.join(DATA, "settings.json")

DEFAULTS = {
    # sizing and risk (the strategy in fomo/SMALL_TRADERS.md)
    "trade_size_usd": 190,          # fomo's 0.5% tier starts at $190; below it the $0.95 minimum bites
    "max_trade_usd": 1000,
    "daily_buy_cap_usd": 5000,
    "max_entries_per_day": 10,
    "daily_loss_limit_pct": 15,     # % of the daily buy cap
    "loss_streak_limit": 4,
    "max_mcap_usd": 80000,
    # copy mechanics
    "entry_delay_s": 30,
    "exit_delay_s": 30,
    "time_stop_min": 120,
    "disaster_stop_pct": -50,
    "auto_paper": True,             # open a paper trade on every GO signal
    # data
    "rpc_url": "https://api.mainnet-beta.solana.com",
    "poll_leaders_s": 5,
    "min_leader_median_usd": 40,    # only watch leaders who trade at size: every positive-EV signal came from $54+ medians
    "poll_positions_s": 15,
    # alerts
    "discord_webhook": "",
    "alert_on": ["GO", "CAUTION", "EXIT", "RISK"],
    # you
    "my_wallet": "",                # your fomo wallet's Solana address: auto-logs your real trades
    # social
    "x_enabled": True,              # used only if tools/x_login.py has saved cookies
}

_lock = threading.Lock()


def load():
    with _lock:
        s = dict(DEFAULTS)
        if os.path.exists(PATH):
            try:
                s.update(json.load(open(PATH, encoding="utf-8")))
            except Exception:
                pass
        return s


def save(updates):
    with _lock:
        cur = dict(DEFAULTS)
        if os.path.exists(PATH):
            try:
                cur.update(json.load(open(PATH, encoding="utf-8")))
            except Exception:
                pass
        for k, v in updates.items():
            if k in DEFAULTS:
                cur[k] = type(DEFAULTS[k])(v) if not isinstance(DEFAULTS[k], (list, bool)) else v
        json.dump(cur, open(PATH, "w", encoding="utf-8"), indent=2)
        return cur
