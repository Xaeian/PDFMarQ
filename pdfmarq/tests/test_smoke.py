"""End-to-end smoke tests - exercise the public API and check that a
valid PDF lands on disk. They are deliberately shallow: pass=no crash,
non-empty PDF, valid header. Catches the most painful regressions
(import errors, signature changes, reportlab version drift, broken
mixin wiring) without locking us into specific byte output.
"""
from pdfmarq import (
  PDF, A4, A5, Align, Styles, TableStyle, TableBuilder, RichSegment, render_rich,
)
from pdfmarq.tests.conftest import assert_valid_pdf

#--------------------------------------------------------------------------------- PDF basic

def test_pdf_empty(tmp_path):
  path = tmp_path / "empty.pdf"
  with PDF(str(path)) as pdf:
    pdf.text("hi")
  assert_valid_pdf(path)

def test_pdf_explicit_save(tmp_path):
  path = tmp_path / "saved.pdf"
  pdf = PDF(str(path))
  pdf.font("Helvetica", 12).text("manual save")
  pdf.save()
  assert_valid_pdf(path)

def test_pdf_unit_mm(tmp_path):
  path = tmp_path / "mm.pdf"
  with PDF(str(path), width=210, height=297, margin=15) as pdf:
    pdf.text("default unit")
  assert_valid_pdf(path)

def test_pdf_unit_pt(tmp_path):
  path = tmp_path / "pt.pdf"
  with PDF(str(path), width=595, height=842, margin=40, unit="pt") as pdf:
    pdf.text("points")
  assert_valid_pdf(path)

def test_pdf_landscape(tmp_path):
  path = tmp_path / "ls.pdf"
  ls = A4.landscape()
  with PDF(str(path), width=ls.width, height=ls.height) as pdf:
    pdf.text("landscape")
  assert pdf.page_width > pdf.page_height
  assert_valid_pdf(path)

def test_pdf_margin_tuple(tmp_path):
  path = tmp_path / "marg.pdf"
  with PDF(str(path), margin=(10, 20, 30)) as pdf:
    pdf.text("margins")
  assert_valid_pdf(path)

#----------------------------------------------------------------------------------- Fonts

def test_font_all_builtins(tmp_path):
  path = tmp_path / "fonts.pdf"
  with PDF(str(path)) as pdf:
    for family, mode in [
      ("Helvetica", "Regular"), ("Helvetica", "Bold"),
      ("Helvetica", "Oblique"), ("Helvetica", "BoldOblique"),
      ("Times", "Regular"), ("Times", "Bold"),
      ("Times", "Italic"), ("Times", "BoldItalic"),
      ("Courier", "Regular"), ("Courier", "Bold"),
    ]:
      pdf.font(family, 11, mode).text(f"{family}-{mode}").enter(6)
  assert_valid_pdf(path)

def test_font_partial_update(tmp_path):
  path = tmp_path / "partial.pdf"
  with PDF(str(path)) as pdf:
    pdf.font("Helvetica", 16, "Bold").text("Title").enter()
    pdf.font(size=11, mode="Regular").text("Body").enter()
  assert_valid_pdf(path)

#------------------------------------------------------------------------------------- Text

def test_text_wrapped(tmp_path):
  path = tmp_path / "wrap.pdf"
  with PDF(str(path)) as pdf:
    pdf.text(
      "Lorem ipsum dolor sit amet consectetur adipiscing elit, "
      "sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.",
      width=80,
    )
  assert_valid_pdf(path)

def test_text_autoscale(tmp_path):
  path = tmp_path / "autoscale.pdf"
  with PDF(str(path)) as pdf:
    # Box too small for text at requested size → autoscale must kick in
    # and NOT recurse to the stack ceiling (see review.md).
    pdf.font("Helvetica", 14)
    pdf.text("This is a fairly long text", width=20, height=10)
  assert_valid_pdf(path)

def test_text_aligns(tmp_path):
  path = tmp_path / "aligns.pdf"
  with PDF(str(path)) as pdf:
    pdf.text("L", width=60, align=Align.LEFT).enter()
    pdf.text("C", width=60, align=Align.CENTER).enter()
    pdf.text("R", width=60, align=Align.RIGHT).enter()
  assert_valid_pdf(path)

def test_text_none_content(tmp_path):
  # `core.text` accepts None silently - guard so we don't regress.
  path = tmp_path / "none.pdf"
  with PDF(str(path)) as pdf:
    pdf.text(None)
  assert_valid_pdf(path)

#----------------------------------------------------------------------------------- Shapes

def test_shapes_all(tmp_path):
  path = tmp_path / "shapes.pdf"
  with PDF(str(path)) as pdf:
    pdf.rect(40, 20).enter(25)
    pdf.rect(40, 20, thickness=1, fill=False).enter(25)
    pdf.round_rect(40, 20, radius=3).enter(25)
    pdf.circle(8, thickness=0.5).enter(20)
    pdf.line(100, 0, 0.5).enter(5)
    pdf.line(80, 0, 1, dash=(3, 2))
  assert_valid_pdf(path)

def test_pdf_path_polygon(tmp_path):
  # Regression: `self.path` (file path attr) used to shadow `def path()`
  # making the documented `pdf.path([...])` polygon API unreachable.
  path = tmp_path / "poly.pdf"
  with PDF(str(path)) as pdf:
    pdf.path([(0, 0), (10, 5), (20, 0)], close=True)
  assert_valid_pdf(path)

#----------------------------------------------------------------------------------- Colors

def test_colors(tmp_path):
  path = tmp_path / "color.pdf"
  with PDF(str(path)) as pdf:
    pdf.color(0.2, 0.4, 0.8).text("rgb").enter()
    pdf.color_hex("#2E75B6").text("hex").enter()
    pdf.color_grey(0.5, 0.8).text("grey").enter()
    pdf.color_black().text("black").enter()
    pdf.stroke_color(0, 0, 1).line(40, 0, 1)
  assert_valid_pdf(path)

#----------------------------------------------------------------------------------- Tables

def test_table_simple(tmp_path):
  path = tmp_path / "table.pdf"
  with PDF(str(path)) as pdf:
    pdf.table(
      [["1", "Widget", "25.00"], ["2", "Gadget", "50.00"]],
      header=["#", "Name", "Price"],
      sizes=[1, 5, 2],
      aligns=[Align.CENTER, Align.LEFT, Align.RIGHT],
    )
  assert_valid_pdf(path)

def test_table_no_header(tmp_path):
  path = tmp_path / "noheader.pdf"
  with PDF(str(path)) as pdf:
    pdf.table([["a", "b"], ["c", "d"]])
  assert_valid_pdf(path)

def test_table_builder(tmp_path):
  path = tmp_path / "builder.pdf"
  style = TableStyle(header_bg=(0.3, 0.3, 0.3), cell_pad_h=1, header_bold=True)
  with PDF(str(path)) as pdf:
    builder = TableBuilder(pdf._metrics, style)
    builder.header(["A", "B"]).rows([["a1", "b1"]]).columns([3, 2], [Align.LEFT, Align.RIGHT])
    data = builder.build(150, "Helvetica", "Regular", 11)
    pdf._draw_table(data, style)
  assert_valid_pdf(path)

#------------------------------------------------------------------------------------ Pages

def test_multi_page(tmp_path):
  path = tmp_path / "pages.pdf"
  with PDF(str(path)) as pdf:
    pdf.text("page 1").new_page()
    pdf.text("page 2").new_page()
    pdf.text("page 3")
    assert pdf.page_num == 3
  assert_valid_pdf(path)

def test_on_page_callback(tmp_path):
  path = tmp_path / "header.pdf"
  hits = []
  with PDF(str(path)) as pdf:
    pdf.on_page(lambda p, n: hits.append(n))
    pdf.text("a").new_page().text("b")
  # Each page (final included) should fire the callback once.
  assert len(hits) >= 2

def test_on_final_page_total(tmp_path):
  path = tmp_path / "final.pdf"
  seen = []
  def footer(p, n, total):
    seen.append((n, total))
  with PDF(str(path)) as pdf:
    pdf.on_final_page(footer)
    pdf.text("a").new_page().text("b").new_page().text("c")
  # `on_final_page` knows the real total once buffered replay runs.
  assert seen, "final-page callback never fired"
  totals = {t for _, t in seen}
  assert totals == {3}, f"expected total=3 on every page, got {seen}"

def test_bookmarks(tmp_path):
  path = tmp_path / "bm.pdf"
  with PDF(str(path)) as pdf:
    pdf.bookmark("Top", level=0).text("intro")
    pdf.new_page()
    pdf.bookmark("Second", level=0).text("more")
  assert_valid_pdf(path)

def test_metadata(tmp_path):
  path = tmp_path / "meta.pdf"
  with PDF(str(path)) as pdf:
    pdf.metadata(title="T", author="X", subject="S", keywords="k1,k2")
    pdf.text("body")
  assert_valid_pdf(path)

#---------------------------------------------------------------------------------- Inline

def test_render_rich_basic(tmp_path):
  path = tmp_path / "rich.pdf"
  with PDF(str(path)) as pdf:
    segs = [
      RichSegment("Hello ", family="Helvetica", mode="Regular", size=11),
      RichSegment("bold", family="Helvetica", mode="Bold", size=11),
      RichSegment(" and ", family="Helvetica", mode="Regular", size=11),
      RichSegment("code", family="Courier", mode="Regular", size=11,
        bg_color=(0.95, 0.95, 0.95)),
      RichSegment(".", family="Helvetica", mode="Regular", size=11),
    ]
    render_rich(pdf, segs, width_mm=120, x_mm=0, y_mm=0)
  assert_valid_pdf(path)

#---------------------------------------------------------------------------------- Styles

def test_style_presets_independent():
  # Each access must yield a fresh Style so users can't accidentally
  # mutate shared state by tweaking a preset.
  a = Styles.BOLD
  b = Styles.BOLD
  assert a is not b
  a.font_size = 99
  assert b.font_size != 99
