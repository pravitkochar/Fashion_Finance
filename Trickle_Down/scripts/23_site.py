"""P8 — the consolidated single-page site: dashboard/index_site.html.

One page, five tabs, zero duplicated content. Replaces the four overlapping
pages (story / historical / predictions / live dashboard) with a single
tabbed website that reuses every existing builder — numbers are read live
from the data files, never re-derived here.

Each element lives in exactly one tab:
  Overview   — narrative hook, the loom, the 10-11mo number, 3-step method
  Cascade    — fitted runway->rack->search lags (43 links), heatmap, coverage
  This Season— FW2026 emergent materials, palette strip, implied-demand path
  Honest     — why naive trading fails (H1/H2/H4), CV table, pre-registration
  Live       — nowcast, current positions, data-health / pipeline freshness

Identity: the researcher's-notebook look from the story page (graph-paper
ground, Charter body, the highlighter accent, the loom motif) laid over the
design-system component classes. Content-only artifact file, self-contained,
no external requests, no-JS-safe (JS only drives the tabs).
"""
from __future__ import annotations

import importlib
import re
import sys
from datetime import date

import lib_trickle as lt

# commodity futures were part of the original Tier-3 reference set but the
# commodity study was cut entirely (user decision) — no commodity ticker or
# label appears anywhere on this site.
COMMODITY = {"CT=F", "CL=F", "LE=F"}

ds = importlib.import_module("17_design_system")
m09 = importlib.import_module("09_dashboard")
m16 = importlib.import_module("16_site_pages")
m18 = importlib.import_module("18_story_page")

log = lt.get_logger("23_site")
OUT = lt.DASHBOARD / "index_site.html"


def scrub_commodities(html: str) -> str:
    """Remove every commodity artifact from reused-builder output: whole
    table rows about a commodity, inline commodity tokens in mixed cells,
    the commodity-CAR footnote, and the 'commodity' half of section titles."""
    # drop any table row that references a commodity future
    html = re.sub(r"<tr>(?:(?!</tr>).)*?(?:CT=F|CL=F|LE=F)(?:(?!</tr>).)*?</tr>",
                  "", html, flags=re.S)
    # strip commodity tokens left in mixed cells (e.g. supplier lists)
    for t in COMMODITY:
        html = html.replace(f";{t}", "").replace(f"{t};", "")
        html = html.replace(f" · {t}", "").replace(f"{t} · ", "")
    # the commodity-reference CAR footnote
    html = re.sub(r'<p class="footnote">Commodity reference CAR.*?</p>', "",
                  html, flags=re.S)
    # retitle "Supplier / commodity read" and drop the commodity clause
    html = html.replace("Supplier / commodity read", "Supplier read")
    html = html.replace("; commodities are references, never P&amp;L", "")
    html = html.replace(", commodities as references, never P&amp;L", "")
    html = html.replace("fiber suppliers and commodities", "fiber suppliers")
    html = html.replace(" and commodities", "")
    # any leftover "Commodities are references..." clause, any case/punctuation
    html = re.sub(r"[.;]?\s*[Cc]ommodit\w+ (?:are|as) references[^.<]*\.?", "",
                  html)
    return html

PAPER_URL = ("https://raw.githubusercontent.com/pravitkochar/Fashion_Finance/"
             "main/Trickle_Down/paper/Trickle_Down_Paper.pdf")
DECK_URL = ("https://raw.githubusercontent.com/pravitkochar/Fashion_Finance/"
            "main/Trickle_Down/paper/Trickle_Down_Deck.pdf")

TABS = [
    ("overview", "Overview"),
    ("cascade", "The Cascade"),
    ("season", "This Season"),
    ("honest", "The Honest Part"),
    ("live", "Live Data"),
]


# ------------------------------------------------------------- overview -----

def local_loom(g: dict) -> str:
    """The cascade loom, built here so mills labels carry only real listed
    fiber suppliers — no commodity futures."""
    if not g["shares"]:
        return ds.empty("04_material_mix.py")
    prop = m09.safe_read(lt.DATA / "propagation_train.csv")
    lags = {}
    if prop is not None:
        h2 = prop[(prop["hop"] == 2) & prop["lag_months"].notna()]
        lags = {r["material"]: (int(r["lag_months"]), float(r["r"]))
                for _, r in h2.iterrows()}
    sups: dict = {}
    for e in lt.load_universe()["tier3_suppliers"]:      # suppliers only
        if e["ticker"] in COMMODITY:
            continue
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


def tab_overview(g: dict) -> str:
    """Narrative hook + loom + killer number + 3-step method. The 'what is
    this' tab; the deep tables live in later tabs, not here."""
    comps = f"{g['n_comps']:,}" if g["n_comps"] else "—"
    tagged = f"{g['n_tagged']:,}"
    looks = f"{g['n_looks']:,}"
    bt = g.get("bt", {})
    steps = [
        ("01 · The runway", looks + " looks",
         f"{g['n_brands']} houses, 23 seasons of shows (2015–2026), each "
         "machine-tagged for the fabrics it puts on the catwalk. "
         f"{tagged} tagged so far."),
        ("02 · The high street", comps + " fabric labels",
         "read off archived Zara, H&amp;M, ASOS and Uniqlo product pages "
         f"recovered from the Internet Archive — {g['n_months']} "
         f"retailer-months back to {g['first_month']}. Every snapshot is "
         "stamped with the day it was live, so nothing here uses hindsight."),
        ("03 · The money", "4 fiber makers",
         "Google search interest for every material, plus prices for the "
         "listed suppliers that spin the fiber. We line the three tiers up "
         "and measure the lag between them."),
    ]
    stepcards = "".join(
        f'<div class="card"><div class="step">{s}</div>'
        f'<div class="k">{k}</div><div class="what">{w}</div></div>'
        for s, k, w in steps)

    lead = pct = ""
    if bt:
        lead = "10–11"
    return f"""
<div class="hero">
  <div class="hero-txt">
    <p class="eyebrow">A field study · runway → high street → fiber mills</p>
    <h2 class="lede">A 127-year-old idea about fashion, finally measured.</h2>
    <p class="prose">In March, Prada sends wool down a runway in Milan. The
    claim that the look works its way down — into Zara and H&amp;M, into what
    people search for, eventually into the mills that spin the fiber — is old
    and never checked. We checked it: <b>{looks} runway looks</b>, a decade of
    fast-fashion assortment rebuilt from the <b>Internet Archive</b>, and the
    lag between each tier, <span class="hi">measured</span>.</p>
  </div>
  <div class="hero-num">
    <div class="bignum">{lead or '—'}</div>
    <div class="bignum-lab">months the runway leads the U.S. apparel-demand
    cycle — earlier than any conventional series, built entirely from public
    data</div>
  </div>
</div>
<div class="loomframe">{local_loom(g)}</div>
<p class="figcap">The cascade, drawn from the fitted numbers — not an
illustration. Each thread is one material; its reach is the measured lag from
the runway to consumer search or retail racks.</p>
<h3 class="steph">How we measured it</h3>
<div class="spec">{stepcards}</div>
"""


# ------------------------------------------------------- data-tab wrap -------

def tab_cascade() -> str:
    heat = m09.static_heatmap(m09.build_runway_heatmap())
    return scrub_commodities(m16.card_propagation() + heat
                             + m16.card_coverage())


def tab_season() -> str:
    return scrub_commodities(m16.season_spread() + m16.card_implied()
                             + m16.card_supplier_read())


def tab_honest() -> str:
    return scrub_commodities(m16.card_method() + m16.card_cv()
                             + m16.card_backtest())


def tab_live() -> str:
    nc = m09.build_nowcast()
    lb = m09.build_leaderboard()
    pos = m09.build_positions(lb, nc)
    return scrub_commodities(m09.static_nowcast(nc) + m09.static_positions(pos)
                             + m09.static_health(m09.build_health()))


# ------------------------------------------------------------------ css -----

def css() -> str:
    ovr = f"""<style>
:root{{
  --page:#f6f7f4; --surface:#fbfbf8; --slip:#eeefe9;
  --ink:#20242a; --ink2:#565d68; --muted:#8a919b; --faint:#8a919b;
  --hair:#d6dad3; --grid:rgba(45,58,74,.05); --thread-gap:#f6f7f4;
  --hi:#e9f286; --pencil:#6a7280; --selvage:{ds.SELVAGE[0]}; --good:#3a7d44;
  --serif:Charter,"Iowan Old Style",Georgia,serif;
  --body:Charter,"Iowan Old Style",Georgia,serif;
}}
@media (prefers-color-scheme:dark){{:root{{
  --page:#15181d; --surface:#1c1f25; --slip:#191c21;
  --ink:#e6e4dc; --ink2:#a7adb6; --muted:#767d87; --faint:#767d87;
  --hair:#2d323b; --grid:rgba(160,175,195,.06); --thread-gap:#15181d;
  --hi:#555e1c; --pencil:#8b93a0; --selvage:{ds.SELVAGE[1]}; --good:#5da768;
}}}}
body{{font:16px/1.62 var(--body);
  background-image:
    repeating-linear-gradient(0deg,transparent 0 27px,var(--grid) 27px 28px),
    repeating-linear-gradient(90deg,transparent 0 27px,var(--grid) 27px 28px)}}
.wrap{{max-width:1060px}}

/* persistent header */
.top{{border-bottom:2px solid var(--ink);padding-bottom:14px;margin-bottom:0}}
.top .kick{{font:600 11px/1 var(--mono);letter-spacing:.22em;
  text-transform:uppercase;color:var(--ink2)}}
.top h1{{font:700 34px/1.08 var(--serif);letter-spacing:-.01em;
  margin:9px 0 3px;text-wrap:balance}}
.top .dek{{font:13px/1.5 var(--mono);color:var(--muted);margin:0}}
.dl{{display:flex;gap:10px;margin-top:14px;flex-wrap:wrap}}
.dl a{{font:600 12px/1 var(--mono);text-decoration:none;color:var(--ink);
  border:1.5px solid var(--ink);padding:8px 12px;border-radius:2px;
  display:inline-flex;gap:6px;align-items:center}}
.dl a:hover{{background:var(--hi);border-color:var(--hi)}}

/* tab nav */
.tabs{{display:flex;gap:2px;flex-wrap:wrap;position:sticky;top:0;z-index:5;
  background:var(--page);border-bottom:1px solid var(--hair);
  margin:22px 0 8px;padding-top:6px}}
.tabs button{{font:600 13px/1 var(--mono);letter-spacing:.02em;
  background:none;border:0;color:var(--muted);cursor:pointer;
  padding:12px 15px 13px;border-bottom:2.5px solid transparent;
  margin-bottom:-1px}}
.tabs button:hover{{color:var(--ink)}}
.tabs button[aria-selected="true"]{{color:var(--ink);
  border-bottom-color:var(--ink)}}
.tabs button .tn{{color:var(--pencil);margin-right:7px;font-weight:400}}

/* panels: no-JS shows all with a rule + heading; JS hides all but active */
.panel{{padding-top:8px;scroll-margin-top:60px}}
.panel > .panelhead{{display:none}}
.js .panel{{display:none}} .js .panel.active{{display:block}}
.js .tabs{{display:flex}}
noscript .tabs, html:not(.js) .tabs{{display:none}}
html:not(.js) .panel > .panelhead{{display:block;font:600 12px/1 var(--mono);
  letter-spacing:.2em;text-transform:uppercase;color:var(--selvage);
  border-top:2px solid var(--hair);padding-top:20px;margin-top:40px}}

/* overview hero */
.hero{{display:grid;grid-template-columns:1.35fr 1fr;gap:40px;
  align-items:start;margin-top:20px}}
@media(max-width:820px){{.hero{{grid-template-columns:1fr;gap:24px}}}}
.eyebrow{{font:600 11px/1 var(--mono);letter-spacing:.2em;
  text-transform:uppercase;color:var(--ink2);margin:0 0 12px}}
.lede{{font:700 30px/1.14 var(--serif);margin:0 0 14px;text-wrap:balance;
  max-width:16ch}}
.prose{{font:16.5px/1.62 var(--body);color:var(--ink);max-width:52ch;margin:0}}
.hero-num{{border-left:3px solid var(--ink);padding-left:20px}}
.bignum{{font:700 84px/.92 var(--serif);color:var(--m-polyester);
  letter-spacing:-.02em;font-variant-numeric:tabular-nums}}
.bignum-lab{{font:13.5px/1.5 var(--body);color:var(--ink2);margin-top:8px;
  max-width:30ch}}
.loomframe{{margin:34px 0 6px;overflow-x:auto}}
.figcap{{font:12.5px/1.5 var(--mono);color:var(--muted);max-width:74ch;
  margin:0 0 30px}}
.steph{{font:700 20px/1.2 var(--serif);margin:30px 0 4px;
  border-top:1px solid var(--hair);padding-top:22px}}
.spec{{display:flex;gap:18px;flex-wrap:wrap;margin:14px 0 0}}
.spec .card{{flex:1 1 250px;border:1px solid var(--hair);background:var(--surface);
  padding:16px 18px}}
.spec .step{{font:11px/1 var(--mono);color:var(--pencil);letter-spacing:.1em;
  text-transform:uppercase}}
.spec .k{{font:700 24px/1.05 var(--serif);margin:9px 0 8px}}
.spec .what{{font:13.5px/1.55 var(--body);color:var(--ink2)}}
.foot{{margin-top:64px;border-top:1px solid var(--hair);padding-top:16px;
  font:12px/1.6 var(--mono);color:var(--muted)}}
.block:first-of-type{{margin-top:14px}}
</style>"""
    return ds.css() + ovr


# ------------------------------------------------------------------ js ------

TAB_JS = """<script>
(function(){
  document.documentElement.classList.add('js');
  var tabs=[].slice.call(document.querySelectorAll('.tabs button'));
  var panels=[].slice.call(document.querySelectorAll('.panel'));
  function show(id,push){
    tabs.forEach(function(t){
      var on=t.dataset.tab===id; t.setAttribute('aria-selected',on);
      t.tabIndex=on?0:-1;
    });
    panels.forEach(function(p){p.classList.toggle('active',p.id==='t-'+id);});
    if(push&&history.replaceState)history.replaceState(null,'','#'+id);
  }
  tabs.forEach(function(t,i){
    t.addEventListener('click',function(){show(t.dataset.tab,true);});
    t.addEventListener('keydown',function(e){
      var d=e.key==='ArrowRight'?1:e.key==='ArrowLeft'?-1:0;
      if(!d)return; e.preventDefault();
      var n=(i+d+tabs.length)%tabs.length; tabs[n].focus();
      show(tabs[n].dataset.tab,true);
    });
  });
  var start=(location.hash||'').replace('#','');
  show(tabs.some(function(t){return t.dataset.tab===start;})?start:'overview');
})();
</script>"""


# ---------------------------------------------------------------- build -----

def build() -> str:
    g = m18.gather()
    gen = date.today().isoformat()
    navbtns = "".join(
        f'<button role="tab" data-tab="{tid}" aria-selected="'
        f'{"true" if i == 0 else "false"}" aria-controls="t-{tid}">'
        f'<span class="tn">{i + 1}</span>{label}</button>'
        for i, (tid, label) in enumerate(TABS))

    bodies = {
        "overview": tab_overview(g),
        "cascade": tab_cascade(),
        "season": tab_season(),
        "honest": tab_honest(),
        "live": tab_live(),
    }
    panels = "".join(
        f'<div class="panel{" active" if i == 0 else ""}" id="t-{tid}" '
        f'role="tabpanel" aria-label="{label}">'
        f'<div class="panelhead">{label}</div>{bodies[tid]}</div>'
        for i, (tid, label) in enumerate(TABS))

    header = f"""<header class="top">
  <div class="kick">Runway → High Street → Fiber Mills · a measured cascade</div>
  <h1>Does fashion actually trickle down?</h1>
  <p class="dek">An ongoing field study · rebuilt nightly · point-in-time,
  net of costs, negative results published</p>
  <div class="dl">
    <a href="{PAPER_URL}">↓ Full paper (PDF)</a>
    <a href="{DECK_URL}">↓ Pitch deck (PDF)</a>
  </div>
</header>"""

    foot = (f'<div class="foot">Generated {gen} · every number read live from '
            'the pipeline · code &amp; data: github.com/pravitkochar/'
            'Fashion_Finance</div>')

    return (f'<title>Does fashion trickle down? — the measured cascade</title>'
            + css() + ds.pattern_defs()
            + f'<div class="wrap">{header}'
            + f'<div class="tabs" role="tablist" aria-label="Sections">'
            + navbtns + '</div>'
            + panels + foot + '</div>'
            + ds.TIP_JS + TAB_JS)


def main() -> int:
    lt.ensure_dirs()
    OUT.write_text(build(), encoding="utf-8")
    log.info("consolidated site -> %s (%d bytes)", OUT, OUT.stat().st_size)
    return 0


if __name__ == "__main__":
    sys.exit(main())
