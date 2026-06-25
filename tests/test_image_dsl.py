# tests/test_image_dsl.py

"""Markdown image title DSL: exhaustive pure parser + smoke-level end-to-end render."""

import warnings
import pytest
from conftest import assert_valid_pdf, assert_valid_docx
from pdfmarq.md.md_images import parse_image_dsl as pdf_parse, ImageDSL as PdfDSL
from docmarq.md.image_utils import parse_image_dsl as doc_parse, ImageDSL as DocDSL
from pdfmarq.md import md_to_pdf
from docmarq.md import md_to_docx

#-------------------------------------------------------------------------- Pure parser

@pytest.mark.parametrize("parser", [pdf_parse, doc_parse])
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

#----------------------------------------------------------------------- Cross-parser parity

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
def parsers_produce_same_result(title):
  a = pdf_parse(title)
  b = doc_parse(title)
  for f in ("exact_w_mm", "exact_h_mm", "max_w_mm", "max_h_mm", "scale", "align"):
    assert getattr(a, f) == getattr(b, f), \
      f"{f}: pdf={getattr(a, f)} doc={getattr(b, f)}"

#------------------------------------------------------------------------- End-to-end render

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

def dsl_align_applied_in_docx(tmp_path, make_img):
  make_img()
  src = '![a](img.png "align=R")'
  path = tmp_path / "align.docx"
  md_to_docx(src, str(path), base_dir=str(tmp_path))
  from docx import Document
  doc = Document(str(path))
  image_paras = [p for p in doc.paragraphs if p.runs]
  assert image_paras, "no paragraphs with content found"
  # `align_to_docx("R") -> WD_ALIGN_PARAGRAPH.RIGHT` (int 2)
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
