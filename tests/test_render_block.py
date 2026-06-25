# tests/test_render_block.py

"""Frontmatter `render:` block: parser, precedence, hard-break on top-level `landscape:`."""

import warnings
import pytest
from conftest import assert_valid_pdf, assert_valid_docx
from pdfmarq.md import md_to_pdf, MarkdownStyle as PdfStyle
from pdfmarq.md.render import (
  parse_render_block as pdf_parse, build_style as pdf_build,
  RenderConfig as PdfRender,
)
from docmarq.md import md_to_docx
from docmarq.md.render import parse_render_block as doc_parse

#---------------------------------------------------------------------------- Pure parser

@pytest.mark.parametrize("parser", [pdf_parse, doc_parse])
class TestParser:
  """Parser parity across both libs."""

  def empty_fm_returns_empty(self, parser):
    r = parser(None)
    assert all(getattr(r, f) is None for f in
      ("page", "margin", "landscape", "font_body", "lang"))

  def no_render_block_returns_empty(self, parser):
    r = parser({"title": "X"})
    assert r.page is None and r.landscape is None

  def render_block_must_be_mapping(self, parser):
    with warnings.catch_warnings(record=True) as w:
      warnings.simplefilter("always")
      r = parser({"render": "not a dict"})
    assert r.page is None
    assert any("must be a mapping" in str(x.message) for x in w)

  def unknown_key_warns_and_drops(self, parser):
    with warnings.catch_warnings(record=True) as w:
      warnings.simplefilter("always")
      r = parser({"render": {"page": "A4", "foo": 1}})
    assert r.page is not None
    assert any("unknown" in str(x.message).lower() for x in w)

  def page_string_preset(self, parser):
    r = parser({"render": {"page": "A4"}})
    assert r.page is not None and r.page.width == 210

  def page_case_insensitive(self, parser):
    r = parser({"render": {"page": "a4"}})
    assert r.page is not None and r.page.width == 210

  def page_unknown_preset_warns(self, parser):
    with warnings.catch_warnings(record=True) as w:
      warnings.simplefilter("always")
      r = parser({"render": {"page": "B5"}})
    assert r.page is None
    assert any("unknown" in str(x.message).lower() for x in w)

  def page_list_rejected_with_helpful_msg(self, parser):
    # custom dims are intentionally NOT supported in frontmatter
    with warnings.catch_warnings(record=True) as w:
      warnings.simplefilter("always")
      r = parser({"render": {"page": [210, 297]}})
    assert r.page is None
    assert any("preset" in str(x.message).lower() for x in w)

  def margin_scalar(self, parser):
    assert parser({"render": {"margin": 25}}).margin == 25

  def margin_list_4(self, parser):
    assert parser({"render": {"margin": [10, 20, 30, 15]}}).margin == [10, 20, 30, 15]

  def margin_too_many_elements_warns(self, parser):
    with warnings.catch_warnings(record=True):
      warnings.simplefilter("always")
      r = parser({"render": {"margin": [10, 20, 30, 15, 5]}})
    assert r.margin is None

  def margin_negative_warns(self, parser):
    with warnings.catch_warnings(record=True):
      warnings.simplefilter("always")
      r = parser({"render": {"margin": -5}})
    assert r.margin is None

  def landscape_bool(self, parser):
    assert parser({"render": {"landscape": True}}).landscape is True
    assert parser({"render": {"landscape": False}}).landscape is False

  def landscape_non_bool_warns(self, parser):
    with warnings.catch_warnings(record=True):
      warnings.simplefilter("always")
      r = parser({"render": {"landscape": "yes"}})
    assert r.landscape is None

  def gutter_zero_allowed(self, parser):
    assert parser({"render": {"gutter": 0}}).gutter == 0.0

  def gutter_positive(self, parser):
    assert parser({"render": {"gutter": 10}}).gutter == 10.0

  def font_string(self, parser):
    assert parser({"render": {"font_body": "Inter"}}).font_body == "Inter"

  def font_size_positive(self, parser):
    assert parser({"render": {"font_size": 11}}).font_size == 11.0

  def font_size_negative_warns(self, parser):
    with warnings.catch_warnings(record=True):
      warnings.simplefilter("always")
      r = parser({"render": {"font_size": -1}})
    assert r.font_size is None

  def lang_string(self, parser):
    assert parser({"render": {"lang": "pl"}}).lang == "pl"

  def all_fields(self, parser):
    r = parser({"render": {
      "page": "A5", "margin": 15, "landscape": True, "gutter": 5,
      "font_body": "Inter", "font_size": 10, "font_head": "Inter",
      "font_mono": "Consolas", "line_height": 1.3,
      "banner": False, "header": True, "page_number": True,
      "lang": "pl",
    }})
    assert r.page is not None and r.page.width == 148
    assert r.margin == 15 and r.landscape is True
    assert r.gutter == 5.0 and r.font_body == "Inter"
    assert r.font_size == 10.0 and r.line_height == 1.3
    assert r.banner is False and r.header is True
    assert r.page_number is True and r.lang == "pl"

#---------------------------------------------------------------------- Parser parity

@pytest.mark.parametrize("block", [
  {"page": "A4"},
  {"margin": [10, 20, 30, 40]},
  {"landscape": True, "gutter": 5},
  {"font_body": "Inter", "font_size": 11},
  {"banner": True, "page_number": False},
  {"lang": "pl"},
])
def both_parsers_produce_same_result(block):
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

def caller_explicit_field_wins_over_render_pdf():
  # caller's non-default `body_family` overrides `render.font_body`
  s = pdf_build(None, PdfStyle(body_family="Inter"), PdfRender(font_body="Calibri"))
  assert s.body_family == "Inter"

def render_applies_when_caller_at_default_pdf():
  # caller passes default style → frontmatter `render` wins
  s = pdf_build(None, PdfStyle(), PdfRender(font_body="Calibri"))
  assert s.body_family == "Calibri"

def lang_preset_applied_when_no_caller_override_pdf():
  # `render.lang` populates locale-driven fields; caller defaults yield
  s = pdf_build(None, PdfStyle(), PdfRender(lang="pl"))
  assert s.page_number_label == "Strona"

def caller_overrides_lang_preset_field_pdf():
  # caller's explicit field beats lang preset
  s = pdf_build(None, PdfStyle(page_number_label="MyPage"), PdfRender(lang="pl"))
  assert s.page_number_label == "MyPage"

def page_number_false_disables_label_pdf():
  s = pdf_build(None, PdfStyle(), PdfRender(page_number=False))
  assert s.page_number_label is None

#----------------------------------------------------------------------- End-to-end

def render_page_a5(tmp_path):
  src = "---\nrender:\n  page: A5\n---\n\n# Body"
  pdf = md_to_pdf(src, str(tmp_path / "a5.pdf"))
  assert pdf.page_width == 148 and pdf.page_height == 210 # A5: 148 x 210

def render_landscape(tmp_path):
  src = "---\nrender:\n  page: A4\n  landscape: true\n---\n\n# Body"
  pdf = md_to_pdf(src, str(tmp_path / "ls.pdf"))
  assert pdf.page_width > pdf.page_height

def render_gutter_adds_to_left_margin_pdf(tmp_path):
  src = "---\nrender:\n  margin: 20\n  gutter: 10\n---\n\n# Body"
  pdf = md_to_pdf(src, str(tmp_path / "gut.pdf"))
  assert pdf._page.margin_left == 30 # 20 + 10
  assert pdf._page.margin_right == 20

def render_docx_gutter_native(tmp_path):
  src = "---\nrender:\n  gutter: 10\n---\n\n# Body"
  doc = md_to_docx(src, str(tmp_path / "gut.docx"))
  assert doc._page.gutter == 10.0

def caller_width_overrides_render_page(tmp_path):
  # when caller passes explicit `width=`, render.page is ignored
  src = "---\nrender:\n  page: A5\n---\n\n# Body"
  pdf = md_to_pdf(src, str(tmp_path / "w.pdf"), width=200, height=250)
  assert pdf.page_width == 200 and pdf.page_height == 250

def no_frontmatter_defaults_to_a4(tmp_path):
  pdf = md_to_pdf("# Body", str(tmp_path / "def.pdf"))
  assert pdf.page_width == 210 and pdf.page_height == 297

#--------------------------------------------------------------------- Hard break

def top_level_landscape_warns_and_ignored_pdf(tmp_path):
  src = "---\nlandscape: true\n---\n\n# Body"
  with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter("always")
    pdf = md_to_pdf(src, str(tmp_path / "tl.pdf"))
  msgs = [str(x.message) for x in w if "landscape" in str(x.message).lower()]
  assert msgs, "expected deprecation warning"
  assert pdf.page_width < pdf.page_height # portrait preserved despite directive

def top_level_landscape_warns_and_ignored_docx(tmp_path):
  src = "---\nlandscape: true\n---\n\n# Body"
  with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter("always")
    doc = md_to_docx(src, str(tmp_path / "tl.docx"))
  msgs = [str(x.message) for x in w if "landscape" in str(x.message).lower()]
  assert msgs
  assert doc.page_width < doc.page_height

#------------------------------------------------------------------ Cross-lib smoke

def render_block_works_in_both_libs(tmp_path):
  # `font: Vera` keeps pdfmarq happy; docmarq tolerates absent fonts
  src = (
    "---\ntitle: T\nrender:\n  page: A5\n  margin: 15\n  landscape: true\n"
    "  font_body: Vera\n  lang: pl\n---\n\n# Body[^1]\n\nText.\n\n[^1]: footnote"
  )
  pdf = md_to_pdf(src, str(tmp_path / "x.pdf"))
  doc = md_to_docx(src, str(tmp_path / "x.docx"))
  assert pdf.page_width > pdf.page_height
  assert doc.page_width > doc.page_height
  assert_valid_pdf(tmp_path / "x.pdf")
  assert_valid_docx(tmp_path / "x.docx")
