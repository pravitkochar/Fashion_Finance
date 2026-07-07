"""Build paper/Trickle_Down_Paper.pdf from paper/trickle_down_paper.md.

md -> HTML (print CSS in the project's researcher's-notebook idiom, light
only) -> chromium page.pdf via playwright. Figures: the loom SVG (rebuilt
live from propagation_train + runway_mix through 16_site_pages.build_loom)
inserted after §5's second table, and the nowcast turning-point chart
embedded as a data URI in §6. Page numbers via the playwright footer
template. Rerunnable any time the data moves.
"""
from __future__ import annotations

import base64
import importlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.argv = ["build_paper"]

import markdown  # noqa: E402
import lib_trickle as lt  # noqa: E402

m16 = importlib.import_module("16_site_pages")

PAPER = lt.ROOT / "paper"
MD = PAPER / "trickle_down_paper.md"
PDF = PAPER / "Trickle_Down_Paper.pdf"

CSS = """
@page { size: A4; margin: 22mm 19mm 24mm 19mm; }
body { font: 10.8pt/1.55 Charter, "Iowan Old Style", Georgia, serif;
       color: #1c1f24; max-width: none; margin: 0;
       -webkit-print-color-adjust: exact; }
h1 { font: 700 19pt/1.2 Charter, Georgia, serif; margin: 0 0 4pt;
     letter-spacing: -.01em; }
h1 + p strong { font-weight: 400; }
h2 { font: 700 13pt/1.25 Charter, Georgia, serif; margin: 22pt 0 6pt;
     border-bottom: .6pt solid #c9cec6; padding-bottom: 3pt; }
p { margin: 0 0 8pt; text-align: justify; hyphens: auto; }
strong { font-weight: 700; }
code { font: 9.3pt ui-monospace, Menlo, monospace;
       background: #f0f1ec; padding: 0 2px; }
table { border-collapse: collapse; margin: 8pt auto 12pt;
        font: 9.2pt/1.45 ui-monospace, Menlo, monospace;
        font-variant-numeric: tabular-nums; }
th { text-align: left; font: 700 8.4pt ui-monospace, Menlo, monospace;
     text-transform: uppercase; letter-spacing: .06em; color: #5c6157;
     border-bottom: .8pt solid #9aa093; padding: 2pt 12pt 3pt 0; }
td { border-bottom: .4pt dotted #c9cec6; padding: 2.5pt 12pt 2.5pt 0; }
figure { margin: 12pt 0; page-break-inside: avoid; }
figure svg, figure img { max-width: 100%; height: auto;
                         border: .5pt solid #c9cec6; }
figcaption { font: 8.6pt/1.4 ui-monospace, Menlo, monospace;
             color: #5c6157; margin-top: 4pt; }
.loom text { font: 8px ui-monospace, Menlo, monospace; fill: #5c6157; }
.loom .bandlab { font: 600 7.5px ui-monospace; letter-spacing: .18em;
                 fill: #8a8f83; }
.loom .lag { fill: #1c1f24; }
em { font-style: italic; }
h2:nth-of-type(n+3) { page-break-after: avoid; }
"""

FOOTER = ('<div style="font-size:7.5pt;color:#8a8f83;width:100%;'
          'text-align:center;font-family:Menlo,monospace;">'
          'Kochar · Does fashion trickle down? · '
          '<span class="pageNumber"></span>/<span class="totalPages"></span>'
          '</div>')


def build_html() -> str:
    md_text = MD.read_text(encoding="utf-8")
    body = markdown.markdown(md_text, extensions=["tables"])

    loom = m16.build_loom()
    loom_fig = ('<figure>' + loom +
                '<figcaption>Figure 1 — the cascade, drawn from the fitted '
                'numbers. Thread width = material share of the current '
                'runway season; the bend marks the fitted runway-to-search '
                'lag; threads terminate at mapped suppliers. A thread with '
                'no reliable fitted lag fades out.</figcaption></figure>')
    # after the hop-1/rack-space results paragraph (before "Rack space →")
    body = body.replace("<p><strong>Rack space",
                        loom_fig + "<p><strong>Rack space", 1)

    png = lt.REPORTS / "img" / "nowcast_turning_points.png"
    if png.exists():
        uri = "data:image/png;base64," + base64.b64encode(
            png.read_bytes()).decode()
        fig2 = (f'<figure><img src="{uri}" alt="Turning points">'
                '<figcaption>Figure 2 — clothing-store retail sales YoY '
                '(SA) with marked turning points, against the '
                'runway-weighted cascade composite.</figcaption></figure>')
        body = re.sub(r"(<p><strong>The forecasting result)",
                      fig2 + r"\1", body, count=1)

    return f"<style>{CSS}</style>\n{body}"


def main() -> int:
    html = build_html()
    tmp = PAPER / "_paper_print.html"
    tmp.write_text("<!doctype html><html><head><meta charset='utf-8'>"
                   "</head><body>" + html + "</body></html>",
                   encoding="utf-8")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.goto(tmp.resolve().as_uri(), wait_until="load")
        pg.pdf(path=str(PDF), format="A4", print_background=True,
               display_header_footer=True, header_template="<div></div>",
               footer_template=FOOTER,
               margin={"top": "22mm", "bottom": "24mm",
                       "left": "19mm", "right": "19mm"})
        b.close()
    print(f"built {PDF} ({PDF.stat().st_size/1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
