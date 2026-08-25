# tests/test_image_dsl.py

"""Markdown image title DSL: exhaustive pure parser + smoke-level end-to-end render."""

import warnings
import pytest
from conftest import assert_valid_pdf, assert_valid_docx, needs_twin
from pdfmarq.md.md_images import (parse_image_dsl as pdf_parse, ImageDSL as PdfDSL,
  ImageInfo as PdfInfo, size_block as pdf_size_block)
from pdfmarq.md import md_to_pdf
try:
  from docmarq.md.image_utils import parse_image_dsl as doc_parse, ImageDSL as DocDSL
  from docmarq.md import md_to_docx
except ImportError:  # the twin ships separately; `needs_twin` skips what needs it
  doc_parse = DocDSL = md_to_docx = None

# both parsers when the twin is here, ours alone when it is not
PARSERS = [pdf_parse] + ([doc_parse] if doc_parse else [])

#-------------------------------------------------------------------------------------- Pure parser

@pytest.mark.parametrize("parser", PARSERS)
class TestParser:
  """Each parser must accept identical input and produce equivalent output."""

  def empty_title_returns_no_dsl(self, parser):
    assert parser("").is_dsl is False

  def none_title_returns_no_dsl(self, parser):
    assert parser(None).is_dsl is False

  def caption_title_no_equals_silent(self, parser):
    # title without any `=` token is treated as opaque description
    with warnings.catch_warnings(record=True) as w:
      warnings.simplefilter("always")
      d = parser("Just a description")
    assert d.is_dsl is False
    assert not w, f"unexpected warnings: {[str(x.message) for x in w]}"

  def single_key_value(self, parser):
    d = parser("max_h=60")
    assert d.is_dsl is True and d.max_h_mm == 60.0

  def multiple_keys(self, parser):
    d = parser("max_h=80 align=R")
    assert d.max_h_mm == 80.0 and d.align == "R"

  def exact_w_and_h(self, parser):
    d = parser("w=100 h=60")
    assert d.exact_w_mm == 100.0 and d.exact_h_mm == 60.0

  def scale(self, parser):
    assert parser("scale=0.5").scale == 0.5

  def align_values(self, parser):
    assert parser("align=L").align == "L"
    assert parser("align=C").align == "C"
    assert parser("align=R").align == "R"

  def case_insensitive_keys(self, parser):
    d = parser("MAX_H=50 ALIGN=c SCALE=2")
    assert d.max_h_mm == 50.0 and d.align == "C" and d.scale == 2.0

  def order_independent(self, parser):
    a = parser("w=100 h=50")
    b = parser("h=50 w=100")
    assert (a.exact_w_mm, a.exact_h_mm) == (b.exact_w_mm, b.exact_h_mm)

  def unknown_key_warns(self, parser):
    with warnings.catch_warnings(record=True) as w:
      warnings.simplefilter("always")
      d = parser("max_h=50 foo=1")
    assert d.max_h_mm == 50.0
    assert any("unknown" in str(x.message).lower() for x in w)

  def invalid_value_warns(self, parser):
    with warnings.catch_warnings(record=True) as w:
      warnings.simplefilter("always")
      d = parser("max_h=zzz")
    assert d.max_h_mm is None
    assert any("not a number" in str(x.message).lower() for x in w)

  def negative_value_warns(self, parser):
    with warnings.catch_warnings(record=True) as w:
      warnings.simplefilter("always")
      d = parser("max_h=-10")
    assert d.max_h_mm is None
    assert any("> 0" in str(x.message) for x in w)

  def zero_value_warns(self, parser):
    with warnings.catch_warnings(record=True):
      warnings.simplefilter("always")
      d = parser("scale=0")
    assert d.scale is None

  def invalid_align_warns(self, parser):
    with warnings.catch_warnings(record=True) as w:
      warnings.simplefilter("always")
      d = parser("align=X")
    assert d.align is None
    assert any("l/c/r" in str(x.message).lower() for x in w)

  def mixed_caption_and_dsl_warns_on_caption(self, parser):
    with warnings.catch_warnings(record=True) as w:
      warnings.simplefilter("always")
      d = parser("Some caption scale=0.5")
    assert d.scale == 0.5
    assert any("key=value" in str(x.message) for x in w)

#------------------------------------------------------------------------------ Cross-parser parity

@needs_twin
def parsers_produce_same_field_set():
  # both libs share field names so a parsed DSL is interchangeable shape
  from dataclasses import fields
  pf = {f.name for f in fields(PdfDSL())}
  df = {f.name for f in fields(DocDSL())}
  assert pf == df

@pytest.mark.parametrize("title", [
  "w=100",
  "h=50",
  "w=80 h=40",
  "scale=0.75",
  "max_w=120 max_h=80",
  "align=L",
  "max_h=60 align=R",
])
@needs_twin
def parsers_produce_same_result(title):
  a = pdf_parse(title)
  b = doc_parse(title)
  for f in ("exact_w_mm", "exact_h_mm", "max_w_mm", "max_h_mm", "scale", "align"):
    assert getattr(a, f) == getattr(b, f), \
      f"{f}: pdf={getattr(a, f)} doc={getattr(b, f)}"

#-------------------------------------------------------------------------------- End-to-end render

@pytest.fixture
def make_img(tmp_path):
  def _make(name="img.png", size=(400, 300)):
    from PIL import Image
    p = tmp_path / name
    Image.new("RGB", size, (100, 150, 200)).save(p)
    return p
  return _make

def dsl_renders_in_pdf(tmp_path, make_img):
  make_img()
  src = (
    '![a](img.png)\n\n'
    '![b](img.png "max_h=30")\n\n'
    '![c](img.png "w=60 align=R")\n\n'
    '![d](img.png "scale=0.3")\n'
  )
  path = tmp_path / "dsl.pdf"
  md_to_pdf(src, str(path), base_dir=str(tmp_path))
  assert_valid_pdf(path)

@needs_twin
def dsl_renders_in_docx(tmp_path, make_img):
  make_img()
  src = (
    '![a](img.png "max_h=30")\n\n'
    '![b](img.png "scale=0.5")\n\n'
    '![c](img.png "align=L")\n'
  )
  path = tmp_path / "dsl.docx"
  md_to_docx(src, str(path), base_dir=str(tmp_path))
  assert_valid_docx(path)

@needs_twin
def dsl_align_applied_in_docx(tmp_path, make_img):
  make_img()
  src = '![a](img.png "align=R")'
  path = tmp_path / "align.docx"
  md_to_docx(src, str(path), base_dir=str(tmp_path))
  from docx import Document
  doc = Document(str(path))
  image_paras = [p for p in doc.paragraphs if p.runs]
  assert image_paras, "no paragraphs with content found"
  # `align_to_docx("R") → WD_ALIGN_PARAGRAPH.RIGHT` (int 2)
  assert image_paras[0].alignment == 2

def caption_only_title_renders_without_warnings(tmp_path, make_img):
  # legacy plain-text title (caption) keeps working silently - no parser warnings
  make_img()
  src = '![a](img.png "An informative caption")'
  path = tmp_path / "caption.pdf"
  with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter("always")
    md_to_pdf(src, str(path), base_dir=str(tmp_path))
  dsl_warns = [x for x in w if "image title" in str(x.message).lower()]
  assert not dsl_warns, f"unexpected DSL warnings: {dsl_warns}"
  assert_valid_pdf(path)

def scale_priority_over_other_keys(tmp_path, make_img):
  # when `scale` is present, w/h/max_* are ignored; output renders fine
  make_img()
  src = '![a](img.png "scale=0.5 w=999 max_h=999")'
  path = tmp_path / "prio.pdf"
  md_to_pdf(src, str(path), base_dir=str(tmp_path))
  assert_valid_pdf(path)

#--------------------------------------------------------------------------------------- Image rows

@pytest.fixture
def block_widths(monkeypatch):
  """Widths of every image drawn as a block figure during a render."""
  from pdfmarq import PDF
  seen = []
  orig = PDF.image
  def spy(self, src, w=None, h=None, *a, **k):
    seen.append(w)
    return orig(self, src, w, h, *a, **k)
  monkeypatch.setattr(PDF, "image", spy)
  return seen

def images_in_one_paragraph_share_the_width(tmp_path, make_img, block_widths):
  # two images on consecutive lines are one paragraph, so they are figures, not icons
  make_img("a.png", (1200, 800))
  make_img("b.png", (1200, 800))
  md_to_pdf("![](a.png)\n![](b.png)", str(tmp_path / "row.pdf"), base_dir=str(tmp_path))
  assert len(block_widths) == 2, f"expected a row of two, got {block_widths}"
  assert block_widths[0] == pytest.approx(block_widths[1])
  assert block_widths[0] > 60, f"row image still at inline scale: {block_widths[0]}mm"

def images_wrap_into_a_balanced_grid(tmp_path, make_img, block_widths):
  # 7 fit across; the 8th wraps to 4+4, so every figure gets wider, not smaller
  for i in range(8):
    make_img(f"i{i}.png", (1200, 800))
  def widths(n, name):
    block_widths.clear()
    md_to_pdf("\n".join(f"![](i{i}.png)" for i in range(n)),
      str(tmp_path / name), base_dir=str(tmp_path))
    return [round(w, 2) for w in block_widths]
  seven, eight = widths(7, "seven.pdf"), widths(8, "eight.pdf")
  assert len(seven) == 7 and len(set(seven)) == 1
  assert len(eight) == 8 and len(set(eight)) == 1
  assert eight[0] > seven[0], f"wrapped, not shrunk: {eight[0]} vs {seven[0]}"

def a_missing_file_stacks_the_row(tmp_path, make_img, block_widths):
  # the broken one prints a placeholder, the good ones still get drawn
  make_img("a.png", (1200, 800))
  make_img("b.png", (1200, 800))
  md_to_pdf("![](a.png)\n![](nope.png)\n![](b.png)",
    str(tmp_path / "miss.pdf"), base_dir=str(tmp_path))
  assert len(block_widths) == 2, f"good images dropped: {block_widths}"
  assert len(set(round(w, 2) for w in block_widths)) == 1

def image_with_text_stays_inline(tmp_path, make_img, block_widths):
  make_img("a.png", (1200, 800))
  md_to_pdf("text ![](a.png) more", str(tmp_path / "inline.pdf"), base_dir=str(tmp_path))
  assert not block_widths, "mid-sentence image was promoted to a block figure"

#------------------------------------------------------------------------------------- Block sizing

def info(nat_w=100.0, nat_h=50.0, dpi=96, **kw):
  """`ImageInfo` without touching the disk - sizing rules are pure."""
  return PdfInfo(src="x.png", is_svg=False, nat_w_mm=nat_w, nat_h_mm=nat_h, dpi=dpi, **kw)
info.__test__ = False

def raster_spends_surplus_dpi_on_width():
  # 300-DPI export: natural 101.6mm, but the pixels carry it to full width
  w, h = pdf_size_block(info(101.6, 67.7, dpi=300), 170, 120)
  assert w == pytest.approx(170) and h == pytest.approx(113.3, abs=0.5)

def raster_without_surplus_dpi_keeps_natural_size():
  # a 96px icon has nothing to spend - blowing it up would only blur it
  w, h = pdf_size_block(info(25.4, 12.7), 170, 120)
  assert (w, h) == pytest.approx((25.4, 12.7))

def raster_stops_at_min_dpi():
  # 600x400 @ 300dpi → as wide as 150dpi allows, not the full 170mm
  w, _ = pdf_size_block(info(50.8, 33.9, dpi=300), 170, 120)
  assert w == pytest.approx(101.6)

def raster_wider_than_page_still_shrinks():
  w, h = pdf_size_block(info(317.5, 211.7), 170, 120)
  assert w == pytest.approx(170) and h == pytest.approx(113.3, abs=0.5)

def min_dpi_zero_always_fills_width():
  w, _ = pdf_size_block(info(25.4, 12.7), 170, 120, min_dpi=0)
  assert w == pytest.approx(170)

def block_height_capped_by_max_h():
  w, h = pdf_size_block(info(200, 400, dpi=300), 170, 120)
  assert h == pytest.approx(120) and w == pytest.approx(60)

def svg_fills_width_but_respects_max_h():
  # a tall SVG answers to the height cap like any other figure
  svg = PdfInfo(src="x.svg", is_svg=True, nat_w_mm=10, nat_h_mm=40, dsl_max_h_mm=30)
  w, h = pdf_size_block(svg, 170, 0)
  assert h == pytest.approx(30) and w == pytest.approx(7.5)

def explicit_width_wins_over_dpi_budget():
  w, h = pdf_size_block(info(25.4, 12.7, explicit_w_mm=80), 170, 120)
  assert w == pytest.approx(80) and h == pytest.approx(40)
