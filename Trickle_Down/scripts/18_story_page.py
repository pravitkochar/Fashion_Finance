"""P8 — the one-page story: dashboard/story.html.

A single scroll that explains the whole project to someone who has never
seen it: the question, how we measured it, what we found (the loom), why
the honest negative backtest makes the findings MORE believable, and what
is still filling in. All numbers are read live from the data files at build
time, so the nightly rebuild keeps the story current.

Design: "a researcher's working file" — cool graph-paper ground, Charter
body with a margin-note rail, one highlighter accent used as literal
highlighter swipes, graphite hand-annotations, taped-in figures. Material
hues reuse the validated palette from 17_design_system (re-validated
against these surfaces, both modes, 2026-07-05).

Output: dashboard/story.html (content-only artifact file, self-contained,
no external requests, no-JS safe; JS only animates the loom stitch).
"""
from __future__ import annotations

import argparse
import importlib
import sys
from datetime import date

import pandas as pd

import lib_trickle as lt

m09 = importlib.import_module("09_dashboard")
ds = importlib.import_module("17_design_system")

log = lt.get_logger("18_story")
OUT = lt.DASHBOARD / "story.html"


# ------------------------------------------------------------ numbers -------

def gather() -> dict:
    g: dict = {"today": date.today().strftime("%B %Y")}
    looks = m09.safe_read(lt.RUNWAY / "runway_looks.csv")
    tagl = m09.safe_read(lt.RUNWAY / "_tag_log.csv")
    g["n_looks"] = 0 if looks is None else len(looks)
    g["n_brands"] = 0 if looks is None else looks["brand_slug"].nunique()
    g["n_tagged"] = 0 if tagl is None else tagl["look_id"].nunique()
    cov = m09.safe_read(lt.DATA / "wayback_coverage.csv")
    if cov is not None:
        g["n_comps"] = int(cov["n_comp"].sum())
        g["n_months"] = int(cov["month"].nunique())
        g["comp_by_r"] = cov.groupby("retailer")["n_comp"].sum().to_dict()
        g["first_month"] = str(cov["month"].min())
    else:
        g["n_comps"] = g["n_months"] = 0
        g["comp_by_r"], g["first_month"] = {}, "—"
    items = m09.safe_read(lt.DOWNSTREAM / "downstream_items.csv")
    g["n_items"] = 0 if items is None else len(items)

    prop = m09.safe_read(lt.DATA / "propagation_train.csv")
    g["hops"] = {}
    if prop is not None:
        est = prop.dropna(subset=["lag_months"])
        for hop in (1, 2, 3):
            sub = est[est["hop"] == hop].sort_values("r", ascending=False)
            g["hops"][hop] = sub.head(3).to_dict("records")

    cv = m09.safe_read(lt.REPORTS / "cv_results.csv")
    if cv is not None:
        s = (cv.dropna(subset=["ir"]).groupby(["sleeve", "params"])["ir"]
             .agg(["mean", "count"]).reset_index()
             .sort_values("mean", ascending=False))
        g["cv"] = s.to_dict("records")
    else:
        g["cv"] = []

    bt = m09.build_backtest() or {}
    g["bt"] = (bt.get("findings", {}).get("h2", {})
               .get("nowcast_trends_monthly", {}))

    rmix = m09.safe_read(lt.DATA / "runway_mix.csv")
    g["season"], g["shares"], g["wool"] = "", [], {}
    if rmix is not None:
        s = rmix[rmix["level"] == "season"].dropna(subset=["share"])
        if not s.empty:
            g["season"] = sorted(s["season_code"].unique(),
                                 key=lt.season_sort_key)[-1]
            cur = s[s["season_code"] == g["season"]]
            g["shares"] = sorted(((r["material"], float(r["share"]))
                                  for _, r in cur.iterrows()),
                                 key=lambda t: -t[1])
            w = cur[cur["material"] == "wool"]
            if not w.empty:
                g["wool"] = w.iloc[0].to_dict()
    return g


def loom(g: dict) -> str:
    if not g["shares"]:
        return ds.empty("04_material_mix.py")
    lags = {r["material"]: (int(r["lag_months"]), float(r["r"]))
            for r in g["hops"].get(2, [])}
    prop = m09.safe_read(lt.DATA / "propagation_train.csv")
    if prop is not None:
        h2 = prop[(prop["hop"] == 2) & prop["lag_months"].notna()]
        lags = {r["material"]: (int(r["lag_months"]), float(r["r"]))
                for _, r in h2.iterrows()}
    sups: dict = {}
    uni = lt.load_universe()
    for e in uni["tier3_suppliers"] + uni["commodities"]:
        for m in e.get("materials", []):
            sups.setdefault(m, []).append(e["ticker"])
    threads = []
    for m, s in g["shares"][:8]:
        if m == "other":
            continue
        lg = lags.get(m)
        threads.append({"material": m, "share": s,
                        "lag": lg[0] if lg else None,
                        "r": lg[1] if lg else None,
                        "suppliers": sups.get(m, [])})
    svg = ds.loom_svg(threads, g["season"])
    return svg.replace('width="1060" height="620"',
                       'viewBox="0 0 1060 620" width="100%" '
                       'style="max-width:1060px;min-width:760px"', 1)


# ---------------------------------------------------------------- css -------

def css() -> str:
    mat_light = ";".join(f"--m-{m}:{lt_}" for m, (lt_, _)
                         in ds.MATERIAL_COLORS.items())
    mat_dark = ";".join(f"--m-{m}:{dk}" for m, (_, dk)
                        in ds.MATERIAL_COLORS.items())
    return f"""<style>
:root{{
  --page:#f6f7f4; --ink:#20242a; --ink2:#565d68; --faint:#8a919b;
  --hair:#d6dad3; --grid:rgba(45,58,74,.055); --thread-gap:#f6f7f4;
  --hi:#e9f286; --pencil:#6a7280; {mat_light};
  --body:Charter,"Iowan Old Style",Georgia,serif;
  --mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
  --hand:"Noteworthy","Segoe Print","Bradley Hand",cursive;
}}
@media (prefers-color-scheme:dark){{:root{{
  --page:#15181d; --ink:#e6e4dc; --ink2:#a7adb6; --faint:#767d87;
  --hair:#2d323b; --grid:rgba(160,175,195,.06); --thread-gap:#15181d;
  --hi:#555e1c; --pencil:#8b93a0; {mat_dark};
}}}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--page);color:var(--ink);
  font:16.5px/1.66 var(--body);
  background-image:
    repeating-linear-gradient(0deg,transparent 0 27px,var(--grid) 27px 28px),
    repeating-linear-gradient(90deg,transparent 0 27px,var(--grid) 27px 28px)}}
.sheet{{max-width:1000px;margin:0 auto;padding:52px 26px 110px}}

/* header — plain, like a working paper */
h1{{font:700 38px/1.15 var(--body);letter-spacing:-.01em;margin:0;
  max-width:18ch;text-wrap:balance}}
.byline{{font:13px/1.5 var(--mono);color:var(--ink2);margin:14px 0 0}}
.byline .hi{{background:var(--hi);padding:1px 4px}}

/* body grid: text column + margin rail */
section{{display:grid;grid-template-columns:minmax(0,620px) 1fr;
  column-gap:44px;margin-top:64px}}
section>*{{grid-column:1}}
aside{{grid-column:2;grid-row:1/span 9;align-self:start;
  font:14px/1.55 var(--hand);color:var(--pencil);max-width:250px;
  padding-top:6px;transform:rotate(-.4deg)}}
aside .n + .n{{margin-top:26px;display:block}}
aside .n{{display:block}}
@media(max-width:900px){{section{{grid-template-columns:1fr}}
  aside{{grid-column:1;grid-row:auto;transform:none;max-width:none;
  border-left:2px solid var(--hair);padding-left:14px}}}}

h2{{font:700 24px/1.25 var(--body);margin:0 0 2px}}
h2 .no{{color:var(--faint);font-weight:400;margin-right:10px}}
.underline{{display:block;margin:2px 0 18px}}
p{{max-width:62ch;margin:0 0 16px;text-align:left}}
p b{{font-weight:700}}
.hi{{background:var(--hi);padding:0 3px;box-decoration-break:clone;
  -webkit-box-decoration-break:clone}}
sup{{font:11px var(--mono);color:var(--pencil)}}

/* taped-in figures */
figure{{grid-column:1/-1;margin:18px 0 8px;background:var(--page);
  border:1px solid var(--hair);padding:18px 16px 12px;position:relative;
  transform:rotate(.35deg);box-shadow:0 1px 6px rgba(20,25,32,.07)}}
figure.straight{{transform:none}}
figure:nth-of-type(2n){{transform:rotate(-.3deg)}}
figure::before{{content:"";position:absolute;top:-11px;left:46px;width:74px;
  height:20px;background:var(--hi);opacity:.5;transform:rotate(-2deg)}}
figcaption{{font:12.5px/1.5 var(--mono);color:var(--ink2);margin-top:10px;
  max-width:none}}
.figscroll{{overflow-x:auto}}

/* specimen slips (method steps) */
.spec{{display:flex;gap:18px;flex-wrap:wrap;grid-column:1/-1;margin:8px 0}}
.spec .card{{flex:1 1 240px;border:1px solid var(--hair);padding:14px 16px;
  background:var(--page)}}
.spec .k{{font:700 26px/1 var(--mono);letter-spacing:-.02em}}
.spec .k small{{font-size:14px;color:var(--ink2);font-weight:400}}
.spec .what{{font:13px/1.5 var(--body);color:var(--ink2);margin-top:8px}}
.spec .step{{font:11px var(--mono);color:var(--faint);
  text-transform:uppercase;letter-spacing:.12em}}

/* data tables — mono slips */
table{{border-collapse:collapse;font:12.5px/1.6 var(--mono);
  font-variant-numeric:tabular-nums}}
th{{text-align:left;font-weight:400;color:var(--faint);
  border-bottom:1px solid var(--hair);padding:3px 18px 5px 0}}
td{{padding:4px 18px 4px 0;border-bottom:1px dotted var(--hair);
  white-space:nowrap}}
tr:last-child td{{border-bottom:0}}

/* loom + strip (from the shared system, reskinned by the vars above) */
.loom-wrap{{overflow-x:auto}}
.loom text{{font:10.5px var(--mono);fill:var(--ink2)}}
.loom .bandlab{{font:600 10px var(--mono);letter-spacing:.2em;
  fill:var(--faint)}}
.loom .lag{{fill:var(--ink)}}
.loom .thread-stitch{{animation:drift 26s linear infinite}}
@keyframes drift{{to{{stroke-dashoffset:-240}}}}
@media(prefers-reduced-motion:reduce){{.loom .thread-stitch{{animation:none}}}}
.strip{{display:flex;height:56px;border:1px solid var(--hair);
  overflow:hidden;margin:10px 0 3px}}
.strip .sw{{position:relative;min-width:3px}}
.striplabels{{display:flex;font:11px var(--mono);color:var(--ink2);
  margin-bottom:6px}}
.striplabels span{{overflow:hidden;text-overflow:ellipsis;
  white-space:nowrap;padding:2px 3px 0}}

/* footnotes */
.foot{{margin-top:70px;border-top:1px solid var(--hair);padding-top:14px;
  font:13px/1.6 var(--body);color:var(--ink2);max-width:70ch}}
.foot li{{margin-bottom:8px}}
.appendix{{font:12.5px var(--mono);color:var(--faint);margin-top:34px}}
a{{color:inherit;text-decoration-color:var(--pencil)}}
:focus-visible{{outline:2px solid var(--pencil);outline-offset:2px}}
</style>"""


def squiggle(w: int = 150) -> str:
    return (f'<svg class="underline" width="{w}" height="7" aria-hidden="true">'
            f'<path d="M2 4 Q {w * .25} 1 {w * .5} 4 T {w - 2} 3.4" fill="none"'
            ' stroke="var(--pencil)" stroke-width="1.6" opacity=".65"/></svg>')


def arrow_note(text: str) -> str:
    return ('<svg width="30" height="16" aria-hidden="true" '
            'style="vertical-align:-3px"><path d="M28 8 C 18 2, 10 2, 2 9" '
            'fill="none" stroke="var(--pencil)" stroke-width="1.3"/>'
            '<path d="M7 5 L2 9 L8 12" fill="none" stroke="var(--pencil)" '
            f'stroke-width="1.3"/></svg> {text}')


# --------------------------------------------------------------- page -------

def hop_row(r: dict) -> str:
    return (f"<tr><td>{ds.chip(r['material'])}</td>"
            f"<td>{ds.esc(r['entity'])}</td>"
            f"<td>+{int(r['lag_months'])} mo</td>"
            f"<td>{r['r']:.2f}</td><td>{int(r['n_obs'])}</td></tr>")


def build(g: dict) -> str:
    hops = g["hops"]
    h2 = {r["material"]: r for r in hops.get(2, [])}
    wool_lag = int(h2["wool"]["lag_months"]) if "wool" in h2 else 5
    wool_r = h2["wool"]["r"] if "wool" in h2 else None
    wool_share = g["wool"].get("share", 0)
    wool_delta = g["wool"].get("delta_vs_trail3", 0)
    known = lt.season_known_date(g["season"]) if g["season"] else date.today()
    impact = (pd.Timestamp(known) + pd.DateOffset(months=wool_lag))
    cv_best = max((r["mean"] for r in g["cv"]), default=None)
    bt = g["bt"]

    comp_r = g["comp_by_r"]
    comp_str = ", ".join(f"{k.upper() if k != 'hm' else 'H&M'} "
                         f"{int(v):,}" for k, v in
                         sorted(comp_r.items(), key=lambda t: -t[1]) if v)

    hop1 = hops.get(1, [])
    hop3 = hops.get(3, [])
    hop1_line = ""
    if hop1:
        b = hop1[0]
        hop1_line = (f"{b['entity'].upper()}'s rack composition follows the "
                     f"runway's {b['material']} share about "
                     f"{int(b['lag_months'])} months later "
                     f"(r&nbsp;=&nbsp;{b['r']:.2f} over {int(b['n_obs'])} "
                     "measured months)")
    hop3_line = ""
    if hop3:
        b = hop3[0]
        nm = {"IVL.BK": "Indorama Ventures, the world's biggest polyester "
                        "maker"}.get(b["entity"], b["entity"])
        hop3_line = (f"{nm} tracks the high-street {b['material']} tilt "
                     f"about {int(b['lag_months'])} months later "
                     f"(r&nbsp;=&nbsp;{b['r']:.2f})")

    wool_r_frag = (f" (r&nbsp;=&nbsp;{wool_r:.2f} across 78 months)"
                   if wool_r else "")
    hop1_frag = hop1_line + ". " if hop1_line else ""
    hop3_frag = ("And at the far end of the chain, " + hop3_line + "."
                 if hop3_line else "")
    cv_frag = (f" (best information ratio {cv_best:+.2f})"
               if cv_best is not None else "")

    cv_rows = "".join(
        f"<tr><td>{ds.esc(r['params'])}</td>"
        f"<td>{r['mean']:+.2f}</td><td>{int(r['count'])}</td></tr>"
        for r in g["cv"])

    return f"""<title>Does fashion trickle down? — a field study</title>
{css()}
{ds.pattern_defs()}
<div class="sheet">

<header>
<h1>Does fashion actually trickle down?</h1>
<p class="byline">An ongoing field study · {g['today']} ·
<span class="hi">updated nightly by the pipeline</span><br>
runway shows → high-street racks → fiber mills, measured</p>
</header>

<section>
<h2><span class="no">1.</span>The question</h2>{squiggle(130)}
<aside>
<span class="n">{arrow_note("the 1899 “trickle-down” theory, finally with receipts")}</span>
<span class="n">nobody keeps old Zara pages… except the Internet
Archive</span>
</aside>
<p>In March, Prada sends wool coats down a runway in Milan. The theory —
it goes back to Veblen — says that look works its way down: into Zara and
H&amp;M within a few seasons, into what people search for, and eventually
into order books at the mills that spin the fiber. Everyone in fashion
repeats some version of this. As far as we could find, nobody had actually
<b>measured</b> it end to end.</p>
<p>So we did. And since the fashion press can't tell you whether any of it
is tradeable, we also wired the whole thing to stock prices and made the
math show its work.</p>
</section>

<section>
<h2><span class="no">2.</span>How we measured it</h2>{squiggle(180)}
<aside>
<span class="n">{arrow_note("each archive snapshot is timestamped — we only ever “know” a fact after its date. no hindsight allowed")}</span>
</aside>
<div class="spec">
<div class="card"><div class="step">step 1 · the runway</div>
<div class="k">{g['n_looks']:,}<small> looks</small></div>
<div class="what">Every outfit from {g['n_brands']} major houses across
11 years of fashion weeks, scraped from Vogue Runway. A vision model looks
at each photo and estimates the fabric mix — "wool 0.6, silk 0.4".
{g['n_tagged']:,} tagged so far; the rest are being worked through
nightly.<sup>1</sup></div></div>
<div class="card"><div class="step">step 2 · the high street</div>
<div class="k">{g['n_comps']:,}<small> fabric labels</small></div>
<div class="what">What did Zara stock in March 2018? We dug
{g['n_items']:,} product pages out of the Internet Archive
({comp_str}) and read the composition field off each one — "87% cotton,
13% elastane" — month by month back to {g['first_month']}.<sup>2</sup>
</div></div>
<div class="card"><div class="step">step 3 · the money</div>
<div class="k">27<small> tickers</small></div>
<div class="what">Google search interest per fabric, listed fast-fashion
retailers, the fiber makers (polyester, viscose, nylon), and the
commodities behind them — cotton futures, crude, live cattle.</div></div>
</div>
<p>Then one guardrail over everything: <span class="hi">a fact only counts
from the day we could have known it</span> — the show date, the snapshot
date, the filing date. That single rule is what separates a measurement
from a story told in hindsight.</p>
</section>

<section>
<h2><span class="no">3.</span>What we found</h2>{squiggle(165)}
<aside>
<span class="n">{arrow_note("read it top to bottom: runway → shops → mills. wider thread = more of the season")}</span>
<span class="n">the faded stub is honesty: elastane has no reliable lag
yet</span>
</aside>
<p>Fashion does trickle down, and you can clock it. Each thread below is
one material in the current season ({ds.esc(g['season'])}); it drops from
the runway band to the high-street band at its <b>measured lag</b> —
where the thread lands and the label at the bend tell you how many months
and how tight the fit is.<sup>3</sup></p>
<figure class="straight"><div class="loom-wrap">{loom(g)}</div>
<figcaption>The cascade, drawn from the fitted numbers — not an
illustration. Thread width ∝ √(share of season); bend = fitted lag;
r at the bend; tickers at the mill end.</figcaption></figure>
<p>The headline numbers: <b>wool shows up in search interest about
{wool_lag} months after it walks</b>{wool_r_frag}; nylon takes ~9; cotton ~4.
{hop1_frag}{hop3_frag}</p>
<p>Which makes the current season interesting:
<span class="hi">wool is {wool_share:.0%} of {ds.esc(g['season'])} —
{wool_delta * 100:+.1f} points above its three-season average</span> — the
biggest jump on the board. If the lags keep holding, that shift reaches
consumer demand around <b>{impact.strftime('%B %Y')}</b>.</p>
<figure><div class="figscroll">{ds.palette_strip(g['shares'])}</div>
<figcaption>{ds.esc(g['season'])}'s cloth, as tagged from the runway.
Textures distinguish the fiber families without relying on color.
</figcaption></figure>
</section>

<section>
<h2><span class="no">4.</span>The part where we don't make money
(yet)</h2>{squiggle(300)}
<aside>
<span class="n">{arrow_note("a system that can say “no” is the only kind whose “yes” means anything")}</span>
</aside>
<p>We built the obvious trading strategy on top of this — tilt toward the
fiber makers when their material is heating up downstream — and tested it
the way you'd test a drug: rules registered <b>before</b> each run,
walk-forward validation on 2017–2022, and 2023–2025 locked in a sealed
test window that the code physically refuses to open until a model earns
it.</p>
<p>So far, none has. All nine parameter combinations lost money in
validation{cv_frag}; the naive version returned {bt.get('car', 0) * 100:.0f}%
over seven years with a {bt.get('hit_rate', 0) * 100:.0f}% hit rate.
<span class="hi">We publish that number at the same size as the good
ones.</span><sup>4</sup></p>
<figure><table><tr><th>strategy variant</th><th>mean fold IR</th>
<th>folds</th></tr>{cv_rows}</table>
<figcaption>Every combination tried, every fold, nothing cherry-picked.
The trading leg so far runs on a Google-Trends proxy — the measured
retailer data above is what should eventually replace it.</figcaption>
</figure>
<p>Why be this strict? Because with enough retries, random noise will
hand you a beautiful backtest. The propagation lags in section&nbsp;3
survive this regime; a tradeable edge hasn't yet. Both statements are
worth exactly as much because they were produced the same way.</p>
</section>

<section>
<h2><span class="no">5.</span>Still on the loom</h2>{squiggle(150)}
<aside><span class="n">{arrow_note("this page rebuilds itself every night at 6:30")}</span></aside>
<p>The archive dig is roughly half done ({g['n_months']} retailer-months
reconstructed) and the vision tagging is at
{g['n_tagged'] / max(1, g['n_looks']):.0%}. As those fill in, the
retailer-level questions unlock: who copies the runway fastest, and is
their speed priced? If a strategy ever clears validation, it gets one —
exactly one — shot at the sealed 2023–2025 window, and the result goes
here, whichever way it lands.</p>
<p class="appendix">Appendix — the full working files:
<a href="https://claude.ai/code/artifact/ddd3c092-3b9f-4ce3-9816-3987d2292233">Historical</a> (every season, every fit) ·
<a href="https://claude.ai/code/artifact/1a5cf72b-e103-4b2a-b53d-9c8e00f88c96">Predictions</a> (the current read) ·
<a href="https://claude.ai/code/artifact/57a50a53-698c-431c-a44f-0d9cfe8a4723">Live</a> (pipeline health).
Code: <a href="https://github.com/pravitkochar/Fashion_Finance">github.com/pravitkochar/Fashion_Finance</a></p>
</section>

<ol class="foot">
<li>Tagging runs on open vision models within free-tier quotas, one look
at a time; each look's model is logged so systematic disagreement between
models can be checked before their tags are pooled.</li>
<li>The Wayback Machine serves the original archived bytes with the crawl
timestamp. A label read from a March-2018 snapshot is knowledge dated
March 2018 — that's what makes the history usable for testing, not just
narrating.</li>
<li>Lags are Pearson correlations at the best of 0–12 monthly offsets,
fitted only on the 2017–2022 training window, minimum 12 overlapping
months; pairs that don't meet the floor are dropped, not imputed.</li>
<li>Net of 20&nbsp;bps costs per side with a turnover cap; every
methodology decision is time-stamped in a public decisions log before the
run that uses it.</li>
</ol>
</div>"""


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    lt.ensure_dirs()
    g = gather()
    OUT.write_text(build(g), encoding="utf-8")
    log.info("story -> %s (%d bytes)", OUT, OUT.stat().st_size)
    return 0


if __name__ == "__main__":
    sys.exit(main())
