"""X (Twitter) mentions for a coin, read-only, via twikit and the cookies saved by
tools/browser_login.py. Throttled hard (one search per 15s, 5-minute cache) because this runs on
your own account: scraping is against X's terms and can get an account limited.
"""
import asyncio, json, os, threading, time
from . import config

COOKIES = os.path.join(config.DATA, "x_cookies.json")
status = {"state": "off", "detail": "", "last_ok": 0.0}
_cache = {}
_lock = threading.Lock()
_last = [0.0]
_loop = None
_client = None


def _ensure():
    global _loop, _client
    if _client is not None:
        return True
    if not config.load().get("x_enabled"):
        status.update(state="off", detail="Disabled in settings"); return False
    if not os.path.exists(COOKIES):
        status.update(state="off", detail="Not signed in: run tools/browser_login.py --x"); return False
    try:
        from twikit import Client
    except Exception:
        status.update(state="off", detail="twikit not installed: pip install twikit"); return False
    _loop = asyncio.new_event_loop()
    threading.Thread(target=_loop.run_forever, daemon=True).start()
    c = Client("en-US")
    c.set_cookies(json.load(open(COOKIES)))
    _client = c
    status.update(state="on", detail="Connected")
    return True


def reset():
    """Drop the client so new cookies are picked up on the next search."""
    global _client
    _client = None
    _cache.clear()
    status.update(state="off", detail="Cookies updated")


def mentions(symbol, mint):
    """Returns dict or None. Never raises."""
    key = mint
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < 300:
        return hit[1]
    with _lock:
        if not _ensure():
            return None
        wait = _last[0] + 15 - time.time()
        if wait > 0:
            return hit[1] if hit else None          # don't block the engine; try next time
        _last[0] = time.time()
    query = f'{mint} OR "${symbol}"' if symbol and symbol != "?" else mint
    try:
        fut = asyncio.run_coroutine_threadsafe(_client.search_tweet(query, "Latest", count=20), _loop)
        tweets = fut.result(timeout=25)
    except Exception as e:
        status.update(state="error", detail=str(e)[:160])
        return None
    now = time.time()
    rows = []
    for t in tweets:
        try:
            ts = t.created_at_datetime.timestamp()
        except Exception:
            ts = now
        u = t.user
        rows.append(dict(ts=ts, user=getattr(u, "screen_name", "?"), followers=getattr(u, "followers_count", 0) or 0,
                         text=(t.text or "")[:220], likes=getattr(t, "favorite_count", 0) or 0))
    out = dict(
        n=len(rows),
        last_30m=sum(now - r["ts"] <= 1800 for r in rows),
        authors=len({r["user"] for r in rows}),
        max_followers=max([r["followers"] for r in rows] or [0]),
        top=sorted(rows, key=lambda r: -(r["followers"] + 50 * r["likes"]))[:3],
        checked=now,
    )
    status.update(state="on", detail="Connected", last_ok=now)
    _cache[key] = (now, out)
    return out
