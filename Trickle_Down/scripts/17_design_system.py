"""V2 design system — "Vogue-meets-Bloomberg" textile editorial.

Shared by 16_site_pages.py (and eventually 09). Identity:
  - unbleached-muslin ground with an ultra-faint warp/weft weave
  - fashion serif mastheads (Bodoni 72/Didot stacks), mono "terminal slips"
    for quant tables, sans for labels
  - one accent: selvage red, spent ONLY on emergent/negative-honesty marks
  - per-material swatch palette (validated with the dataviz six checks,
    light on #fffdf9 and dark on #1d1a17) + inline-SVG fabric textures
    (currentColor patterns: twill/knit/grain/slub/weave/tech)
  - the loom: a static SVG cascade hero — threads fall runway -> high
    street -> mills at their fitted lags

Everything is inline CSS/SVG — zero external requests, no-JS safe.
"""
from __future__ import annotations

import html as _html
import math

# ------------------------------------------------------------- palette ------
# fixed order for the loom's top-8 (validated); extras always ship labeled
MATERIAL_COLORS = {          # material: (light, dark)
    "wool":      ("#B5762E", "#BD8035"),
    "polyester": ("#3E6FB0", "#4E86D4"),
    "viscose":   ("#0E9080", "#17A08E"),
    "leather":   ("#96430E", "#B85A1F"),
    "nylon":     ("#6C5BB5", "#8B77D9"),
    "cotton":    ("#8A7A14", "#9C8B1A"),
    "elastane":  ("#B04A78", "#C75D8D"),
    "silk":      ("#2E8FC4", "#2E97CC"),
    "denim":     ("#31518F", "#5D7FC7"),
    "cashmere":  ("#9C6A45", "#C08A5C"),
    "linen":     ("#6E7A3A", "#8C9A50"),
    "technical": ("#55636E", "#7C8E9C"),
    "other":     ("#77706A", "#8F8880"),
}
SELVAGE = ("#B6382E", "#D95F4F")          # accent: emergent / drawdown only
TEXTURE = {                               # material family -> pattern id
    "denim": "twill", "wool": "knit", "cashmere": "knit",
    "leather": "grain", "linen": "slub", "silk": "slub",
    "cotton": "weave", "viscose": "weave",
    "polyester": "tech", "nylon": "tech", "elastane": "tech",
    "technical": "tech", "other": "weave",
}


def esc(x) -> str:
    return _html.escape("—" if x is None else str(x))


def color_var(material: str) -> str:
    return f"var(--m-{material})" if material in MATERIAL_COLORS \
        else "var(--m-other)"


# -------------------------------------------------------------- defs --------

def pattern_defs() -> str:
    """One hidden SVG with currentColor textures, referenced page-wide."""
    return """
<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs>
<pattern id="tx-twill" width="7" height="7" patternUnits="userSpaceOnUse"
 patternTransform="rotate(45)"><rect width="7" height="7" fill="none"/>
 <line x1="0" y1="0" x2="0" y2="7" stroke="currentColor" stroke-width="2.4"
  opacity=".35"/></pattern>
<pattern id="tx-knit" width="9" height="7" patternUnits="userSpaceOnUse">
 <path d="M0 6 Q2.2 1 4.5 6 Q6.8 1 9 6" fill="none" stroke="currentColor"
  stroke-width="1.1" opacity=".38"/></pattern>
<pattern id="tx-grain" width="10" height="10" patternUnits="userSpaceOnUse">
 <circle cx="2" cy="3" r=".9" fill="currentColor" opacity=".4"/>
 <circle cx="7" cy="7" r=".7" fill="currentColor" opacity=".3"/>
 <circle cx="5" cy="1" r=".6" fill="currentColor" opacity=".25"/></pattern>
<pattern id="tx-slub" width="14" height="6" patternUnits="userSpaceOnUse">
 <line x1="0" y1="2" x2="9" y2="2" stroke="currentColor" stroke-width="1"
  opacity=".3"/><line x1="5" y1="5" x2="14" y2="5" stroke="currentColor"
  stroke-width=".8" opacity=".22"/></pattern>
<pattern id="tx-weave" width="6" height="6" patternUnits="userSpaceOnUse">
 <path d="M0 3 H6 M3 0 V6" stroke="currentColor" stroke-width=".8"
  opacity=".3"/></pattern>
<pattern id="tx-tech" width="6" height="6" patternUnits="userSpaceOnUse"
 patternTransform="rotate(-45)"><line x1="0" y1="0" x2="0" y2="6"
 stroke="currentColor" stroke-width=".9" opacity=".3"/></pattern>
</defs></svg>"""


# --------------------------------------------------------------- css --------

def css() -> str:
    mat_light = "".join(f"--m-{m}:{lc};" for m, (lc, _) in
                        MATERIAL_COLORS.items())
    mat_dark = "".join(f"--m-{m}:{dc};" for m, (_, dc) in
                       MATERIAL_COLORS.items())
    return f"""<style>
:root{{
  --page:#faf7f1; --surface:#fffdf9; --slip:#f4efe4;
  --ink:#1a1613; --ink2:#5c554b; --muted:#8f887c;
  --hair:#e0d8c8; --thread-gap:#faf7f1;
  --selvage:{SELVAGE[0]}; --good:#3a7d44;
  {mat_light}
  --serif:"Bodoni 72","Didot","Playfair Display",Georgia,"Times New Roman",serif;
  --mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
  --sans:system-ui,-apple-system,"Segoe UI",sans-serif;
}}
@media (prefers-color-scheme:dark){{:root{{
  --page:#131110; --surface:#1d1a17; --slip:#141210;
  --ink:#f0eade; --ink2:#b5ac9d; --muted:#867e70;
  --hair:#332e27; --thread-gap:#131110; --selvage:{SELVAGE[1]};
  --good:#5da768; {mat_dark}
}}}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--page);color:var(--ink);
  font:15px/1.6 var(--sans);
  background-image:
    repeating-linear-gradient(0deg,transparent 0 27px,
      color-mix(in srgb,var(--ink) 3%,transparent) 27px 28px),
    repeating-linear-gradient(90deg,transparent 0 27px,
      color-mix(in srgb,var(--ink) 2%,transparent) 27px 28px);}}
.wrap{{max-width:1080px;margin:0 auto;padding:34px 24px 90px}}

/* masthead */
.mast{{border-bottom:3px double var(--hair);padding-bottom:18px}}
.mast .kicker{{font:600 11px/1 var(--sans);letter-spacing:.24em;
  text-transform:uppercase;color:var(--ink2)}}
.mast h1{{font:400 58px/1.02 var(--serif);letter-spacing:.01em;margin:10px 0 6px;
  text-wrap:balance}}
.mast .pages{{font:12px var(--mono);color:var(--muted);margin-top:8px}}
.mast .pages b{{color:var(--ink)}}
.dateline{{font:11px var(--mono);color:var(--muted);margin-top:4px}}

/* editorial sections */
section.block{{margin-top:46px}}
.block>h2{{font:400 27px/1.15 var(--serif);margin:0 0 4px;text-wrap:balance}}
.block>.note{{font:13px/1.5 var(--sans);color:var(--ink2);max-width:64ch;
  margin:0 0 16px}}
.rule{{border:0;border-top:1px solid var(--hair);margin:0 0 14px}}
.prose{{max-width:66ch;font:15px/1.65 Georgia,var(--serif)}}
.callout{{font:400 21px/1.4 var(--serif);max-width:56ch;margin:14px 0;
  padding-left:14px;border-left:3px solid var(--selvage)}}
.callout .num{{font-family:var(--mono);font-size:17px}}

/* terminal slips (quant tables) */
.slip{{background:var(--slip);border:1px solid var(--hair);border-radius:3px;
  padding:10px 14px;overflow-x:auto;margin-top:8px}}
.slip table{{border-collapse:collapse;width:100%;
  font:12px/1.5 var(--mono);font-variant-numeric:tabular-nums}}
.slip th{{text-align:left;font:600 10px/1.2 var(--sans);letter-spacing:.12em;
  text-transform:uppercase;color:var(--muted);padding:4px 14px 6px 0;
  border-bottom:1px solid var(--hair)}}
.slip td{{padding:4.5px 14px 4.5px 0;border-bottom:1px solid
  color-mix(in srgb,var(--hair) 55%,transparent);white-space:nowrap}}
.slip tr:last-child td{{border-bottom:0}}
.neg{{color:var(--selvage)}} .pos{{color:var(--good)}}

/* badges / status */
.badge{{display:inline-block;font:600 9.5px/1 var(--sans);letter-spacing:.14em;
  text-transform:uppercase;color:var(--ink2);border:1px solid var(--hair);
  border-radius:2px;padding:3px 7px;margin-left:8px;vertical-align:2px}}
.badge.warn{{color:var(--selvage);border-color:var(--selvage)}}
.emergent{{font:600 9.5px/1 var(--sans);letter-spacing:.14em;
  color:var(--selvage)}}

/* swatch chips */
.chip{{display:inline-flex;align-items:center;gap:7px;font:12px var(--mono)}}
.chip svg{{flex:none}}

/* palette strip */
.strip{{display:flex;height:64px;border:1px solid var(--hair);
  border-radius:3px;overflow:hidden;margin:14px 0 4px}}
.strip .sw{{position:relative;min-width:3px}}
.striplabels{{display:flex;font:10.5px var(--mono);color:var(--ink2);
  gap:0;margin-bottom:8px}}
.striplabels span{{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  padding:2px 3px 0}}

/* loom hero */
.loom-wrap{{overflow-x:auto;margin-top:10px}}
.loom text{{font:10.5px var(--mono);fill:var(--ink2)}}
.loom .bandlab{{font:600 10px var(--sans);letter-spacing:.22em;
  fill:var(--muted)}}
.loom .lag{{fill:var(--ink)}}
.loom .thread-stitch{{animation:drift 26s linear infinite}}
@keyframes drift{{to{{stroke-dashoffset:-240}}}}
@media (prefers-reduced-motion:reduce){{.loom .thread-stitch{{animation:none}}}}
.loom .thread:hover{{filter:brightness(1.12)}}

.empty{{color:var(--muted);padding:24px 8px;text-align:center;font:13px
  var(--sans)}}
.empty code{{background:var(--slip);border-radius:3px;padding:1px 5px;
  font-family:var(--mono)}}
.footnote{{color:var(--muted);font:11.5px/1.5 var(--sans);margin-top:10px;
  max-width:70ch}}
a{{color:inherit}}
:focus-visible{{outline:2px solid var(--selvage);outline-offset:2px}}
</style>"""


# --------------------------------------------------------- components -------

def masthead(page_title: str, here: str, generated: str) -> str:
    return (f'<header class="mast"><div class="kicker">Runway → High '
            'Street → Mills · a measured trend cascade</div>'
            f'<h1>Trickle Down<span style="font-style:italic"> · '
            f'{esc(page_title)}</span></h1>'
            f'<div class="pages">pages: '
            + " / ".join(f"<b>{p}</b>" if p == here else p
                         for p in ("Historical", "Predictions", "Live"))
            + f'</div><div class="dateline">Generated {esc(generated)} · '
            'rebuilt daily · point-in-time, net of costs · negative results '
            'published</div></header>')


def block(title: str, note: str, body: str, badge: str = "") -> str:
    b = f'<span class="badge warn">{esc(badge)}</span>' if badge else ""
    n = f'<p class="note">{esc(note)}</p>' if note else ""
    return (f'<section class="block"><h2>{esc(title)}{b}</h2>{n}'
            f'<hr class="rule">{body}</section>')


def slip_table(headers: list, rows: list, signed_cols: set[int] = frozenset()
               ) -> str:
    th = "".join(f"<th>{esc(h)}</th>" for h in headers)
    out = []
    for row in rows:
        tds = []
        for i, c in enumerate(row):
            cls = ""
            if i in signed_cols and isinstance(c, str):
                if c.startswith("-"):
                    cls = ' class="neg"'
                elif c not in ("—", "") and c[0].isdigit() or \
                        (c.startswith("+")):
                    cls = ' class="pos"'
            tds.append(f"<td{cls}>{esc(c)}</td>")
        out.append("<tr>" + "".join(tds) + "</tr>")
    return (f'<div class="slip"><table><tr>{th}</tr>'
            + "".join(out) + "</table></div>")


def chip(material: str) -> str:
    tx = TEXTURE.get(material, "weave")
    col = color_var(material)
    return (f'<span class="chip"><svg width="15" height="15" '
            f'style="color:{col}" aria-hidden="true">'
            f'<rect width="15" height="15" rx="2" fill="{col}"/>'
            f'<rect width="15" height="15" rx="2" fill="url(#tx-{tx})"/>'
            f'</svg>{esc(material)}</span>')


def empty(hint: str) -> str:
    return (f'<div class="empty">No data yet — <code>{esc(hint)}</code>'
            "</div>")


def palette_strip(shares: list[tuple[str, float]]) -> str:
    """shares: [(material, share)] descending; widths proportional."""
    total = sum(s for _, s in shares) or 1
    sw, labs = [], []
    for m, s in shares:
        w = max(0.8, 100 * s / total)
        tx = TEXTURE.get(m, "weave")
        col = color_var(m)
        sw.append(f'<div class="sw" style="flex:0 0 {w:.2f}%;color:{col};'
                  f'background:{col}"><svg width="100%" height="100%">'
                  f'<rect width="100%" height="100%" fill="url(#tx-{tx})"/>'
                  "</svg></div>")
        labs.append(f'<span style="flex:0 0 {w:.2f}%">'
                    f"{esc(m)} {100 * s:.0f}%</span>" if s / total > 0.055
                    else f'<span style="flex:0 0 {w:.2f}%"></span>')
    return ('<div class="strip">' + "".join(sw) + "</div>"
            '<div class="striplabels">' + "".join(labs) + "</div>")


# ------------------------------------------------------------- loom ---------

def loom_svg(threads: list[dict], season: str) -> str:
    """threads: [{material, share, lag (mo|None), r, suppliers: [str]}],
    ordered by share desc, max 8 drawn as full threads."""
    W, H = 1060, 620
    LEFT, RIGHT = 96, 40
    Y0, Y1, Y2 = 120, 340, 528
    n = len(threads)
    if n == 0:
        return empty("13_fit_propagation.py")
    span = W - LEFT - RIGHT
    xs = [LEFT + span * (i + 0.5) / n for i in range(n)]
    parts = []
    # band rules + labels
    for y, lab in ((Y0, f"RUNWAY · {season}"),
                   (Y1, "HIGH STREET"),
                   (Y2, "MILLS")):
        parts.append(f'<line x1="24" y1="{y}" x2="{W - 24}" y2="{y}" '
                     'stroke="var(--hair)" stroke-width="1"/>')
        parts.append(f'<text x="24" y="{y - 12}" class="bandlab" '
                     'style="paint-order:stroke" stroke="var(--page)" '
                     f'stroke-width="4">{lab}</text>')
    for i, t in enumerate(threads):
        m = t["material"]
        col = color_var(m)
        w = max(3.0, 40 * math.sqrt(t["share"]))
        x0 = xs[i]
        lag = t.get("lag")
        title = (f"{m}: {100 * t['share']:.1f}% of {season}"
                 + (f"; +{lag}mo lag, r={t['r']:.2f}" if lag is not None
                    else "; no fitted lag yet"))
        if lag is None:
            parts.append(
                f'<g class="thread" opacity=".28"><title>{esc(title)}</title>'
                f'<path d="M{x0:.0f},{Y0} V{Y0 + 74}" fill="none" '
                f'stroke="{col}" stroke-width="{w:.1f}" '
                'stroke-dasharray="3 7" stroke-linecap="round"/>'
                f'<text x="{x0:.0f}" y="{Y0 - 22}" text-anchor="middle">'
                f"{esc(m)}</text></g>")
            continue
        drift = (lag - 6) * 16
        x1 = min(max(x0 + drift, LEFT + 6), W - RIGHT - 34)
        mid = f"C{x0:.0f},{Y0 + 110} {x1:.0f},{Y1 - 110} {x1:.0f},{Y1}"
        path = f"M{x0:.0f},{Y0} {mid}"
        has_mill = bool(t.get("suppliers"))
        if has_mill:
            path += f" C{x1:.0f},{Y1 + 80} {x1:.0f},{Y2 - 80} {x1:.0f},{Y2}"
        parts.append(
            f'<g class="thread"><title>{esc(title)}</title>'
            f'<path d="{path}" fill="none" stroke="{col}" '
            f'stroke-width="{w:.1f}" stroke-linecap="round"/>'
            f'<path class="thread-stitch" d="{path}" fill="none" '
            f'stroke="var(--thread-gap)" stroke-width="{max(1.0, w - 2.6):.1f}"'
            f' stroke-dasharray="8 6" stroke-linecap="round" opacity=".5"/>')
        parts.append(f'<text x="{x0:.0f}" y="{Y0 - 22}" text-anchor="middle">'
                     f"{esc(m)}</text>")
        # lag label at the street node, 3-level stagger + page-color halo
        ly = Y1 + (18, 33, 48)[i % 3]
        halo = ('style="paint-order:stroke" stroke="var(--page)" '
                'stroke-width="3.5"')
        parts.append(f'<circle cx="{x1:.0f}" cy="{Y1}" r="{w / 2 + 1.5:.1f}" '
                     f'fill="{col}"/>')
        parts.append(f'<text x="{x1:.0f}" y="{ly}" text-anchor="middle" '
                     f'class="lag" {halo}>+{lag}mo · r {t["r"]:.2f}</text>')
        if has_mill:
            sup = t["suppliers"]
            names = " · ".join(sup[:2]) + (f" +{len(sup) - 2}"
                                           if len(sup) > 2 else "")
            my = Y2 + (20 if i % 2 == 0 else 34)
            parts.append(f'<circle cx="{x1:.0f}" cy="{Y2}" '
                         f'r="{w / 2 + 1.5:.1f}" fill="{col}"/>')
            parts.append(f'<text x="{x1:.0f}" y="{my}" '
                         f'text-anchor="middle" {halo}>{esc(names)}</text>')
        parts.append("</g>")
    return ('<div class="loom-wrap"><svg class="loom" '
            f'width="{W}" height="{H}" role="img" aria-label="The cascade: '
            f'{season} runway shares flowing to high street at fitted lags, '
            'then to mills">' + "".join(parts) + "</svg></div>")


# ------------------------------------------------------------ heatmap -------

def heatmap(d: dict) -> str:
    """Textured swatch-tile heatmap: one material hue per row, alpha by
    share (sequential within row), selvage ring = emergent."""
    if not d:
        return empty("01 → 02 → 04")
    cw, ch, gap, left, top, bottom = 31, 21, 3, 92, 6, 52
    vmax = max((v for row in d["values"] for v in row if v), default=1) or 1
    parts = []
    for r, mat in enumerate(d["materials"]):
        y = top + r * (ch + gap)
        col = color_var(mat)
        parts.append(f'<text x="{left - 8}" y="{y + 15}" text-anchor="end">'
                     f"{esc(mat)}</text>")
        tx = TEXTURE.get(mat, "weave")
        for c in range(len(d["seasons"])):
            v = d["values"][r][c] or 0
            x = left + c * (cw + gap)
            if v <= 0:
                parts.append(f'<rect x="{x}" y="{y}" width="{cw}" '
                             f'height="{ch}" rx="2" fill="var(--slip)"/>')
                continue
            alpha = 0.18 + 0.82 * min(1.0, v / vmax)
            ring = (' stroke="var(--selvage)" stroke-width="2"'
                    if d.get("emergent") and d["emergent"][r][c] else "")
            parts.append(
                f'<g style="color:{col}">'
                f'<rect x="{x}" y="{y}" width="{cw}" height="{ch}" rx="2" '
                f'fill="{col}" fill-opacity="{alpha:.2f}"{ring}>'
                f"<title>{esc(mat)} {esc(d['seasons'][c])}: "
                f"{100 * v:.1f}%</title></rect>"
                f'<rect x="{x}" y="{y}" width="{cw}" height="{ch}" rx="2" '
                f'fill="url(#tx-{tx})" fill-opacity="{alpha:.2f}"/></g>')
    ybase = top + len(d["materials"]) * (ch + gap) + 14
    for c, season in enumerate(d["seasons"]):
        x = left + c * (cw + gap) + cw / 2
        parts.append(f'<text x="{x}" y="{ybase}" text-anchor="end" '
                     f'transform="rotate(-45 {x} {ybase})">{esc(season)}'
                     "</text>")
    W = left + len(d["seasons"]) * (cw + gap) + 6
    H = ybase + bottom - 14
    return ('<div class="slip" style="padding:14px"><svg width="' + str(W)
            + f'" height="{H}" role="img" aria-label="Runway material mix '
            'by season" style="font:10.5px var(--mono)">'
            '<style>text{fill:var(--ink2)}</style>'
            + "".join(parts) + "</svg></div>"
            '<p class="footnote"><span class="emergent">▮</span> selvage '
            "ring = emergent vs trailing 3 seasons · depth of dye = share "
            "of tagged looks</p>")


TIP_JS = """<script>
(function(){
 "use strict";
 var tip=document.createElement("div");
 tip.style.cssText="position:fixed;display:none;pointer-events:none;"+
  "background:var(--surface);border:1px solid var(--hair);border-radius:3px;"+
  "padding:7px 10px;font:12px ui-monospace,Menlo,monospace;z-index:9;"+
  "max-width:300px;box-shadow:0 4px 16px rgba(0,0,0,.16)";
 document.body.appendChild(tip);
 document.querySelectorAll(".loom .thread").forEach(function(g){
  var t=g.querySelector("title");if(!t)return;var txt=t.textContent;
  g.addEventListener("pointermove",function(e){
   tip.textContent=txt;tip.style.display="block";
   var x=e.clientX+14,y=e.clientY+14,r=tip.getBoundingClientRect();
   if(x+r.width>innerWidth-8)x=e.clientX-r.width-14;
   if(y+r.height>innerHeight-8)y=e.clientY-r.height-14;
   tip.style.left=x+"px";tip.style.top=y+"px";});
  g.addEventListener("pointerleave",function(){tip.style.display="none";});
 });
})();
</script>"""


def page(title: str, here: str, generated: str, sections: list[str]) -> str:
    return (f"<title>Trickle Down — {esc(title)}</title>\n" + css()
            + pattern_defs()
            + '<div class="wrap">' + masthead(title, here, generated)
            + "".join(sections) + "</div>" + TIP_JS)
