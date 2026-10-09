# tests/test_parallel.py

"""`md_parallel_to_pdf`: versions side by side, rows level, page breaks between rows only."""

import inspect, re
import pytest
from pdfmarq import MM_TO_PT, PDF
from pdfmarq.legal import md_parallel_to_pdf, md_to_pdf, lang_style
from conftest import needs_fitz, pdf_page_words, pdf_images

LEFT = """---
title: Left title
attachments: [Leftfile]
---

## Firstmark left

Short text.

## Secondmark left

Also short.
"""

RIGHT = """---
title: Right title
attachments: [Rightfile]
---

## Firstmark right

A much longer text on this side that wraps over several lines of the column, so the next
row has to wait below it on both sides before it starts.

## Secondmark right

Short again.
"""

#------------------------------------------------------------------------------------------ Helpers

@pytest.fixture
def render(tmp_path):
  """Render versions side by side with English styles, return the PDF path."""
  def run(*texts:str, **style) -> str:
    path = str(tmp_path / "parallel.pdf")
    styles = [lang_style("en", **style) for _ in texts]
    md_parallel_to_pdf(list(texts), path, styles=styles)
    return path
  return run

#--------------------------------------------------------------------------------------------- Rows

@needs_fitz
def rows_start_level_across_columns(render, word):
  words = pdf_page_words(render(LEFT, RIGHT))[0]
  for mark in ("Firstmark", "Secondmark"):
    left, right = sorted((w for w in words if w[4] == mark), key=lambda w: w[0])
    assert left[2] < 105 * MM_TO_PT < right[0]
    assert left[1] == pytest.approx(right[1], abs=0.5)
  assert word(words, "Left")[2] < 105 * MM_TO_PT < word(words, "Right")[0] # a title each

@needs_fitz
def next_row_waits_for_the_taller_side(render):
  words = pdf_page_words(render(LEFT, RIGHT))[0]
  longer = max(w[3] for w in words if w[4] in ("wraps", "below", "starts."))
  second = min(w[1] for w in words if w[4] == "Secondmark")
  assert second > longer

@needs_fitz
def pagebreak_row_breaks_once_for_all_columns(render, word):
  pages = pdf_page_words(render("One.\n\n<!-- pagebreak -->\n\nTwo.\n",
    "First.\n\n<!-- pagebreak -->\n\nSecond.\n"))
  assert len(pages) == 2
  assert word(pages[1], "Two.") and word(pages[1], "Second.")

@needs_fitz
def rows_never_cross_the_page_bottom(render):
  body = "\n\n".join(f"## Head{i}\n\nText{i} " + "with words " * 30 for i in range(14))
  pages = pdf_page_words(render(body, body))
  assert len(pages) > 1
  bottom = (297 - 20) * MM_TO_PT + 1
  footer = re.compile(r"Page|\d+/\d+")
  assert all(w[3] <= bottom for page in pages for w in page if not footer.fullmatch(w[4]))
  # a heading row keeps the row after it on its page
  page_of = {w[4]: n for n, page in enumerate(pages) for w in page}
  assert all(page_of[f"Head{i}"] == page_of[f"Text{i}"] for i in range(14))

@needs_fitz
def group_is_one_row(render, word):
  pages = pdf_page_words(render(
    "<!-- group -->\n\nAlpha.\n\nBeta.\n\n<!-- /group -->\n\nAfter.\n",
    "<!-- group -->\n\nGamma.\n\n<!-- /group -->\n\nAfterwards.\n"))
  words = pages[0]
  assert word(words, "After.")[1] == pytest.approx(word(words, "Afterwards.")[1], abs=0.5)

@needs_fitz
def same_headings_in_both_versions_render(render):
  words = pdf_page_words(render("## Same\n\nA.\n", "## Same\n\nB.\n"))[0]
  assert len([w for w in words if w[4] == "Same"]) == 2

def footnotes_pair_up_as_one_row(render):
  text = "Text[^a] and[^b].\n\n[^a]: First note.\n\n[^b]: Second note.\n"
  render(text, text) # every note keeps its anchor, or the PDF would not save

#---------------------------------------------------------------------------------------------- End

@needs_fitz
def signatures_span_and_attachments_stay_in_columns(tmp_path, word):
  path = str(tmp_path / "end.pdf")
  md_parallel_to_pdf([LEFT, RIGHT], path, styles=[
    lang_style("en", sign=["First / Erste", "Second / Zweite"]), lang_style("de")])
  words = pdf_page_words(path)[0]
  signer = word(words, "First")
  assert signer[0] < 105 * MM_TO_PT < word(words, "Second")[0]
  left, right = word(words, "Leftfile"), word(words, "Rightfile")
  assert left[2] < 105 * MM_TO_PT < right[0]
  assert left[1] > signer[3] and right[1] > signer[3]
  assert word(words, "Attachments:") and word(words, "Anlagen:")

#------------------------------------------------------------------------------------------- Errors

def versions_with_different_blocks_are_refused(render):
  with pytest.raises(ValueError, match="block 2") as caught:
    render("Para.\n\n## Heading\n", "Para.\n\nAnother paragraph.\n")
  assert "heading_open" in str(caught.value) and "paragraph_open" in str(caught.value)
  with pytest.raises(ValueError, match="block 2"):
    render("One.\n\nTwo.\n", "One.\n")

def block_taller_than_a_column_is_refused(render):
  long = "Word " * 4000
  with pytest.raises(ValueError, match="taller than a whole column"):
    render(long, long)

def page_breaks_inside_rows_are_refused(tmp_path, render):
  with pytest.raises(ValueError, match="h1_page_break"):
    md_parallel_to_pdf(["# A", "# B"], str(tmp_path / "x.pdf"),
      styles=[lang_style("en", h1_page_break=True), lang_style("en")])
  group = "<!-- group -->\n\nA.\n\n<!-- pagebreak -->\n\nB.\n\n<!-- /group -->\n"
  with pytest.raises(ValueError, match="pagebreak"):
    render(group, group)
  quote = "> A.\n>\n> <!-- pagebreak -->\n>\n> B.\n"
  with pytest.raises(ValueError, match="pagebreak"):
    render(quote, quote)

@needs_fitz
def sender_goes_under_a_stamp_too_wide_to_share_its_line(render, word):
  text = "---\nplace: A very long place name that fills a column\nfrom: Sendermark\n---\n\nText.\n"
  words = pdf_page_words(render(text, text, text))[0]
  assert word(words, "Sendermark")[1] > word(words, "very")[3]

def one_version_is_refused(tmp_path):
  with pytest.raises(ValueError, match="two versions"):
    md_parallel_to_pdf(["Only one."], str(tmp_path / "x.pdf"), styles=[lang_style("en")])

def styles_must_match_the_versions(tmp_path):
  with pytest.raises(ValueError, match="as many styles"):
    md_parallel_to_pdf(["A.", "B."], str(tmp_path / "x.pdf"), styles=[lang_style("en")])

def signature_matches_md_to_pdf():
  def params(f) -> list[tuple]:
    return [(name, p.default) for name, p in inspect.signature(f).parameters.items()]
  assert params(md_parallel_to_pdf)[3:] == params(md_to_pdf)[3:] # after the texts and styles

#--------------------------------------------------------------------------------------------- Logo

@needs_fitz
@pytest.mark.usefixtures("logo")
def logo_keeps_a_row_of_its_own(tmp_path):
  text = "---\ntitle: Titlemark\nlogo: logo.png\n---\n\n## Head\n\nText.\n"
  path = str(tmp_path / "logo.pdf")
  styles = [lang_style("en", logo_align="R") for _ in range(2)]
  md_parallel_to_pdf([text, text], path, styles=styles, base_dir=str(tmp_path))
  bottom = max(box[3] for box in pdf_images(path)[0])
  titles = [w for w in pdf_page_words(path)[0] if w[4] == "Titlemark"]
  assert len(titles) == 2 and all(w[1] > bottom for w in titles)

def versions_keep_their_anchors_apart(tmp_path, monkeypatch):
  out = str(tmp_path / "a.pdf")
  names = []
  anchor = PDF.anchor
  def spy(self, key):
    if self.output_path == out: names.append(key) # rows are measured on scratch PDFs too
    return anchor(self, key)
  monkeypatch.setattr(PDF, "anchor", spy)
  text = "## Scope\n\nSee [scope](#scope).\n"
  md_parallel_to_pdf([text, text], out, styles=[lang_style("pl"), lang_style("en")])
  assert names == ["scope", "v2-scope"]
