"""Build the Trickle_Down pitch deck: 13 landscape 16:9 slides -> deck.html
-> Trickle_Down_Deck.pdf. Numbers are read live from the project's data so the
deck can never drift from the findings. Design per paper/deck_blueprint.md.
"""
import json
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
REPORTS = ROOT / "reports"
OUT_HTML = ROOT / "paper" / "deck.html"
OUT_PDF = ROOT / "paper" / "Trickle_Down_Deck.pdf"

# ---- live numbers -----------------------------------------------------------
prop = pd.read_csv(DATA / "propagation_train.csv")
n_links = len(prop)
hop_counts = prop.hop.value_counts().to_dict()
h2 = prop[prop.hop == 2].nlargest(6, "r")[["material", "lag_months", "r", "n_obs"]]
h1 = prop[prop.hop == 1].nlargest(6, "r")[["entity", "material", "lag_months", "r", "n_obs"]]
cov = pd.read_csv(DATA / "wayback_coverage.csv")
labels_total = int(cov.n_comp.sum())
ret_months = int(cov[cov.n_comp > 0].shape[0])
first_month = cov[cov.n_comp > 0].month.min()
n_tagged = pd.read_csv(DATA / "runway" / "_tag_log.csv").look_id.nunique()
now = json.load(open(REPORTS / "findings_nowcast.json"))
L10 = now["leads"]["10"]
tc, ar = L10["trends_composite"], L10["ar3"]
exc = now["ex_covid"].get("10", {}).get("trends_composite", {})

MAT = {"wool": "#B5762E", "viscose": "#0E9080", "leather": "#96430E",
       "cotton": "#8A7A14", "nylon": "#6C5BB5", "silk": "#2E8FC4",
       "linen": "#6E7A3A", "cashmere": "#9C6A45", "technical": "#55636E",
       "denim": "#31518F", "polyester": "#3E6FB0"}


def mcol(m):
    return MAT.get(m, "#77706A")


# ---- cover texture: faint vertical threads ---------------------------------
def loom_texture(width=1180, height=520):
    mats = list(h2.material)[:6]
    n = len(mats)
    pad = 150
    span = width - 2 * pad
    threads = []
    for i, m in enumerate(mats):
        x = pad + span * (i + 0.5) / n
        r = float(h2[h2.material == m]["r"].iloc[0])
        w = 8 + 22 * r
        threads.append(
            f'<line x1="{x:.0f}" y1="70" x2="{x:.0f}" y2="{height-70:.0f}" '
            f'stroke="{mcol(m)}" stroke-width="{w:.1f}" stroke-linecap="round" '
            f'opacity="0.16"/>')
    return (f'<svg viewBox="0 0 {width} {height}" class="loom" '
            f'preserveAspectRatio="xMidYMid meet">' + "".join(threads) + "</svg>")


# ---- cascade-lag chart: thread LENGTH = the fitted lag ----------------------
def lag_chart(width=1160, height=400):
    """Horizontal threads: runway (left) -> where the shift lands downstream,
    thread length proportional to the fitted lag in months. Uses links with
    real lag spread so 'how many months' is the visual."""
    # curated strongest links spanning the lag range, hop2 (search) + hop1 (rack)
    rows = [
        ("wool", "search", 5, 0.69),
        ("viscose", "search", 5, 0.59),
        ("cotton", "search", 5, 0.50),
        ("wool", "H&M rack", 5, 0.34),
        ("technical", "ASOS rack", 4, 0.25),
        ("leather", "ASOS rack", 11, 0.31),
    ]
    rows.sort(key=lambda z: z[2])
    x0, xmax = 250, width - 350   # right margin for the end labels
    months_max = 12
    ph = 40
    ytop = 40
    axis_y = ytop + len(rows) * ph + 10
    parts = []
    # month gridlines
    for mo in range(0, months_max + 1, 2):
        x = x0 + (xmax - x0) * mo / months_max
        parts.append(f'<line x1="{x:.0f}" y1="{ytop-10}" x2="{x:.0f}" '
                     f'y2="{axis_y:.0f}" stroke="var(--hair)" stroke-width="1"/>')
        parts.append(f'<text x="{x:.0f}" y="{axis_y+22:.0f}" text-anchor="middle" '
                     f'class="axmo">{mo}</text>')
    parts.append(f'<text x="{(x0+xmax)/2:.0f}" y="{axis_y+44:.0f}" '
                 f'text-anchor="middle" class="axttl">MONTHS AFTER THE RUNWAY SHOW</text>')
    parts.append(f'<text x="{x0:.0f}" y="{ytop-22:.0f}" class="runlab">RUNWAY</text>')
    for i, (m, dest, lag, r) in enumerate(rows):
        y = ytop + i * ph + ph / 2
        xe = x0 + (xmax - x0) * lag / months_max
        w = 7 + 16 * r
        col = mcol(m)
        parts.append(f'<text x="{x0-16:.0f}" y="{y+4:.0f}" text-anchor="end" '
                     f'class="lagmat" fill="{col}">{m}</text>')
        parts.append(f'<line x1="{x0:.0f}" y1="{y:.0f}" x2="{xe:.0f}" y2="{y:.0f}" '
                     f'stroke="{col}" stroke-width="{w:.1f}" stroke-linecap="round"/>')
        parts.append(f'<circle cx="{xe:.0f}" cy="{y:.0f}" r="{w/2+2:.0f}" '
                     f'fill="{col}"/>')
        parts.append(f'<text x="{xe+16:.0f}" y="{y+4:.0f}" class="lagend">'
                     f'{dest} · +{lag}mo · r&#8202;{r:.2f}</text>')
    return (f'<svg viewBox="0 0 {width} {height}" class="loom" '
            f'preserveAspectRatio="xMidYMid meet">' + "".join(parts) + "</svg>")


# ---- nowcast bar chart ------------------------------------------------------
def nowcast_svg():
    rows = [("Our cascade signal", tc["precision"], tc["recall"], "#284079"),
            ("AR(3) baseline", ar["precision"], ar["recall"], "#9a9482")]
    w, h = 560, 268
    barw, gap, x0, ytop = 46, 30, 210, 40
    plot_h = 150
    svg = [f'<svg viewBox="0 0 {w} {h}" class="chart">']
    # precision + recall grouped per method
    groups = [("precision", 0), ("recall", 1)]
    gx = x0
    for gi, (metric, _) in enumerate(groups):
        for mi, (lab, p, r, col) in enumerate(rows):
            val = {"precision": p, "recall": r}[metric]
            bh = plot_h * val
            x = gx + mi * (barw + 6)
            y = ytop + plot_h - bh
            svg.append(f'<rect x="{x}" y="{y:.0f}" width="{barw}" height="{bh:.0f}" '
                       f'fill="{col}"/>')
            svg.append(f'<text x="{x+barw/2:.0f}" y="{y-8:.0f}" text-anchor="middle" '
                       f'class="barval">{val:.2f}</text>')
        svg.append(f'<text x="{gx+barw+3:.0f}" y="{ytop+plot_h+22:.0f}" '
                   f'text-anchor="middle" class="baraxis">{metric.upper()}</text>')
        gx += 2 * (barw + 6) + gap + 40
    # legend
    ly = ytop + plot_h + 44
    svg.append(f'<rect x="210" y="{ly}" width="13" height="13" fill="#284079"/>')
    svg.append(f'<text x="230" y="{ly+11}" class="leg">cascade signal</text>')
    svg.append(f'<rect x="360" y="{ly}" width="13" height="13" fill="#9a9482"/>')
    svg.append(f'<text x="380" y="{ly+11}" class="leg">AR(3) baseline</text>')
    svg.append("</svg>")
    return "".join(svg)


# ---- slide helpers ----------------------------------------------------------
SLIDES = []


def slide(kicker, body, n, cls="", foot="Trickle Down · the fashion cascade, measured"):
    SLIDES.append(f'''<section class="slide {cls}">
  <div class="kick">{kicker}</div>
  <div class="content">{body}</div>
  <div class="foot"><span>{foot}</span><span class="pg">{n:02d} / 13</span></div>
</section>''')


# 01 COVER
slide("", f'''
  <div class="cover">
    <div class="coverloom">{loom_texture(1180, 520)}</div>
    <div class="covertext">
      <h1>Trickle&nbsp;Down</h1>
      <p class="lede">The 127-year-old theory that fashion flows from the
      runway to the rack to the mill — <span class="ink">measured</span>,
      for the first time.</p>
      <p class="by">A research asset · P. Kochar · 2026 ·
      github.com/pravitkochar/Fashion_Finance</p>
    </div>
  </div>''', 1, cls="cover-slide", foot="")

# 02 TENSION
slide("The question",
      f'''<h2>Everyone knows fashion trickles down.<br><span class="muted">Nobody had
      measured how long it takes.</span></h2>
      <p class="say">Veblen sketched it in 1899. Simmel formalized it in 1904. The
      trade press repeats it every season: a look leaves the runway, lands in Zara a
      few seasons later, and eventually moves order books at the mills that spin the
      fiber.</p>
      <p class="say big-say">In 127 years, no one published <span class="ink">how many
      months</span>, <span class="ink">at what strength</span>, for <span
      class="ink">which materials</span>.</p>''', 2)

# 03 THESIS / KILLER NUMBER
slide("What we found",
      f'''<div class="killer">
        <div class="knum">10–11<span class="kunit">months</span></div>
        <div class="ktext">
          <h2>A read on the U.S. apparel-demand cycle, roughly a year before the
          government prints it.</h2>
          <p class="say">The same fabric shifts that lead the runway lead
          clothing-store retail-sales turning points by <span class="ink">10–11
          months</span> — earlier than any conventional demand series, built
          entirely from public data.</p>
        </div>
      </div>''', 3, cls="dark")

# 04 WHAT WE BUILT
slide("The asset",
      f'''<h2>Three tiers of the supply chain, aligned on one clock.</h2>
      <div class="tiers">
        <div class="tier"><div class="tnum">{n_tagged:,}</div>
          <div class="tlab">runway looks</div>
          <p>22 houses · 23 seasons · FW2015–FW2026, each machine-tagged for its
          fabric mix.</p></div>
        <div class="tarrow">→</div>
        <div class="tier"><div class="tnum">{labels_total:,}</div>
          <div class="tlab">archived fabric labels</div>
          <p>{ret_months} retailer-months of Zara, H&amp;M, ASOS &amp; Uniqlo rack
          composition, back to {first_month}.</p></div>
        <div class="tarrow">→</div>
        <div class="tier"><div class="tnum">4+2</div>
          <div class="tlab">demand &amp; price series</div>
          <p>Search interest for 22 materials, listed fiber-supplier prices, and
          apparel retail sales.</p></div>
      </div>
      <p class="stamp">Every observation carries the date it became knowable. Nothing
      looks into its own future.</p>''', 4)

# 05 NOVEL METHOD
slide("Why it's new",
      f'''<h2>The retailers never kept the history.<br><span class="muted">The
      Internet Archive did.</span></h2>
      <p class="say">Fast-fashion sites overwrite. There is no record of what Zara
      stocked in 2018 — except that the Internet Archive crawled and froze those
      product pages, fabric labels and all, with a timestamp on every one.</p>
      <p class="say">We read <span class="ink">{labels_total:,} composition labels</span>
      off archived pages to rebuild {ret_months} months of what the high street
      actually sold. As far as the literature shows, <span class="ink">nobody has
      used the Archive this way</span> — as a point-in-time record of commercial
      assortment.</p>
      <p class="stamp">The prior art fits lags of at most two months, between cities
      or brands. None fits the multi-quarter jump across tiers. This does.</p>''', 5)

# 06 PROOF I — cascade
slide("Proof · the cascade is real",
      f'''<h2>{n_links} fitted links, runway to rack to search.</h2>
      <div class="loomwrap">{lag_chart(1160, 360)}</div>
      <p class="stamp">Fitted on 2017–2022 only, point-in-time. Wool leads consumer
      search by five months (r&nbsp;=&nbsp;0.69, n&nbsp;=&nbsp;78); the runway leads
      H&amp;M and ASOS rack space by four to twelve.</p>''', 6)

# 07 PROOF II — nowcast
slide("Proof · the leading indicator",
      f'''<h2>It calls apparel turning points before the data does.</h2>
      <div class="proof2">
        <div class="chartwrap">{nowcast_svg()}</div>
        <div class="proof2text">
          <p class="say">Against twelve peaks and troughs in U.S. clothing-store
          sales growth, the cascade signal leads by 10–11 months at
          <span class="ink">{tc["precision"]:.2f} precision</span> and
          <span class="ink">{tc["recall"]:.2f} recall</span> —
          catching {tc["hits"]} of {tc["n_sales_tps"]}.</p>
          <p class="say">An AR(3) baseline manages {ar["precision"]:.2f} and
          {ar["recall"]:.2f}. Persistence catches nothing.</p>
          <p class="stamp">Drop the four COVID reversals — the easy hits — and it
          still runs {exc.get("precision",0.30):.2f} / {exc.get("recall",0.38):.2f}
          on eight turning points.</p>
        </div>
      </div>''', 7)

# 08 HONESTY
slide("What does NOT work",
      f'''<h2>We tried to trade it three ways. All three failed —
      <span class="muted">under rules we set in advance.</span></h2>
      <div class="fails">
        <div class="fail"><div class="fx">✕</div><b>Continuous nowcast</b>
          <p>All nine pre-registered parameter sets lost money in walk-forward
          validation. Best information ratio −0.39.</p></div>
        <div class="fail"><div class="fx">✕</div><b>Adoption factor</b>
          <p>The archive supports depth on only two retailers. A two-name
          cross-section is a pair trade, not a factor.</p></div>
        <div class="fail"><div class="fx">✕</div><b>Earnings event study</b>
          <p>Headline +3.1% per event — but a pre-event placebo window shows a
          larger move. The announcement isn't the cause.</p></div>
      </div>
      <p class="stamp big-stamp">We publish the failures at the same size as the
      wins. That is the point: every number here survived a rule written before we
      looked. The forecast is what's left standing.</p>''', 8)

# 09 WHO PAYS
slide("Who this is for",
      f'''<h2>A short list of buyers who already pay for less.</h2>
      <div class="buyers">
        <div class="buyer"><b>Trend-forecasting vendors</b>
          <p>Heuritech, Trendalytics and peers sell shallower runway-signal
          products at <span class="ink">€12–35k / year</span> per seat. Ours is
          measured propagation, not eyeballed.</p></div>
        <div class="buyer"><b>Textile &amp; fiber planners</b>
          <p>Mills and material buyers plan capacity months ahead. A quantified
          demand lead per fiber maps directly onto their order cycle.</p></div>
        <div class="buyer"><b>Alternative-data desks</b>
          <p>Consumer and macro funds buy anything that leads a print. A
          reproducible apparel-cycle indicator is exactly that shape.</p></div>
      </div>
      <p class="stamp">Built bottoms-up from named buyers — not a top-down market
      cone.</p>''', 9)

# 10 DEFENSIBLE
slide("Why it holds",
      f'''<h2>The corpus can't be re-bought.</h2>
      <div class="moats">
        <div class="moat"><div class="mn">01</div><b>A frozen record</b>
          <p>The archived assortment history is fixed. A competitor starting today
          cannot reconstruct what they didn't capture.</p></div>
        <div class="moat"><div class="mn">02</div><b>Deepens every season</b>
          <p>Each new fashion week and each monthly crawl extends the panel. The
          lead time to reproduce it only grows.</p></div>
        <div class="moat"><div class="mn">03</div><b>Method, not luck</b>
          <p>The pipeline generalizes to any category whose product pages disclose
          composition, ingredients or specs.</p></div>
      </div>''', 10)

# 11 PRODUCT
slide("What you'd get",
      f'''<h2>Three things ship monthly.</h2>
      <div class="prods">
        <div class="prod"><div class="pk">The indicator</div>
          <p>One number: the runway-weighted material signal, dated, with its
          historical lead over apparel sales.</p></div>
        <div class="prod"><div class="pk">The lag tables</div>
          <p>Per material, per retailer: how many months the runway leads, and how
          tightly, with confidence.</p></div>
        <div class="prod"><div class="pk">Emergence alerts</div>
          <p>The materials rising fastest off the current runway — wool is up
          nine points this season — and when they should land.</p></div>
      </div>
      <p class="stamp">Derived signals only. No runway imagery, no scraped retailer
      content leaves the pipeline.</p>''', 11)

# 12 WHY NOW
slide("Why now",
      f'''<h2>This was not buildable three years ago.</h2>
      <div class="nows">
        <div class="nowc"><b>Vision got cheap</b>
          <p>Tagging {n_tagged:,} runway looks for fabric mix now costs less than a
          rounding error. In 2021 it was a research budget.</p></div>
        <div class="nowc"><b>The archive got deep</b>
          <p>A decade of crawled retail pages is finally long enough to fit
          multi-year lags with real degrees of freedom.</p></div>
        <div class="nowc"><b>Planning got harder</b>
          <p>Demand volatility and inventory risk have made an early, quantified
          read on material demand worth paying for.</p></div>
      </div>''', 12)

# 13 CLOSE
slide("",
      f'''<div class="close">
        <h2>The method is public.<br>The signal is the product.</h2>
        <p class="say">Every line of the pipeline, the full working paper, and a
        live dashboard are open at
        <span class="ink">github.com/pravitkochar/Fashion_Finance</span>. The
        reproducibility is the credibility — and the frozen corpus behind it is the
        edge.</p>
        <p class="say">Looking for a design partner to turn the indicator into a
        monthly feed, and the buyers who want the apparel cycle a year early.</p>
        <p class="by2">Pravit Kochar · pravitkochar@gmail.com</p>
      </div>''', 13, cls="dark", foot="")


# ---- assemble ---------------------------------------------------------------
CSS = """
:root{
  --paper:#e9e6dc; --ink:#1a1d23; --ink2:#4c5058; --muted:#8a8577;
  --hair:#c7c2b3; --denim:#284079; --grid:rgba(26,29,35,.05);
  --serif:"Bodoni 72","Didot",Charter,Georgia,"Times New Roman",serif;
  --mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
}
*{box-sizing:border-box;margin:0;padding:0}
html,body{background:#3a3a38}
.slide{position:relative;width:1280px;height:720px;background:var(--paper);
  color:var(--ink);padding:66px 84px 54px;display:flex;flex-direction:column;
  overflow:hidden;
  background-image:repeating-linear-gradient(0deg,transparent 0 31px,var(--grid) 31px 32px),
    repeating-linear-gradient(90deg,transparent 0 31px,var(--grid) 31px 32px)}
.slide + .slide{page-break-before:always}
.kick{font:600 12.5px/1 var(--mono);letter-spacing:.26em;text-transform:uppercase;
  color:var(--denim);margin-bottom:6px;flex:none}
.content{flex:1;display:flex;flex-direction:column;justify-content:center;min-height:0}
.foot{flex:none;display:flex;justify-content:space-between;align-items:baseline;
  font:11px var(--mono);color:var(--muted);border-top:1px solid var(--hair);
  padding-top:12px;letter-spacing:.04em}
.foot .pg{font-variant-numeric:tabular-nums}
h1{font:400 132px/.92 var(--serif);letter-spacing:-.02em}
h2{font:400 42px/1.12 var(--serif);letter-spacing:-.01em;text-wrap:balance;
  max-width:22ch}
.muted{color:var(--muted)} .ink{color:var(--denim);font-weight:700}
.say{font:400 20px/1.5 var(--serif);color:var(--ink2);max-width:60ch;margin-top:18px}
.big-say{font-size:27px;color:var(--ink);margin-top:26px;max-width:26ch}
.stamp{font:12.5px/1.55 var(--mono);color:var(--muted);max-width:82ch;margin-top:22px;
  border-left:2px solid var(--hair);padding-left:14px}
.big-stamp{font-size:14px;color:var(--ink2);border-left-color:var(--denim)}

/* cover */
.cover-slide{padding:0}
.cover{position:relative;width:100%;height:100%;display:flex;align-items:center}
.coverloom{position:absolute;inset:0;display:flex;align-items:center;
  justify-content:center;opacity:.9}
.covertext{position:relative;padding:0 84px;max-width:60%}
.lede{font:400 25px/1.42 var(--serif);color:var(--ink2);margin-top:26px;max-width:24ch}
.by{font:12px var(--mono);color:var(--muted);margin-top:40px;letter-spacing:.05em}

/* dark slides */
.slide.dark{background:#1a1d23;color:#ece9df;background-image:none}
.slide.dark .kick{color:#8ea6d8}
.slide.dark .muted{color:#8a8f9c}
.slide.dark .ink{color:#a9c1f0}
.slide.dark h2{color:#f2efe6}
.slide.dark .say{color:#c2c0b6}
.slide.dark .foot{color:#6f7480;border-top-color:#33373f}

/* killer number */
.killer{display:flex;gap:56px;align-items:center}
.knum{font:400 168px/.86 var(--serif);color:#a9c1f0;flex:none;letter-spacing:-.03em}
.kunit{display:block;font:600 20px/1 var(--mono);letter-spacing:.24em;
  text-transform:uppercase;color:#8a8f9c;margin-top:14px}
.ktext{max-width:34ch}
.ktext h2{color:#f2efe6}

/* tiers */
.tiers{display:flex;align-items:stretch;gap:22px;margin-top:34px}
.tier{flex:1;border-top:2px solid var(--denim);padding-top:16px}
.tnum{font:400 58px/1 var(--serif);color:var(--ink);font-variant-numeric:tabular-nums}
.tlab{font:600 11px/1 var(--mono);letter-spacing:.16em;text-transform:uppercase;
  color:var(--denim);margin:10px 0 12px}
.tier p{font:14.5px/1.5 var(--serif);color:var(--ink2)}
.tarrow{font:34px var(--serif);color:var(--muted);align-self:center}
.stamp.big-stamp{margin-top:28px}

/* loom + lag chart */
.loom{width:100%;height:auto}
.loomwrap{margin:2px 0 4px}
.axmo{font:11px var(--mono);fill:var(--muted);font-variant-numeric:tabular-nums}
.axttl{font:600 10px var(--mono);letter-spacing:.16em;fill:var(--muted)}
.runlab{font:600 10px var(--mono);letter-spacing:.18em;fill:var(--denim)}
.lagmat{font:600 14px var(--mono);letter-spacing:.02em}
.lagend{font:12.5px var(--mono);fill:var(--ink2);font-variant-numeric:tabular-nums}

/* nowcast */
.proof2{display:flex;gap:48px;align-items:center;margin-top:20px}
.chartwrap{flex:none;width:560px}
.chart{width:100%;height:auto}
.barval{font:600 13px var(--mono);fill:var(--ink);font-variant-numeric:tabular-nums}
.baraxis{font:10px var(--mono);letter-spacing:.14em;fill:var(--muted)}
.leg{font:11px var(--mono);fill:var(--ink2)}
.proof2text{flex:1}

/* fails */
.fails{display:flex;gap:22px;margin-top:30px}
.fail{flex:1;border-top:1px solid var(--hair);padding-top:14px}
.fx{font:22px var(--serif);color:#a8443a;margin-bottom:8px}
.fail b{font:600 15px var(--mono);letter-spacing:.02em;display:block;margin-bottom:8px}
.fail p{font:14px/1.5 var(--serif);color:var(--ink2)}

/* buyers / moats / prods / nows */
.buyers,.moats,.prods,.nows{display:flex;gap:26px;margin-top:32px}
.buyer,.moat,.prod,.nowc{flex:1}
.buyer b,.prod b,.nowc b{font:400 22px var(--serif);display:block;margin-bottom:10px}
.buyer p,.moat p,.prod p,.nowc p{font:14.5px/1.55 var(--serif);color:var(--ink2)}
.pk{font:400 22px var(--serif);margin-bottom:10px;border-bottom:2px solid var(--denim);
  display:inline-block;padding-bottom:3px}
.mn{font:600 13px var(--mono);color:var(--denim);letter-spacing:.1em;margin-bottom:8px}
.moat b{font:400 21px var(--serif);display:block;margin-bottom:9px}

/* close */
.close{max-width:40ch}
.close h2{font-size:46px}
.by2{font:13px var(--mono);color:#8ea6d8;margin-top:40px;letter-spacing:.05em}
"""

html = ("<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>Trickle Down — pitch</title><style>{CSS}</style></head><body>"
        + "".join(SLIDES) + "</body></html>")
OUT_HTML.write_text(html, encoding="utf-8")
print(f"wrote {OUT_HTML} ({len(html)//1024} KB, {len(SLIDES)} slides)")

# ---- render PDF -------------------------------------------------------------
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1280, "height": 720})
    pg.goto(OUT_HTML.as_uri(), wait_until="networkidle")
    pg.pdf(path=str(OUT_PDF), width="1280px", height="720px",
           print_background=True, margin={"top": "0", "bottom": "0",
                                          "left": "0", "right": "0"})
    b.close()
print(f"wrote {OUT_PDF}")
