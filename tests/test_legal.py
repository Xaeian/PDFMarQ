# tests/test_legal.py

"""`pdfmarq.legal`: letter header, signing lines, attachments, columns, the md2paper contract."""

import dataclasses, inspect, io, warnings
import pytest
from pdfmarq import PDF, MM_TO_PT
from pdfmarq.paper import md_to_pdf as paper_md_to_pdf
from pdfmarq.graphics import image_aspect
from pdfmarq.legal import md_to_pdf, LegalStyle, lang_style
from pdfmarq.legal.header import _title_segments
from pdfmarq.legal.measure import Probe, Region
from pdfmarq.legal.render import _clauses
from pdfmarq.md import MarkdownRenderer, MarkdownStyle
from conftest import (needs_fitz, pdf_page_words, pdf_pages, pdf_faces, pdf_images,
  pdf_strokes, pdf_chars)

LETTER = """---
title: Termination notice
place: Gdynia
date: 2026-10-07
from: |
  Sender Name
  1 Sender Street
to: [Recipient Ltd, 2 Recipient Avenue]
attachments: [copy of the contract, delivery receipt]
---

I hereby terminate the contract with one month's notice, effective at the end of the month.
"""

SECTION = ("Sectionmark text that runs long enough to fill a few lines of a narrow column "
  "and shows how the columns share the page between them. ")
CONTRACT = "---\ntitle: Service contract\n---\n\nPreamble naming the parties.\n\n" + "\n\n".join(
  f"## §{i}. Clause {i}\n\n" + SECTION * 3 for i in range(1, 9))
# fits one page in two columns with the signing lines below, at the default style
SHORT_CONTRACT = "---\ntitle: Service contract\n---\n\nPreamble naming the parties.\n\n" \
  + "\n\n".join(f"## §{i}. Clause {i}\n\n" + SECTION * 2 for i in range(1, 7))
PARTIES = ("Firstparty named at enough length to run past the middle of the page and wrap "
  "more than once beside a logo standing at its side. ") * 2
# a preamble beside the logo `logo.png`, then a clause below it
SIDE = f"---\ntitle: Service contract\nlogo: logo.png\n---\n\n{PARTIES}\n\nSecondparty.\n\n" \
  "## §1. Subject\n\n" + SECTION * 2
HALF_PT = 105 * MM_TO_PT # middle of an A4 page
RIGHT_PT = (210 - 20) * MM_TO_PT # right margin of an A4 page

#------------------------------------------------------------------------------------------ Helpers

@pytest.fixture
def render(tmp_path):
  """Render `md` with `LegalStyle(**style)`, return the PDF path."""
  def run(md:str, **style) -> str:
    path = str(tmp_path / "legal.pdf")
    md_to_pdf(md, path, style=LegalStyle(**style), base_dir=str(tmp_path))
    return path
  return run

@pytest.fixture
def column_ends():
  """Lowest `Sectionmark` of the left and of the right column on a page, as a word bottom (pt)."""
  def ends(words:list) -> tuple[float, float]:
    body = [w for w in words if w[4] == "Sectionmark"]
    return max(w[3] for w in body if w[2] < HALF_PT), max(w[3] for w in body if w[0] > HALF_PT)
  return ends

@pytest.fixture
def slack() -> float:
  """
  Most the column ends of a balanced page may differ by (pt): one unit that may not split,
  a heading's reserve with the gap above it, its three lines of text and the paragraph gap before.
  """
  s = LegalStyle()
  return 2 * s.body_size + (s.head_gap_top + s.para_gap) * MM_TO_PT \
    + 3 * s.body_size * s.line_height + 1

#-------------------------------------------------------------------------------- md2paper contract

def md_to_pdf_matches_the_paper_signature():
  def params(f) -> list[tuple]:
    return [(name, p.default) for name, p in inspect.signature(f).parameters.items()]
  assert params(md_to_pdf) == params(paper_md_to_pdf)

def option_fields_exist():
  fields = {f.name for f in dataclasses.fields(LegalStyle)}
  assert {"columns", "justify", "keep_together", "sign", "sign_bottom", "logo_align",
    "page_number_label", "body_size", "font_body"} <= fields

def wrong_style_is_refused(tmp_path):
  path = str(tmp_path / "x.pdf")
  with pytest.raises(TypeError, match="LegalStyle"):
    md_to_pdf("Text.", path, style=MarkdownStyle())
  with pytest.raises(ValueError, match="logo_align"):
    md_to_pdf("Text.", path, style=LegalStyle(logo_align="X"))
  with pytest.raises(ValueError, match="to_align"):
    md_to_pdf("Text.", path, style=LegalStyle(to_align="C"))

def preset_formats_dates_its_own_way():
  assert lang_style("de").date_format == "%d.%m.%Y"

def preset_names_the_end_in_its_language():
  pl = lang_style("pl")
  assert (pl.attachments_label, pl.ref_label) == ("Załączniki", "Sygn. akt")

def preset_hyphenates_in_its_language():
  assert (lang_style("pl").hyphenate, lang_style("en").hyphenate) == ("pl", "en")
  # no language named, no patterns guessed
  assert LegalStyle().hyphenate is None and lang_style("xx").hyphenate is None

def each_style_gets_its_own_preset():
  lang_style("pl").sign_labels["contract"].append("Witness")
  assert lang_style("pl").sign_labels["contract"] == ["Zleceniodawca", "Zleceniobiorca"]

def columns_must_be_a_whole_number(tmp_path):
  with pytest.raises(ValueError, match="columns"):
    md_to_pdf("Text.", str(tmp_path / "x.pdf"), style=LegalStyle(columns=2.5))

def clauses_start_at_a_top_level_heading(tmp_path):
  renderer = MarkdownRenderer(PDF(str(tmp_path / "x.pdf")), LegalStyle())
  tokens = renderer.parse("Preamble.\n\n> ## Quoted\n> text\n\n## §1. Clause\n\nText.\n")
  start = _clauses(tokens)
  assert tokens[start].type == "heading_open" and tokens[start].level == 0

def balancing_counts_the_gap_after_the_last_block(tmp_path):
  style = LegalStyle()
  pdf = PDF(str(tmp_path / "x.pdf"))
  tokens = MarkdownRenderer(pdf, style).parse("Text that fills a few lines. " * 6)
  probe = Probe(pdf, style, tokens, None)
  drawn = probe.height(tokens, 80) # the lines and the paragraph gap after them
  lines = drawn - style.para_gap
  region = Region(tokens, 80, 1, 0)
  assert probe.fits(region, drawn)
  assert not probe.fits(region, (lines + drawn) / 2) # room for the lines only

#------------------------------------------------------------------------------------------- Header

@needs_fitz
def header_rows_follow_the_frontmatter(render, word):
  words = pdf_page_words(render(LETTER, sign=["Sender Name"]))[0]
  sender, date, recipient, title = (word(words, t) for t in
    ("Sender", "2026-10-07", "Recipient", "Termination"))
  assert sender[0] == pytest.approx(20 * MM_TO_PT, abs=0.5) # left
  assert date[2] == pytest.approx(RIGHT_PT, abs=0.5) # right, on the sender's first line
  assert date[1] == pytest.approx(sender[1], abs=1)
  assert recipient[0] > HALF_PT # right half, every line flush with the margin
  assert all(word(words, t)[2] == pytest.approx(RIGHT_PT, abs=0.5) for t in ("Ltd", "Avenue"))
  assert title[1] > recipient[3] # title below the rows

@needs_fitz
def recipient_moves_to_the_left_margin(render, word):
  words = pdf_page_words(render(LETTER, to_align="L"))[0]
  sender, recipient = word(words, "Sender"), word(words, "Recipient")
  assert recipient[0] == pytest.approx(20 * MM_TO_PT, abs=0.5)
  assert recipient[1] > sender[3] # still its own row, below the sender

@needs_fitz
def ref_is_bold_under_the_recipient(render, word):
  path = render(LETTER.replace("to: [", "ref: VI P 7/25\nto: ["))
  words = pdf_page_words(path)[0]
  faces = pdf_faces(path)
  assert "Bold" in faces["7/25"][0] and "Bold" not in faces["Ref.:"][0]
  case = word(words, "7/25")
  assert case[1] > word(words, "Avenue")[3] # below the recipient
  assert case[2] == pytest.approx(RIGHT_PT, abs=0.5) # flush right, like it

@needs_fitz
def header_skips_missing_keys(render, word):
  words = pdf_page_words(render("---\ntitle: Statement\n---\n\nI state this.\n"))[0]
  assert word(words, "Statement")[1] == pytest.approx(20 * MM_TO_PT, abs=2) # at the very top

@needs_fitz
def yaml_lists_print_as_lines_and_commas(render, word):
  md = ("---\ntitle: [Service contract, No 7]\nplace: [Gdynia, Poland]\n"
    "to:\n  - Recipient Ltd\n  -\n---\n\nText.\n")
  words = pdf_page_words(render(md))[0]
  assert word(words, "Gdynia,") and word(words, "Poland") # one line, joined by commas
  assert word(words, "No")[1] > word(words, "Service")[3] # a title line per entry
  assert not word(words, "None") # the empty entry is left out

def yaml_mapping_is_refused(render):
  with pytest.raises(ValueError, match="mapping"):
    render("---\ntitle:\n  name: Contract\n---\n\nText.\n")

@needs_fitz
@pytest.mark.usefixtures("logo")
def title_without_room_beside_the_logo_goes_under_it(render, word):
  md = "---\ntitle: Service contract\nlogo: logo.png\n---\n\nText.\n"
  path = render(md, logo_align="R", logo_max_h=200, logo_max_w=90)
  bottom = pdf_images(path)[0][0][3]
  assert word(pdf_page_words(path)[0], "Service")[1] > bottom

@needs_fitz
def missing_logo_warns_and_renders(render):
  with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    path = render("---\nlogo: absent.png\ntitle: T\n---\n\nText.\n")
  assert any("logo" in str(w.message) for w in caught)
  assert "Text." in [w[4] for w in pdf_page_words(path)[0]]

#---------------------------------------------------------------------------------- Around the text

def title_caps_scale_capitals_without_small_ones():
  pdf = PDF(io.BytesIO())
  style = LegalStyle(title_caps=True, title_size=20, header_font="Helvetica") # no small capitals
  segs = _title_segments(pdf, style, ["Service Contract"])
  assert [s.text for s in segs] == ["S", "ERVICE", " C", "ONTRACT"]
  assert [s.size for s in segs] == pytest.approx([20, 16, 20, 16])
  assert segs[0].char_space == 0 and segs[1].char_space > 0 # small capitals spaced out
  lines = _title_segments(pdf, style, ["Service", "Contract"]) # a YAML list: a line per entry
  assert [s.text for s in lines] == ["S", "ERVICE", "\n", "C", "ONTRACT"]

def title_caps_take_the_font_small_capitals(small_caps_font):
  pdf = PDF(io.BytesIO(), font_dir=small_caps_font)
  style = LegalStyle(title_caps=True, title_size=20, header_font="TestSC", head_mode="Regular")
  segs = _title_segments(pdf, style, ["Aab"])
  assert [(s.text, s.family, s.size, s.char_space) for s in segs] == [
    ("A", "TestSC", 20, 0), ("AB", "TestSC.sc", 20, 0)]
  def width(text:str, family:str) -> float:
    return pdf._fonts.text_width(text, family, "Regular", 20)
  assert (width("A", "TestSC"), width("A", "TestSC.sc")) == pytest.approx((14, 12)) # `A`, `a.sc`
  assert width("B", "TestSC.sc") == pytest.approx(13) # no small capital: the capital stays

@needs_fitz
def small_capitals_are_drawn(tmp_path, small_caps_font):
  path = str(tmp_path / "caps.pdf")
  md_to_pdf("---\ntitle: Aab\n---\n\nText.\n", path, font_dir=small_caps_font,
    style=LegalStyle(title_caps=True, title_size=20, header_font="TestSC", head_mode="Regular"))
  title = [c for c in pdf_chars(path) if c[0] in "AB"][:3]
  # copied out as capitals, advancing by the widths of `A`, then of `a.sc`
  assert [c[0] for c in title] == ["A", "A", "B"]
  advances = [title[1][1] - title[0][1], title[2][1] - title[1][1]]
  assert advances == pytest.approx([14, 12], abs=0.05)

def logo_aspect_follows_the_drawing(tmp_path):
  svg = tmp_path / "wide.svg" # no width or height: its bounds give the shape
  svg.write_text('<svg xmlns="http://www.w3.org/2000/svg">'
    '<rect x="0" y="0" width="40" height="10"/></svg>', encoding="utf-8")
  assert image_aspect(svg) == pytest.approx(4)

@needs_fitz
def header_font_sets_the_page_around_the_text(render):
  md = "---\ntitle: Contract\n---\n\nPreamble here.\n\n## §1. Subject\n\nClause text.\n"
  faces = pdf_faces(render(md, header_font="Courier", sign=["Signer"]))
  assert all(faces[t][0].startswith("Courier") for t in ("Contract", "Preamble", "Signer"))
  assert not faces["Clause"][0].startswith("Courier")

@needs_fitz
def preamble_takes_its_own_size_and_spacing(render, word):
  md = "First party.\n\nSecond party.\n\n## §1. Subject\n\nClause text.\n"
  def tops(**style) -> tuple:
    words = pdf_page_words(render(md, **style))[0]
    return tuple(word(words, text)[1] for text in ("First", "Second", "§1."))
  base, spaced, parted = tops(), tops(preamble_para_gap=10), tops(preamble_gap=12)
  s = LegalStyle()
  grown = (spaced[1] - spaced[0]) - (base[1] - base[0])
  assert grown == pytest.approx((10 - s.para_gap) * MM_TO_PT, abs=0.2)
  moved = (parted[2] - parted[1]) - (base[2] - base[1])
  assert moved == pytest.approx((12 - s.preamble_gap) * MM_TO_PT, abs=0.2)
  faces = pdf_faces(render(md, preamble_size=14))
  assert faces["First"][1] == pytest.approx(14)
  assert faces["Clause"][1] == pytest.approx(s.body_size)

@needs_fitz
@pytest.mark.usefixtures("logo")
@pytest.mark.parametrize("align, columns", [("R", 2), ("L", 1)])
def preamble_runs_beside_a_side_logo(render, align, columns):
  path = render(SIDE, logo_align=align, logo_max_h=40, columns=columns)
  x0, _, x1, bottom = pdf_images(path)[0][0]
  words = pdf_page_words(path)[0]
  beside = [w for w in words if w[1] < bottom]
  assert any(w[4] == "Secondparty." for w in beside) # both paragraphs start next to it
  if align == "R": assert all(w[2] < x0 for w in beside)
  else: assert all(w[0] > x1 for w in beside)
  clauses = [w for w in words if w[4] == "Sectionmark"]
  assert clauses and all(w[1] > bottom for w in clauses) # the clauses below it

@needs_fitz
def signing_lines_are_dotted(render):
  strokes = pdf_strokes(render(LETTER, sign="contract"))[0]
  lines = [d for d in strokes if d["rect"].height < 1 and d["rect"].width > 100]
  assert len(lines) == 2 and all(d["dashes"].startswith("[ 1 2 ]") for d in lines)

#---------------------------------------------------------------------------------------------- End

@needs_fitz
def one_signature_on_the_right_attachments_below(render, word):
  words = pdf_page_words(render(LETTER, sign=["Sender Name"]))[0]
  signer = [w for w in words if w[4] == "Sender"][-1] # the label, not the header line
  listing = word(words, "Attachments:")
  assert signer[0] > HALF_PT
  assert listing[1] > signer[3]
  assert word(words, "1.") and word(words, "2.")

@needs_fitz
def sign_bottom_moves_signatures_and_attachments_down(render, word):
  words = pdf_page_words(render(LETTER, sign=["Sender Name"], sign_bottom=True))[0]
  signer = [w for w in words if w[4] == "Sender"][-1]
  last = max(words, key=lambda w: w[3])
  assert signer[1] > 200 * MM_TO_PT # far below the short letter above it
  assert last[3] > (297 - 20 - 15) * MM_TO_PT # the end sits at the bottom margin
  assert word(words, "Attachments:")[1] > signer[1]

@needs_fitz
def single_page_has_no_page_number(render, word):
  words = pdf_page_words(render(LETTER))[0]
  assert not word(words, "Page")

@needs_fitz
def longer_document_is_numbered(render, word):
  pages = pdf_page_words(render(CONTRACT))
  assert len(pages) > 1 and word(pages[0], "Page")

#------------------------------------------------------------------------------------------ Columns

@needs_fitz
def preamble_spans_columns_start_at_first_section(render, word):
  words = pdf_page_words(render(CONTRACT, columns=2))[0]
  preamble = word(words, "Preamble")
  assert preamble[0] == pytest.approx(20 * MM_TO_PT, abs=0.5)
  body = [w for w in words if w[4] == "Sectionmark"]
  assert any(w[2] < HALF_PT for w in body) and any(w[0] > HALF_PT for w in body)
  assert all(w[1] > preamble[3] for w in body)

@needs_fitz
def without_sections_everything_flows_in_columns(render):
  md = "\n\n".join([SECTION * 2] * 12)
  words = pdf_page_words(render(md, columns=2))[0]
  assert any(w[0] > HALF_PT for w in words)
  assert all(w[2] < HALF_PT or w[0] > HALF_PT for w in words) # nothing spans the gap

@needs_fitz
def callout_keeps_its_title_in_columns(render, word):
  # balancing measures the clauses off the page first, so drawing must not depend on that
  md = "Preamble.\n\n## §1. Clause\n\n> [!IMPORTANT]\n> Read this.\n"
  assert word(pdf_page_words(render(md, columns=2))[0], "Important")

@needs_fitz
def short_contract_balances_and_keeps_signatures(render, word, column_ends, slack):
  path = render(SHORT_CONTRACT, columns=2, sign="contract")
  assert pdf_pages(path) == 1
  words = pdf_page_words(path)[0]
  left, right = column_ends(words)
  assert abs(left - right) <= slack
  assert word(words, "Client")[1] > max(left, right)

@needs_fitz
def long_region_flows_and_signatures_follow(render, word):
  path = render(CONTRACT, columns=2, sign="contract")
  pages = pdf_page_words(path)
  assert len(pages) == 2
  assert word(pages[-1], "Client") and not word(pages[0], "Client")

@needs_fitz
def long_region_balances_its_last_page(render, word, column_ends, slack):
  pages = pdf_page_words(render(CONTRACT, columns=2, sign="contract"))
  first_left, first_right = column_ends(pages[0])
  assert abs(first_left - first_right) < 20 # the pages before stay full
  left, right = column_ends(pages[-1])
  assert abs(left - right) <= slack
  assert word(pages[-1], "Client")[1] > max(left, right)
