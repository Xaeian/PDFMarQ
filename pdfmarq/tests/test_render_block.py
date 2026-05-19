"""Frontmatter `render:` block tests.

Covers parser, precedence (`defaults < lang < render < caller`), hard break
on top-level `landscape:`, and edge cases. Symmetric checks across pdfmarq
and docmarq so behavior stays in lock-step.
"""
import warnings
import pytest
from pdfmarq.md import md_to_pdf, MarkdownStyle as PdfStyle
from pdfmarq.md.render import (
  parse_render_block as pdf_parse, build_style as pdf_build,
  RenderConfig as PdfRender,
)
from docmarq.md import md_to_docx, MarkdownStyle as DocStyle
from docmarq.md.render import (
  parse_render_block as doc_parse, build_style as doc_build,
  RenderConfig as DocRender,
)
from pdfmarq.tests.conftest import assert_valid_pdf
from docmarq.tests.conftest import assert_valid_docx

#---------------------------------------------------------------------- Pure parser

@pytest.mark.parametrize("parser", [pdf_parse, doc_parse])
class TestParser:
  """Parser parity across both libs."""

  def test_empty_fm_returns_empty(self, parser):
    r = parser(None)
    assert all(getattr(r, f) is None for f in
      ("page", "margin", "landscape", "font", "lang"))

  def test_no_render_block_returns_empty(self, parser):
    r = parser({"title": "X"})
    assert r.page is None and r.landscape is None

  def test_render_block_must_be_mapping(self, parser):
    with warnings.catch_warnings(record=True) as w:
      warnings.simplefilter("always")
      r = parser({"render": "not a dict"})
    assert r.page is None
    assert any("must be a mapping" in str(x.message) for x in w)

  def test_unknown_key_warns_and_drops(self, parser):
    with warnings.catch_warnings(record=True) as w:
      warnings.simplefilter("always")
      r = parser({"render": {"page": "A4", "foo": 1}})
    assert r.page is not None
    assert any("unknown" in str(x.message).lower() for x in w)

  def test_page_string_preset(self, parser):
    r = parser({"render": {"page": "A4"}})
    assert r.page is not None and r.page.width == 210

  def test_page_case_insensitive(self, parser):
    r = parser({"render": {"page": "a4"}})
    assert r.page is not None and r.page.width == 210

  def test_page_unknown_preset_warns(self, parser):
    with warnings.catch_warnings(record=True) as w:
      warnings.simplefilter("always")
      r = parser({"render": {"page": "B5"}})
    assert r.page is None
    assert any("unknown" in str(x.message).lower() for x in w)

  def test_page_list_rejected_with_helpful_msg(self, parser):
    # Custom dims are intentionally NOT supported in frontmatter.
    with warnings.catch_warnings(record=True) as w:
      warnings.simplefilter("always")
      r = parser({"render": {"page": [210, 297]}})
    assert r.page is None
    assert any("preset" in str(x.message).lower() for x in w)

  def test_margin_scalar(self, parser):
    r = parser({"render": {"margin": 25}})
    assert r.margin == 25

  def test_margin_list_4(self, parser):
    r = parser({"render": {"margin": [10, 20, 30, 15]}})
    assert r.margin == [10, 20, 30, 15]

  def test_margin_too_many_elements_warns(self, parser):
    with warnings.catch_warnings(record=True) as w:
      warnings.simplefilter("always")
      r = parser({"render": {"margin": [10, 20, 30, 15, 5]}})
    assert r.margin is None

  def test_margin_negative_warns(self, parser):
    with warnings.catch_warnings(record=True) as w:
      warnings.simplefilter("always")
      r = parser({"render": {"margin": -5}})
    assert r.margin is None

  def test_landscape_bool(self, parser):
    assert parser({"render": {"landscape": True}}).landscape is True
    assert parser({"render": {"landscape": False}}).landscape is False

  def test_landscape_non_bool_warns(self, parser):
    with warnings.catch_warnings(record=True) as w:
      warnings.simplefilter("always")
      r = parser({"render": {"landscape": "yes"}})
    assert r.landscape is None

  def test_gutter_zero_allowed(self, parser):
    r = parser({"render": {"gutter": 0}})
    assert r.gutter == 0.0

  def test_gutter_positive(self, parser):
    assert parser({"render": {"gutter": 10}}).gutter == 10.0

  def test_font_string(self, parser):
    r = parser({"render": {"font": "Inter"}})
    assert r.font == "Inter"

  def test_font_size_positive(self, parser):
    assert parser({"render": {"font_size": 11}}).font_size == 11.0

  def test_font_size_negative_warns(self, parser):
    with warnings.catch_warnings(record=True) as w:
      warnings.simplefilter("always")
      r = parser({"render": {"font_size": -1}})
    assert r.font_size is None

  def test_lang_string(self, parser):
    assert parser({"render": {"lang": "pl"}}).lang == "pl"

  def test_all_fields(self, parser):
    r = parser({"render": {
      "page": "A5", "margin": 15, "landscape": True, "gutter": 5,
      "font": "Inter", "font_size": 10, "head_font": "Inter",
      "mono_font": "Consolas", "line_height": 1.3,
      "banner": False, "header": True, "page_number": True,
      "lang": "pl",
    }})
    assert r.page is not None and r.page.width == 148
    assert r.margin == 15 and r.landscape is True
    assert r.gutter == 5.0 and r.font == "Inter"
    assert r.font_size == 10.0 and r.line_height == 1.3
    assert r.banner is False and r.header is True
    assert r.page_number is True and r.lang == "pl"

#---------------------------------------------------------------------- Parser parity

@pytest.mark.parametrize("block", [
  {"page": "A4"},
  {"margin": [10, 20, 30, 40]},
  {"landscape": True, "gutter": 5},
  {"font": "Inter", "font_size": 11},
  {"banner": True, "page_number": False},
  {"lang": "pl"},
])
def test_both_parsers_produce_same_result(block):
  fm = {"render": block}
  a = pdf_parse(fm)
  b = doc_parse(fm)
  from dataclasses import fields
  for f in fields(a):
    av, bv = getattr(a, f.name), getattr(b, f.name)
    if hasattr(av, "width") and hasattr(bv, "width"):
      assert (av.width, av.height) == (bv.width, bv.height)
    else:
      assert av == bv, f"{f.name}: pdf={av} doc={bv}"

#------------------------------------------------------------------- Style precedence

def test_caller_explicit_field_wins_over_render_pdf():
  """Caller's non-default `body_family` overrides `render.font`."""
  caller = PdfStyle(body_family="Inter")
  render = PdfRender(font="Calibri")
  s = pdf_build(None, caller, render)
  assert s.body_family == "Inter"

def test_render_applies_when_caller_at_default_pdf():
  """Caller passes default style → frontmatter `render` wins."""
  caller = PdfStyle()  # all defaults
  render = PdfRender(font="Calibri")
  s = pdf_build(None, caller, render)
  assert s.body_family == "Calibri"

def test_lang_preset_applied_when_no_caller_override_pdf():
  """`render.lang` populates locale-driven fields; caller defaults yield."""
  caller = PdfStyle()
  render = PdfRender(lang="pl")
  s = pdf_build(None, caller, render)
  assert s.page_number_label == "Strona"

def test_caller_overrides_lang_preset_field_pdf():
  """Caller's explicit field beats lang preset."""
  caller = PdfStyle(page_number_label="MyPage")
  render = PdfRender(lang="pl")
  s = pdf_build(None, caller, render)
  assert s.page_number_label == "MyPage"

def test_page_number_false_disables_label_pdf():
  render = PdfRender(page_number=False)
  s = pdf_build(None, PdfStyle(), render)
  assert s.page_number_label is None

#----------------------------------------------------------------------- End-to-end

def test_render_page_a5(tmp_path):
  src = "---\nrender:\n  page: A5\n---\n\n# Body"
  pdf = md_to_pdf(src, str(tmp_path / "a5.pdf"))
  # A5: 148 x 210
  assert pdf.page_width == 148 and pdf.page_height == 210

def test_render_landscape(tmp_path):
  src = "---\nrender:\n  page: A4\n  landscape: true\n---\n\n# Body"
  pdf = md_to_pdf(src, str(tmp_path / "ls.pdf"))
  assert pdf.page_width > pdf.page_height

def test_render_gutter_adds_to_left_margin_pdf(tmp_path):
  src = "---\nrender:\n  margin: 20\n  gutter: 10\n---\n\n# Body"
  pdf = md_to_pdf(src, str(tmp_path / "gut.pdf"))
  assert pdf._page.margin_left == 30  # 20 + 10
  assert pdf._page.margin_right == 20

def test_render_docx_gutter_native(tmp_path):
  src = "---\nrender:\n  gutter: 10\n---\n\n# Body"
  doc = md_to_docx(src, str(tmp_path / "gut.docx"))
  assert doc._page.gutter == 10.0

def test_caller_width_overrides_render_page(tmp_path):
  """When caller passes explicit `width=`, render.page is ignored."""
  src = "---\nrender:\n  page: A5\n---\n\n# Body"
  pdf = md_to_pdf(src, str(tmp_path / "w.pdf"), width=200, height=250)
  assert pdf.page_width == 200 and pdf.page_height == 250

def test_no_frontmatter_defaults_to_a4(tmp_path):
  pdf = md_to_pdf("# Body", str(tmp_path / "def.pdf"))
  assert pdf.page_width == 210 and pdf.page_height == 297

#--------------------------------------------------------------------- Hard break

def test_top_level_landscape_warns_and_ignored_pdf(tmp_path):
  src = "---\nlandscape: true\n---\n\n# Body"
  with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter("always")
    pdf = md_to_pdf(src, str(tmp_path / "tl.pdf"))
  msgs = [str(x.message) for x in w if "landscape" in str(x.message).lower()]
  assert msgs, "expected deprecation warning"
  # Portrait preserved despite the directive
  assert pdf.page_width < pdf.page_height

def test_top_level_landscape_warns_and_ignored_docx(tmp_path):
  src = "---\nlandscape: true\n---\n\n# Body"
  with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter("always")
    doc = md_to_docx(src, str(tmp_path / "tl.docx"))
  msgs = [str(x.message) for x in w if "landscape" in str(x.message).lower()]
  assert msgs
  assert doc.page_width < doc.page_height

#------------------------------------------------------------------ Cross-lib smoke

def test_render_block_works_in_both_libs(tmp_path):
  # `font: Vera` keeps pdfmarq happy (bundled with reportlab); docmarq
  # tolerates absent fonts (Word substitutes at open time).
  src = (
    "---\n"
    "title: T\n"
    "render:\n"
    "  page: A5\n"
    "  margin: 15\n"
    "  landscape: true\n"
    "  font: Vera\n"
    "  lang: pl\n"
    "---\n\n"
    "# Body[^1]\n\nText.\n\n[^1]: footnote"
  )
  pdf = md_to_pdf(src, str(tmp_path / "x.pdf"))
  doc = md_to_docx(src, str(tmp_path / "x.docx"))
  assert pdf.page_width > pdf.page_height
  assert doc.page_width > doc.page_height
  assert_valid_pdf(tmp_path / "x.pdf")
  assert_valid_docx(tmp_path / "x.docx")
