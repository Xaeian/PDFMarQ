# tests/test_cross_lib.py

"""Cross-library parity: same markdown through `pdfmarq` and `docmarq` must both render."""

from pathlib import Path
import pytest
from pdfmarq.md import md_to_pdf, MarkdownStyle as PdfStyle
from docmarq.md import md_to_docx, MarkdownStyle as DocStyle

#------------------------------------------------------------------------------ Shared sources

_BASIC = "# Title\n\nFirst paragraph with **bold** and *italic*."
_TABLE = (
  "| A | B |\n|---|--:|\n| a | 1 |\n| b | 2 |\n"
)
_LISTS_CODE = (
  "## Recipe\n\n- prep\n- mix\n- bake\n\n"
  "```python\ndef hello():\n  return 42\n```\n"
)
_CALLOUT_QUOTE_HR = (
  "> [!NOTE]\n> Pay attention.\n\n> A normal quote.\n\n---\n\nAfter horizontal rule."
)
_FRONTMATTER = (
  "---\ntitle: Cross-lib doc\nauthor: Xaeian\nrender:\n  landscape: false\n---\n\n"
  "# Body\n\nContent here."
)

#----------------------------------------------------------------------------------- Helpers

@pytest.fixture
def is_pdf():
  def _check(path:Path) -> bool:
    with Path(path).open("rb") as f:
      return f.read(5) == b"%PDF-"
  return _check

@pytest.fixture
def is_docx():
  def _check(path:Path) -> bool:
    with Path(path).open("rb") as f:
      return f.read(4) == b"PK\x03\x04"
  return _check

@pytest.fixture
def render_both(tmp_path):
  def _render(src:str, name:str):
    pdf_path = tmp_path / f"{name}.pdf"
    docx_path = tmp_path / f"{name}.docx"
    md_to_pdf(src, str(pdf_path))
    md_to_docx(src, str(docx_path))
    return pdf_path, docx_path
  return _render

#--------------------------------------------------------------------------- Same-source render

@pytest.mark.parametrize("name, src", [
  ("basic", _BASIC),
  ("table", _TABLE),
  ("lists_code", _LISTS_CODE),
  ("callout_quote_hr", _CALLOUT_QUOTE_HR),
  ("frontmatter", _FRONTMATTER),
])
def same_source_renders_in_both_libs(render_both, is_pdf, is_docx, name, src):
  pdf_path, docx_path = render_both(src, name)
  assert is_pdf(pdf_path), f"PDF render failed for {name!r}"
  assert is_docx(docx_path), f"DOCX render failed for {name!r}"
  assert pdf_path.stat().st_size > 200
  assert docx_path.stat().st_size > 2000

def landscape_from_frontmatter_consistent(tmp_path):
  # `render.landscape: true` in YAML flips orientation in BOTH libs
  src = "---\nrender:\n  landscape: true\n---\n\n# Wide"
  pdf = md_to_pdf(src, str(tmp_path / "ls.pdf"))
  doc = md_to_docx(src, str(tmp_path / "ls.docx"))
  assert pdf.page_width > pdf.page_height, "pdfmarq did not flip"
  assert doc.page_width > doc.page_height, "docmarq did not flip"

def footnote_label_handled_in_both(tmp_path):
  # footnote renders without crashing default (HR) and labeled (H2) in both libs
  src = "Body[^1].\n\n[^1]: footnote text."
  md_to_pdf(src, str(tmp_path / "fn_default.pdf"))
  md_to_docx(src, str(tmp_path / "fn_default.docx"))
  md_to_pdf(src, str(tmp_path / "fn_labeled.pdf"), style=PdfStyle(footnote_label="References"))
  md_to_docx(src, str(tmp_path / "fn_labeled.docx"), style=DocStyle(footnote_label="References"))
  for name in ("fn_default", "fn_labeled"):
    assert (tmp_path / f"{name}.pdf").exists()
    assert (tmp_path / f"{name}.docx").exists()

#-------------------------------------------------------------------------------- Visual parity

def smaller_size_function_parity():
  # both libs export `smaller_size` with identical ladder semantics
  from pdfmarq.utils import smaller_size as pdf_smaller
  from docmarq.utils import smaller_size as doc_smaller
  for body in (8, 9, 10, 11, 12, 14, 16, 18, 20, 22, 24):
    assert pdf_smaller(body) == doc_smaller(body), \
      f"body={body}: pdf={pdf_smaller(body)} doc={doc_smaller(body)}"

def heading_sizes_parity():
  # same h1..h6 sizes so markdown headings render at the same scale
  from docmarq.constants import Defaults as DocDef
  p = PdfStyle()
  pdf_sizes = (p.h1_size, p.h2_size, p.h3_size, p.h4_size, p.h5_size, p.h6_size)
  doc_sizes = tuple(DocDef.HEAD_SIZES)
  assert pdf_sizes == doc_sizes, f"heading size drift: pdf={pdf_sizes} doc={doc_sizes}"

def table_font_size_derivation_parity():
  # default markdown table cell size auto-derives from body via smaller_size
  from pdfmarq.utils import smaller_size
  from docmarq.styles import TableStyle
  p = PdfStyle()
  assert p.table_size is None # None triggers derivation
  assert smaller_size(p.body_size) == 10 # body=11 → 10
  assert TableStyle().font_size is None

def footnote_font_size_derivation_parity():
  # bibliography uses the same smaller_size(body) derivation in both libs
  from pdfmarq.utils import smaller_size as pdf_smaller
  from docmarq.utils import smaller_size as doc_smaller
  for body in (10, 11, 12, 14):
    assert pdf_smaller(body) == doc_smaller(body)

def markdown_body_line_height_intentionally_different():
  # INTENTIONAL: reportlab applies line_height as a direct ratio (pdf=1.4),
  # Word multiplies the font's natural height, so docmarq=1.0 lands comparable.
  # regression guard against well-meaning "consistency" cleanup
  assert PdfStyle().line_height == 1.4
  assert DocStyle().line_height == 1.0

def mermaid_scale_parity():
  # same mermaid scale → same cache key + output regardless of pipeline
  assert PdfStyle().mermaid_scale == DocStyle().mermaid_scale

def banner_title_size_parity():
  assert PdfStyle().banner_title_size == DocStyle().banner_title_size

def callout_colors_parity():
  # same per-type RGB tuples for callout border + text in both libs
  assert PdfStyle().callout_colors == DocStyle().callout_colors

def mark_bg_default_parity():
  # both libs default `mark_bg` to the same named highlight ('yellow')
  assert PdfStyle().mark_bg == DocStyle().mark_bg == "yellow"

def lang_presets_do_not_set_footnote_label():
  # footnote label is OFF by default in all language presets in both libs
  from pdfmarq.md.presets import LANG_PRESETS as PdfPresets
  from docmarq.md.presets import LANG_PRESETS as DocPresets
  for lang, preset in PdfPresets.items():
    assert "footnote_label" not in preset, f"pdfmarq lang={lang!r} sets footnote_label"
  for lang, preset in DocPresets.items():
    assert "footnote_label" not in preset, f"docmarq lang={lang!r} sets footnote_label"

def body_family_intentionally_different():
  # INTENTIONAL: pdfmarq → Vera (bundled, has Polish glyphs), docmarq → Calibri
  # (Word native). regression guard against well-meaning "consistency" cleanup
  assert PdfStyle().body_family != DocStyle().body_family
  assert PdfStyle().body_family == "Vera"
  assert DocStyle().body_family == "Calibri"

def md_to_signatures_share_arg_names():
  # md_to_pdf and md_to_docx accept the same cross-lib keyword subset
  import inspect
  pdf_params = set(inspect.signature(md_to_pdf).parameters)
  doc_params = set(inspect.signature(md_to_docx).parameters)
  shared = {"md_text", "output_path", "style", "width", "height", "margin",
    "metadata", "landscape", "base_dir"}
  assert not (shared - pdf_params), f"md_to_pdf missing: {shared - pdf_params}"
  assert not (shared - doc_params), f"md_to_docx missing: {shared - doc_params}"
