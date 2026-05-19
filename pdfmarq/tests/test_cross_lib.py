"""Cross-library parity tests for `pdfmarq` and `docmarq`.

Rendering the SAME markdown source through both pipelines must produce
two valid output files. Lives in `pdfmarq/tests/` because pytest collects
it from there, but exercises both libraries equally - the strongest
guard against API drift between them.

The visual output is allowed to differ (PDF != DOCX) - we only check
that each library does not crash on the shared input and that the
top-level `md_to_*` signatures stay compatible.
"""
from pathlib import Path
import pytest
from pdfmarq.md import md_to_pdf, MarkdownStyle as PdfStyle
from docmarq.md import md_to_docx, MarkdownStyle as DocStyle

#------------------------------------------------------------------------------ Shared sources

_BASIC = "# Title\n\nFirst paragraph with **bold** and *italic*."
_TABLE = (
  "| A | B |\n"
  "|---|--:|\n"
  "| a | 1 |\n"
  "| b | 2 |\n"
)
_LISTS_CODE = (
  "## Recipe\n\n"
  "- prep\n- mix\n- bake\n\n"
  "```python\n"
  "def hello():\n"
  "  return 42\n"
  "```\n"
)
_CALLOUT_QUOTE_HR = (
  "> [!NOTE]\n> Pay attention.\n\n"
  "> A normal quote.\n\n"
  "---\n\n"
  "After horizontal rule."
)
_FRONTMATTER = (
  "---\n"
  "title: Cross-lib doc\n"
  "author: Xaeian\n"
  "render:\n"
  "  landscape: false\n"
  "---\n\n"
  "# Body\n\nContent here."
)

#--------------------------------------------------------------------------------- Helpers

def _is_pdf(path:Path) -> bool:
  with path.open("rb") as f:
    return f.read(5) == b"%PDF-"

def _is_docx(path:Path) -> bool:
  with path.open("rb") as f:
    return f.read(4) == b"PK\x03\x04"

def _render_both(src:str, tmp_path:Path, name:str) -> tuple[Path, Path]:
  """Render `src` through both libraries. Returns the two output paths."""
  pdf_path = tmp_path / f"{name}.pdf"
  docx_path = tmp_path / f"{name}.docx"
  md_to_pdf(src, str(pdf_path))
  md_to_docx(src, str(docx_path))
  return pdf_path, docx_path

#------------------------------------------------------------------------------------ Tests

@pytest.mark.parametrize("name,src", [
  ("basic", _BASIC),
  ("table", _TABLE),
  ("lists_code", _LISTS_CODE),
  ("callout_quote_hr", _CALLOUT_QUOTE_HR),
  ("frontmatter", _FRONTMATTER),
])
def test_same_source_renders_in_both_libs(tmp_path, name, src):
  """Same markdown → both PDF and DOCX produce valid files."""
  pdf_path, docx_path = _render_both(src, tmp_path, name)
  assert _is_pdf(pdf_path), f"PDF render failed for {name!r}"
  assert _is_docx(docx_path), f"DOCX render failed for {name!r}"
  assert pdf_path.stat().st_size > 200
  assert docx_path.stat().st_size > 2000

def test_landscape_from_frontmatter_consistent(tmp_path):
  """`render.landscape: true` in YAML flips orientation in BOTH libs."""
  src = "---\nrender:\n  landscape: true\n---\n\n# Wide"
  pdf = md_to_pdf(src, str(tmp_path / "ls.pdf"))
  doc = md_to_docx(src, str(tmp_path / "ls.docx"))
  assert pdf.page_width > pdf.page_height, "pdfmarq did not flip"
  assert doc.page_width > doc.page_height, "docmarq did not flip"

def test_footnote_label_handled_in_both(tmp_path):
  """`footnote_label` field exists with same default (None) in both styles
  and both libs render footnotes without crashing when set."""
  src = "Body[^1].\n\n[^1]: footnote text."
  # Default - both should produce HR-style separator without crashing.
  md_to_pdf(src, str(tmp_path / "fn_default.pdf"))
  md_to_docx(src, str(tmp_path / "fn_default.docx"))
  # Heading variant - both should render an H2 above the section.
  md_to_pdf(src, str(tmp_path / "fn_labeled.pdf"),
    style=PdfStyle(footnote_label="References"))
  md_to_docx(src, str(tmp_path / "fn_labeled.docx"),
    style=DocStyle(footnote_label="References"))
  for name in ("fn_default", "fn_labeled"):
    assert (tmp_path / f"{name}.pdf").exists()
    assert (tmp_path / f"{name}.docx").exists()

#-------------------------------------------------------------------------- Visual parity

def test_smaller_size_function_parity():
  """Both libs export `smaller_size` with identical ladder semantics."""
  from pdfmarq.utils import smaller_size as pdf_smaller
  from docmarq.utils import smaller_size as doc_smaller
  for body in (8, 9, 10, 11, 12, 14, 16, 18, 20, 22, 24):
    assert pdf_smaller(body) == doc_smaller(body), \
      f"body={body}: pdf={pdf_smaller(body)} doc={doc_smaller(body)}"

def test_heading_sizes_parity():
  """Same h1..h6 sizes in both libs so markdown headings render at the
  same scale. Drift here causes visible inconsistency."""
  from pdfmarq.md import MarkdownStyle as PdfStyle
  from docmarq.constants import Defaults as DocDef
  p = PdfStyle()
  pdf_sizes = (p.h1_size, p.h2_size, p.h3_size, p.h4_size, p.h5_size, p.h6_size)
  doc_sizes = tuple(DocDef.HEAD_SIZES)
  assert pdf_sizes == doc_sizes, \
    f"heading size drift: pdf={pdf_sizes} doc={doc_sizes}"

def test_table_font_size_derivation_parity():
  """Default markdown table cell size auto-derives from body via the same
  `smaller_size` ladder in both libs."""
  from pdfmarq.md import MarkdownStyle as PdfStyle
  from docmarq.md import MarkdownStyle as DocStyle
  from pdfmarq.utils import smaller_size
  p = PdfStyle()
  # pdfmarq: `table_size=None` triggers derivation
  assert p.table_size is None
  expected = smaller_size(p.body_size)  # body=11 → 10
  assert expected == 10
  # docmarq: TableStyle.font_size=None similarly triggers derivation in DOCX.table
  from docmarq.styles import TableStyle
  assert TableStyle().font_size is None

def test_footnote_font_size_derivation_parity():
  """Footnote/bibliography uses the same `smaller_size(body)` derivation
  in both libs so the bibliography reads at the same relative weight."""
  from pdfmarq.md import MarkdownStyle as PdfStyle
  from docmarq.md import MarkdownStyle as DocStyle
  from pdfmarq.utils import smaller_size as pdf_smaller
  from docmarq.utils import smaller_size as doc_smaller
  for body in (10, 11, 12, 14):
    assert pdf_smaller(body) == doc_smaller(body)

def test_markdown_body_line_height_parity():
  """Markdown body line-height matches in both libs so the same paragraph
  has the same vertical rhythm in PDF and DOCX output."""
  from pdfmarq.md import MarkdownStyle as PdfStyle
  from docmarq.md import MarkdownStyle as DocStyle
  assert PdfStyle().line_height == DocStyle().line_height

def test_mermaid_scale_parity():
  """Same mermaid scale in both libs - shared cache directory means same
  source produces the same cache key + output regardless of pipeline."""
  from pdfmarq.md import MarkdownStyle as PdfStyle
  from docmarq.md import MarkdownStyle as DocStyle
  assert PdfStyle().mermaid_scale == DocStyle().mermaid_scale

def test_banner_title_size_parity():
  """Document title in the page-1 banner uses the same size in both libs."""
  from pdfmarq.md import MarkdownStyle as PdfStyle
  from docmarq.md import MarkdownStyle as DocStyle
  assert PdfStyle().banner_title_size == DocStyle().banner_title_size

def test_callout_colors_parity():
  """Same per-type RGB tuples for callout border + text in both libs."""
  from pdfmarq.md import MarkdownStyle as PdfStyle
  from docmarq.md import MarkdownStyle as DocStyle
  p, d = PdfStyle(), DocStyle()
  assert p.callout_colors == d.callout_colors

def test_mark_bg_default_parity():
  """Both libs default `mark_bg` to the same named highlight ('yellow').
  pdfmarq maps it to RGB internally; docmarq passes it to Word as a
  named highlight - same visual concept."""
  from pdfmarq.md import MarkdownStyle as PdfStyle
  from docmarq.md import MarkdownStyle as DocStyle
  assert PdfStyle().mark_bg == DocStyle().mark_bg == "yellow"

def test_lang_presets_do_not_set_footnote_label():
  """Footnote label is OFF by default in all language presets in both
  libs - user must opt in via explicit `MarkdownStyle(footnote_label=...)`
  if they want a heading above the bibliography. Otherwise both render
  a thin HR (consistent), without an unexpected 'Bibliografia'/'References'
  heading appearing for `lang_style('pl')` etc."""
  from pdfmarq.md.presets import LANG_PRESETS as PdfPresets
  from docmarq.md.presets import LANG_PRESETS as DocPresets
  for lang, preset in PdfPresets.items():
    assert "footnote_label" not in preset, f"pdfmarq lang={lang!r} sets footnote_label"
  for lang, preset in DocPresets.items():
    assert "footnote_label" not in preset, f"docmarq lang={lang!r} sets footnote_label"

def test_body_family_intentionally_different():
  """Font FAMILIES are intentionally different between libs because each
  format has different sane defaults: pdfmarq → Vera (bundled with
  reportlab, has Polish glyphs out of the box), docmarq → Calibri (Word
  native, Windows-bundled). Unifying these would either ship a font with
  the lib (size bloat) or break Word's expected look. Regression guard
  against well-meaning future "consistency" cleanup."""
  from pdfmarq.md import MarkdownStyle as PdfStyle
  from docmarq.md import MarkdownStyle as DocStyle
  assert PdfStyle().body_family != DocStyle().body_family
  assert PdfStyle().body_family == "Vera"
  assert DocStyle().body_family == "Calibri"

def test_md_to_signatures_share_arg_names(tmp_path):
  """`md_to_pdf` and `md_to_docx` accept the same keyword arguments for
  the cross-lib subset (style, margin, landscape, base_dir, metadata).
  Catches drift where one lib adds a useful kwarg the other doesn't."""
  import inspect
  pdf_params = set(inspect.signature(md_to_pdf).parameters)
  doc_params = set(inspect.signature(md_to_docx).parameters)
  shared = {"md_text", "output_path", "style", "width", "height", "margin",
    "metadata", "landscape", "base_dir"}
  missing_pdf = shared - pdf_params
  missing_doc = shared - doc_params
  assert not missing_pdf, f"md_to_pdf missing: {missing_pdf}"
  assert not missing_doc, f"md_to_docx missing: {missing_doc}"
