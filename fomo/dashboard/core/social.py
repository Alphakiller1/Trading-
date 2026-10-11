"""X (Twitter) mentions for a coin, read-only, using YOUR session cookies (data/x_cookies.json).

Searches run in a real headless Edge (Playwright) so X's own web client signs the requests;
library clients like twikit broke when X changed its request signing ("KEY_BYTE indices").
We open x.com/search?f=live and read the SearchTimeline JSON the page receives.
Throttled hard (one search per 15s, 5-minute cache): scraping is against X's terms and can get an
account limited.
"""
import json, os, queue, threading, time, datetime as dt
from concurrent.futures import Future
from urllib.parse import quote
from . import config

COOKIES = os.path.join(config.DATA, "x_cookies.json")
status = {"state": "off", "detail": "", "last_ok": 0.0}
_cache, _last = {}, [0.0]
_q = queue.Queue()
_worker = None
_lock = threading.Lock()


def view():
    """Status for the UI: 'ready' when a session is saved but no search has run yet."""
    if status["state"] == "off" and config.load().get("x_enabled") and os.path.exists(COOKIES):
        return dict(status, state="ready", detail="Session saved; searches on the next signal")
    return status


def reset():
    """Pick up new cookies: restart the browser worker."""
    global _worker
    if _worker:
        _q.put(None)
    _worker = None
    _cache.clear()
    status.update(state="off", detail="Cookies updated")


def _find(obj, key):
    """First value for `key` anywhere inside obj (X moves user fields between schema versions)."""
    if isinstance(obj, dict):
        if key in obj and not isinstance(obj[key], (dict, list)):
            return obj[key]
        for v in obj.values():
            r = _find(v, key)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _find(v, key)
            if r is not None:
                return r
    return None


def _tweets(obj, out):
    """Walk X's GraphQL JSON and collect tweets with their authors."""
    if isinstance(obj, dict):
        leg = obj.get("legacy")
        if isinstance(leg, dict) and "full_text" in leg and "created_at" in leg:
            u = (((obj.get("core") or {}).get("user_results") or {}).get("result") or {})
            ul = u.get("legacy") or {}
            uc = u.get("core") or {}
            out.append(dict(
                ts=dt.datetime.strptime(leg["created_at"], "%a %b %d %H:%M:%S %z %Y").timestamp(),
                user=uc.get("screen_name") or ul.get("screen_name") or _find(u, "screen_name") or "?",
                followers=_find(u, "followers_count") or 0, likes=leg.get("favorite_count") or 0,
                text=leg["full_text"][:220], id=leg.get("id_str")))
            return
        for v in obj.values():
            _tweets(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _tweets(v, out)


def _run():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        try:
            b = p.chromium.launch(channel="msedge", headless=True)
        except Exception:
            b = p.chromium.launch(headless=True)
        ctx = b.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36 Edg/140.0")
        ck = json.load(open(COOKIES))
        ctx.add_cookies([dict(name=k, value=v, domain=".x.com", path="/", secure=True, httpOnly=(k == "auth_token"))
                         for k, v in ck.items()])
        pg = ctx.new_page()
        while True:
            job = _q.get()
            if job is None:
                break
            query, fut = job
            got = []

            def on(r):
                if "SearchTimeline" in r.url:
                    try:
                        _tweets(r.json(), got)
                    except Exception:
                        pass
            pg.on("response", on)
            try:
                pg.goto(f"https://x.com/search?q={quote(query)}&src=typed_query&f=live", wait_until="domcontentloaded", timeout=30000)
                t0 = time.time()
                while not got and time.time() - t0 < 12:
                    pg.wait_for_timeout(400)
                if "login" in pg.url or "onboarding" in pg.url:
                    fut.set_exception(RuntimeError("X session expired: re-save cookies in Settings"))
                else:
                    fut.set_result(got)
            except Exception as e:
                fut.set_exception(e)
            finally:
                pg.remove_listener("response", on)
        b.close()


def _ensure():
    global _worker
    if not config.load().get("x_enabled"):
        status.update(state="off", detail="Disabled in settings"); return False
    if not os.path.exists(COOKIES):
        status.update(state="off", detail="Not connected: add X cookies in Settings"); return False
    if _worker is None or not _worker.is_alive():
        _worker = threading.Thread(target=_run, daemon=True)
        _worker.start()
    return True


def mentions(symbol, mint):
    """Recent X mentions of a coin (by contract address or $SYMBOL). Returns dict or None; never raises."""
    hit = _cache.get(mint)
    if hit and time.time() - hit[0] < 300:
        return hit[1]
    with _lock:
        if not _ensure():
            return None
        if time.time() - _last[0] < 15:
            return hit[1] if hit else None
        _last[0] = time.time()
    query = f'{mint} OR "${symbol}"' if symbol and symbol != "?" and len(symbol) <= 12 else mint
    fut = Future()
    _q.put((query, fut))
    try:
        rows = fut.result(timeout=45)
    except Exception as e:
        status.update(state="error", detail=str(e)[:160])
        return None
    now = time.time()
    rows = list({r["id"]: r for r in rows}.values())
    out = dict(n=len(rows), last_30m=sum(now - r["ts"] <= 1800 for r in rows), authors=len({r["user"] for r in rows}),
               max_followers=max([r["followers"] for r in rows] or [0]),
               top=sorted(rows, key=lambda r: -(r["followers"] + 50 * r["likes"]))[:3], checked=now)
    status.update(state="on", detail="Connected", last_ok=now)
    _cache[mint] = (now, out)
    return out
