"""The live engine: watches leader wallets (and yours) on-chain, scores every leader buy, runs the
paper trader, raises exit alerts, auto-logs your real trades and enforces the daily risk limits."""
import datetime as dt, json, threading, time, traceback
from zoneinfo import ZoneInfo
import requests
from . import config, store, pump, chain, intel, social, leaders, model

ET = ZoneInfo("America/New_York")
state = {"started": time.time(), "last_cycle": 0.0, "watching": 0, "errors": [], "kill": {}}
_timers = []
_alerted = set()


def log_error(where, e):
    state["errors"] = (state["errors"] + [f"{time.strftime('%H:%M:%S')} {where}: {e}"])[-20:]


# ---------------------------------------------------------------- alerts
def notify(level, kind, title, body="", mint=None):
    store.alert(level, kind, title, body, mint)
    cfg = config.load()
    hook = cfg.get("discord_webhook")
    if hook and kind in cfg.get("alert_on", []):
        color = {"go": 0x8B5CF6, "caution": 0xF59E0B, "exit": 0xF43F5E, "risk": 0xF43F5E}.get(level, 0x6B7280)
        try:
            requests.post(hook, json={"embeds": [{"title": title, "description": body[:1800], "color": color,
                                                  "url": f"https://pump.fun/coin/{mint}" if mint else None}]}, timeout=8)
        except Exception as e:
            log_error("discord", e)


# ---------------------------------------------------------------- risk
def alerted_recently(kind, mint, title, hours=12):
    """Survives restarts: don't repeat the same alert for the same coin within `hours`."""
    return bool(store.one("SELECT 1 x FROM alerts WHERE kind=? AND mint=? AND title=? AND ts>=?",
                          (kind, mint, title, time.time() - hours * 3600)))


def today_et():
    return dt.datetime.now(ET).date()


def _day_start():
    d = today_et()
    return dt.datetime(d.year, d.month, d.day, tzinfo=ET).timestamp()


def risk(mode):
    t0 = _day_start()
    opened = [r["size_usd"] or 0 for r in store.q("SELECT size_usd FROM trades WHERE mode=? AND opened_at>=?", (mode, t0))]
    closed = [r["pnl_usd"] or 0 for r in store.q("SELECT pnl_usd FROM trades WHERE mode=? AND status='closed' AND closed_at>=? ORDER BY closed_at", (mode, t0))]
    return risk_from(opened, closed, config.load())


def risk_from(opened, closed, cfg):
    """Pure kill-switch / cap logic (unit-tested in tools/verify.py).
    opened: today's entry sizes; closed: today's realized P&L in close order."""
    streak = 0
    for p in reversed(closed):
        if p < 0:
            streak += 1
        else:
            break
    day_pnl = sum(closed)
    limit = cfg["daily_loss_limit_pct"] / 100 * cfg["daily_buy_cap_usd"]
    reasons = []
    if streak >= cfg["loss_streak_limit"]:
        reasons.append(f"{streak} losses in a row")
    if day_pnl <= -limit:
        reasons.append(f"day P&L ${day_pnl:,.0f} hit the -${limit:,.0f} limit")
    buys = sum(opened)
    return dict(entries=len(opened), max_entries=cfg["max_entries_per_day"], buys_usd=round(buys, 2),
                cap_usd=cfg["daily_buy_cap_usd"], day_pnl=round(day_pnl, 2), loss_limit=round(limit, 2),
                streak=streak, killed=bool(reasons), reasons=reasons,
                can_enter=not reasons and len(opened) < cfg["max_entries_per_day"]
                and buys + cfg["trade_size_usd"] <= cfg["daily_buy_cap_usd"])


def check_kill():
    for mode in ("paper", "real"):
        r = risk(mode)
        key = (mode, str(today_et()))
        if r["killed"] and state["kill"].get(key) is None:
            state["kill"][key] = time.time()
            notify("risk", "RISK", f"Kill switch ({mode}): stop trading today", "; ".join(r["reasons"]))


# ---------------------------------------------------------------- paper trader
def open_paper(signal_id):
    cfg = config.load()
    s = store.one("SELECT * FROM signals WHERE id=?", (signal_id,))
    if not s or not risk("paper")["can_enter"]:
        return
    if store.one("SELECT id FROM trades WHERE mode='paper' AND mint=? AND status='open'", (s["mint"],)):
        return
    mc = pump.mcap(s["mint"], max_age=0)
    if not mc:
        return
    size = min(cfg["trade_size_usd"], cfg["max_trade_usd"])
    tok, lift = pump.buy_fill(size, mc / 1e9)
    tid = store.insert("trades", dict(mode="paper", mint=s["mint"], symbol=s["symbol"], leader=s["wallet"], signal_id=s["id"],
                                      opened_at=time.time(), entry_mcap=mc, size_usd=size, tokens=tok, lift=lift,
                                      status="open", last_mcap=mc, peak_mcap=mc, source="auto"))
    notify("info", "PAPER", f"Paper buy {s['symbol']} ${size:.0f} at ${mc:,.0f} mcap", f"Trade #{tid}, copying {s['wallet'][:6]}", s["mint"])


def close_trade(t, reason, mc=None, proceeds=None, quiet=False, at=None):
    if not (quiet and proceeds is not None):
        mc = mc or pump.mcap(t["mint"], max_age=0) or t["last_mcap"] or t["entry_mcap"]
    if proceeds is None:
        proceeds = pump.sell_value(t["tokens"], mc / 1e9, t["lift"] or 1.0) if t["tokens"] else t["size_usd"] * mc / t["entry_mcap"]
    pnl = proceeds - t["size_usd"]
    store.update("trades", "id", t["id"], dict(status="closed", closed_at=at or time.time(), exit_mcap=mc, proceeds_usd=round(proceeds, 2),
                                               pnl_usd=round(pnl, 2), roi=pnl / t["size_usd"] if t["size_usd"] else 0, exit_reason=reason))
    if quiet:
        return
    notify("info" if pnl >= 0 else "caution", "CLOSED", f"{t['mode'].title()} {t['symbol']} closed {pnl:+.2f} USD ({pnl / t['size_usd']:+.0%})", reason, t["mint"])
    check_kill()


def later(delay, fn, *a):
    tm = threading.Timer(delay, _safe, (fn,) + a)
    tm.daemon = True
    tm.start()
    _timers.append(tm)


def _safe(fn, *a):
    try:
        fn(*a)
    except Exception as e:
        log_error(fn.__name__, e)


# ---------------------------------------------------------------- leader + own trades
def apply_model(x, leader, leader_usd):
    """Walk-forward EV gate: GO needs a positive expected copier ROI at your size."""
    mv = model.ev(leader, x["m"].get("mcap"), leader_usd)
    x["model"] = mv
    if not mv or x["verdict"] == "SKIP":
        return
    cls, mb, sb = mv["cell"]
    line = f"Model: {mv['copier_ev']:+.1%} expected after costs at your size ({cls} leader, {mb} mcap, {sb} buy; n={mv['n']})"
    if mv["copier_ev"] <= 0:
        x["soft"].append(line)
        x["verdict"] = "CAUTION"
    else:
        x.setdefault("info", []).insert(0, line)


def on_leader_trade(tr, leader):
    cfg = config.load()
    c = pump.coin(tr["mint"]) or {}
    sym = c.get("symbol") or tr["mint"][:6]
    mc = float(c["usd_market_cap"]) if c.get("usd_market_cap") else None
    store.update("leaders", "wallet", leader["wallet"], {"last_trade_at": tr["ts"]})
    if tr["side"] == "buy":
        first = not store.one("SELECT id FROM signals WHERE wallet=? AND mint=? AND side='buy'", (leader["wallet"], tr["mint"]))
        if not first:
            store.insert("signals", dict(ts=tr["ts"], wallet=leader["wallet"], role="leader", mint=tr["mint"], symbol=sym, side="buy",
                                         usd=tr["usd"], mcap=mc, verdict="ADD", score=None, reasons="[]", intel="{}", tx=tr["sig"]))
            return
        x = intel.xray(tr["mint"], leader, tr["usd"])
        apply_model(x, leader, tr["usd"])
        if x["verdict"] != "SKIP":
            x["social"] = social.mentions(sym, tr["mint"])
        sid = store.insert("signals", dict(ts=tr["ts"], wallet=leader["wallet"], role="leader", mint=tr["mint"], symbol=sym, side="buy",
                                           usd=tr["usd"], mcap=x["m"]["mcap"] or mc, verdict=x["verdict"], score=x["score"],
                                           reasons=x["hard"] + x["soft"], intel=x, tx=tr["sig"]))
        lead = f"{leader['wallet'][:6]} (14d ROI {leader['roi_14d']:+.0%}, win {leader['win_rate']:.0%})" if leader.get("roi_14d") is not None else leader["wallet"][:6]
        body = f"Leader {lead} bought ${tr['usd']:.0f} at ${(x['m']['mcap'] or 0):,.0f} mcap. " + ("; ".join(x["hard"] + x["soft"]) or "All checks passed.")
        level = {"GO": "go", "CAUTION": "caution"}.get(x["verdict"], "skip")
        notify(level, x["verdict"], f"{x['verdict']}: {sym}", body, tr["mint"])
        if x["verdict"] == "GO" and cfg["auto_paper"] and sid:
            later(cfg["entry_delay_s"], open_paper, sid)
    else:
        store.insert("signals", dict(ts=tr["ts"], wallet=leader["wallet"], role="leader", mint=tr["mint"], symbol=sym, side="sell",
                                     usd=tr["usd"], mcap=mc, verdict="EXIT", score=None, reasons="[]", intel="{}", tx=tr["sig"]))
        for t in store.q("SELECT * FROM trades WHERE mint=? AND status='open'", (tr["mint"],)):
            if t["mode"] == "paper" and t["leader"] == leader["wallet"]:
                later(cfg["exit_delay_s"], lambda tid=t["id"]: _close_if_open(tid, "leader sold"))
            elif t["mode"] == "real":
                notify("exit", "EXIT", f"EXIT {sym}: leader sold", f"{leader['wallet'][:6]} sold ${tr['usd']:.0f}. The rule is to sell within 30s.", tr["mint"])


def _close_if_open(tid, reason):
    t = store.one("SELECT * FROM trades WHERE id=? AND status='open'", (tid,))
    if t:
        close_trade(t, reason)


def on_my_trade(tr, quiet=False):
    """Auto-log your real fomo trades from your wallet (quiet=True for the history backfill)."""
    c = pump.coin(tr["mint"]) or {}
    sym = c.get("symbol") or tr["mint"][:6]
    mc = None if quiet else pump.mcap(tr["mint"])
    t = store.one("SELECT * FROM trades WHERE mode='real' AND mint=? AND status='open' ORDER BY id DESC", (tr["mint"],))
    if tr["side"] == "buy":
        if t:
            store.update("trades", "id", t["id"], dict(size_usd=round((t["size_usd"] or 0) + tr["usd"], 2), tokens=(t["tokens"] or 0) + tr["tokens"]))
        else:
            sig = store.one("SELECT * FROM signals WHERE mint=? AND side='buy' AND role='leader' AND ts>=? ORDER BY ts DESC", (tr["mint"], tr["ts"] - 3600))
            store.insert("trades", dict(mode="real", mint=tr["mint"], symbol=sym, leader=sig["wallet"] if sig else None,
                                        signal_id=sig["id"] if sig else None, opened_at=tr["ts"], entry_mcap=mc, size_usd=round(tr["usd"], 2),
                                        tokens=tr["tokens"], lift=1.0, status="open", last_mcap=mc, peak_mcap=mc, proceeds_usd=0, source="wallet"))
        if not quiet:
            notify("info", "MINE", f"Logged your buy: {sym} ${tr['usd']:.2f}", "", tr["mint"])
    elif t:
        proceeds = (t["proceeds_usd"] or 0) + tr["usd"]
        if tr["remaining"] <= max(1e-6, 0.001 * (t["tokens"] or 0)):
            close_trade(t, "you sold", mc, proceeds, quiet=quiet, at=tr["ts"] if quiet else None)
        else:
            store.update("trades", "id", t["id"], dict(proceeds_usd=round(proceeds, 2), notes=f"partial sells ${proceeds:.2f}"))
        if not quiet:
            notify("info", "MINE", f"Logged your sell: {sym} ${tr['usd']:.2f}", "", tr["mint"])


def backfill_me(w):
    sol = pump.sol_price()
    sigs = [s for s in (chain.rpc("getSignaturesForAddress", [w, {"limit": 1000}]) or []) if not s.get("err")]
    n = 0
    for s in reversed(sigs):
        store.insert("seen", dict(sig=s["signature"], wallet=w, ts=s.get("blockTime") or time.time()))
        tr = chain.parse_trade(s["signature"], w, sol)
        if tr:
            on_my_trade(tr, quiet=True); n += 1
    if n:
        store.alert("info", "MINE", f"Imported {n} of your past fomo trades", "Your trade log now starts with your real history.")


def watch_loop():
    while True:
        try:
            cfg = config.load()
            watch = [(r, "leader") for r in store.q("SELECT * FROM leaders WHERE enabled=1")]
            if cfg.get("my_wallet"):
                watch.append(({"wallet": cfg["my_wallet"]}, "me"))
            state["watching"] = len(watch)
            sol = pump.sol_price()
            for row, role in watch:
                w = row["wallet"]
                sigs = [s for s in chain.signatures(w, 15) if not s.get("err")]
                primed = store.one("SELECT 1 x FROM seen WHERE wallet=? LIMIT 1", (w,))
                new = [s for s in sigs if not store.one("SELECT 1 x FROM seen WHERE sig=?", (s["signature"],))]
                for s in new:
                    store.insert("seen", dict(sig=s["signature"], wallet=w, ts=s.get("blockTime") or time.time()))
                if not primed and role == "me":
                    backfill_me(w)          # first sight of your wallet: import your history quietly
                    continue
                if not primed:
                    continue                 # first sight of a leader: remember history, don't alert on it
                for s in reversed(new):
                    tr = chain.parse_trade(s["signature"], w, sol)
                    if not tr:
                        continue
                    (on_leader_trade(tr, row) if role == "leader" else on_my_trade(tr))
            state["last_cycle"] = time.time()
        except Exception as e:
            log_error("watch", traceback.format_exc(limit=2))
        time.sleep(config.load()["poll_leaders_s"])


def positions_loop():
    while True:
        try:
            cfg = config.load()
            for t in store.q("SELECT * FROM trades WHERE status='open'"):
                mc = pump.mcap(t["mint"])
                if not mc:
                    continue
                store.update("trades", "id", t["id"], dict(last_mcap=mc, peak_mcap=max(mc, t["peak_mcap"] or mc)))
                value = pump.sell_value(t["tokens"], mc / 1e9, t["lift"] or 1.0) if t["tokens"] else t["size_usd"] * mc / (t["entry_mcap"] or mc)
                roi = value / t["size_usd"] - 1 if t["size_usd"] else 0
                age_min = (time.time() - t["opened_at"]) / 60
                if roi * 100 <= cfg["disaster_stop_pct"]:
                    if t["mode"] == "paper":
                        close_trade(t, f"disaster stop {roi:.0%}", mc)
                    elif (t["id"], "stop") not in _alerted:
                        _alerted.add((t["id"], "stop"))
                        title = f"EXIT {t['symbol']}: disaster stop"
                        if not alerted_recently("EXIT", t["mint"], title):
                            notify("exit", "EXIT", title, f"Down {roi:.0%}. The -50% rule says sell now.", t["mint"])
                elif age_min >= cfg["time_stop_min"]:
                    if t["mode"] == "paper":
                        close_trade(t, "time stop", mc)
                    elif (t["id"], "time") not in _alerted:
                        _alerted.add((t["id"], "time"))
                        title = f"EXIT {t['symbol']}: {cfg['time_stop_min']} min time stop"
                        if not alerted_recently("EXIT", t["mint"], title):
                            notify("exit", "EXIT", title, f"Position is {roi:+.0%}. The rule is to close it.", t["mint"])
            check_kill()
        except Exception as e:
            log_error("positions", traceback.format_exc(limit=2))
        time.sleep(config.load()["poll_positions_s"])


def start():
    leaders.seed_from_results()
    last = store.one("SELECT MAX(updated_at) t FROM leaders WHERE source IN ('auto','lapsed')")
    if not last or not last["t"] or time.time() - last["t"] > 20 * 3600:
        leaders.refresh_async()
    for fn in (watch_loop, positions_loop):
        threading.Thread(target=fn, daemon=True).start()
