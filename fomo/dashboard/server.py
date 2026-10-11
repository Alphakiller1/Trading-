"""fomo command center: local dashboard server.

    python server.py            -> http://127.0.0.1:8777

Read-only toward every exchange and wallet: it never places trades. It watches wallets on-chain,
scores signals, paper-trades, logs your real trades from your wallet, and alerts you.
"""
import json, os, re, sys, time, statistics, threading, mimetypes, datetime as dt
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from core import config, store, pump, chain, intel, social, leaders, engine  # noqa: E402

PORT = int(os.environ.get("FOMO_DASH_PORT", "8777"))
# The hosted interface on GitHub Pages may call this local engine; nothing else may (CORS).
ALLOWED_ORIGINS = {"https://alphakiller1.github.io"}
STATIC = os.path.join(config.ROOT, "static")
_me_cache = {"t": 0, "data": None}


def hourly():
    path = os.path.join(config.FOMO_DIR, "results", "hourly_launches_graduations.txt")
    rows = []
    try:
        for line in open(path):
            m = re.match(r"\s*(\d\d)\s+(\d\d)\s+(\d+)\s+([\d.]+)\s+([\d.]+)", line)
            if m:
                rows.append(dict(et=int(m.group(2)), launches=int(m.group(3)), grads=float(m.group(4)), per1k=float(m.group(5))))
    except Exception:
        pass
    return sorted(rows, key=lambda r: r["et"])


HOURLY = hourly()


def trade_stats(mode):
    rows = store.q("SELECT * FROM trades WHERE mode=? AND status='closed' ORDER BY closed_at", (mode,))
    if not rows:
        return dict(n=0, curve=[])
    pnl = [r["pnl_usd"] or 0 for r in rows]
    size = [r["size_usd"] or 0 for r in rows]
    rois = sorted(((r["pnl_usd"] or 0) / r["size_usd"]) for r in rows if r["size_usd"])
    wins = [p for p in pnl if p > 0]; losses = [p for p in pnl if p <= 0]
    top2 = sorted(range(len(pnl)), key=lambda i: -pnl[i])[:2]
    rest_p = sum(p for i, p in enumerate(pnl) if i not in top2); rest_s = sum(s for i, s in enumerate(size) if i not in top2)
    cum, curve = 0.0, []
    for r in rows:
        cum += r["pnl_usd"] or 0
        curve.append([r["closed_at"], round(cum, 2)])
    return dict(n=len(rows), pnl=round(sum(pnl), 2), roi=sum(pnl) / sum(size) if sum(size) else 0,
                roi_ex_top2=rest_p / rest_s if rest_s else None, win_rate=len(wins) / len(rows),
                avg_win=statistics.mean(wins) if wins else 0, avg_loss=statistics.mean(losses) if losses else 0,
                median_roi=statistics.median(rois) if rois else 0, best=max(pnl), worst=min(pnl), curve=curve)


def state():
    cfg = config.load()
    now_et = dt.datetime.now(engine.ET)
    h = next((r for r in HOURLY if r["et"] == now_et.hour), None)
    avg = statistics.mean(r["per1k"] for r in HOURLY) if HOURLY else None
    paper = trade_stats("paper")
    gate = dict(n=paper["n"], need=50, roi=paper.get("roi"), roi_ex_top2=paper.get("roi_ex_top2"),
                passed=paper["n"] >= 50 and (paper.get("roi") or 0) > 0 and (paper.get("roi_ex_top2") or 0) > 0)
    return dict(
        now=time.time(), et=now_et.strftime("%a %H:%M ET"), sol=pump.sol_price(),
        window=dict(hour=now_et.hour, per1k=h["per1k"] if h else None, launches=h["launches"] if h else None,
                    rel=(h["per1k"] / avg - 1) if h and avg else None),
        risk={m: engine.risk(m) for m in ("paper", "real")}, gate=gate,
        open={m: store.one("SELECT COUNT(*) n FROM trades WHERE mode=? AND status='open'", (m,))["n"] for m in ("paper", "real")},
        signals_today=store.one("SELECT COUNT(*) n FROM signals WHERE side='buy' AND verdict!='ADD' AND ts>=?", (engine._day_start(),))["n"],
        unread=store.one("SELECT COUNT(*) n FROM alerts WHERE read=0")["n"],
        leaders=dict(active=store.one("SELECT COUNT(*) n FROM leaders WHERE enabled=1")["n"], job=leaders.job),
        health=dict(rpc_ok=chain.health["last_ok"], pump_ok=pump.health["last_ok"], pump_throttled_until=pump.health["throttled_until"],
                    x=social.status, last_cycle=engine.state["last_cycle"], watching=engine.state["watching"], errors=engine.state["errors"][-5:]),
        settings=dict(trade_size_usd=cfg["trade_size_usd"], my_wallet=cfg["my_wallet"], auto_paper=cfg["auto_paper"]),
    )


def me():
    """Your edge report, built from your real trade log (auto-imported from your fomo wallet)."""
    w = config.load().get("my_wallet")
    if not w:
        return None
    rows = store.q("SELECT * FROM trades WHERE mode='real' ORDER BY opened_at")
    closed = [r for r in rows if r["status"] == "closed" and r["size_usd"]]
    out = dict(wallet=w, n=len(closed))
    if time.time() - _me_cache["t"] > 600 or not _me_cache["data"] or _me_cache["data"].get("wallet") != w:
        _me_cache.update(t=time.time(), data=dict(wallet=w, week=pump.portfolio_summary(w, "1w")))
    out["week"] = _me_cache["data"]["week"]
    if not closed:
        out["insights"] = []
        return out
    fee = lambda usd: pump.fomo_fee(usd) + pump.PUMP_FEE * usd
    fees = sum(fee(r["size_usd"]) + fee(r["proceeds_usd"] or 0) for r in closed)
    pnl = [r["pnl_usd"] or 0 for r in closed]
    net = sum(pnl); size = sum(r["size_usd"] for r in closed)
    holds = [((r["closed_at"] or 0) - (r["opened_at"] or 0)) / 60 for r in closed]
    avg_size = size / len(closed)
    # re-entries into a coin you had just lost on (same ET day)
    reent, last_loss = [], {}
    for r in closed:
        d = dt.datetime.fromtimestamp(r["opened_at"], engine.ET).date()
        if (r["mint"], d) in last_loss:
            reent.append(r)
        if (r["pnl_usd"] or 0) < 0:
            last_loss[(r["mint"], d)] = True
    opened = [r for r in rows if r["status"] == "open"]
    bag_val = 0.0; bag_n = 0
    for r in opened:
        if r["tokens"] and r["last_mcap"]:
            v = pump.sell_value(r["tokens"], r["last_mcap"] / 1e9, 1.0)
            if v < 0.5 * r["size_usd"]:
                bag_n += 1; bag_val += v - r["size_usd"]
    buckets = {"< 1 min": [], "1-5 min": [], "> 5 min": []}
    for r, h in zip(closed, holds):
        buckets["< 1 min" if h < 1 else "1-5 min" if h <= 5 else "> 5 min"].append(r["pnl_usd"] or 0)
    copied = [r["pnl_usd"] or 0 for r in closed if r["leader"]]
    own = [r["pnl_usd"] or 0 for r in closed if not r["leader"]]
    best = max(pnl)
    out.update(net=net, gross=net + fees, fees=fees, avg_size=avg_size, cost_now=pump.round_trip_cost(max(5, avg_size)),
               cost_190=pump.round_trip_cost(190), median_hold=statistics.median(holds), win_rate=sum(p > 0 for p in pnl) / len(pnl),
               ex_best=net - best, reentries=dict(n=len(reent), pnl=sum(r["pnl_usd"] or 0 for r in reent)),
               bags=dict(n=bag_n, pnl=bag_val), holds={k: dict(n=len(v), pnl=sum(v)) for k, v in buckets.items()},
               copied=dict(n=len(copied), pnl=sum(copied)), own=dict(n=len(own), pnl=sum(own)))
    ins = []
    if fees > abs(net):
        ins.append(("bad", f"<b>Fees ate ${fees:,.2f}</b>, more than your net P&L of ${net:+,.2f}. Before fees you made <b>${net + fees:+,.2f}</b>: "
                           f"your picks work, your size doesn't. At your ${avg_size:,.0f} average a round trip costs {out['cost_now']:.1%}; at $190 it's {out['cost_190']:.1%}."))
    if reent:
        ins.append(("bad", f"<b>{len(reent)} re-entries</b> into a coin you had just lost on today: <b>${out['reentries']['pnl']:+,.2f}</b>. Rule 5: no re-entry after a loss."))
    if bag_n:
        ins.append(("bad", f"<b>{bag_n} open bag{'s' if bag_n > 1 else ''}</b> down more than 50% (<b>${bag_val:+,.2f}</b>). The −50% disaster stop says sell and free the cash."))
    if best > 0 and net - best < 0:
        ins.append(("bad", f"Without your best trade you're at <b>${net - best:+,.2f}</b>. One runner is carrying the record; that's normal here, but it means the sample is still luck-sized."))
    hb = out["holds"]
    if hb["< 1 min"]["n"] >= 3:
        ins.append(("", f"Median hold <b>{out['median_hold']:.1f} min</b>. Trades under a minute: <b>${hb['< 1 min']['pnl']:+,.2f}</b> on {hb['< 1 min']['n']}; "
                        f"1–5 min: <b>${hb['1-5 min']['pnl']:+,.2f}</b>; over 5 min: <b>${hb['> 5 min']['pnl']:+,.2f}</b>. Sub-minute scalps pay the full fee for very little move."))
    if own and not copied:
        ins.append(("", "All of your trades so far are your own picks. Copy-signal trades will show here separately so you can compare the two."))
    elif copied:
        ins.append(("good" if sum(copied) > sum(own) else "", f"Copied leaders: <b>${sum(copied):+,.2f}</b> on {len(copied)} · own picks: <b>${sum(own):+,.2f}</b> on {len(own)}."))
    out["insights"] = [dict(level=a, html=b) for a, b in ins]
    return out


EVIDENCE = [
    dict(k="Skill persists", v="+15.1%", d="Strict small-trader leaders on later days (95% CI +5.7% to +20.8%). Past losers: -6.1%."),
    dict(k="Copy penalty", v="-5 to -6 pts", d="What a copier loses vs the leader per trade: fees (3.5-6.3%) + 5-60s delay drift."),
    dict(k="Random entry", v="-11% to -14%", d="Average result of random entries under $80k after costs and a 10s delay."),
    dict(k="Dev sold", v="-19%", d="Buying after the dev sold. 13% win rate. Never do this."),
    dict(k="Live record", v="0 / 7", d="Live picks during the first research session. All fell 25-99% within minutes."),
    dict(k="Edge source", v="Small wins", d="Strict leaders win by taking more 0-50% gains (36% vs 26%), not more moonshots."),
]
RULES = [
    "Copy only a listed leader's FIRST buy in a coin, within ~30 seconds",
    "Skip: dev sold, bundled launch (top-3 > 60%), 5-min range < 12%, < 3 trades/min, launch < 1 min old",
    "Size $100-$190 (fomo's 0.5% tier starts at $190); never above $1k; max $5k and 10 entries a day",
    "Sell within 30s of the leader's first sell; 2-hour time stop; -50% disaster stop",
    "No re-entry into a coin you lost on today",
    "Kill switch: 4 losses in a row or -15% of the day's budget = done for the day",
    "Real money only after 50+ paper trades positive with and without the best 2",
]


def intel_payload():
    fees = [dict(size=s, cost=round(pump.round_trip_cost(s), 4)) for s in (25, 50, 100, 190, 250, 500, 1000)]
    return dict(hourly=HOURLY, evidence=EVIDENCE, rules=RULES, fees=fees)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _cors(self):
        o = self.headers.get("Origin")
        if o in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", o)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Private-Network", "true")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.end_headers()

    def _json(self, obj, code=200):
        b = json.dumps(obj, default=str).encode()
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def do_GET(self):
        u = urlparse(self.path); qs = {k: v[0] for k, v in parse_qs(u.query).items()}
        p = u.path
        try:
            if p == "/" or p.startswith("/static/"):
                f = os.path.join(STATIC, "index.html" if p == "/" else p[len("/static/"):])
                f = os.path.normpath(f)
                if not f.startswith(STATIC) or not os.path.exists(f):
                    return self._json({"error": "not found"}, 404)
                b = open(f, "rb").read()
                self.send_response(200)
                self.send_header("Content-Type", (mimetypes.guess_type(f)[0] or "text/plain") + "; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                return self.wfile.write(b)
            if p == "/api/state":
                return self._json(state())
            if p == "/api/signals":
                lim = int(qs.get("limit", 80))
                rows = store.q("SELECT * FROM signals WHERE side='buy' AND verdict!='ADD' ORDER BY ts DESC LIMIT ?", (lim,)) \
                    if qs.get("kind") != "all" else store.q("SELECT * FROM signals ORDER BY ts DESC LIMIT ?", (lim,))
                for r in rows:
                    r["reasons"] = json.loads(r["reasons"] or "[]"); r["intel"] = json.loads(r["intel"] or "{}")
                    r["leader"] = store.one("SELECT wallet,label,roi_14d,win_rate,closed_14d FROM leaders WHERE wallet=?", (r["wallet"],))
                    r["exit_seen"] = bool(store.one("SELECT 1 x FROM signals WHERE wallet=? AND mint=? AND side='sell'", (r["wallet"], r["mint"])))
                return self._json(rows)
            if p == "/api/alerts":
                return self._json(store.q("SELECT * FROM alerts WHERE id>? ORDER BY id DESC LIMIT 100", (int(qs.get("after", 0)),)))
            if p == "/api/trades":
                sql, args = "SELECT * FROM trades WHERE 1=1", []
                for k in ("mode", "status"):
                    if qs.get(k):
                        sql += f" AND {k}=?"; args.append(qs[k])
                rows = store.q(sql + " ORDER BY COALESCE(closed_at, opened_at) DESC LIMIT 500", args)
                for t in rows:
                    if t["status"] == "open" and t["last_mcap"]:
                        v = pump.sell_value(t["tokens"], t["last_mcap"] / 1e9, t["lift"] or 1.0) if t["tokens"] else t["size_usd"] * t["last_mcap"] / (t["entry_mcap"] or t["last_mcap"])
                        t["value_usd"] = round(v, 2); t["upnl"] = round(v - t["size_usd"], 2)
                return self._json(dict(rows=rows, stats={m: trade_stats(m) for m in ("paper", "real")}))
            if p == "/api/leaders":
                return self._json(dict(rows=store.q("SELECT * FROM leaders ORDER BY enabled DESC, roi_14d DESC"), job=leaders.job, imp=leaders.imp))
            if p == "/api/xray":
                mint = qs.get("mint", "").strip()
                if not re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", mint):
                    return self._json({"error": "Paste a Solana token address"}, 400)
                x = intel.xray(mint)
                x["social"] = social.mentions(x["m"]["symbol"], mint)
                return self._json(x)
            if p == "/api/intel":
                return self._json(intel_payload())
            if p == "/api/me":
                return self._json(me() or {"wallet": None})
            if p == "/api/settings":
                return self._json(config.load())
            if p == "/api/x-cookies":
                return self._json({"has": os.path.exists(social.COOKIES)})
            return self._json({"error": "not found"}, 404)
        except Exception as e:
            return self._json({"error": str(e)}, 500)

    def do_POST(self):
        p = urlparse(self.path).path
        try:
            b = self._body()
            if p == "/api/alerts/read":
                store.run("UPDATE alerts SET read=1 WHERE read=0"); return self._json({"ok": True})
            if p == "/api/trades":
                mint = b["mint"].strip(); mode = b.get("mode", "real")
                size = float(b["size_usd"])
                c = pump.coin(mint) or {}
                mc = float(b.get("entry_mcap") or c.get("usd_market_cap") or 0) or None
                tok, lift = pump.buy_fill(size, mc / 1e9) if (mode == "paper" and mc) else (None, 1.0)
                tid = store.insert("trades", dict(mode=mode, mint=mint, symbol=c.get("symbol") or mint[:6], leader=b.get("leader") or None,
                                                  opened_at=time.time(), entry_mcap=mc, size_usd=size, tokens=tok, lift=lift,
                                                  status="open", last_mcap=mc, peak_mcap=mc, notes=b.get("notes", ""), source="manual"))
                return self._json({"id": tid})
            if p == "/api/trades/close":
                t = store.one("SELECT * FROM trades WHERE id=? AND status='open'", (int(b["id"]),))
                if not t:
                    return self._json({"error": "trade not open"}, 400)
                engine.close_trade(t, b.get("reason") or "manual close",
                                   proceeds=float(b["proceeds_usd"]) if b.get("proceeds_usd") not in (None, "") else None)
                return self._json({"ok": True})
            if p == "/api/trades/note":
                store.update("trades", "id", int(b["id"]), {"notes": b.get("notes", "")}); return self._json({"ok": True})
            if p == "/api/leaders":
                w = b["wallet"].strip()
                if b.get("remove"):
                    store.run("DELETE FROM leaders WHERE wallet=?", (w,))
                elif not store.one("SELECT 1 x FROM leaders WHERE wallet=?", (w,)):
                    store.insert("leaders", dict(wallet=w, label=b.get("label"), enabled=1, source="manual", updated_at=time.time()))
                else:
                    store.update("leaders", "wallet", w, {k: b[k] for k in ("enabled", "label", "note") if k in b})
                return self._json({"ok": True})
            if p == "/api/leaders/import":
                cands = [c for c in b.get("candidates", []) if re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", c.get("wallet", ""))]
                return self._json({"started": leaders.import_async(cands[:400]), "n": len(cands)})
            if p == "/api/leaders/refresh":
                return self._json({"started": leaders.refresh_async()})
            if p == "/api/settings":
                return self._json(config.save(b))
            if p == "/api/x-cookies":
                if not (b.get("auth_token") and b.get("ct0")):
                    return self._json({"error": "both auth_token and ct0 are required"}, 400)
                json.dump({"auth_token": b["auth_token"], "ct0": b["ct0"]}, open(social.COOKIES, "w"))
                social.reset()
                return self._json({"ok": True})
            if p == "/api/test-alert":
                engine.notify("go", "GO", "Test alert", "If you see this on Discord, alerts are wired."); return self._json({"ok": True})
            return self._json({"error": "not found"}, 404)
        except Exception as e:
            return self._json({"error": str(e)}, 500)


if __name__ == "__main__":
    engine.start()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    print(f"fomo command center on http://127.0.0.1:{PORT}", flush=True)
    srv.serve_forever()
