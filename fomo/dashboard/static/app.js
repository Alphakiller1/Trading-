"use strict";
// ---------- helpers ----------
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
// Served by the local engine: same origin. Served from GitHub Pages: talk to the engine on this PC.
const BASE = /github\.io$/.test(location.hostname) ? "http://127.0.0.1:8777" : "";
const api = async (path, body) => {
  const r = await fetch(BASE + path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
};
const usd = (n, d = 2) => n == null || isNaN(n) ? "—" : (n < 0 ? "-$" : "$") + Math.abs(n).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
const sgn = (n, d = 2) => n == null || isNaN(n) ? "—" : (n > 0 ? "+" : "") + usd(n, d);
const pct = (n, d = 0) => n == null || isNaN(n) ? "—" : (n > 0 ? "+" : "") + (n * 100).toFixed(d) + "%";
const kfmt = (n) => n == null || isNaN(n) ? "—" : n >= 1e6 ? "$" + (n / 1e6).toFixed(2) + "M" : n >= 1e3 ? "$" + (n / 1e3).toFixed(1) + "k" : "$" + n.toFixed(0);
const short = (a) => a ? a.slice(0, 4) + "…" + a.slice(-4) : "—";
const cls = (n) => n > 0 ? "up" : n < 0 ? "down" : "";
const ago = (t) => { if (!t) return "—"; const s = Date.now() / 1000 - t; if (s < 60) return Math.max(0, s | 0) + "s ago"; if (s < 3600) return (s / 60 | 0) + "m ago"; if (s < 86400) return (s / 3600 | 0) + "h ago"; return (s / 86400 | 0) + "d ago"; };
const toast = (title, body, level = "info") => {
  const el = document.createElement("div"); el.className = "toast " + level;
  el.innerHTML = `<b>${esc(title)}</b>${body ? `<p>${esc(body)}</p>` : ""}`;
  $("#toasts").prepend(el); setTimeout(() => el.remove(), 9000);
};
const copy = async (text, label = "Copied") => { try { await navigator.clipboard.writeText(text); toast(label, text.length > 40 ? short(text) : text); } catch { toast("Copy failed", text); } };

// ---------- sound + desktop notifications ----------
let actx = null;
function beep(level) {
  try {
    actx = actx || new (window.AudioContext || window.webkitAudioContext)();
    const seq = level === "go" ? [660, 990] : level === "caution" ? [520] : [330, 220];
    seq.forEach((f, i) => {
      const o = actx.createOscillator(), g = actx.createGain(), t = actx.currentTime + i * 0.16;
      o.type = "sine"; o.frequency.value = f; g.gain.setValueAtTime(0.0001, t);
      g.gain.exponentialRampToValueAtTime(0.18, t + 0.02); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.14);
      o.connect(g).connect(actx.destination); o.start(t); o.stop(t + 0.15);
    });
  } catch { }
}
function desktop(a) {
  if (!("Notification" in window) || Notification.permission !== "granted") return;
  try { const n = new Notification(a.title, { body: a.body || "", tag: "fomo-" + a.id }); n.onclick = () => { window.focus(); n.close(); }; } catch { }
}
$("#notif-btn").onclick = async () => {
  if (!("Notification" in window)) return toast("Not supported", "This browser can't show desktop notifications.");
  const p = await Notification.requestPermission(); beep("go");
  toast(p === "granted" ? "Alerts on" : "Alerts blocked", p === "granted" ? "Desktop notifications + sound are enabled." : "Allow notifications for 127.0.0.1 in your browser.");
  syncNotifBtn();
};
const syncNotifBtn = () => { if ("Notification" in window && Notification.permission === "granted") $("#notif-btn").style.display = "none"; };
syncNotifBtn();

// ---------- navigation ----------
let view = "command";
$$("#nav a").forEach((a) => a.onclick = () => go(a.dataset.view));
function go(v) {
  view = v;
  $$("#nav a").forEach((a) => a.classList.toggle("on", a.dataset.view === v));
  $$(".view").forEach((s) => s.classList.toggle("on", s.id === "v-" + v));
  refreshView(true);
}
$("#bell").onclick = () => go("command");

// ---------- state / top bar ----------
let S = null;
async function loadState() {
  try { S = await api("/api/state"); $("#offline").classList.remove("on"); }
  catch { $("#offline").classList.add("on"); return; }
  $("#clock").textContent = S.et;
  const w = S.window;
  const we = $("#window");
  if (w.per1k != null) {
    const good = w.rel > 0.08, bad = w.rel < -0.08;
    we.className = "window " + (good ? "good" : bad ? "bad" : "");
    we.textContent = `${good ? "Prime window" : bad ? "Weak window" : "Average window"} · ${w.per1k.toFixed(1)} grads / 1k launches`;
  }
  $("#sol").textContent = "SOL " + usd(S.sol, 2);
  const rr = S.risk.real, rp = S.risk.paper;
  const k = $("#kill");
  if (rr.killed || rp.killed) { k.className = "pill killed"; k.textContent = `KILL SWITCH · ${rr.killed ? "real" : "paper"}`; k.title = [...rr.reasons, ...rp.reasons].join("; "); }
  else { k.className = "pill armed"; k.textContent = "Risk armed"; k.title = "Kill switch not tripped today"; }
  $("#gate").textContent = `Paper gate ${S.gate.n}/${S.gate.need}`;
  $("#gate").title = S.gate.passed ? "Passed: paper results positive with and without the best 2 trades" : "Real money only after 50+ paper trades positive with and without the best 2";
  const u = $("#unread"); u.textContent = S.unread; u.className = S.unread ? "" : "zero";
  const h = S.health, now = Date.now() / 1000;
  const d = (ok, warn) => ok ? "ok" : warn ? "warn" : "bad";
  $("#health").innerHTML = `
    <div><span class="dot ${d(now - h.rpc_ok < 90)}"></span>Solana RPC</div>
    <div><span class="dot ${h.pump_throttled_until > now ? "warn" : d(now - h.pump_ok < 180, true)}"></span>pump.fun ${h.pump_throttled_until > now ? "(cooling down)" : ""}</div>
    <div><span class="dot ${h.x.state === "on" ? "ok" : h.x.state === "error" ? "bad" : ""}"></span>X ${h.x.state === "on" ? "connected" : "off"}</div>
    <div><span class="dot ${d(now - h.last_cycle < 120)}"></span>Watching ${h.watching} wallets</div>`;
  if (view === "command") renderKpis();
}
function renderKpis() {
  const rr = S.risk.real, rp = S.risk.paper;
  const kpi = (l, v, s, extra = "") => `<div class="kpi"><label>${l}</label><div class="v">${v}</div><div class="s">${s}</div>${extra}</div>`;
  const bar = (f) => `<div class="bar"><i style="width:${Math.min(100, f * 100).toFixed(0)}%"></i></div>`;
  $("#kpis").innerHTML =
    kpi("Today P&amp;L · real", `<span class="${cls(rr.day_pnl)}">${sgn(rr.day_pnl)}</span>`, `limit −${usd(rr.loss_limit, 0)} · streak ${rr.streak}`) +
    kpi("Today P&amp;L · paper", `<span class="${cls(rp.day_pnl)}">${sgn(rp.day_pnl)}</span>`, `${rp.entries} paper entries today`) +
    kpi("Entries today", `${rr.entries}<span class="dim">/${rr.max_entries}</span>`, `${usd(rr.buys_usd, 0)} of ${usd(rr.cap_usd, 0)} cap`, bar(rr.buys_usd / rr.cap_usd)) +
    kpi("Open · real / paper", `${S.open.real}<span class="dim"> / </span>${S.open.paper}`, "Live P&amp;L below") +
    kpi("Signals today", S.signals_today, `${S.leaders.active} leaders on watch`) +
    kpi("Paper gate", `${S.gate.n}<span class="dim">/50</span>`, S.gate.roi != null ? `ROI ${pct(S.gate.roi, 1)} · ex-top-2 ${pct(S.gate.roi_ex_top2, 1)}` : "No closed paper trades yet", bar(S.gate.n / 50));
}

// ---------- signals ----------
let lastSigId = 0, sigFilter = "";
function sigCard(s, fresh) {
  const x = s.intel || {}, m = x.m || {};
  const L = s.leader || {};
  const hard = x.hard || [], soft = x.soft || [];
  const score = s.score ?? x.score ?? 0;
  const met = (l, v) => `<div class="metric"><label>${l}</label><span>${v}</span></div>`;
  const dev = m.dev_sold === true ? '<span class="down">yes</span>' : m.dev_sold === false ? "no" : "?";
  const soc = x.social;
  const img = m.image ? `<img src="${esc(m.image)}" loading="lazy" referrerpolicy="no-referrer" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'ph'}))">` : '<div class="ph"></div>';
  return `<div class="sig ${esc(s.verdict)} ${fresh ? "fresh" : ""}">
    <div class="sig-top">${img}
      <div class="sig-name"><b>${esc(s.symbol)}</b> <span class="dim">${esc(m.name || "")}</span>
        <div class="meta">Leader <a class="mono" data-copy="${esc(s.wallet)}">${short(s.wallet)}</a>${L.roi_14d != null ? ` · 14d ROI ${pct(L.roi_14d)} · win ${pct(L.win_rate).replace("+", "")}` : ""} · bought ${usd(s.usd, 0)} · ${ago(s.ts)}</div></div>
      ${s.exit_seen ? '<span class="chip sold">LEADER SOLD</span>' : ""}
      <span class="score" title="Predictability score ${score}/5">${[0, 1, 2, 3, 4].map((i) => `<i class="${i < score ? "on" : ""}"></i>`).join("")}</span>
      <span class="chip ${esc(s.verdict)}">${esc(s.verdict)}</span>
    </div>
    <div class="metrics">
      ${met("Mcap", kfmt(m.mcap ?? s.mcap))}${met("Age", m.age_min != null ? (m.age_min < 60 ? m.age_min.toFixed(0) + "m" : (m.age_min / 60).toFixed(1) + "h") : "—")}
      ${met("Trades/min", m.trades_60s ?? "—")}${met("Buyers 5m", m.buyers_5m ?? "—")}
      ${met("Net flow 5m", m.net_flow_5m != null ? `<span class="${cls(m.net_flow_5m)}">${sgn(m.net_flow_5m, 0)}</span>` : "—")}${met("Range 5m", m.range_5m != null ? pct(m.range_5m).replace("+", "") : "—")}
      ${met("Top-3 early", m.top3_early != null ? pct(m.top3_early).replace("+", "") : "?")}${met("Dev sold", dev)}
      ${met("ATH", kfmt(m.ath))}${met("Vol 1h", kfmt(m.volume_1h))}${met("Bot dust", m.dust_share != null ? pct(m.dust_share).replace("+", "") : "—")}${met("Replies", m.replies ?? "—")}
    </div>
    ${hard.length + soft.length ? `<ul class="reasons">${hard.map((r) => `<li class="hard">${esc(r)}</li>`).join("")}${soft.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>` : '<ul class="reasons"><li>All avoid-rule checks passed</li></ul>'}
    ${soc ? `<div class="xsoc"><span>X: <b>${soc.n}</b> recent mentions</span><span><b>${soc.last_30m}</b> in 30m</span><span><b>${soc.authors}</b> authors</span><span>max followers <b>${(soc.max_followers || 0).toLocaleString()}</b></span>${soc.top && soc.top[0] ? `<span>top: @${esc(soc.top[0].user)}</span>` : ""}</div>` : ""}
    <div class="sig-act">
      <a href="https://fomo.family/tokens/solana/${esc(s.mint)}" target="_blank" rel="noopener" style="color:var(--p3);border-color:rgba(139,92,246,.5)">Open in fomo</a>
      <button class="tag" data-copy="${esc(s.mint)}">Copy CA</button>
      <a href="https://pump.fun/coin/${esc(s.mint)}" target="_blank" rel="noopener">pump.fun</a>
      <a href="https://dexscreener.com/solana/${esc(s.mint)}" target="_blank" rel="noopener">DexScreener</a>
      <a href="https://solscan.io/token/${esc(s.mint)}" target="_blank" rel="noopener">Solscan</a>
      <a href="https://x.com/search?q=${encodeURIComponent(s.mint)}&f=live" target="_blank" rel="noopener">X search</a>
      ${m.twitter ? `<a href="${esc(m.twitter)}" target="_blank" rel="noopener">Coin X</a>` : ""}${m.telegram ? `<a href="${esc(m.telegram)}" target="_blank" rel="noopener">Telegram</a>` : ""}${m.website ? `<a href="${esc(m.website)}" target="_blank" rel="noopener">Site</a>` : ""}
      <button class="tag" data-log="${esc(s.mint)}" data-leader="${esc(s.wallet)}" data-mcap="${m.mcap || s.mcap || ""}">Log my buy</button>
    </div></div>`;
}
document.addEventListener("click", (e) => {
  const c = e.target.closest("[data-copy]"); if (c) { e.preventDefault(); copy(c.dataset.copy, "Address copied"); return; }
  const l = e.target.closest("[data-log]"); if (l) { openLog({ mint: l.dataset.log, leader: l.dataset.leader, mode: "real" }); }
});
async function loadFeed() {
  const rows = await api("/api/signals?limit=25").catch(() => []);
  const top = rows[0]?.id || 0;
  $("#feed").innerHTML = rows.length ? rows.map((s) => sigCard(s, lastSigId && s.id > lastSigId)).join("") :
    `<div class="empty">No leader buys yet. The engine is watching ${S ? S.health.watching : "the"} wallets on-chain; signals appear here within ~20s of a leader's first buy.</div>`;
  lastSigId = Math.max(lastSigId, top);
}
async function loadSignalsView() {
  const rows = await api("/api/signals?limit=200").catch(() => []);
  const f = rows.filter((s) => !sigFilter || s.verdict === sigFilter);
  $("#sig-list").innerHTML = f.length ? f.map((s) => sigCard(s)).join("") : '<div class="empty">No signals match.</div>';
}
$$("#sig-filter a").forEach((a) => a.onclick = () => { sigFilter = a.dataset.v; $$("#sig-filter a").forEach((b) => b.classList.toggle("on", b === a)); loadSignalsView(); });

// ---------- alerts ----------
let lastAlert = null;
async function loadAlerts() {
  const rows = await api("/api/alerts?after=0").catch(() => []);
  if (lastAlert !== null) {
    rows.filter((a) => a.id > lastAlert).reverse().forEach((a) => {
      if (["go", "caution", "exit", "risk"].includes(a.level)) { beep(a.level); desktop(a); toast(a.title, a.body, a.level); }
    });
  }
  lastAlert = Math.max(lastAlert || 0, rows[0]?.id || 0);
  if (view === "command") $("#alerts").innerHTML = rows.length ? rows.slice(0, 40).map((a) => `
    <div class="al ${a.read ? "" : "unread"}"><span class="dot ${esc(a.level)}"></span><div><b>${esc(a.title)}</b>${a.body ? `<p>${esc(a.body)}</p>` : ""}</div><span class="t">${ago(a.ts)}</span></div>`).join("")
    : '<div class="empty">No alerts yet.</div>';
}
$("#mark-read").onclick = async () => { await api("/api/alerts/read", {}); loadAlerts(); loadState(); };

// ---------- positions ----------
async function loadPositions() {
  const d = await api("/api/trades?status=open").catch(() => ({ rows: [] }));
  const now = Date.now() / 1000;
  $("#pos-sub").textContent = d.rows.length ? `${d.rows.length} open` : "";
  $("#positions").innerHTML = d.rows.length ? d.rows.map((t) => {
    const mins = (now - t.opened_at) / 60;
    const warn = mins > 100 ? `<span class="down">time stop in ${Math.max(0, 120 - mins).toFixed(0)}m</span>` : "";
    return `<div class="pos"><div><b>${esc(t.symbol)}</b><span class="tag-mode">${t.mode.toUpperCase()}</span>
      <div class="dim" style="font-size:12px">${usd(t.size_usd, 0)} at ${kfmt(t.entry_mcap)} → ${kfmt(t.last_mcap)} · ${mins.toFixed(0)}m ${warn}</div></div>
      <div class="r"><div class="${cls(t.upnl)}">${sgn(t.upnl)}</div><div class="dim" style="font-size:12px">${t.size_usd ? pct(t.upnl / t.size_usd) : ""}</div>
      <button class="btn ghost sm" data-close="${t.id}" data-mode="${t.mode}" style="margin-top:4px">Close</button></div></div>`;
  }).join("") : '<div class="empty">Flat. No open positions.</div>';
}
document.addEventListener("click", (e) => { const c = e.target.closest("[data-close]"); if (c) openClose(+c.dataset.close, c.dataset.mode); });

// ---------- trades ----------
let tmode = "real";
$$("#mode-seg a").forEach((a) => a.onclick = () => { tmode = a.dataset.v; $$("#mode-seg a").forEach((b) => b.classList.toggle("on", b === a)); loadTrades(); });
async function loadTrades() {
  const d = await api("/api/trades?mode=" + tmode).catch(() => ({ rows: [], stats: {} }));
  const st = d.stats[tmode] || { n: 0 };
  const kpi = (l, v, s) => `<div class="kpi"><label>${l}</label><div class="v">${v}</div><div class="s">${s || ""}</div></div>`;
  $("#tstats").innerHTML = st.n ? kpi("Closed trades", st.n, tmode === "paper" ? `${Math.max(0, 50 - st.n)} to the gate` : "") +
    kpi("Net P&amp;L", `<span class="${cls(st.pnl)}">${sgn(st.pnl)}</span>`, `ROI ${pct(st.roi, 1)}`) +
    kpi("Without best 2", `<span class="${cls(st.roi_ex_top2)}">${pct(st.roi_ex_top2, 1)}</span>`, "Is the edge more than 2 lucky trades?") +
    kpi("Win rate", pct(st.win_rate).replace("+", ""), `median trade ${pct(st.median_roi, 1)}`) +
    kpi("Avg win / loss", `<span class="up">${sgn(st.avg_win)}</span>`, `<span class="down">${sgn(st.avg_loss)}</span>`) +
    kpi("Best / worst", `<span class="up">${sgn(st.best, 0)}</span>`, `<span class="down">${sgn(st.worst, 0)}</span>`)
    : `<div class="empty" style="grid-column:1/-1">No closed ${tmode} trades yet. ${tmode === "real" ? "Add your fomo wallet in Settings and your trades log themselves." : "Paper trades open automatically on GO signals."}</div>`;
  drawCurve(st.curve || []);
  const rows = d.rows;
  $("#trade-tbl").innerHTML = `<tr><th>Opened</th><th>Coin</th><th>Leader</th><th class="num">Size</th><th class="num">Entry mcap</th><th class="num">Exit / now</th><th class="num">P&amp;L</th><th class="num">ROI</th><th>Exit reason</th><th>Notes</th><th></th></tr>` +
    (rows.length ? rows.map((t) => {
      const pnl = t.status === "open" ? t.upnl : t.pnl_usd;
      return `<tr><td class="mono">${new Date(t.opened_at * 1000).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}</td>
      <td><b>${esc(t.symbol)}</b> <a class="dim" data-copy="${esc(t.mint)}">${short(t.mint)}</a></td>
      <td class="mono">${t.leader ? short(t.leader) : '<span class="dim">own idea</span>'}</td>
      <td class="num">${usd(t.size_usd, 0)}</td><td class="num">${kfmt(t.entry_mcap)}</td><td class="num">${kfmt(t.status === "open" ? t.last_mcap : t.exit_mcap)}</td>
      <td class="num ${cls(pnl)}">${sgn(pnl)}</td><td class="num ${cls(pnl)}">${t.size_usd ? pct(pnl / t.size_usd) : "—"}</td>
      <td>${t.status === "open" ? '<span class="chip GO">OPEN</span>' : esc(t.exit_reason || "")}</td>
      <td><input data-note="${t.id}" value="${esc(t.notes || "")}" placeholder="Why?" style="padding:5px 8px;width:180px"></td>
      <td>${t.status === "open" ? `<button class="btn ghost sm" data-close="${t.id}" data-mode="${t.mode}">Close</button>` : ""}</td></tr>`;
    }).join("") : `<tr><td colspan="11" class="dim" style="text-align:center;padding:26px">No ${tmode} trades yet.</td></tr>`);
  $$("[data-note]").forEach((i) => i.onchange = () => api("/api/trades/note", { id: +i.dataset.note, notes: i.value }).then(() => toast("Note saved")));
}
function drawCurve(pts) {
  const el = $("#curve");
  if (pts.length < 2) { el.innerHTML = '<div class="empty" style="height:100%;display:grid;place-items:center">The curve appears after two closed trades.</div>'; return; }
  const W = 1000, H = 220, p = 28;
  const xs = pts.map((q) => q[0]), ys = pts.map((q) => q[1]).concat([0]);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const X = (v) => p + (W - 2 * p) * (x1 === x0 ? 0 : (v - x0) / (x1 - x0));
  const Y = (v) => H - p - (H - 2 * p) * (y1 === y0 ? 0.5 : (v - y0) / (y1 - y0));
  const line = pts.map((q, i) => `${i ? "L" : "M"}${X(q[0]).toFixed(1)},${Y(q[1]).toFixed(1)}`).join(" ");
  const last = pts[pts.length - 1][1];
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
    <defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#8b5cf6" stop-opacity=".22"/><stop offset="1" stop-color="#8b5cf6" stop-opacity=".02"/></linearGradient></defs>
    <line x1="${p}" x2="${W - p}" y1="${Y(0)}" y2="${Y(0)}" stroke="#2b2245" stroke-dasharray="4 5"/>
    <path d="${line} L${X(x1)},${Y(0)} L${X(x0)},${Y(0)} Z" fill="url(#g)"/>
    <path d="${line}" fill="none" stroke="${last >= 0 ? "#a78bfa" : "#fb7185"}" stroke-width="2.4" vector-effect="non-scaling-stroke"/>
    <text x="${W - p}" y="${Math.max(14, Y(last) - 8)}" text-anchor="end" fill="#c4b5fd" font-size="13" font-family="JetBrains Mono">${esc(sgn(last))}</text></svg>`;
}

// ---------- modals: log + close ----------
function modal(html) { $("#modal-box").innerHTML = html; $("#modal").classList.add("on"); }
$("#modal").onclick = (e) => { if (e.target.id === "modal") $("#modal").classList.remove("on"); };
function openLog(pre = {}) {
  const size = S ? S.settings.trade_size_usd : 190;
  modal(`<h3>Log a trade</h3><form class="form" id="log-form">
    <label class="wide">Token address<input name="mint" required value="${esc(pre.mint || "")}" class="mono"></label>
    <label>Mode<select name="mode"><option value="real" ${pre.mode !== "paper" ? "selected" : ""}>Real</option><option value="paper" ${pre.mode === "paper" ? "selected" : ""}>Paper</option></select></label>
    <label>Size (USD)<input name="size_usd" type="number" step="0.01" min="1" max="1000" value="${size}" required></label>
    <label>Entry mcap (blank = now)<input name="entry_mcap" type="number" step="1"></label>
    <label>Leader copied<input name="leader" class="mono" value="${esc(pre.leader || "")}"></label>
    <label class="wide">Why this trade?<input name="notes" placeholder="Signal, thesis, checklist…"></label>
    <div class="actions"><button class="btn">Save</button><button type="button" class="btn ghost" onclick="document.getElementById('modal').classList.remove('on')">Cancel</button></div></form>
    <p class="note">If your fomo wallet is set in Settings, real buys log themselves. Use this for anything the wallet watcher misses.</p>`);
  $("#log-form").onsubmit = async (e) => {
    e.preventDefault(); const f = Object.fromEntries(new FormData(e.target));
    if (+f.size_usd > 1000) return toast("Over your $1k limit", "Max trade size is $1,000.", "risk");
    try { await api("/api/trades", f); $("#modal").classList.remove("on"); toast("Trade logged", f.mint); refreshView(); } catch (err) { toast("Couldn't log trade", err.message, "risk"); }
  };
}
$("#log-btn").onclick = () => openLog({ mode: tmode });
function openClose(id, mode) {
  modal(`<h3>Close trade #${id}</h3><form class="form" id="close-form">
    ${mode === "real" ? '<label class="wide">What you got back (USD, after fees)<input name="proceeds_usd" type="number" step="0.01" placeholder="Blank = estimate at current price"></label>' : '<p class="note wide">Paper trades close at the current price with fees and slippage.</p>'}
    <label class="wide">Reason<select name="reason"><option>leader sold</option><option>time stop</option><option>disaster stop</option><option>took profit</option><option>manual close</option></select></label>
    <div class="actions"><button class="btn">Close trade</button><button type="button" class="btn ghost" onclick="document.getElementById('modal').classList.remove('on')">Cancel</button></div></form>`);
  $("#close-form").onsubmit = async (e) => {
    e.preventDefault(); const f = Object.fromEntries(new FormData(e.target));
    try { await api("/api/trades/close", { id, ...f }); $("#modal").classList.remove("on"); refreshView(); } catch (err) { toast("Couldn't close", err.message, "risk"); }
  };
}

// ---------- intelligence ----------
let intelLoaded = false;
async function loadIntel() {
  if (!intelLoaded) {
    const d = await api("/api/intel").catch(() => null); if (!d) return;
    intelLoaded = true;
    const nowH = S ? S.window.hour : new Date().getHours();
    drawHours(d.hourly, nowH);
    const best = d.fees.reduce((a, b) => (b.cost < a.cost ? b : a));
    $("#fees").innerHTML = d.fees.map((f) => `<div class="fee ${f.size === 190 ? "best" : ""}"><span>${usd(f.size, 0)}</span><b>${(f.cost * 100).toFixed(1)}%</b><span>${usd(f.size * f.cost)}</span></div>`).join("");
    $("#evidence").innerHTML = d.evidence.map((e) => `<div class="ev"><label>${esc(e.k)}</label><b>${esc(e.v)}</b><p>${esc(e.d)}</p></div>`).join("");
    $("#rules").innerHTML = d.rules.map((r) => `<li>${esc(r)}</li>`).join("");
  }
  loadMe();
}
function drawHours(rows, nowH) {
  if (!rows.length) { $("#clockchart").innerHTML = '<div class="empty">No hourly data.</div>'; return; }
  const W = 960, H = 260, p = 30, bw = (W - 2 * p) / 24;
  const max = Math.max(...rows.map((r) => r.per1k)), min = Math.min(...rows.map((r) => r.per1k));
  const bars = rows.map((r) => {
    const h = 20 + (H - 2 * p - 20) * (r.per1k - min * 0.9) / (max - min * 0.9);
    const x = p + r.et * bw, y = H - p - h, cur = r.et === nowH;
    const a = 0.25 + 0.75 * (r.per1k - min) / (max - min);
    return `<rect x="${(x + 2).toFixed(1)}" y="${y.toFixed(1)}" width="${(bw - 4).toFixed(1)}" height="${h.toFixed(1)}" rx="3" fill="${cur ? "#c4b5fd" : `rgba(139,92,246,${a.toFixed(2)})`}"><title>${r.et}:00 ET · ${r.per1k} grads/1k · ${r.launches} launches/hr</title></rect>
      ${r.et % 3 === 0 ? `<text x="${(x + bw / 2).toFixed(1)}" y="${H - 6}" text-anchor="middle" fill="#9a92b5" font-size="20" font-family="JetBrains Mono">${r.et}</text>` : ""}`;
  }).join("");
  $("#clockchart").innerHTML = `<svg viewBox="0 0 ${W} ${H}">${bars}</svg>`;
  const cur = rows.find((r) => r.et === nowH);
  $("#clock-note").innerHTML = `Now (${nowH}:00 ET): <b>${cur ? cur.per1k : "—"}</b> graduations per 1k launches. Best: 5–7 PM and midnight–4 AM ET. Worst: 7–8 AM ET. Saturday is the best day; Wed/Thu the weakest.`;
}
async function loadMe() {
  const d = await api("/api/me").catch(() => null);
  if (!d || !d.wallet) { $("#me-sub").textContent = ""; $("#me").innerHTML = '<div class="empty">Add your fomo wallet&#39;s Solana address in Settings. Your trades import from the chain and this report builds itself.</div>'; return; }
  $("#me-sub").innerHTML = `wallet <a data-copy="${esc(d.wallet)}" class="mono">${short(d.wallet)}</a> · ${d.n} closed trades`;
  if (!d.n) { $("#me").innerHTML = '<div class="empty">No closed trades yet.</div>'; return; }
  const kv = (l, v, s) => `<div class="kpi"><label>${l}</label><div class="v">${v}</div><div class="s">${s || ""}</div></div>`;
  const wk = d.week || {};
  $("#me").innerHTML = `<div class="me-grid">
    ${kv("Net P&amp;L", `<span class="${cls(d.net)}">${sgn(d.net)}</span>`, `win rate ${pct(d.win_rate).replace("+", "")}`)}
    ${kv("Before fees", `<span class="${cls(d.gross)}">${sgn(d.gross)}</span>`, "what your picks made")}
    ${kv("Fees paid (est.)", `<span class="down">${usd(d.fees)}</span>`, `${(d.cost_now * 100).toFixed(1)}% per round trip at ${usd(d.avg_size, 0)}`)}
    ${kv("Without best trade", `<span class="${cls(d.ex_best)}">${sgn(d.ex_best)}</span>`, "is it skill or one runner?")}
    ${kv("Median hold", `${d.median_hold.toFixed(1)}<small>min</small>`, "")}
    ${kv("Re-entries after a loss", d.reentries.n, `<span class="${cls(d.reentries.pnl)}">${sgn(d.reentries.pnl)}</span>`)}
    ${kv("Open bags (< −50%)", d.bags.n, d.bags.n ? `<span class="down">${sgn(d.bags.pnl)}</span>` : "none")}
    ${kv("pump.fun 7-day", `<span class="${cls(wk.pnl?.usd)}">${sgn(wk.pnl?.usd)}</span>`, wk.tokenCount != null ? `${wk.tokenCount} coins · bought ${usd(wk.totalBuySpend?.usd, 0)}` : "")}
  </div>
  <ul class="insight">${(d.insights || []).map((i) => `<li class="${esc(i.level)}">${i.html}</li>`).join("")}</ul>
  <div class="table-wrap"><table class="tbl"><tr><th>Hold time</th><th class="num">Trades</th><th class="num">P&amp;L</th></tr>
    ${Object.entries(d.holds).map(([k, v]) => `<tr><td>${esc(k)}</td><td class="num">${v.n}</td><td class="num ${cls(v.pnl)}">${sgn(v.pnl)}</td></tr>`).join("")}
    <tr><td>Copied a leader</td><td class="num">${d.copied.n}</td><td class="num ${cls(d.copied.pnl)}">${sgn(d.copied.pnl)}</td></tr>
    <tr><td>Own picks</td><td class="num">${d.own.n}</td><td class="num ${cls(d.own.pnl)}">${sgn(d.own.pnl)}</td></tr></table></div>`;
}
$("#xray-form").onsubmit = async (e) => {
  e.preventDefault(); const mint = $("#xray-in").value.trim(); if (!mint) return;
  $("#xray-out").innerHTML = '<div class="empty">Scanning…</div>';
  try {
    const x = await api("/api/xray?mint=" + encodeURIComponent(mint));
    $("#xray-out").innerHTML = sigCard({ id: 0, mint, wallet: "", symbol: x.m.symbol, verdict: x.verdict, score: x.score, ts: x.ts, usd: null, mcap: x.m.mcap, intel: x, leader: null })
      .replace(/Leader <a[^>]*>[^<]*<\/a> · bought — · /, "Scanned ");
  } catch (err) { $("#xray-out").innerHTML = `<div class="empty">${esc(err.message)}</div>`; }
};

// ---------- leaders ----------
async function loadLeaders() {
  const d = await api("/api/leaders").catch(() => ({ rows: [], job: {} }));
  const j = d.job || {};
  const im = d.imp || {};
  $("#ljob").textContent = [j.running ? `Scoring ${j.done}/${j.total}… (${j.qualified} qualify so far)` : j.finished ? `Last re-score ${ago(j.finished)}: ${j.msg}` : "",
    im.running ? `fomo leaderboard: ${im.done}/${im.total} scored, ${im.added} added` : im.msg || ""].filter(Boolean).join(" · ");
  $("#trade-tbl"); // no-op
  $("#leader-tbl").innerHTML = `<tr><th>Watch</th><th>Wallet</th><th>Label</th><th class="num">Closed 14d</th><th class="num">ROI 14d</th><th class="num">Win</th><th class="num">Median size</th><th class="num">Median entry mcap</th><th>Last trade</th><th>Source</th><th></th></tr>` +
    (d.rows.length ? d.rows.map((r) => `<tr>
      <td><button class="switch ${r.enabled ? "on" : ""}" data-toggle="${esc(r.wallet)}" data-on="${r.enabled ? 1 : 0}"></button></td>
      <td class="mono"><a data-copy="${esc(r.wallet)}">${short(r.wallet)}</a> <a href="https://pump.fun/profile/${esc(r.wallet)}" target="_blank" rel="noopener" class="dim">↗</a></td>
      <td title="${esc(r.note || "")}">${esc(r.label || "")}</td><td class="num">${r.closed_14d ?? "—"}</td><td class="num ${cls(r.roi_14d)}">${pct(r.roi_14d)}</td>
      <td class="num">${r.win_rate != null ? pct(r.win_rate).replace("+", "") : "—"}</td><td class="num">${r.median_size != null ? usd(r.median_size, 0) : "—"}</td>
      <td class="num">${kfmt(r.median_mcap)}${r.median_mcap && r.median_mcap < 5500 ? ' <span class="chip CAUTION" title="Buys seconds after launch: hard to follow at app speed">FAST</span>' : ""}</td>
      <td class="dim">${ago(r.last_trade_at)}</td><td class="dim">${esc(r.source || "")}</td>
      <td><button class="link" data-remove="${esc(r.wallet)}">Remove</button></td></tr>`).join("")
      : '<tr><td colspan="11" class="dim" style="text-align:center;padding:26px">No leaders yet. Click Re-score leaders.</td></tr>');
  $$("[data-toggle]").forEach((b) => b.onclick = async () => { await api("/api/leaders", { wallet: b.dataset.toggle, enabled: b.dataset.on === "1" ? 0 : 1 }); loadLeaders(); });
  $$("[data-remove]").forEach((b) => b.onclick = async () => { await api("/api/leaders", { wallet: b.dataset.remove, remove: true }); loadLeaders(); });
}
$("#lrefresh").onclick = async () => { const r = await api("/api/leaders/refresh", {}); toast(r.started ? "Re-scoring leaders" : "Already running", "Scores 364 small wallets from their closed positions (~10–20 min)."); loadLeaders(); };
$("#add-leader").onsubmit = async (e) => {
  e.preventDefault(); const w = $("#add-w").value.trim(); if (!/^[1-9A-HJ-NP-Za-km-z]{32,44}$/.test(w)) return toast("Not a Solana address", w, "risk");
  await api("/api/leaders", { wallet: w, label: $("#add-l").value.trim() }); $("#add-w").value = ""; $("#add-l").value = ""; loadLeaders();
};

// ---------- settings ----------
async function loadSettings() {
  const s = await api("/api/settings");
  const x0 = await api("/api/x-cookies").catch(() => ({ has: false }));
  const f = (k, l, t = "number", extra = "") => `<label>${l}<input name="${k}" type="${t}" value="${esc(s[k])}" ${extra}></label>`;
  $("#set-risk").innerHTML = f("trade_size_usd", "Trade size (USD)", "number", 'min="5" max="1000" step="1"') + f("max_trade_usd", "Max per trade (USD)", "number", 'max="1000"') +
    f("daily_buy_cap_usd", "Daily buy cap (USD)", "number", 'max="5000"') + f("max_entries_per_day", "Max entries / day") +
    f("daily_loss_limit_pct", "Daily loss limit (% of cap)") + f("loss_streak_limit", "Kill after N losses in a row") +
    f("max_mcap_usd", "Max entry market cap (USD)") + f("entry_delay_s", "Paper entry delay (s)") + f("exit_delay_s", "Paper exit delay (s)") +
    f("time_stop_min", "Time stop (min)") + f("disaster_stop_pct", "Disaster stop (%)") +
    `<label>Auto paper-trade GO signals<select name="auto_paper"><option value="true" ${s.auto_paper ? "selected" : ""}>On</option><option value="false" ${!s.auto_paper ? "selected" : ""}>Off</option></select></label>
     <div class="actions"><button class="btn">Save risk settings</button></div>`;
  $("#set-conn").innerHTML = `<label class="wide">Your fomo wallet (Solana address)<input name="my_wallet" class="mono" value="${esc(s.my_wallet)}" placeholder="fomo app → Deposit → Solana"></label>
    <label class="wide">Discord webhook (alerts to your phone)<input name="discord_webhook" value="${esc(s.discord_webhook)}" placeholder="https://discord.com/api/webhooks/…"></label>
    <label class="wide">Solana RPC URL<input name="rpc_url" class="mono" value="${esc(s.rpc_url)}"></label>
    <label>X auth_token (from x.com cookies)<input name="x_auth_token" type="password" autocomplete="off" placeholder="${x0.has ? "saved: paste to replace" : "not set"}"></label>
    <label>X ct0<input name="x_ct0" type="password" autocomplete="off" placeholder="${x0.has ? "saved: paste to replace" : "not set"}"></label>
    <label>X mentions<select name="x_enabled"><option value="true" ${s.x_enabled ? "selected" : ""}>On</option><option value="false" ${!s.x_enabled ? "selected" : ""}>Off</option></select></label>
    <label>Leader poll (s)<input name="poll_leaders_s" type="number" value="${s.poll_leaders_s}"></label>
    <div class="actions"><button class="btn">Save connections</button><button type="button" class="btn ghost" id="test-alert">Send test alert</button></div>`;
  const x = S ? S.health.x : { state: "off", detail: "" };
  $("#conn-note").innerHTML = `X status: <b>${esc(x.state)}</b> ${esc(x.detail || "")}. X cookies: in your normal Edge on x.com press F12 → Application → Cookies → https://x.com, then copy <span class="mono">auth_token</span> and <span class="mono">ct0</span> into the fields above. They stay in a local file on this PC.
    A free Helius RPC URL makes wallet watching faster than the public endpoint.`;
  const save = async (e) => {
    e.preventDefault(); const d = Object.fromEntries(new FormData(e.target));
    for (const k of ["auto_paper", "x_enabled"]) if (k in d) d[k] = d[k] === "true";
    if (+d.trade_size_usd > 1000 || +d.max_trade_usd > 1000) return toast("Limit", "Your rule caps trades at $1,000.", "risk");
    if (+d.daily_buy_cap_usd > 5000) return toast("Limit", "Your rule caps a day at $5,000.", "risk");
    if (d.x_auth_token || d.x_ct0) {
      if (!(d.x_auth_token && d.x_ct0)) return toast("X needs both", "Paste both auth_token and ct0.", "risk");
      await api("/api/x-cookies", { auth_token: d.x_auth_token.trim(), ct0: d.x_ct0.trim() });
    }
    delete d.x_auth_token; delete d.x_ct0;
    await api("/api/settings", d); toast("Saved"); loadState(); loadSettings();
  };
  $("#set-risk").onsubmit = save; $("#set-conn").onsubmit = save;
  $("#test-alert").onclick = async () => { await api("/api/test-alert", {}); toast("Test alert sent", "Check Discord if a webhook is set."); };
}

// ---------- loop ----------
async function refreshView(first) {
  if (view === "command") { await Promise.all([loadFeed(), loadPositions(), loadAlerts()]); }
  else { loadAlerts(); }
  if (view === "signals") loadSignalsView();
  if (view === "trades") loadTrades();
  if (view === "intel" && first) loadIntel();
  if (view === "leaders") loadLeaders();
  if (view === "settings" && first) loadSettings();
}
(async () => {
  await loadState(); await refreshView(true);
  setInterval(loadState, 5000);
  setInterval(() => refreshView(false), 6000);
})();
