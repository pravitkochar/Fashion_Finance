"""P6 — build dashboard/index.html: the Trickle_Down nowcasting dashboard.

Fully self-contained: inline CSS/JS, data embedded as one JSON blob, charts
drawn as inline SVG by small local JS renderers. Zero external requests, so
the file works offline and can be published as-is (e.g. as a claude.ai
Artifact for the public site).

Renders correctly with ZERO pipeline data — every section shows a clean
"no data yet" state naming the script that feeds it.

Design follows the dataviz skill: validated palette (light+dark), one-hue
sequential heatmap ramp, diverging blue/red for polarity (scores, z), thin
marks, hairline grid, legends for multi-series, tooltips that enhance not
gate, and a table-view twin per chart.

Usage:  python scripts/09_dashboard.py [--open]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import date

import pandas as pd

import lib_trickle as lt

log = lt.get_logger("09_dashboard")

OUT = lt.DASHBOARD / "index.html"
MAX_EQUITY_POINTS = 400
MAX_GRID_MATERIALS = 4          # per retailer small-multiple; never cycle hues


# ---------------------------------------------------------- data loading ----

def safe_read(path) -> pd.DataFrame | None:
    try:
        if path.exists():
            df = pd.read_csv(path)
            if not df.empty:
                return df
    except Exception as exc:
        log.warning("could not read %s: %s", path, exc)
    return None


def clean_records(df: pd.DataFrame) -> list[dict]:
    """NaN-safe records (json.dumps chokes on float NaN)."""
    return json.loads(df.to_json(orient="records", date_format="iso"))


# ------------------------------------------------------- section builders ---

def build_runway_heatmap() -> dict | None:
    df = safe_read(lt.DATA / "runway_mix.csv")
    if df is None or "level" not in df.columns:
        return None
    season = df[df["level"] == "season"].copy()
    if season.empty:
        return None
    seasons = sorted(season["season_code"].unique(), key=lt.season_sort_key)
    mat_order = (season.groupby("material")["share"].mean()
                 .sort_values(ascending=False).index.tolist())
    pivot = season.pivot_table(index="material", columns="season_code",
                               values="share", aggfunc="last")
    pivot = pivot.reindex(index=mat_order, columns=seasons)
    emergent = None
    if "is_emergent" in season.columns:
        epiv = season.pivot_table(index="material", columns="season_code",
                                  values="is_emergent", aggfunc="last")
        epiv = epiv.reindex(index=mat_order, columns=seasons)
        emergent = [[bool(v) if pd.notna(v) else False for v in row]
                    for row in epiv.values]
    values = [[round(float(v), 4) if pd.notna(v) else None for v in row]
              for row in pivot.values]
    return {"seasons": seasons, "materials": mat_order,
            "values": values, "emergent": emergent}


def build_propagation() -> dict | None:
    best = safe_read(lt.DATA / "propagation.csv")
    if best is None:
        return None
    out: dict = {"best": clean_records(best)}
    grid = safe_read(lt.DATA / "_propagation_grid.csv")
    if grid is not None and {"retailer", "material", "lag", "r"} <= set(grid.columns):
        by_retailer: dict = {}
        for retailer, g in grid.groupby("retailer"):
            top = (g.groupby("material")["r"].apply(lambda s: s.abs().max())
                   .sort_values(ascending=False)
                   .head(MAX_GRID_MATERIALS).index.tolist())
            series = {}
            for mat in top:
                sub = g[g["material"] == mat].sort_values("lag")
                series[mat] = [round(float(r), 3) if pd.notna(r) else None
                               for r in sub["r"]]
            by_retailer[retailer] = series
        out["grid"] = by_retailer
    return out


def build_leaderboard() -> dict | None:
    df = safe_read(lt.DATA / "signals_adoption.csv")
    if df is None:
        return None
    names = {r["ticker"]: r["name"]
             for r in lt.load_universe()["tier2_retailers"] if r["ticker"]}
    for cadence in ("seasonal", "monthly"):
        sub = df[df["cadence"] == cadence]
        if sub.empty:
            continue
        latest = sub["rebalance_date"].max()
        rows = sub[sub["rebalance_date"] == latest].copy()
        rows["name"] = rows["ticker"].map(names).fillna(rows["ticker"])
        rows = rows.sort_values("score", ascending=False)
        return {"asof": str(latest), "cadence": cadence,
                "rows": clean_records(rows[["ticker", "name", "score",
                                            "rank", "weight"]])}
    return None


def build_nowcast() -> dict | None:
    df = safe_read(lt.DATA / "signals_nowcast.csv")
    if df is None:
        return None
    latest = df["date"].max()
    rows = df[df["date"] == latest].sort_values("nowcast_z", ascending=False)
    return {"asof": str(latest),
            "rows": clean_records(rows[["material", "nowcast_z",
                                        "direction", "tickers"]])}


def build_positions(leaderboard, nowcast) -> dict | None:
    rows = []
    if leaderboard:
        for r in leaderboard["rows"]:
            w = r.get("weight") or 0
            if w:
                rows.append({"sleeve": f"H1 adoption ({leaderboard['cadence']})",
                             "ticker": r["ticker"], "detail": r["name"],
                             "weight": round(float(w), 4),
                             "asof": leaderboard["asof"]})
    if nowcast:
        for r in nowcast["rows"]:
            if r.get("direction") in ("long", "short"):
                rows.append({"sleeve": "H2 nowcast", "ticker": r["tickers"],
                             "detail": r["material"],
                             "weight": 1 if r["direction"] == "long" else -1,
                             "asof": nowcast["asof"]})
    return {"rows": rows} if rows else None


def build_backtest() -> dict | None:
    fp = lt.REPORTS / "findings.json"
    if not fp.exists():
        return None
    with open(fp, encoding="utf-8") as f:
        findings = json.load(f)
    out: dict = {"findings": findings}
    eq = safe_read(lt.REPORTS / "equity_curves.csv")
    if eq is not None:
        curves = {}
        for strat, g in eq.groupby("strategy"):
            g = g.sort_values("date")
            step = max(1, len(g) // MAX_EQUITY_POINTS)
            g = g.iloc[::step]
            curves[strat] = {"dates": g["date"].tolist(),
                             "equity": [round(float(v), 4)
                                        for v in g["equity"]]}
        out["curves"] = curves
    periods = safe_read(lt.REPORTS / "backtest_results.csv")
    if periods is not None:
        out["periods"] = clean_records(periods)
    return out


def build_health() -> dict:
    files = [
        ("runway looks", lt.RUNWAY / "runway_looks.csv", "01_scrape_runway.py", "show_date"),
        ("runway tags", lt.RUNWAY / "runway_tags.csv", "02_tag_gemini.py", None),
        ("downstream items", lt.DOWNSTREAM / "downstream_items.csv", "03_scrape_downstream.py", "first_seen"),
        ("runway mix", lt.DATA / "runway_mix.csv", "04_material_mix.py", "known_date"),
        ("downstream mix", lt.DATA / "downstream_mix.csv", "04_material_mix.py", "known_date"),
        ("google trends", lt.TRENDS / "trends.csv", "05_google_trends.py", "known_date"),
        ("propagation", lt.DATA / "propagation.csv", "06_propagation_lag.py", None),
        ("adoption signals", lt.DATA / "signals_adoption.csv", "07_signals.py", "rebalance_date"),
        ("nowcast signals", lt.DATA / "signals_nowcast.csv", "07_signals.py", "date"),
        ("prices tier2/3", lt.PRICES / "prices_tier23.csv", "08_backtest.py --fetch", "date"),
    ]
    rows = []
    for label, path, script, datecol in files:
        df = safe_read(path)
        rows.append({
            "label": label, "script": script,
            "rows": 0 if df is None else int(len(df)),
            "latest": (str(df[datecol].max())[:10]
                       if df is not None and datecol and datecol in df.columns
                       else None),
            "ok": df is not None,
        })
    src = safe_read(lt.DATA / "_source_log.csv")
    events = clean_records(src.tail(20)) if src is not None else []
    return {"files": rows, "source_events": events}


# ----------------------------------------------------------------- html -----

TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Trickle Down — Trend Cascade</title>
<style>
:root{
  --page:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e;
  --muted:#898781; --grid:#e1e0d9; --axis:#c3c2b7;
  --border:rgba(11,11,11,.10);
  --s1:#2a78d6; --s2:#1baf7a; --s3:#eda100; --s4:#008300;
  --s5:#4a3aa7; --s6:#e34948; --s7:#e87ba4; --s8:#eb6834;
  --pos:#2a78d6; --neg:#e34948; --mid:#f0efec;
  --good:#0ca30c; --warn:#fab219;
  --heat0:#cde2fb; --heat1:#9ec5f4; --heat2:#86b6ef; --heat3:#5598e7;
  --heat4:#3987e5; --heat5:#256abf; --heat6:#184f95; --heat7:#0d366b;
}
@media (prefers-color-scheme: dark){
  :root{
    --page:#0d0d0d; --surface:#1a1a19; --ink:#ffffff; --ink2:#c3c2b7;
    --muted:#898781; --grid:#2c2c2a; --axis:#383835;
    --border:rgba(255,255,255,.10);
    --s1:#3987e5; --s2:#199e70; --s3:#c98500; --s4:#008300;
    --s5:#9085e9; --s6:#e66767; --s7:#d55181; --s8:#d95926;
    --pos:#3987e5; --neg:#e66767; --mid:#383835;
    --heat0:#184f95; --heat1:#1c5cab; --heat2:#256abf; --heat3:#3987e5;
    --heat4:#5598e7; --heat5:#86b6ef; --heat6:#9ec5f4; --heat7:#cde2fb;
  }
}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);
  font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:24px 20px 60px}
header h1{font-size:22px;font-weight:650;margin:0}
header .sub{color:var(--ink2);margin:4px 0 0}
header .meta{color:var(--muted);font-size:12px;margin-top:6px}
.grid{display:grid;grid-template-columns:repeat(12,1fr);gap:16px;margin-top:20px}
.card{grid-column:span 12;background:var(--surface);border:1px solid var(--border);
  border-radius:10px;padding:16px 18px}
.card.half{grid-column:span 6}
@media (max-width:900px){.card.half{grid-column:span 12}}
.card h2{font-size:15px;font-weight:650;margin:0 0 2px}
.card .note{color:var(--muted);font-size:12px;margin:0 0 10px}
.badge{display:inline-block;font-size:11px;color:var(--ink2);
  border:1px solid var(--border);border-radius:999px;padding:1px 8px;
  margin-left:6px;vertical-align:1px}
.empty{color:var(--muted);padding:26px 8px;text-align:center;font-size:13px}
.empty code{background:var(--mid);border-radius:4px;padding:1px 5px}
.scroll{overflow-x:auto}
svg{display:block}
svg text{font:11px system-ui,-apple-system,"Segoe UI",sans-serif;fill:var(--ink2)}
svg .muted{fill:var(--muted)}
svg .val{fill:var(--ink);font-weight:600}
.legend{display:flex;flex-wrap:wrap;gap:12px;margin:6px 0 8px;font-size:12px;
  color:var(--ink2)}
.legend .key{display:inline-flex;align-items:center;gap:6px}
.legend .line{width:14px;height:0;border-top:2.5px solid}
.legend .swatch{width:10px;height:10px;border-radius:2px}
.tiles{display:flex;flex-wrap:wrap;gap:12px;margin:4px 0 14px}
.tile{flex:1 1 120px;min-width:120px;background:var(--page);
  border:1px solid var(--border);border-radius:8px;padding:10px 12px}
.tile .lab{font-size:11px;color:var(--muted)}
.tile .num{font-size:24px;font-weight:600;margin-top:2px}
.tile .num.na{color:var(--muted);font-weight:400}
table{border-collapse:collapse;width:100%;font-size:12.5px}
th{color:var(--muted);text-align:left;font-weight:500;border-bottom:1px solid var(--grid);
  padding:5px 10px 5px 0}
td{border-bottom:1px solid var(--grid);padding:5px 10px 5px 0;
  font-variant-numeric:tabular-nums}
details{margin-top:10px}
details summary{cursor:pointer;color:var(--muted);font-size:12px}
.status{display:inline-flex;align-items:center;gap:5px}
.status .dot{width:8px;height:8px;border-radius:50%}
#tip{position:fixed;pointer-events:none;background:var(--surface);
  border:1px solid var(--border);border-radius:8px;padding:8px 10px;
  font-size:12px;box-shadow:0 4px 14px rgba(0,0,0,.18);display:none;z-index:9;
  max-width:280px}
#tip .t-val{font-weight:650;color:var(--ink)}
#tip .t-row{display:flex;align-items:center;gap:6px;margin-top:2px;color:var(--ink2)}
#tip .t-key{width:12px;height:0;border-top:2.5px solid}
.footnote{color:var(--muted);font-size:11.5px;margin-top:8px}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>Trickle Down — Trend Cascade</h1>
    <p class="sub">Runway → high street → material demand. Point-in-time signals; all results net of costs.</p>
    <p class="meta" id="meta"></p>
  </header>
  <div class="grid">
    <section class="card" id="sec-backtest"></section>
    <section class="card" id="sec-heatmap"></section>
    <section class="card half" id="sec-leaderboard"></section>
    <section class="card half" id="sec-nowcast"></section>
    <section class="card" id="sec-propagation"></section>
    <section class="card half" id="sec-positions"></section>
    <section class="card half" id="sec-health"></section>
  </div>
</div>
<div id="tip"></div>
<script id="payload" type="application/json">__PAYLOAD__</script>
<script>
"use strict";
const DATA = JSON.parse(document.getElementById("payload").textContent);
const SVGNS = "http://www.w3.org/2000/svg";
const SERIES = ["--s1","--s2","--s3","--s4","--s5","--s6","--s7","--s8"];
const cssv = n => `var(${n})`;

function el(tag, attrs, parent){
  const node = document.createElementNS(SVGNS, tag);
  for (const k in attrs || {}) node.setAttribute(k, attrs[k]);
  if (parent) parent.appendChild(node);
  return node;
}
function div(cls, parent){
  const d = document.createElement("div");
  if (cls) d.className = cls;
  if (parent) parent.appendChild(d);
  return d;
}
function fmt(x, d){
  if (x === null || x === undefined || Number.isNaN(x)) return "—";
  return Number(x).toFixed(d === undefined ? 2 : d);
}
function pct(x, d){
  return x === null || x === undefined ? "—" : (100 * x).toFixed(d === undefined ? 1 : d) + "%";
}

/* ---------- tooltip (textContent only — labels are untrusted) ---------- */
const tip = document.getElementById("tip");
function tipShow(evt, rows){
  tip.textContent = "";
  rows.forEach(function(r, i){
    const line = div(i === 0 ? "t-val" : "t-row", tip);
    if (r.color){
      const key = div("t-key", line);
      key.style.borderTopColor = r.color;
    }
    line.appendChild(document.createTextNode(r.text));
  });
  tip.style.display = "block";
  tipMove(evt);
}
function tipMove(evt){
  const pad = 14;
  let x = evt.clientX + pad, y = evt.clientY + pad;
  const r = tip.getBoundingClientRect();
  if (x + r.width > innerWidth - 8) x = evt.clientX - r.width - pad;
  if (y + r.height > innerHeight - 8) y = evt.clientY - r.height - pad;
  tip.style.left = x + "px"; tip.style.top = y + "px";
}
function tipHide(){ tip.style.display = "none"; }
function hover(node, rowsFn){
  node.addEventListener("pointerenter", e => tipShow(e, rowsFn()));
  node.addEventListener("pointermove", tipMove);
  node.addEventListener("pointerleave", tipHide);
}

/* ------------------------------ scaffolding ---------------------------- */
function section(id, title, note, badge){
  const sec = document.getElementById(id);
  const h = document.createElement("h2");
  h.textContent = title;
  if (badge){
    const b = document.createElement("span");
    b.className = "badge"; b.textContent = badge;
    h.appendChild(b);
  }
  sec.appendChild(h);
  if (note){
    const p = document.createElement("p");
    p.className = "note"; p.textContent = note;
    sec.appendChild(p);
  }
  return sec;
}
function emptyState(sec, script){
  const e = div("empty", sec);
  e.appendChild(document.createTextNode("No data yet — run "));
  const c = document.createElement("code");
  c.textContent = "scripts/" + script;
  e.appendChild(c);
}
function makeTable(parent, headers, rows){
  const wrap = div("scroll", parent);
  const t = document.createElement("table");
  const tr = document.createElement("tr");
  headers.forEach(function(h){
    const th = document.createElement("th"); th.textContent = h; tr.appendChild(th);
  });
  t.appendChild(tr);
  rows.forEach(function(row){
    const trr = document.createElement("tr");
    row.forEach(function(cell){
      const td = document.createElement("td");
      td.textContent = (cell === null || cell === undefined) ? "—" : String(cell);
      trr.appendChild(td);
    });
    t.appendChild(trr);
  });
  wrap.appendChild(t);
  return wrap;
}
function tableTwin(parent, headers, rows){
  const d = document.createElement("details");
  const s = document.createElement("summary");
  s.textContent = "Table view";
  d.appendChild(s);
  makeTable(d, headers, rows);
  parent.appendChild(d);
}
function legend(parent, entries, mark){
  const lg = div("legend", parent);
  entries.forEach(function(e){
    const k = div("key", lg);
    const sw = div(mark === "line" ? "line" : "swatch", k);
    if (mark === "line") sw.style.borderTopColor = e.color;
    else sw.style.background = e.color;
    k.appendChild(document.createTextNode(e.label));
  });
}

/* ------------------------------- heatmap ------------------------------- */
function renderHeatmap(){
  const sec = section("sec-heatmap", "Runway material mix",
    "Season-level share of each material across tagged looks; deeper = larger share. Ring = emergent (rising vs trailing 3 seasons).");
  const d = DATA.runway_heatmap;
  if (!d){ emptyState(sec, "01_scrape_runway.py → 02_tag_gemini.py → 04_material_mix.py"); return; }
  const cw = 30, ch = 20, gap = 2, left = 84, top = 4, bottom = 46;
  const W = left + d.seasons.length * (cw + gap);
  const H = top + d.materials.length * (ch + gap) + bottom;
  const wrap = div("scroll", sec);
  const svg = el("svg", {width: W, height: H, role: "img",
                         "aria-label": "Runway material mix heatmap"}, null);
  wrap.appendChild(svg);
  let vmax = 0;
  d.values.forEach(r => r.forEach(v => { if (v !== null && v > vmax) vmax = v; }));
  vmax = vmax || 1;
  d.materials.forEach(function(mat, i){
    const t = el("text", {x: left - 8, y: top + i * (ch + gap) + ch / 2 + 4,
                          "text-anchor": "end"}, svg);
    t.textContent = mat;
    d.seasons.forEach(function(se, j){
      const v = d.values[i][j];
      const x = left + j * (cw + gap), y = top + i * (ch + gap);
      const cell = el("rect", {x: x, y: y, width: cw, height: ch, rx: 2}, svg);
      if (v === null){
        cell.setAttribute("fill", "var(--mid)");
      } else {
        const step = Math.min(7, Math.floor((v / vmax) * 7.999));
        cell.setAttribute("fill", cssv("--heat" + step));
        if (d.emergent && d.emergent[i][j])
          cell.setAttribute("stroke", cssv("--s3")),
          cell.setAttribute("stroke-width", "2");
      }
      hover(cell, () => [
        {text: v === null ? "no looks tagged" : pct(v)},
        {text: mat + " · " + se}]);
    });
  });
  d.seasons.forEach(function(se, j){
    if (j % 2 === 1 && d.seasons.length > 14) return;   // thin dense axis
    const t = el("text", {x: left + j * (cw + gap) + cw / 2,
                          y: H - bottom + 14, "text-anchor": "middle",
                          class: "muted"}, svg);
    t.textContent = se.replace("20", "'");
  });
  tableTwin(sec, ["material"].concat(d.seasons),
    d.materials.map((m, i) => [m].concat(d.values[i].map(v => v === null ? null : pct(v)))));
}

/* --------------------------- propagation lags -------------------------- */
function renderPropagation(){
  const sec = section("sec-propagation", "Propagation lag — runway → retailer",
    "Cross-correlation of runway share vs downstream share by lag (months). Peak = how long a trend takes to reach the racks.");
  const d = DATA.propagation;
  if (!d){ emptyState(sec, "06_propagation_lag.py"); return; }
  if (d.grid){
    const mats = [];
    Object.values(d.grid).forEach(g => Object.keys(g).forEach(m => {
      if (!mats.includes(m)) mats.push(m);
    }));
    const shown = mats.slice(0, 8);                 // fixed slots, never cycled
    const colorOf = m => cssv(SERIES[shown.indexOf(m)]);
    legend(sec, shown.map(m => ({label: m, color: colorOf(m)})), "line");
    const row = div("scroll", sec);
    row.style.display = "flex"; row.style.gap = "14px";
    Object.keys(d.grid).forEach(function(ret){
      const g = d.grid[ret];
      const cardW = 190, plotW = 160, plotH = 90, lx = 22, ty = 18;
      const holder = document.createElement("div");
      const svg = el("svg", {width: cardW, height: plotH + ty + 28}, null);
      holder.appendChild(svg);
      const title = el("text", {x: lx, y: 11, class: "val"}, svg);
      title.textContent = ret;
      el("line", {x1: lx, x2: lx + plotW, y1: ty + plotH / 2, y2: ty + plotH / 2,
                  stroke: "var(--axis)", "stroke-width": 1}, svg);
      const xOf = i => lx + (i / 12) * plotW;
      const yOf = r => ty + plotH / 2 - r * (plotH / 2);
      Object.keys(g).forEach(function(mat){
        if (!shown.includes(mat)) return;
        const pts = g[mat].map((r, i) => r === null ? null : [xOf(i), yOf(Math.max(-1, Math.min(1, r)))])
                          .filter(Boolean);
        if (pts.length < 2) return;
        el("path", {d: "M" + pts.map(p => p[0] + "," + p[1]).join("L"),
                    fill: "none", "stroke-width": 2,
                    "stroke-linejoin": "round", "stroke-linecap": "round",
                    style: "stroke:" + colorOf(mat)}, svg);
      });
      [0, 6, 12].forEach(function(lag){
        const t = el("text", {x: xOf(lag), y: ty + plotH + 16,
                              "text-anchor": "middle", class: "muted"}, svg);
        t.textContent = lag + "m";
      });
      const hit = el("rect", {x: lx, y: ty, width: plotW, height: plotH,
                              fill: "transparent"}, svg);
      hit.addEventListener("pointermove", function(e){
        const box = svg.getBoundingClientRect();
        const lag = Math.max(0, Math.min(12,
          Math.round(((e.clientX - box.left) - lx) / plotW * 12)));
        const rows = [{text: ret + " · lag " + lag + "m"}];
        Object.keys(g).forEach(function(mat){
          if (!shown.includes(mat)) return;
          rows.push({text: mat + "  r=" + fmt(g[mat][lag]),
                     color: getComputedStyle(document.documentElement)
                            .getPropertyValue(SERIES[shown.indexOf(mat)])});
        });
        tipShow(e, rows);
      });
      hit.addEventListener("pointerleave", tipHide);
      row.appendChild(holder);
    });
  }
  tableTwin(sec, ["retailer", "material", "lag (m)", "adoption coef", "r", "n"],
    d.best.map(b => [b.retailer, b.material, b.lag_months, fmt(b.adoption_coef, 3),
                     fmt(b.r, 3), b.n_obs]));
}

/* ----------------------------- leaderboard ----------------------------- */
function renderLeaderboard(){
  const sec = section("sec-leaderboard", "Retailer adoption-speed leaderboard", null);
  const d = DATA.leaderboard;
  if (!d){ emptyState(sec, "07_signals.py"); return; }
  sec.querySelector("h2").appendChild(Object.assign(
    document.createElement("span"),
    {className: "badge", textContent: d.cadence + " · as of " + d.asof.slice(0, 10)}));
  const rows = d.rows;
  const barMax = 24, rowH = 26, left = 56, plotW = 300, right = 56;
  const scores = rows.map(r => Math.abs(r.score || 0));
  const smax = Math.max.apply(null, scores.concat([0.0001]));
  const W = left + plotW + right, H = rows.length * rowH + 8;
  const wrap = div("scroll", sec);
  const svg = el("svg", {width: W, height: H}, null);
  wrap.appendChild(svg);
  const x0 = left + plotW / 2;
  el("line", {x1: x0, x2: x0, y1: 0, y2: H - 6, stroke: "var(--axis)",
              "stroke-width": 1}, svg);
  rows.forEach(function(r, i){
    const y = i * rowH + 4, bh = Math.min(barMax, rowH - 8);
    const w = (Math.abs(r.score || 0) / smax) * (plotW / 2 - 6);
    const isPos = (r.score || 0) >= 0;
    const bx = isPos ? x0 : x0 - w;
    const bar = el("rect", {x: bx, y: y, width: Math.max(w, 1), height: bh,
                            rx: 4, style: "fill:" + (isPos ? "var(--pos)" : "var(--neg)")}, svg);
    const lab = el("text", {x: left - 8, y: y + bh / 2 + 4, "text-anchor": "end"}, svg);
    lab.textContent = r.ticker;
    const val = el("text", {x: isPos ? x0 + w + 6 : x0 - w - 6,
                            y: y + bh / 2 + 4,
                            "text-anchor": isPos ? "start" : "end",
                            class: "val"}, svg);
    val.textContent = fmt(r.score, 2);
    hover(bar, () => [
      {text: "score " + fmt(r.score, 3)},
      {text: r.name + " (" + r.ticker + ")"},
      {text: "rank " + r.rank + " · weight " + fmt(r.weight, 3)}]);
  });
  const fn = div("footnote", sec);
  fn.textContent = "Blue = converging to runway (long candidates), red = diverging (short candidates).";
  tableTwin(sec, ["ticker", "name", "score", "rank", "weight"],
    rows.map(r => [r.ticker, r.name, fmt(r.score, 3), r.rank, fmt(r.weight, 3)]));
}

/* -------------------------------- nowcast ------------------------------ */
function renderNowcast(){
  const sec = section("sec-nowcast", "Material-demand nowcast",
    "z-score of current downstream share vs trailing 12 months. |z| > 1 arms the supplier sleeve.");
  const d = DATA.nowcast;
  if (!d){ emptyState(sec, "07_signals.py"); return; }
  sec.querySelector("h2").appendChild(Object.assign(
    document.createElement("span"),
    {className: "badge", textContent: "as of " + d.asof.slice(0, 7)}));
  const rows = d.rows, rowH = 26, left = 76, plotW = 240, right = 90;
  const W = left + plotW + right, H = rows.length * rowH + 8;
  const wrap = div("scroll", sec);
  const svg = el("svg", {width: W, height: H}, null);
  wrap.appendChild(svg);
  const x0 = left + plotW / 2, zmax = 3;
  el("line", {x1: x0, x2: x0, y1: 0, y2: H - 6, stroke: "var(--axis)"}, svg);
  rows.forEach(function(r, i){
    const y = i * rowH + 5, bh = 14;
    el("rect", {x: left, y: y, width: plotW, height: bh, rx: 4,
                fill: "var(--mid)"}, svg);
    const z = Math.max(-zmax, Math.min(zmax, r.nowcast_z || 0));
    const w = Math.abs(z) / zmax * (plotW / 2);
    const bar = el("rect", {x: z >= 0 ? x0 : x0 - w, y: y, width: Math.max(w, 1),
                            height: bh, rx: 4,
                            style: "fill:" + (z >= 0 ? "var(--pos)" : "var(--neg)")}, svg);
    const lab = el("text", {x: left - 8, y: y + bh / 2 + 4, "text-anchor": "end"}, svg);
    lab.textContent = r.material;
    const val = el("text", {x: left + plotW + 8, y: y + bh / 2 + 4, class: "val"}, svg);
    val.textContent = fmt(r.nowcast_z, 2) + (r.direction !== "flat" ? " · " + r.direction : "");
    hover(bar, () => [
      {text: "z = " + fmt(r.nowcast_z, 2) + " (" + r.direction + ")"},
      {text: r.material},
      {text: r.tickers ? "suppliers: " + r.tickers : "no listed supplier mapping"}]);
  });
  tableTwin(sec, ["material", "z", "direction", "suppliers"],
    rows.map(r => [r.material, fmt(r.nowcast_z, 2), r.direction, r.tickers]));
}

/* ------------------------------- positions ----------------------------- */
function renderPositions(){
  const sec = section("sec-positions", "Current signal positions", null);
  const d = DATA.positions;
  if (!d){ emptyState(sec, "07_signals.py"); return; }
  makeTable(sec, ["sleeve", "ticker", "detail", "weight", "as of"],
    d.rows.map(r => [r.sleeve, r.ticker, r.detail, fmt(r.weight, 3),
                     String(r.asof).slice(0, 10)]));
}

/* -------------------------------- backtest ----------------------------- */
function renderBacktest(){
  const sec = section("sec-backtest", "Backtest — pre-registered runs",
    "Seasonal is the primary; monthly is robustness. Net of 20 bps/side, turnover-capped, local-index excess returns.");
  const d = DATA.backtest;
  if (!d){ emptyState(sec, "08_backtest.py"); return; }
  const meta = d.findings.meta || {};
  sec.querySelector("h2").appendChild(Object.assign(
    document.createElement("span"),
    {className: "badge",
     textContent: "dev window " + (meta.dev_window || []).join(" → ")}));
  const primary = (d.findings.h1 || {}).seasonal || {};
  const tiles = div("tiles", sec);
  [["Sharpe", fmt(primary.sharpe)], ["IR vs XRT", fmt(primary.ir)],
   ["Hit rate", primary.hit_rate == null ? "—" : pct(primary.hit_rate, 0)],
   ["CAR", primary.car == null ? "—" : pct(primary.car)],
   ["Max drawdown", primary.max_drawdown == null ? "—" : pct(primary.max_drawdown)]]
  .forEach(function(pair){
    const t = div("tile", tiles);
    div("lab", t).textContent = pair[0] + " (H1 seasonal)";
    const n = div("num" + (pair[1] === "—" ? " na" : ""), t);
    n.textContent = pair[1];
  });
  if (d.curves && Object.keys(d.curves).length){
    const strats = Object.keys(d.curves).slice(0, 8);
    legend(sec, strats.map((s, i) => ({label: s, color: cssv(SERIES[i])})), "line");
    const W = 1080, H = 240, lx = 46, rx = 12, ty = 8, by = 28;
    const plotW = W - lx - rx, plotH = H - ty - by;
    let lo = Infinity, hi = -Infinity, maxN = 0;
    strats.forEach(function(s){
      d.curves[s].equity.forEach(function(v){
        if (v < lo) lo = v; if (v > hi) hi = v;
      });
      maxN = Math.max(maxN, d.curves[s].equity.length);
    });
    if (lo === hi){ lo -= 0.01; hi += 0.01; }
    const wrap = div("scroll", sec);
    const svg = el("svg", {width: W, height: H}, null);
    wrap.appendChild(svg);
    const yOf = v => ty + (1 - (v - lo) / (hi - lo)) * plotH;
    [lo, 1, hi].forEach(function(v){
      if (v < lo || v > hi) return;
      el("line", {x1: lx, x2: lx + plotW, y1: yOf(v), y2: yOf(v),
                  stroke: "var(--grid)", "stroke-width": 1}, svg);
      const t = el("text", {x: lx - 6, y: yOf(v) + 4, "text-anchor": "end",
                            class: "muted"}, svg);
      t.textContent = fmt(v, 2);
    });
    const xall = d.curves[strats[0]].dates;
    strats.forEach(function(s, i){
      const c = d.curves[s];
      const n = c.equity.length;
      const pts = c.equity.map((v, k) =>
        [lx + (n === 1 ? 0 : k / (n - 1)) * plotW, yOf(v)]);
      el("path", {d: "M" + pts.map(p => fmt(p[0], 1) + "," + fmt(p[1], 1)).join("L"),
                  fill: "none", "stroke-width": 2, "stroke-linejoin": "round",
                  "stroke-linecap": "round", style: "stroke:" + cssv(SERIES[i])}, svg);
    });
    [0, Math.floor(xall.length / 2), xall.length - 1].forEach(function(k){
      if (k < 0 || !xall[k]) return;
      const t = el("text", {x: lx + (xall.length === 1 ? 0 : k / (xall.length - 1)) * plotW,
                            y: H - 8, "text-anchor": "middle", class: "muted"}, svg);
      t.textContent = String(xall[k]).slice(0, 10);
    });
    const cross = el("line", {y1: ty, y2: ty + plotH, stroke: "var(--axis)",
                              "stroke-width": 1, opacity: 0}, svg);
    const hit = el("rect", {x: lx, y: ty, width: plotW, height: plotH,
                            fill: "transparent"}, svg);
    hit.addEventListener("pointermove", function(e){
      const box = svg.getBoundingClientRect();
      const fx = Math.max(0, Math.min(1, (e.clientX - box.left - lx) / plotW));
      cross.setAttribute("x1", lx + fx * plotW);
      cross.setAttribute("x2", lx + fx * plotW);
      cross.setAttribute("opacity", 1);
      const rows = [];
      strats.forEach(function(s, i){
        const c = d.curves[s];
        const k = Math.round(fx * (c.equity.length - 1));
        if (!rows.length) rows.push({text: String(c.dates[k]).slice(0, 10)});
        rows.push({text: s + "  " + fmt(c.equity[k], 3),
                   color: getComputedStyle(document.documentElement)
                          .getPropertyValue(SERIES[i])});
      });
      tipShow(e, rows);
    });
    hit.addEventListener("pointerleave", function(){
      cross.setAttribute("opacity", 0); tipHide();
    });
  }
  const allRuns = [];
  ["h1", "h2"].forEach(function(root){
    const grp = d.findings[root] || {};
    Object.keys(grp).forEach(function(k){
      const m = grp[k];
      if (m && typeof m === "object")
        allRuns.push([root + "_" + k, fmt(m.sharpe), fmt(m.ir),
                      m.hit_rate == null ? "—" : pct(m.hit_rate, 0),
                      m.car == null ? "—" : pct(m.car),
                      m.max_drawdown == null ? "—" : pct(m.max_drawdown),
                      m.n_rebalances || m.status || ""]);
    });
  });
  makeTable(sec, ["run", "sharpe", "IR", "hit", "CAR", "maxDD", "n / status"], allRuns);
  const fn = div("footnote", sec);
  fn.textContent = "All pre-registered runs shown (objectivity charter — no cherry-picking). " +
    (meta.holdout_included ? "Holdout runs included and keyed separately." :
     "2024–2025 holdout locked until dev methodology is frozen in DECISIONS.md.");
}

/* -------------------------------- health ------------------------------- */
function renderHealth(){
  const sec = section("sec-health", "Pipeline data health", null);
  const d = DATA.health;
  const rows = d.files.map(function(f){
    return [f.label, f.ok ? "ok" : "missing", f.rows,
            f.latest || "—", f.script];
  });
  const wrap = div("scroll", sec);
  const t = document.createElement("table");
  const hr = document.createElement("tr");
  ["dataset", "status", "rows", "latest", "feeds from"].forEach(function(h){
    const th = document.createElement("th"); th.textContent = h; hr.appendChild(th);
  });
  t.appendChild(hr);
  rows.forEach(function(r){
    const tr = document.createElement("tr");
    r.forEach(function(cell, ci){
      const td = document.createElement("td");
      if (ci === 1){
        const st = div("status", td);
        const dot = div("dot", st);
        dot.style.background = cell === "ok" ? "var(--good)" : "var(--muted)";
        st.appendChild(document.createTextNode(cell === "ok" ? "✓ ok" : "– no data"));
      } else td.textContent = String(cell);
      tr.appendChild(td);
    });
    t.appendChild(tr);
  });
  wrap.appendChild(t);
  if (d.source_events.length){
    const dt = document.createElement("details");
    const s = document.createElement("summary");
    s.textContent = "Source/adapter events (" + d.source_events.length + ")";
    dt.appendChild(s);
    makeTable(dt, ["date", "retailer", "source", "event", "detail"],
      d.source_events.map(e => [e.date, e.retailer, e.source, e.event, e.detail]));
    sec.appendChild(dt);
  }
}

document.getElementById("meta").textContent =
  "Generated " + DATA.generated + " · static snapshot · rebuild with scripts/09_dashboard.py";
renderBacktest();
renderHeatmap();
renderLeaderboard();
renderNowcast();
renderPropagation();
renderPositions();
renderHealth();
</script>
</body>
</html>
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--open", action="store_true", dest="open_after",
                    help="open in default browser after build")
    args = ap.parse_args()

    lt.ensure_dirs()
    leaderboard = build_leaderboard()
    nowcast = build_nowcast()
    payload = {
        "generated": date.today().isoformat(),
        "runway_heatmap": build_runway_heatmap(),
        "propagation": build_propagation(),
        "leaderboard": leaderboard,
        "nowcast": nowcast,
        "positions": build_positions(leaderboard, nowcast),
        "backtest": build_backtest(),
        "health": build_health(),
    }
    blob = json.dumps(payload, default=str).replace("</", "<\\/")
    html = TEMPLATE.replace("__PAYLOAD__", blob)
    OUT.write_text(html, encoding="utf-8")
    # content-only copy for claude.ai Artifact publishing (host wraps it in
    # its own doctype/head/body); redeploy target URL is noted in CLAUDE.md
    title = re.search(r"<title>.*?</title>", html, re.S).group(0)
    styles = "\n".join(re.findall(r"<style>.*?</style>", html, re.S))
    body = re.search(r"<body[^>]*>(.*)</body>", html, re.S).group(1)
    (lt.DASHBOARD / "artifact.html").write_text(
        title + "\n" + styles + "\n" + body, encoding="utf-8")
    filled = sum(1 for k, v in payload.items()
                 if v and k not in ("generated", "health"))
    log.info("dashboard -> %s (%d/6 sections with data)", OUT, filled)
    if args.open_after:
        subprocess.run(["open", str(OUT)], check=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
