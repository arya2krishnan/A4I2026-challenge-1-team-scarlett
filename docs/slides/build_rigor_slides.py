"""Build three rigor slides (data sources, model improvements, limitations) as a .pptx for Google Slides import."""
import sys
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN

INK = RGBColor(0x1F, 0x1D, 0x1A)
MUTED = RGBColor(0x5F, 0x5A, 0x52)
HEAT = RGBColor(0xC2, 0x3B, 0x2B)
TEAL = RGBColor(0x0B, 0x8F, 0x86)
SOFT = RGBColor(0xF4, 0xF1, 0xEA)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

prs = Presentation()
prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
BLANK = prs.slide_layouts[6]


def text(slide, x, y, w, h, runs, size=16, color=INK, bold=False, align=PP_ALIGN.LEFT, space=6):
    """runs: list of paragraphs; each paragraph is a str or a list of (text, bold, color) segments."""
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    for i, para in enumerate(runs):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.space_after = Pt(space)
        segs = [(para, bold, color)] if isinstance(para, str) else para
        for seg_text, seg_bold, seg_color in segs:
            r = p.add_run()
            r.text = seg_text
            r.font.size = Pt(size)
            r.font.bold = seg_bold
            r.font.color.rgb = seg_color
    return tb


def title(slide, t, kicker):
    text(slide, 0.6, 0.35, 12.1, 0.4, [kicker.upper()], size=12, color=HEAT, bold=True)
    text(slide, 0.6, 0.7, 12.1, 0.9, [t], size=30, bold=True)


def table(slide, x, y, w, rows, col_w, size=14, header_fill=INK, bold_rows=()):
    shape = slide.shapes.add_table(len(rows), len(rows[0]), Inches(x), Inches(y), Inches(w), Inches(0.4 * len(rows)))
    tbl = shape.table
    for j, cw in enumerate(col_w):
        tbl.columns[j].width = Inches(cw)
    for i, row in enumerate(rows):
        for j, val in enumerate(row):
            cell = tbl.cell(i, j)
            cell.text = val
            cell.fill.solid()
            cell.fill.fore_color.rgb = header_fill if i == 0 else (SOFT if i % 2 == 0 else WHITE)
            for p in cell.text_frame.paragraphs:
                p.alignment = PP_ALIGN.RIGHT if (j > 0 and len(row) == 3 and i > 0 and col_w[j] < 2.5) else PP_ALIGN.LEFT
                for r in p.runs:
                    r.font.size = Pt(size)
                    r.font.color.rgb = WHITE if i == 0 else INK
                    r.font.bold = i == 0 or i in bold_rows
    return shape


def strip(slide, y, items):
    box = slide.shapes.add_shape(1, Inches(0.6), Inches(y), Inches(12.1), Inches(0.75))
    box.fill.solid()
    box.fill.fore_color.rgb = SOFT
    box.line.fill.background()
    text(slide, 0.8, y + 0.12, 11.8, 0.6, [items], size=13, space=0)


def notes(slide, s):
    slide.notes_slide.notes_text_frame.text = s


# ---------------------------------------------------------------- Slide 1: data sources
s = prs.slides.add_slide(BLANK)
title(s, "Data we chose, and why we can defend it", "Rigor · data decisions")
text(s, 0.6, 1.75, 5.9, 0.4, ["Core data"], size=16, color=TEAL, bold=True)
text(s, 0.6, 2.2, 5.9, 3.2, [
    [("NOAA Heat Watch", True, INK), (": 48,855 afternoon air readings (the model's label)", False, INK)],
    [("NOAA GHCN-Daily", True, INK), (": 13 stations, daily highs, 2019–2025", False, INK)],
    [("Census ACS 2024 + 2024 tract boundaries", True, INK), (": age, car access, poverty", False, INK)],
], size=16, space=12)
text(s, 6.9, 1.75, 5.8, 0.4, ["Data we brought"], size=16, color=TEAL, bold=True)
text(s, 6.9, 2.2, 5.8, 3.2, [
    [("Landsat 8/9 (USGS)", True, INK), (": surface heat, 14 clear summer days, 2019–2025", False, INK)],
    [("NLCD 2021 (USGS/USFS)", True, INK), (": pavement and tree canopy for every block", False, INK)],
    [("City of Chicago", True, INK), (": 995 cooling and facility records, reconciled across sources", False, INK)],
    [("OpenStreetMap · NWS", True, INK), (": built environment · 7-day forecast", False, INK)],
], size=16, space=12)
strip(s, 5.75, [("✔ Licenses checked", True, TEAL), (": public domain, ODbL, City open data     ", False, INK),
                ("✘ Excluded on purpose", True, HEAT), (": CMAP canopy (no reuse license), CTA transit (rider-info only)     ", False, INK),
                ("✔ Race never loaded or used", True, TEAL)])
notes(s, "We chose every source for a reason and checked its license. We dropped a richer canopy layer because its "
         "reuse terms weren't clear. Race isn't in the data at all, and the equity audit reports outcomes instead.")

# ---------------------------------------------------------------- Slide 2: model improvements
s = prs.slides.add_slide(BLANK)
title(s, "Accuracy more than doubled, tested on blocks the model never saw", "Rigor · validation")
table(s, 0.6, 1.9, 5.9, [
    ["Model (442 held-out cells)", "r²", "Typical error"],
    ["Original", "0.26", "2.06°F"],
    ["Location trend alone", "0.50", "1.68°F"],
    ["New model", "0.59", "1.54°F"],
], col_w=[3.3, 1.0, 1.6], size=16, bold_rows=(3,))
text(s, 0.6, 3.75, 5.9, 1.2, ["New model = location trend + satellite surface heat + pavement and canopy, "
                               "trained in BigQuery ML; evaluated on whole 2.7 km blocks held out of training."],
     size=13, color=MUTED)
text(s, 6.9, 1.75, 5.8, 0.4, ["How we know it's real"], size=16, color=TEAL, bold=True)
text(s, 6.9, 2.2, 5.8, 4.2, [
    [("Spatial hold-out", True, INK), (": whole blocks kept out of training", False, INK)],
    [("Bar set before training", True, INK), (": beat location alone by ≥0.02 → ", False, INK), ("+0.084", True, HEAT)],
    [("Data fixes", True, INK), (": 26% of blocks re-mapped to their correct Census tract", False, INK)],
    [("Equity audit", True, INK), (": top sites reach vulnerable tracts at ", False, INK), ("4.3× the city rate", True, HEAT)],
    [("Older residents", True, INK), (": 23% at top sites vs 14% citywide", False, INK)],
    [("Reversible", True, INK), (": every version backed up; rollback is one command", False, INK)],
], size=16, space=12)
notes(s, "We didn't just quote a better score. We fixed a pass bar before training: the new model had to beat simple "
         "location by at least 0.02 on blocks it had never seen. It beat it by 0.08. We also corrected the data: a "
         "quarter of blocks had been assigned to the wrong tract. Then we audited the outcome: the top sites reach the "
         "most vulnerable tracts at four times the city rate.")

# ---------------------------------------------------------------- Slide 3: limitations
s = prs.slides.add_slide(BLANK)
title(s, "What the model can't tell you, and what we did about it", "Rigor · knowing the limits")
table(s, 0.6, 1.75, 12.1, [
    ["Limitation", "How we handle it"],
    ["Heat Watch is one afternoon, driven by volunteers", "14 days of satellite data, covering every block, confirm the south and southwest run hot"],
    ["Satellite heat measures surfaces at 10:30 a.m., not the air people breathe", "Used only as an input, never shown as a temperature"],
    ["Part of the gradient may reflect the order volunteers drove their routes", "Stated openly; no timestamps exist to correct it"],
    ["Cooling sites aren't confirmed open for the event", "Every stop flags \"verify before dispatch\""],
    ["We can't simulate tree or pavement fixes", "We show where and why it's hot, not \"after\" temperatures"],
    ["Census figures are 5-year estimates", "Margins of error kept; tracts treated whole"],
], col_w=[5.6, 6.5], size=15)
text(s, 0.6, 6.75, 12.1, 0.4, ["Every number is reproducible from the repo (docs/ARCHITECTURE.md)."], size=12, color=MUTED)
notes(s, "These are the honest limits. The biggest is that the air readings come from one afternoon, which is why we "
         "cross-checked with 14 days of satellite data. And we never show a cooling site as open unless someone has "
         "confirmed it.")

prs.save(sys.argv[1])
print("saved", sys.argv[1])
