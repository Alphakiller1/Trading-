// ==UserScript==
// @name         FOMO Command chart levels
// @namespace    chase-fomo-command
// @version      1.0
// @description  Adds the model's market-cap levels ($10k / $25k / $45k / $80k) and VWAP to every fomo token chart.
// @match        https://fomo.family/tokens/*
// @grant        unsafeWindow
// @run-at       document-idle
// ==/UserScript==
// Chart drawings only: it never touches Buy/Sell or any account setting.
// fomo saves drawings per coin, so this re-adds the lines whenever a coin doesn't have them.
// Levels come from fomo/dashboard/AUDIT.md: below $10k = best copy entries, above $25k the edge
// fades, ~$45k = pump.fun graduation at ~$110 SOL (~411 SOL), $80k = your max.
(function () {
  // fomo's CSP blocks page-injected scripts, so read the page through Tampermonkey's unsafeWindow.
  const W = typeof unsafeWindow !== "undefined" ? unsafeWindow : window;
  const LEVELS = [
    [10000, "$10k: best entries below", "#9d4dff"],
    [25000, "$25k: edge fades above", "#9d4dff"],
    [45000, "$45k: graduation (~411 SOL)", "#9d4dff"],
    [80000, "$80k: your max", "#ff4d6d"],
  ];
  const busy = new Set();

  function chartApi() {
    for (const f of W.document.querySelectorAll("iframe")) {
      try {
        if (f.contentWindow && f.contentWindow.tradingViewApi) return f.contentWindow.tradingViewApi;
      } catch (e) { /* cross-origin frame: not the chart */ }
    }
    return null;
  }

  function inMcapMode(c) {
    // MCap axis values are in the thousands; Price mode is a tiny fraction of a dollar.
    try {
      const r = c.getPanes()[0].getMainSourcePriceScale().getVisiblePriceRange();
      return r && r.to > 100;
    } catch (e) { return false; }
  }

  async function apply() {
    const api = chartApi();
    if (!api) return;
    let c;
    try { c = api.activeChart(); } catch (e) { return; }
    const sym = c.symbol();
    if (!sym || busy.has(sym) || !inMcapMode(c)) return;
    busy.add(sym);
    try {
      const have = new Set(c.getAllShapes().map((s) => {
        try { return c.getShapeById(s.id).getProperties().text; } catch (e) { return ""; }
      }));
      for (const [price, label, color] of LEVELS) {
        if (have.has(label)) continue;
        await c.createShape({ price }, {
          shape: "horizontal_line", lock: true, text: label,
          overrides: { linecolor: color, linestyle: 2, linewidth: 1, showLabel: true, textcolor: "#dcc2ff",
                       fontsize: 11, horzLabelsAlign: "right", vertLabelsAlign: "bottom" },
        });
      }
      if (!c.getAllStudies().some((s) => /VWAP/i.test(s.name))) await c.createStudy("VWAP", false, false);
    } catch (e) { /* chart still loading; try again on the next tick */ }
    finally { busy.delete(sym); }
  }

  setInterval(apply, 2000);
})();
