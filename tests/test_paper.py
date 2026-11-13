# tests/test_paper.py

"""`pdfmarq.paper` around the markdown engine, the engine's slicing API, and the shared parts."""

import dataclasses, inspect
from pathlib import Path
import pytest
from pdfmarq import PDF, MM_TO_PT, RichSegment
from pdfmarq.constants import A4
from pdfmarq.parts import signatures, signatures_height, sign_labels, page_number
from pdfmarq.paper import md_to_pdf, md_into, PaperStyle, lang_style
from pdfmarq.md import (MarkdownRenderer, MarkdownStyle, top_blocks, metadata_from_frontmatter,
  people, byline)
from conftest import needs_pymupdf, pdf_words, pdf_faces, pdf_page_words, pdf_text

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
    "two_sided", "base_dir", "font_dir", "metadata"]
  assert (params["page"].default, params["margin"].default, params["gutter"].default,
    params["two_sided"].default) == (A4, 20, 0, False)

def lang_style_layers_engine_and_document_labels():
  style = lang_style("de")
  assert isinstance(style, PaperStyle)
  assert (style.page_number_label, style.callout_label_note) == ("Seite", "Hinweis")

def every_language_is_complete():
  # each preset language brings its own words to every table, and a number format for merge
  pytest.importorskip("jinja2")
  from pdfmarq.md import LANG_PRESETS
  from pdfmarq.legal import lang_style as legal_style
  from pdfmarq.merge import fill
  en, en_legal = lang_style("en"), legal_style("en")
  for lang in LANG_PRESETS.keys() - {"en"}:
    paper, legal = lang_style(lang), legal_style(lang)
    assert paper.footnote_word != en.footnote_word, lang # the engine's words
    assert paper.sign_labels != en.sign_labels, lang # the parts'
    assert paper.banner_label_created != en.banner_label_created, lang # the banner's
    assert legal.attachments_label != en_legal.attachments_label, lang # the letter's
    fill("{{ amount | number }}", {"amount": 1}, lang=lang) # without a number format it raises

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

@needs_pymupdf
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

@needs_pymupdf
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

@needs_pymupdf
def page_number_keeps_its_face_beside_signatures(tmp_path):
  path = str(tmp_path / "chrome.pdf")
  md_to_pdf("# One\n\nText.\n", path, style=PaperStyle(sign=True))
  font = pdf_faces(path)["Page 1/1"][0] # drawn as one string, not word by word
  assert "Oblique" not in font and "Italic" not in font

#------------------------------------------------------------------------------------------ md_into

@needs_pymupdf
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

#-------------------------------------------------------------------------------------- Frontmatter

@needs_pymupdf
def banner_prints_id_and_version_as_written(tmp_path):
  path = str(tmp_path / "v.pdf")
  md_to_pdf("---\ntitle: T\nid: 0012\nversion: 1.10\n---\n\nBody.\n", path)
  words = [w[4] for w in pdf_words(path)]
  assert "0012" in words and "1.10" in words

@pytest.mark.parametrize("heading, title, dropped", [
  ("# Sp\\. z o\\.o\\.", "Sp. z o.o.", True), ("# **Sp. z o.o.**", "Sp. z o.o.", True),
  ("# `pdfmarq` guide", "`pdfmarq` guide", True), ("# `pdfmarq` guide", "pdfmarq guide", True),
  ("# Report $x^2$", "Report", False), ("# Report[^1]\n\n[^1]: Note.", "Report", False),
  ("# Report ![logo](x.png)", "Report", False),
])
def repeated_title_drops_only_when_nothing_else_goes_with_it(tmp_path, heading, title, dropped):
  # parsed by the engine, with its math and footnote plugins
  from pdfmarq.paper.render import _skip_matching_h1
  tokens = MarkdownRenderer(PDF(str(tmp_path / "t.pdf"))).parse(heading + "\n\nBody.\n")
  assert (len(_skip_matching_h1(tokens, title)) < len(tokens)) == dropped

@needs_pymupdf
def people_show_by_name_in_the_banner_and_the_metadata(tmp_path):
  import pymupdf
  path = str(tmp_path / "p.pdf")
  md_to_pdf("---\ntitle: T\nauthor:\n  - name: Anna Nowak\n    orcid: 0000-0001\n"
    "  - Jan Kowalski\n---\n\nBody.\n", path)
  text = pdf_text(path)
  assert "Authors: Anna Nowak, Jan Kowalski" in text and "orcid" not in text
  with pymupdf.open(path) as doc:
    assert doc.metadata["author"] == "Anna Nowak, Jan Kowalski"

def the_author_label_agrees_with_the_names():
  style = lang_style("pl")
  assert style.author_label("Anna Nowak") == "Autor"
  assert style.author_label("Anna Nowak, Jan Kowalski") == "Autorzy"
  assert style.author_label([{"name": "Anna Nowak"}, "Jan Kowalski"]) == "Autorzy"

def a_string_author_stays_as_written_and_a_nameless_person_warns():
  assert byline("Walker, Texas Ranger") == "Walker, Texas Ranger"
  with pytest.warns(RuntimeWarning, match="no name"):
    assert people([{"orcid": "0000-0001"}, "Ann"]) == [{"name": "Ann"}]

def a_group_with_options_is_one_block(renderer):
  tokens = renderer.parse("<!-- group wide -->\n\nOne.\n\nTwo.\n\n<!-- /group -->\n\nThree.\n")
  assert len(top_blocks(tokens)) == 2

def details_in_a_string_join_the_name_before_them():
  value = ["Anna Nowak, 0000-0002-1825-0097, a.nowak@example.com", "Jan Kowalski, j.k@example.com"]
  assert byline(value) == "Anna Nowak, Jan Kowalski"
  assert byline("Anna Nowak, a.nowak@example.com, Jan Kowalski") == "Anna Nowak, Jan Kowalski"
  assert byline("Anna Nowak a.nowak@example.com") == "Anna Nowak" # a comma left out
  with pytest.warns(RuntimeWarning, match="follows no name"):
    assert people("a.nowak@example.com, Anna") == [{"name": "Anna"}]
  with pytest.warns(RuntimeWarning, match="follows no name"): # nor shown in the banner
    assert byline("a.nowak@example.com, Anna") == "Anna"
  with pytest.warns(RuntimeWarning, match="a second email of Anna Nowak"):
    assert people("Anna Nowak, a@example.com, b@example.com") == [
      {"name": "Anna Nowak", "email": "a@example.com"}]
  assert byline("Jan Kowalski, 1950-2020") == "Jan Kowalski, 1950-2020" # no detail, as written

def a_bound_byline_breaks_only_after_a_comma():
  nbsp = "\u00a0"
  bound = byline(["Anna Maria Nowak", "Jan  Kowalski"], bind=True)
  assert bound == f"Anna{nbsp}Maria{nbsp}Nowak, Jan{nbsp}Kowalski"
  assert byline("Walker, Texas Ranger", bind=True) == f"Walker, Texas{nbsp}Ranger"
  team = "Department of Marine Electronics"
  assert byline(team, bind=True) == team # a single name breaks as any text does

def a_banner_sets_its_codes_unshaded_with_code_inline_bg_none(tmp_path):
  md = "---\ntitle: Report\nid: MD-001\nversion: 1.2\n---\n\nBody.\n"
  md_to_pdf(md, str(tmp_path / "b.pdf"), style=PaperStyle(code_inline_bg=None))
  assert (tmp_path / "b.pdf").stat().st_size > 0

@needs_pymupdf
def a_long_author_row_wraps_beside_the_date_and_pushes_the_text_down(tmp_path):
  path = str(tmp_path / "authors.pdf")
  authors = "".join(f"  - Author Number{k} Longsurname\n" for k in range(8))
  md_to_pdf(f"---\ntitle: Report\nauthor:\n{authors}updated: 2026-02-02\n---\n\nBodymark.\n", path)
  words = pdf_page_words(path)[0]
  names = [w for w in words if w[4].startswith("Longsurname")]
  date = next(w for w in words if w[4].startswith("Updated"))
  body = next(w for w in words if w[4] == "Bodymark.")
  assert len({round(w[1]) for w in names}) > 1 # the names wrap
  assert max(w[2] for w in names) < date[0] # never under the date
  assert max(w[3] for w in names) < body[1] # and the text starts below them
  people = [w for w in words if w[4].startswith(("Author", "Number", "Longsurname"))][1:]
  for first, middle, last in zip(people[0::3], people[1::3], people[2::3]):
    assert round(first[1]) == round(middle[1]) == round(last[1]) # a name never breaks

def two_page_breaks_under_the_compact_banner_leave_no_blank_page(tmp_path):
  md = "---\ntitle: Test\n---\n\nBefore.\n\n<!-- pagebreak -->\n\n<!-- pagebreak -->\n\nAfter.\n"
  assert md_to_pdf(md, str(tmp_path / "x.pdf"), style=PaperStyle()).page_num == 2

@needs_pymupdf
def a_paper_in_columns_balances_its_last_page_under_the_banner(tmp_path):
  # The compact banner starts the text of later pages lower, and the measure counts from there
  import warnings
  sentence = "Words that fill the columns of several pages. "
  md = "---\ntitle: Test\n---\n\n" + "\n\n".join([sentence * 30] * 9)
  with warnings.catch_warnings():
    warnings.simplefilter("error", RuntimeWarning)
    path = str(tmp_path / "x.pdf")
    md_to_pdf(md, path, style=PaperStyle(columns=2))
  pages = pdf_page_words(path)
  assert len(pages) == 4
  text = [w for w in pages[-1] if w[4] in sentence.split()]
  left = max(w[3] for w in text if w[0] < 105 * MM_TO_PT)
  right = max(w[3] for w in text if w[0] > 105 * MM_TO_PT)
  assert abs(left - right) <= 2 * 11 * 1.5 # paragraphs split, so two lines at most part them

def a_paper_in_columns_caps_its_last_page_from_under_the_banner(tmp_path, monkeypatch):
  # The same without PyMuPDF: the last page's cap holds about half of what that page carries
  calls = []
  columns = PDF.columns
  def recorded(self, count, *args, **kwargs):
    calls.append((self, count, kwargs.get("height")))
    return columns(self, count, *args, **kwargs)
  monkeypatch.setattr(PDF, "columns", recorded)
  sentence = "Words that fill the columns of several pages. "
  md = "---\ntitle: Test\n---\n\n" + "\n\n".join([sentence * 30] * 9)
  pdf = md_to_pdf(md, str(tmp_path / "x.pdf"), style=PaperStyle(columns=2))
  caps = next(height for owner, count, height in calls if owner is pdf and count == 2)
  assert caps[-1] < 0.75 * (pdf.content_height - pdf.headroom)

#------------------------------------------------------------------------------------ Closing break

ENDING = "---\ntitle: Test\n---\n\nText of the paper.\n\n<!-- pagebreak -->\n"

def a_closing_page_break_opens_no_page_of_chrome(tmp_path):
  pdf = md_to_pdf(ENDING, str(tmp_path / "end.pdf"))
  assert pdf.page_num == 1 # a page holding the compact banner and its number alone is gone

def a_closing_page_break_goes_with_a_comment_after_it(tmp_path):
  pdf = md_to_pdf(ENDING + "\n<!-- the end -->\n", str(tmp_path / "end.pdf"))
  assert pdf.page_num == 1

def a_closing_page_break_moves_the_signing_lines_on(tmp_path):
  pdf = md_to_pdf(ENDING, str(tmp_path / "end.pdf"), style=PaperStyle(sign=True))
  assert pdf.page_num == 2 # the break before them is the author's

def a_closing_page_break_stays_for_what_the_caller_sets_after(tmp_path):
  pdf = PDF(str(tmp_path / "end.pdf"))
  md_into(pdf, ENDING)
  assert pdf.page_num == 2 # `md_into` leaves the file to the caller
