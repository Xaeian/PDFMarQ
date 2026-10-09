# tests/test_paper.py

"""`pdfmarq.paper` around the markdown engine, the engine's slicing API, and the shared parts."""

import dataclasses, inspect
from pathlib import Path
import pytest
from pdfmarq import PDF, MM_TO_PT, RichSegment
from pdfmarq.constants import A4
from pdfmarq.parts import signatures, signatures_height, sign_labels, page_number
from pdfmarq.paper import md_to_pdf, md_into, PaperStyle, lang_style
from pdfmarq.md import MarkdownRenderer, MarkdownStyle, top_blocks, metadata_from_frontmatter
from conftest import needs_fitz, pdf_words, pdf_faces, pdf_page_words

# Style fields md2paper sets by name from request options (its `_STYLE` and `pdf_style`).
MD2PAPER_FIELDS = {
  "body_size", "line_height", "image_max_h", "image_min_dpi", "banner", "banner_compact",
  "sign", "mermaid_theme", "link_root", "link_base", "syntax_theme", "math_font",
  "math_fontset", "font_body", "font_head", "font_mono", "page_number_label",
}

@pytest.fixture
def pdf(tmp_path):
  return PDF(str(tmp_path / "doc.pdf"))

@pytest.fixture
def renderer(pdf):
  return MarkdownRenderer(pdf, MarkdownStyle())

#-------------------------------------------------------------------------------- md2paper contract

def style_carries_every_md2paper_field():
  fields = {f.name for f in dataclasses.fields(PaperStyle)}
  assert MD2PAPER_FIELDS <= fields, MD2PAPER_FIELDS - fields

def md_to_pdf_signature_is_stable():
  params = inspect.signature(md_to_pdf).parameters
  assert list(params) == ["md_text", "output_path", "style", "page", "margin", "gutter",
    "base_dir", "font_dir", "metadata"]
  assert (params["page"].default, params["margin"].default, params["gutter"].default) \
    == (A4, 20, 0)

def lang_style_layers_engine_and_document_labels():
  style = lang_style("de")
  assert isinstance(style, PaperStyle)
  assert (style.page_number_label, style.callout_label_note) == ("Seite", "Hinweis")

def engine_style_is_refused(tmp_path):
  with pytest.raises(TypeError, match="PaperStyle"):
    md_to_pdf("# Title", str(tmp_path / "x.pdf"), style=MarkdownStyle())

#--------------------------------------------------------------------------------------- Engine API

def parse_drops_frontmatter(renderer):
  tokens = renderer.parse("---\ntitle: Kept out\n---\n\n# Body\n")
  assert [t.type for t in tokens[:3]] == ["heading_open", "inline", "heading_close"]
  assert tokens[1].content == "Body"

def top_blocks_tile_the_document(renderer):
  tokens = renderer.parse(
    "# Head\n\nText.\n\n- a\n- b\n\n<!-- group -->\n\nOne.\n\nTwo.\n\n<!-- /group -->\n\n---\n")
  blocks = top_blocks(tokens)
  assert blocks[0][0] == 0 and blocks[-1][1] == len(tokens)
  assert all(a[1] == b[0] for a, b in zip(blocks, blocks[1:]))
  kinds = [tokens[start].type for start, _ in blocks]
  assert kinds == ["heading_open", "paragraph_open", "bullet_list_open", "html_block", "hr"]

@needs_fitz
def slices_render_like_the_whole(tmp_path):
  src = "# Alpha\n\nOne line with a [link](#beta).\n\n## Beta\n\nTwo.\n"
  whole = str(tmp_path / "whole.pdf")
  pdf = PDF(whole)
  MarkdownRenderer(pdf, MarkdownStyle()).render(src)
  pdf.save()
  sliced = str(tmp_path / "sliced.pdf")
  pdf = PDF(sliced)
  renderer = MarkdownRenderer(pdf, MarkdownStyle())
  tokens = renderer.parse(src)
  renderer.index(tokens)
  for start, end in top_blocks(tokens):
    renderer.render_tokens(tokens[start:end])
  pdf.save()
  assert pdf_words(whole) == pdf_words(sliced)

#-------------------------------------------------------------------------------------------- Parts

@needs_fitz
def one_signature_sits_at_the_right_margin(tmp_path):
  path = str(tmp_path / "sign.pdf")
  pdf = PDF(path)
  signatures(pdf, ["Signed"], RichSegment("", mode="Oblique", size=9), gap=20, width=70, thick=0.3)
  pdf.save()
  word = next(w for w in pdf_words(path) if w[4] == "Signed")
  center_mm = (word[0] + word[2]) / 2 / MM_TO_PT
  assert center_mm == pytest.approx(210 - 20 - 35, abs=0.5)

def signatures_leave_the_cursor_below_the_labels(pdf):
  signatures(pdf, ["Left", "Right"], RichSegment("", size=9), gap=20, width=70, thick=0.3)
  assert pdf.y == pytest.approx(20 + 1 + 9 / MM_TO_PT) # gap, line, one label line

def signing_block_grows_with_its_labels(pdf):
  face = RichSegment("", size=9)
  short = signatures_height(pdf, ["Signed"], face, gap=20, width=70)
  wrapped = signatures_height(pdf, ["A label long enough to wrap " * 4], face, gap=20, width=30)
  assert short == pytest.approx(30) # the least block: the gap and 10mm for the line and label
  assert wrapped > short

def sign_true_without_its_scenario_draws_a_bare_line():
  assert sign_labels(True, {"contract": ["A", "B"]}) == [""]
  assert sign_labels("missing", {}) == ["missing"]

def page_number_of_a_missing_font_raises(pdf):
  pdf.text("Page content")
  with pytest.raises(FileNotFoundError):
    page_number(pdf, "Page", 1, 1, RichSegment("", family="NoSuchFace"), show_total=True)

@needs_fitz
def page_number_keeps_its_face_beside_signatures(tmp_path):
  path = str(tmp_path / "chrome.pdf")
  md_to_pdf("# One\n\nText.\n", path, style=PaperStyle(sign=True))
  font = pdf_faces(path)["Page 1/1"][0] # drawn as one string, not word by word
  assert "Oblique" not in font and "Italic" not in font

#------------------------------------------------------------------------------------------ md_into

@needs_fitz
def md_into_writes_after_a_cover(tmp_path):
  path = str(tmp_path / "cover.pdf")
  pdf = PDF(path)
  pdf.font("Helvetica", 20).text("Coverword")
  pdf.new_page()
  md_into(pdf, "---\ntitle: Report\nid: R-1\n---\n\nBodyword here.\n", style=PaperStyle())
  pdf.save()
  pages = [[w[4] for w in page] for page in pdf_page_words(path)]
  assert "Coverword" in pages[0] and "Bodyword" in pages[1]
  assert ("1/2" in pages[0], "2/2" in pages[1]) == (True, True) # the cover counts
  assert pages[1].count("R-1") == 1 # banner only: the compact one starts after this page

def missing_logo_warns_at_the_callers_line(tmp_path):
  md = "---\ntitle: T\nlogo: none.png\n---\n\nBody.\n"
  with pytest.warns(RuntimeWarning, match="not found") as caught:
    md_to_pdf(md, str(tmp_path / "a.pdf"))
    md_into(PDF(str(tmp_path / "b.pdf")), md)
  assert {Path(w.filename).name for w in caught} == {Path(__file__).name}

def invalid_frontmatter_warns_once(tmp_path):
  with pytest.warns(RuntimeWarning, match="invalid YAML") as caught:
    md_to_pdf("---\ntitle: [\n---\n\nBody.\n", str(tmp_path / "y.pdf"))
  assert len([w for w in caught if "invalid YAML" in str(w.message)]) == 1

def title_given_as_a_list_is_one_line():
  fm = {"title": ["Umowa", "o dzieło"], "author": "Jan\nKowalski"}
  assert metadata_from_frontmatter(fm) == {"title": "Umowa o dzieło", "author": "Jan Kowalski"}

def status_given_as_a_number_is_a_badge(tmp_path):
  md_to_pdf("---\ntitle: T\nstatus: 1\n---\n\nBody.\n", str(tmp_path / "s.pdf"))
