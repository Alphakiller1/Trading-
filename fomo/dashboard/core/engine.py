"""The live engine: watches leader wallets (and yours) on-chain, scores every leader buy, runs the
paper trader, raises exit alerts, auto-logs your real trades and enforces the daily risk limits."""
import datetime as dt, json, queue, threading, time, traceback
from zoneinfo import ZoneInfo
import requests
from . import config, store, pump, chain, intel, social, leaders, model, holdplan

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
    hp = (json.loads(s["intel"] or "{}") or {}).get("hold")
    tid = store.insert("trades", dict(mode="paper", mint=s["mint"], symbol=s["symbol"], leader=s["wallet"], signal_id=s["id"],
                                      opened_at=time.time(), entry_mcap=mc, size_usd=size, tokens=tok, lift=lift,
                                      status="open", last_mcap=mc, peak_mcap=mc, source="auto",
                                      analysis=json.dumps(dict(kind="paper", plan=hp))))
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


LATE_S = 45     # replays: alerts within 30s made +11.8%; 30-60s late -15.5%; 60s+ -13 to -16%


def fast_alert(tr, leader, lag):
    """Instant alert from the transaction alone (no pump.fun calls): leader, size, entry market cap
    from the leader's own fill, and the model EV. Sent only when the buy could be a GO."""
    try:
        if tr["side"] != "buy" or not tr.get("tokens") or not str(tr["mint"]).endswith("pump"):
            return
        mc = tr["usd"] / tr["tokens"] * 1e9 if tr["usd"] else None
        mv = model.ev(leader, mc, tr["usd"])
        if not mc or not mv or mv["copier_ev"] <= 0 or lag > LATE_S:
            return
        notify("go", "FAST", f"FAST: leader bought {tr['mint'][:6]} ${tr['usd']:.0f} at ${mc:,.0f} mcap",
               f"{lag:.0f}s after their buy · model EV {mv['copier_ev']:+.1%} · full X-ray verdict follows in seconds. "
               f"Entries within 30s of the leader did best.", tr["mint"])
    except Exception as ex:
        log_error("fast_alert", ex)


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
        lag = time.time() - (tr["ts"] or time.time())
        fast_alert(tr, leader, lag)
        x = intel.xray(tr["mint"], leader, tr["usd"])
        apply_model(x, leader, tr["usd"])
        x["lag_s"] = round(lag, 1)
        x["detect"] = tr.get("via", "poll")
        if lag > LATE_S and x["verdict"] != "SKIP":
            x["soft"].append(f"LATE: detected {lag:.0f}s after the leader (entries 30s+ late lost 13-16% in replays)")
            x["verdict"] = "CAUTION"
        x["hold"] = holdplan.plan(x["verdict"], bool(x.get("model") and x["model"]["copier_ev"] > 0))
        if x["verdict"] != "SKIP":
            x["social"] = social.mentions(sym, tr["mint"])
        sid = store.insert("signals", dict(ts=tr["ts"], wallet=leader["wallet"], role="leader", mint=tr["mint"], symbol=sym, side="buy",
                                           usd=tr["usd"], mcap=x["m"]["mcap"] or mc, verdict=x["verdict"], score=x["score"],
                                           reasons=x["hard"] + x["soft"], intel=x, tx=tr["sig"]))
        lead = f"{leader['wallet'][:6]} (14d ROI {leader['roi_14d']:+.0%}, win {leader['win_rate']:.0%})" if leader.get("roi_14d") is not None else leader["wallet"][:6]
        body = f"Leader {lead} bought ${tr['usd']:.0f} at ${(x['m']['mcap'] or 0):,.0f} mcap. " + ("; ".join(x["hard"] + x["soft"]) or "All checks passed.")
        hp = x.get("hold")
        if hp and hp.get("enter"):
            body += f" PLAN: out within {hp['window_min']} min" + (f", take +{hp['take_profit_pct']}%" if hp.get("take_profit_pct") else "") + "."
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
            tid = store.insert("trades", dict(mode="real", mint=tr["mint"], symbol=sym, leader=sig["wallet"] if sig else None,
                                              signal_id=sig["id"] if sig else None, opened_at=tr["ts"], entry_mcap=mc, size_usd=round(tr["usd"], 2),
                                              tokens=tr["tokens"], lift=1.0, status="open", last_mcap=mc, peak_mcap=mc, proceeds_usd=0, source="wallet"))
            if not quiet:
                threading.Thread(target=_safe, args=(coach_buy, tid), daemon=True).start()
        if not quiet and t:
            notify("info", "MINE", f"Added to {sym}: +${tr['usd']:.2f}", "Averaging into an open position.", tr["mint"])
    elif t:
        proceeds = (t["proceeds_usd"] or 0) + tr["usd"]
        if tr["remaining"] <= max(1e-6, 0.001 * (t["tokens"] or 0)):
            close_trade(t, "you sold", mc, proceeds, quiet=True, at=tr["ts"] if quiet else None)
            if not quiet:
                threading.Thread(target=_safe, args=(coach_sell, t["id"]), daemon=True).start()
        else:
            store.update("trades", "id", t["id"], dict(proceeds_usd=round(proceeds, 2), notes=f"partial sells ${proceeds:.2f}"))
            if not quiet:
                notify("info", "MINE", f"Partial sell {sym}: ${tr['usd']:.2f}", f"${proceeds:.2f} taken out so far.", tr["mint"])


# ---------------------------------------------------------------- live coach (your own trades)
def _grade(checks):
    if any(l == "bad" for l, _ in checks): return "C"
    if any(l == "warn" for l, _ in checks): return "B"
    return "A"


def coach_buy(tid):
    """Analyze one of YOUR buys the moment it lands: coin X-ray, model EV, and the rules."""
    cfg = config.load()
    t = store.one("SELECT * FROM trades WHERE id=?", (tid,))
    if not t:
        return
    mint, sym = t["mint"], t["symbol"]
    sig = store.one("SELECT * FROM signals WHERE mint=? AND side='buy' AND role='leader' AND ts>=? ORDER BY ts DESC", (mint, t["opened_at"] - 3600))
    leader = store.one("SELECT * FROM leaders WHERE wallet=?", (sig["wallet"],)) if sig else None
    x = intel.xray(mint, leader, sig["usd"] if sig else None)
    if sig and leader:
        apply_model(x, leader, sig["usd"])
    m = x["m"]
    mc = m.get("mcap") or t["entry_mcap"]
    if mc and not t["entry_mcap"]:
        store.update("trades", "id", tid, {"entry_mcap": mc, "last_mcap": mc, "peak_mcap": mc})
    checks = []
    lost = store.q("SELECT pnl_usd FROM trades WHERE mode='real' AND mint=? AND status='closed' AND closed_at>=? AND closed_at<=? "
                   "AND pnl_usd<0 AND id<>?", (mint, _day_start(), t["opened_at"], tid))
    if lost:
        rec = reentry_record()
        checks.append(("warn", f"Re-entry: you already lost ${-sum(r['pnl_usd'] for r in lost):.2f} on {sym} today "
                               f"(your re-entries after a loss so far: ${rec['pnl']:+.2f} over {rec['n']})"))
    rk = risk("real")
    if rk["killed"]:
        checks.append(("bad", "Kill switch was on: " + "; ".join(rk["reasons"])))
    if t["size_usd"] > cfg["max_trade_usd"]:
        checks.append(("bad", f"Size ${t['size_usd']:.0f} is over your ${cfg['max_trade_usd']:.0f} max"))
    elif t["size_usd"] > 1.5 * cfg["trade_size_usd"]:
        checks.append(("warn", f"Size ${t['size_usd']:.0f} is above your ${cfg['trade_size_usd']:.0f} plan"))
    if mc:
        if mc >= cfg["max_mcap_usd"]:
            checks.append(("bad", f"Entry at ${mc:,.0f}: above your ${cfg['max_mcap_usd']:,.0f} limit"))
        elif mc >= 25000:
            checks.append(("warn", f"Entry at ${mc:,.0f}: above $25k, where every trade type lost out of sample"))
        elif mc < 10000:
            checks.append(("good", f"Entry at ${mc:,.0f}: in the model's best zone (< $10k)"))
    if x["verdict"] == "SKIP":
        checks.append(("bad", "Coin fails the avoid rules: " + "; ".join(x["hard"][:3])))
    elif x["soft"]:
        checks.append(("warn", "Caution flags: " + "; ".join(x["soft"][:3])))
    else:
        checks.append(("good", "Coin passes every avoid rule"))
    if sig:
        mv = x.get("model")
        ev = f", model EV {mv['copier_ev']:+.1%}" if mv else ""
        lvl = "bad" if sig["verdict"] == "SKIP" else ("good" if sig["verdict"] == "GO" else "warn")
        late = t["opened_at"] - sig["ts"]
        checks.append((lvl, f"Copied leader {sig['wallet'][:6]} ({sig['verdict']} signal{ev}, {late:.0f}s after their buy)"))
        if late > 60:
            checks.append(("warn", f"Entered {late / 60:.1f} min after the leader: your entries within 1 min made +3.0%, 5+ min late -3.1% (paid ~23% more)"))
    else:
        own = store.one("SELECT COALESCE(SUM(pnl_usd),0) p, COUNT(*) n FROM trades WHERE mode='real' AND status='closed' AND leader IS NULL")
        checks.append(("info", f"Own pick, no leader signal (your own picks so far: ${own['p']:+.2f} over {own['n']} trades)"))
    if dt.datetime.now(ET).hour in (7, 8):
        checks.append(("warn", "7-8 AM ET is the weakest hour for graduations"))
    hp = holdplan.plan(x["verdict"], bool(x.get("model") and x["model"]["copier_ev"] > 0)) or \
        holdplan.plan("CAUTION", False)                     # own picks get the general plan
    if hp and hp.get("enter"):
        checks.append(("info", "Hold plan: " + hp["text"]))
    g = _grade(checks)
    an = dict(kind="buy", grade=g, verdict=x["verdict"], model=x.get("model"), checks=checks, at=time.time(), plan=hp,
              m={k: m.get(k) for k in ("mcap", "age_min", "trades_60s", "buyers_5m", "net_flow_5m", "range_5m",
                                       "dev_sold", "dev_holds_pct", "top3_holders", "top3_early")})
    store.update("trades", "id", tid, {"analysis": json.dumps(an)})
    body = " | ".join(c for l, c in checks if l in ("bad", "warn")) or " | ".join(c for _, c in checks[:2])
    notify({"A": "go", "B": "caution", "C": "risk"}[g], "COACH", f"Your buy {sym} ${t['size_usd']:.2f}: grade {g}, coin {x['verdict']}", body, mint)


def coach_sell(tid):
    """Review one of YOUR closed trades: result, hold time, fee drag, and the exit rules."""
    t = store.one("SELECT * FROM trades WHERE id=?", (tid,))
    if not t or t["status"] != "closed":
        return
    an = json.loads(t["analysis"]) if t.get("analysis") else {}
    hold = ((t["closed_at"] or time.time()) - t["opened_at"]) / 60
    proceeds = t["proceeds_usd"] or 0
    fee = pump.fomo_fee(t["size_usd"]) + pump.PUMP_FEE * t["size_usd"] + pump.fomo_fee(proceeds) + pump.PUMP_FEE * proceeds
    review = [("good" if t["pnl_usd"] > 0 else "bad", f"{t['pnl_usd']:+.2f} USD ({t['roi']:+.0%}) after ~${fee:.2f} in fees, held {hold:.1f} min")]
    if hold < 1:
        review.append(("warn", f"Held under a minute: fees took ~{fee / t['size_usd']:.0%} of the trade; your 5-min+ holds have done better"))
    hp = an.get("plan") or {}
    if hp.get("window_min"):
        w = hp["window_min"]
        review.append(("good" if hold <= w * 1.5 else "warn",
                       f"Held {hold:.1f} min vs a {w}-min plan" + ("" if hold <= w * 1.5 else ": replays bled the longer coins were held")))
    if t["leader"]:
        ls = store.one("SELECT ts FROM signals WHERE wallet=? AND mint=? AND side='sell' AND ts>=? ORDER BY ts LIMIT 1", (t["leader"], t["mint"], t["opened_at"]))
        if ls:
            d = t["closed_at"] - ls["ts"]
            review.append(("good" if abs(d) <= 60 else "warn", f"Leader sold {abs(d):.0f}s {'before' if d > 0 else 'after'} you (rule: exit within 30s of the leader)"))
        else:
            review.append(("warn", "You sold before the leader did (the rule is to mirror the leader's exit)"))
    if t.get("peak_mcap") and t.get("exit_mcap") and t["peak_mcap"] > 1.3 * t["exit_mcap"] and t["pnl_usd"] < 0:
        review.append(("warn", f"It reached ${t['peak_mcap']:,.0f} mcap while you held; the exit gave it back"))
    an.update(review=review, review_at=time.time())
    store.update("trades", "id", tid, {"analysis": json.dumps(an)})
    notify("go" if t["pnl_usd"] > 0 else "caution", "COACH", f"Your sell {t['symbol']}: {t['pnl_usd']:+.2f} USD ({t['roi']:+.0%}), {hold:.1f} min",
           " | ".join(c for _, c in review[1:]) or review[0][1], t["mint"])
    check_kill()


def reentry_record():
    """Your realized P&L on trades that re-entered a coin after a same-day loss (the coach cites it)."""
    rows = store.q("SELECT mint, opened_at, pnl_usd FROM trades WHERE mode='real' AND status='closed' ORDER BY opened_at")
    lost, n, pnl = set(), 0, 0.0
    for r in rows:
        k = (r["mint"], dt.datetime.fromtimestamp(r["opened_at"], ET).date())
        if k in lost:
            n += 1; pnl += r["pnl_usd"] or 0
        if (r["pnl_usd"] or 0) < 0:
            lost.add(k)
    return dict(n=n, pnl=pnl)


def retro_coach(t):
    """Grade a past trade from what was recorded (no live coin state): entry zone from your fill,
    size, hour, re-entry after a loss, hold time and fee drag. Used for history and catch-up."""
    cfg = config.load()
    checks = []
    mc = t["entry_mcap"]
    if not mc and t["tokens"] and t["size_usd"] and str(t["mint"]).endswith("pump"):
        mc = t["size_usd"] / t["tokens"] * 1e9          # pump.fun supply is 1B: avg fill price -> mcap
        store.update("trades", "id", t["id"], {"entry_mcap": mc})
    if mc:
        if mc >= cfg["max_mcap_usd"]:
            checks.append(("bad", f"Entry at ${mc:,.0f}: above your ${cfg['max_mcap_usd']:,.0f} limit"))
        elif mc >= 25000:
            checks.append(("warn", f"Entry at ${mc:,.0f}: above $25k, where every trade type lost out of sample"))
        elif mc < 10000:
            checks.append(("good", f"Entry at ${mc:,.0f}: in the model's best zone (< $10k)"))
        else:
            checks.append(("info", f"Entry at ${mc:,.0f}: middle zone ($10k-$25k)"))
    d0 = dt.datetime.fromtimestamp(t["opened_at"], ET)
    day0 = dt.datetime(d0.year, d0.month, d0.day, tzinfo=ET).timestamp()
    lost = store.q("SELECT pnl_usd FROM trades WHERE mode='real' AND mint=? AND status='closed' AND closed_at>=? AND closed_at<=? AND pnl_usd<0 AND id<>?",
                   (t["mint"], day0, t["opened_at"], t["id"]))
    if lost:
        checks.append(("warn", f"Re-entry after losing ${-sum(r['pnl_usd'] for r in lost):.2f} on this coin the same day"))
    if t["size_usd"] > 1.5 * cfg["trade_size_usd"]:
        checks.append(("warn", f"Size ${t['size_usd']:.0f} above your ${cfg['trade_size_usd']:.0f} plan"))
    if d0.hour in (7, 8):
        checks.append(("warn", "Entered in the 7-8 AM ET weak window"))
    checks.append(("good", f"Copied leader {t['leader'][:6]}") if t["leader"] else ("info", "Own pick (no leader signal)"))
    review = []
    if t["status"] == "closed" and t["size_usd"]:
        hold = ((t["closed_at"] or 0) - t["opened_at"]) / 60
        proceeds = t["proceeds_usd"] or 0
        fee = pump.fomo_fee(t["size_usd"]) + pump.PUMP_FEE * t["size_usd"] + pump.fomo_fee(proceeds) + pump.PUMP_FEE * proceeds
        review.append(("good" if (t["pnl_usd"] or 0) > 0 else "bad", f"{(t['pnl_usd'] or 0):+.2f} USD ({(t['roi'] or 0):+.0%}) after ~${fee:.2f} fees, held {hold:.1f} min"))
        if hold < 1:
            review.append(("warn", f"Held under a minute: fees took ~{fee / t['size_usd']:.0%} of the trade"))
    an = dict(kind="retro", grade=_grade(checks + [r for r in review if r[0] == "warn"]), checks=checks, review=review, at=time.time())
    store.update("trades", "id", t["id"], {"analysis": json.dumps(an)})
    return an


def retro_all():
    for t in store.q("SELECT * FROM trades WHERE mode='real' AND (analysis IS NULL OR analysis='') ORDER BY opened_at"):
        retro_coach(t)


def me_loop():
    """Your wallet on its own fast loop, so your trades are analyzed within seconds."""
    while True:
        try:
            w = config.load().get("my_wallet")
            if w:
                sigs = [s for s in chain.signatures(w, 10) if not s.get("err")]
                if not store.one("SELECT 1 x FROM seen WHERE wallet=? LIMIT 1", (w,)):
                    backfill_me(w)
                else:
                    new = [s for s in sigs if not store.one("SELECT 1 x FROM seen WHERE sig=?", (s["signature"],))]
                    if new and len(new) == len(sigs):
                        # every recent tx is unseen: the engine was off, so catch up on the whole gap
                        full = [s for s in (chain.rpc("getSignaturesForAddress", [w, {"limit": 1000}]) or []) if not s.get("err")]
                        new = [s for s in full if not store.one("SELECT 1 x FROM seen WHERE sig=?", (s["signature"],))]
                    caught = 0
                    for s in reversed(new):
                        store.insert("seen", dict(sig=s["signature"], wallet=w, ts=s.get("blockTime") or time.time()))
                        tr = chain.parse_trade(s["signature"], w, pump.sol_price())
                        if tr:
                            stale = time.time() - (tr["ts"] or 0) > 300   # older than 5 min: log it, don't alert
                            on_my_trade(tr, quiet=stale)
                            caught += stale
                    if caught:
                        retro_all()
                        store.alert("info", "MINE", f"Caught up {caught} trades made while the engine was off",
                                    "They're in your trade log; the retro coach grades them.")
                state["me_cycle"] = time.time()
        except Exception:
            log_error("me", traceback.format_exc(limit=2))
        time.sleep(5)


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


STALE_S = 180          # a leader trade older than this is history, not a signal
_jobs = queue.Queue()


def _signal_worker():
    """X-rays and alerts run here, off the polling loop, so one slow coin can't delay the next leader."""
    while True:
        tr, row = _jobs.get()
        _safe(on_leader_trade, tr, row)


def _ws_url():
    u = config.load()["rpc_url"]
    return ("wss://" + u.split("://", 1)[1]) if u.startswith("https://") else u.replace("http://", "ws://")


def ws_loop():
    """Leader transactions pushed by the Solana node (logsSubscribe per wallet) instead of polled.
    The poll loop stays as a slower backup; the 'seen' table de-duplicates the two."""
    import asyncio, websockets

    def handle(sig, w, row):
        if store.one("SELECT 1 x FROM seen WHERE sig=?", (sig,)):
            return
        store.insert("seen", dict(sig=sig, wallet=w, ts=time.time()))
        tr = chain.parse_trade(sig, w, pump.sol_price(), fresh=True)
        if tr:
            state["ws_trades"] = state.get("ws_trades", 0) + 1
        if tr and time.time() - (tr["ts"] or 0) <= STALE_S:
            tr["via"] = "push"
            state["ws_lags"] = (state.get("ws_lags", []) + [round(time.time() - tr["ts"], 1)])[-50:]
            _jobs.put((tr, row))

    async def session():
        rows = store.q("SELECT * FROM leaders WHERE enabled=1 AND (source='manual' OR COALESCE(median_size, 0) >= ?)",
                       (config.load()["min_leader_median_usd"],))
        by_id, subs = {}, {}
        async with websockets.connect(_ws_url(), ping_interval=20, max_size=2 ** 22) as ws:
            for i, r in enumerate(rows):
                by_id[i + 1] = r
                await ws.send(json.dumps({"jsonrpc": "2.0", "id": i + 1, "method": "logsSubscribe",
                                          "params": [{"mentions": [r["wallet"]]}, {"commitment": "confirmed"}]}))
            state.update(ws="connecting", ws_subs=0)
            t0 = time.time()
            while time.time() - t0 < 15 * 60:          # re-subscribe every 15 min to pick up leader changes
                try:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
                except asyncio.TimeoutError:
                    continue
                if "result" in msg and "id" in msg:
                    subs[msg["result"]] = by_id.get(msg["id"])
                    state.update(ws="live", ws_subs=len(subs))
                elif msg.get("method") == "logsNotification":
                    v = msg["params"]["result"]["value"]
                    row = subs.get(msg["params"]["subscription"])
                    if row and not v.get("err"):
                        state["ws_last"] = time.time()
                        state["ws_notes"] = state.get("ws_notes", 0) + 1
                        threading.Thread(target=_safe, args=(handle, v["signature"], row["wallet"], row), daemon=True).start()

    while True:
        try:
            asyncio.run(session())
        except Exception as ex:
            state["ws"] = "reconnecting"
            log_error("ws", ex)
            time.sleep(5)


def watch_loop():
    while True:
        t0 = time.time()
        try:
            # your wallet runs in me_loop; small-ticket leaders never produce a positive-EV signal, so skip them
            watch = store.q("SELECT * FROM leaders WHERE enabled=1 AND (source='manual' OR COALESCE(median_size, 0) >= ?)",
                            (config.load()["min_leader_median_usd"],))
            state["watching"] = len(watch)
            sol = pump.sol_price()
            for row in watch:
                w = row["wallet"]
                sigs = [s for s in chain.signatures(w, 5) if not s.get("err")]
                primed = store.one("SELECT 1 x FROM seen WHERE wallet=? LIMIT 1", (w,))
                new = [s for s in sigs if not store.one("SELECT 1 x FROM seen WHERE sig=?", (s["signature"],))]
                for s in new:
                    store.insert("seen", dict(sig=s["signature"], wallet=w, ts=s.get("blockTime") or time.time()))
                if not primed:
                    continue                 # first sight of a leader: remember history, don't alert on it
                for s in reversed(new):
                    if time.time() - (s.get("blockTime") or 0) > STALE_S:
                        continue             # made while we weren't looking: too late to copy
                    tr = chain.parse_trade(s["signature"], w, sol)
                    if tr:
                        _jobs.put((tr, row))
            state["last_cycle"] = time.time()
            state["cycle_s"] = round(time.time() - t0, 1)
        except Exception:
            log_error("watch", traceback.format_exc(limit=2))
        live = state.get("ws") == "live"
        time.sleep(60 if live else config.load()["poll_leaders_s"])   # push feed live: polling is only a backup


def plan_exit(t, roi, age_min, mc):
    """Apply the trade's hold plan. Paper trades exit; real trades get one alert per event."""
    try:
        hp = (json.loads(t["analysis"]) if t.get("analysis") else {}).get("plan") or {}
    except Exception:
        hp = {}
    w, tp = hp.get("window_min"), hp.get("take_profit_pct")
    if not w:
        return False
    event = None
    if tp and roi * 100 >= tp:
        event = ("tp", f"TAKE PROFIT {t['symbol']}: +{roi:.0%}", f"Your plan takes profit at +{tp}%. Sell now.")
    elif age_min >= w:
        event = ("window", f"EXIT {t['symbol']}: {w}-min hold window over", f"Position is {roi:+.0%} after {age_min:.0f} min. Replays bled after the window.")
    if not event:
        return False
    if t["mode"] == "paper":
        close_trade(t, "take profit" if event[0] == "tp" else f"{w}-min hold plan", mc)
    elif (t["id"], event[0]) not in _alerted:
        _alerted.add((t["id"], event[0]))
        if not alerted_recently("EXIT", t["mint"], event[1]):
            notify("exit", "EXIT", event[1], event[2], t["mint"])
    return True


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
                elif plan_exit(t, roi, age_min, mc):
                    pass
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


def hold_refit_loop():
    """Re-run tools/hold_fit.py every 6 hours so the hold plan keeps learning from new signals."""
    import importlib.util, os as _os
    path = _os.path.join(config.ROOT, "tools", "hold_fit.py")
    while True:
        try:
            age = time.time() - _os.path.getmtime(holdplan.PATH) if _os.path.exists(holdplan.PATH) else 1e9
            if age > 6 * 3600:
                spec = importlib.util.spec_from_file_location("hold_fit", path)
                mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
                mod.main()
        except Exception:
            log_error("hold_fit", traceback.format_exc(limit=2))
        time.sleep(1800)


def start():
    leaders.seed_from_results()
    last = store.one("SELECT MAX(updated_at) t FROM leaders WHERE source IN ('auto','lapsed')")
    if not last or not last["t"] or time.time() - last["t"] > 20 * 3600:
        leaders.refresh_async()
    threading.Thread(target=_safe, args=(retro_all,), daemon=True).start()
    threading.Thread(target=hold_refit_loop, daemon=True).start()
    for _ in range(2):
        threading.Thread(target=_signal_worker, daemon=True).start()
    for fn in (ws_loop, watch_loop, me_loop, positions_loop):
        threading.Thread(target=fn, daemon=True).start()
