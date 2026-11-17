"""One merged slide: data sources + model improvements (rigor), as a .pptx for Google Slides import."""
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
s = prs.slides.add_slide(prs.slide_layouts[6])


def text(x, y, w, h, paras, size=14, color=INK, bold=False, space=5):
    tf = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h)).text_frame
    tf.word_wrap = True
    for i, para in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.space_after = Pt(space)
        for seg, b, c in ([(para, bold, color)] if isinstance(para, str) else para):
            r = p.add_run()
            r.text, r.font.size, r.font.bold, r.font.color.rgb = seg, Pt(size), b, c


def B(t):  # bold lead-in
    return (t, True, INK)


def N(t):  # normal
    return (t, False, INK)


def H(t):  # highlighted number
    return (t, True, HEAT)


# Header
text(0.6, 0.3, 12.1, 0.35, ["RIGOR · DATA DECISIONS AND VALIDATION"], size=12, color=HEAT, bold=True)
text(0.6, 0.62, 12.1, 0.8, ["Defensible data, and a model tested on blocks it never saw"], size=28, bold=True)

# Divider between columns
line = s.shapes.add_connector(1, Inches(6.55), Inches(1.65), Inches(6.55), Inches(6.55))
line.line.color.rgb = SOFT
line.line.width = Pt(1.5)

# ---- Left column: data sources
text(0.6, 1.6, 5.7, 0.4, ["Data sources"], size=16, color=TEAL, bold=True)
text(0.6, 2.0, 5.7, 3.3, [
    [B("NOAA Heat Watch"), N(": 48,855 afternoon air readings (label)")],
    [B("NOAA GHCN-Daily"), N(": 13 stations, daily highs, 2019–2025")],
    [B("Census ACS 2024 + 2024 tracts"), N(": age, car access, poverty")],
    [B("Landsat 8/9 (USGS)"), N(": surface heat, 14 clear summer days")],
    [B("NLCD 2021 (USGS/USFS)"), N(": pavement and tree canopy")],
    [B("City of Chicago"), N(": 995 cooling and facility records, reconciled")],
    [B("OpenStreetMap · NWS"), N(": built environment · 7-day forecast")],
], size=14, space=6)
box = s.shapes.add_shape(1, Inches(0.6), Inches(5.35), Inches(5.7), Inches(1.2))
box.fill.solid()
box.fill.fore_color.rgb = SOFT
box.line.fill.background()
text(0.75, 5.42, 5.45, 1.1, [
    [("✔ Licenses checked", True, TEAL), N(": public domain, ODbL, City open data")],
    [("✘ Excluded on purpose", True, HEAT), N(": CMAP canopy (no reuse license), CTA transit (rider-info only)")],
    [("✔ Race never loaded or used", True, TEAL), N("; equity audit reports outcomes")],
], size=12, space=3)

# ---- Right column: model improvements
text(6.85, 1.6, 5.9, 0.4, ["Model improvements"], size=16, color=TEAL, bold=True)
rows = [["Held-out blocks (442 cells)", "r²", "Typical error"],
        ["Original model", "0.26", "2.06°F"],
        ["Location trend alone", "0.50", "1.68°F"],
        ["New model", "0.59", "1.54°F"]]
tbl = s.shapes.add_table(4, 3, Inches(6.85), Inches(2.05), Inches(5.85), Inches(1.5)).table
for j, w in enumerate([3.25, 1.0, 1.6]):
    tbl.columns[j].width = Inches(w)
for i, row in enumerate(rows):
    for j, val in enumerate(row):
        c = tbl.cell(i, j)
        c.text = val
        c.fill.solid()
        c.fill.fore_color.rgb = INK if i == 0 else (SOFT if i == 3 else WHITE)
        for p in c.text_frame.paragraphs:
            p.alignment = PP_ALIGN.RIGHT if j > 0 else PP_ALIGN.LEFT
            for r in p.runs:
                r.font.size = Pt(14)
                r.font.bold = i in (0, 3)
                r.font.color.rgb = WHITE if i == 0 else (HEAT if i == 3 and j > 0 else INK)
text(6.85, 3.75, 5.9, 2.8, [
    [B("Spatial hold-out"), N(": whole 2.7 km blocks kept out of training")],
    [B("Bar set before training"), N(": beat location alone by ≥0.02 → "), H("+0.084")],
    [B("Data fixes"), N(": 26% of blocks re-mapped to the correct tract")],
    [B("Equity audit"), N(": top sites reach vulnerable tracts at "), H("4.3× the city rate")],
    [B("Older residents"), N(": 23% at top sites vs 14% citywide")],
    [B("Reversible"), N(": every version backed up; one-command rollback")],
], size=14, space=6)

# Footer
text(0.6, 6.8, 12.1, 0.4, ["New model = location trend + satellite surface heat (an input, never shown as air temperature) "
                           "+ pavement and canopy, in BigQuery ML. Every number is reproducible from the repo."],
     size=11, color=MUTED)

s.notes_slide.notes_text_frame.text = (
    "Every source was chosen for a reason and its license checked. We dropped a richer canopy layer because its reuse "
    "terms weren't clear, and race isn't in the data at all. On the model: we fixed a pass bar before training. The new "
    "model had to beat simple location by at least 0.02 on whole blocks it had never seen. It beat it by 0.08, more "
    "than doubling accuracy over the original. We also corrected the data: a quarter of blocks had been assigned to "
    "the wrong Census tract. Then we audited the outcome: the top sites reach the most vulnerable tracts at four times "
    "the city rate, and reach more older residents.")

prs.save(sys.argv[1])
print("saved", sys.argv[1])
