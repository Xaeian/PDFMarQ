# tests/test_flow.py

"""
Engine options for flowing documents: `keep_together`, hyphenation, heading sizes, bold,
list markers, parts drawn in a style of their own.
"""

import dataclasses
import pytest
from pdfmarq import PDF, MM_TO_PT
from pdfmarq.inline import RichSegment, wrap_line_heights
from pdfmarq.md import MarkdownRenderer, MarkdownStyle, top_blocks
from conftest import (needs_fitz, pdf_words, pdf_page_words, pdf_faces, pdf_pages, pdf_spans,
  tight_mm)

# A4, 20mm margins, 10mm gap: column 0 spans 20..100mm, column 1 110..190mm.
SPLIT_MM = 105
LINE_MM = MarkdownStyle().body_size * MarkdownStyle().line_height / MM_TO_PT # one body line
BODY = "Startmark " + " ".join(f"word{i}" for i in range(20)) + " Endmark" # five lines

#------------------------------------------------------------------------------------------ Helpers

@pytest.fixture
def columns(tmp_path):
  """
  Render `md` into two columns `lines_high` body lines tall,
  with `room` lines left in the first one.
  Returns `(left, right)`: the word boxes of page 1 on each side.
  """
  def run(md:str, lines_high:float, room:float, **style) -> tuple[list, list]:
    path = str(tmp_path / "flow.pdf")
    pdf = PDF(path)
    height = lines_high * LINE_MM
    pdf.columns(2, gap=10, height=height)
    pdf.cursor(0, height - room * LINE_MM)
    MarkdownRenderer(pdf, MarkdownStyle(**style)).render(md)
    pdf.columns(1)
    pdf.save()
    words = pdf_page_words(path)[0]
    left = [w for w in words if w[2] < SPLIT_MM * MM_TO_PT]
    right = [w for w in words if w[0] > SPLIT_MM * MM_TO_PT]
    return left, right
  return run

@pytest.fixture
def lines(tmp_path):
  """Number of lines `text` wraps to at `width` mm in the default body style."""
  def count(text:str, width:float=80) -> int:
    s = MarkdownStyle()
    pdf = PDF(str(tmp_path / "measure.pdf"))
    MarkdownRenderer(pdf, s) # registers the body font
    seg = RichSegment(text, family=s.font_body, size=s.body_size)
    return len(wrap_line_heights(pdf, [seg], width, line_gap=s.line_height))
  return count

@pytest.fixture
def body_lines():
  """Distinct baselines among the words of `BODY` in `words`."""
  mine = set(BODY.split())
  return lambda words: len({round(w[3], 1) for w in words if w[4] in mine})

#------------------------------------------------------------------------------------------- Splits

def body_is_five_lines_in_a_column_and_in_a_list_item(lines):
  assert lines(BODY) == 5 and lines(BODY, 80 - MarkdownStyle().list_indent) == 5

@needs_fitz
def paragraph_moves_whole_when_kept(columns, word):
  left, right = columns(BODY, 7, 3.6)
  assert word(right, "Startmark") and not word(left, "Startmark")

@needs_fitz
def paragraph_splits_when_flowing(columns, word, body_lines):
  left, right = columns(BODY, 7, 3.6, keep_together=False)
  assert word(left, "Startmark") and word(right, "Endmark")
  assert body_lines(left) >= 2 and body_lines(right) >= 2

@needs_fitz
def list_flows_item_by_item(columns, word):
  items = "\n".join(f"- Item{i} short" for i in range(4))
  kept_left, _ = columns(items, 7, 3.6)
  flow_left, flow_right = columns(items, 7, 3.6, keep_together=False)
  assert not word(kept_left, "Item0")
  assert word(flow_left, "Item0") and word(flow_right, "Item3")

@needs_fitz
def heading_stays_with_three_lines_of_text(columns, word):
  md = "## Headmark\n\n" + BODY
  kept_left, _ = columns(md, 10, 5.9)
  flow_left, _ = columns(md, 10, 5.9, keep_together=False)
  short_left, _ = columns(md, 10, 5.0, keep_together=False) # room for two lines only
  assert not word(kept_left, "Headmark")
  assert word(flow_left, "Headmark")
  assert not word(short_left, "Headmark")

@needs_fitz
def heading_before_table_moves_with_it(columns, word):
  md = "## Tablemark\n\n| a | b |\n|---|---|\n" + "".join(f"| r{i} | v |\n" for i in range(5))
  left, right = columns(md, 10, 5.9, keep_together=False)
  assert word(right, "Tablemark") and not word(left, "Tablemark")

@needs_fitz
def marker_never_alone_at_column_bottom(columns, word):
  left, right = columns("1. " + BODY, 10, 1.5, keep_together=False)
  assert word(right, "1.") and not word(left, "1.")

@needs_fitz
def justified_paragraph_is_measured_as_drawn(tmp_path):
  # four words a line only with tightened spaces: 4 lines justified, 6 ragged, room for 5
  path = str(tmp_path / "tight.pdf")
  pdf = PDF(path)
  style = MarkdownStyle(justify=True)
  renderer = MarkdownRenderer(pdf, style)
  font = pdf._fonts.register(style.font_body, style.body_mode)
  width = tight_mm(" ".join(["Tightmark"] * 4), font, style.body_size)
  pdf.inset(right=pdf.content_width - width)
  pdf.cursor(0, pdf.content_height - 5 * LINE_MM)
  renderer.render(" ".join(["Tightmark"] * 16))
  pdf.inset()
  pdf.save()
  assert pdf_pages(path) == 1 and len(pdf_words(path)) == 16

@needs_fitz
def marker_stays_with_two_lines_of_its_text(columns, word, body_lines):
  left, right = columns("1. " + BODY, 10, 3.6, keep_together=False)
  assert word(left, "1.") and body_lines(left) >= 2 and body_lines(right) >= 2

#----------------------------------------------------------------------------------------- Headings

def heading_size_none_follows_body(tmp_path):
  style = MarkdownStyle(body_size=10, h2_size=None)
  renderer = MarkdownRenderer(PDF(str(tmp_path / "x.pdf")), style)
  assert renderer._heading_size(2) == 10
  assert renderer._heading_size(1) == 20

#-------------------------------------------------------------------------------------------- Parts

@needs_fitz
def part_takes_its_own_style_and_state_runs_on(tmp_path):
  path = str(tmp_path / "parts.pdf")
  style = MarkdownStyle()
  renderer = MarkdownRenderer(PDF(path), style)
  tokens = renderer.parse(
    "[to the second](#same-1)\n\n## Same\n\nBig text.\n\n## Same\n\nSmall text.\n")
  renderer.index(tokens)
  cut = top_blocks(tokens)[3][0] # the second heading opens part two
  renderer.render_tokens(tokens[:cut], dataclasses.replace(style, body_size=16))
  assert renderer.style is style
  renderer.render_tokens(tokens[cut:])
  renderer.pdf.save() # the link reaches the second heading: slugs ran on across the parts
  faces = pdf_faces(path)
  assert faces["Big"][1] == pytest.approx(16)
  assert faces["Small"][1] == pytest.approx(style.body_size)

def footnotes_stay_one_block(tmp_path):
  renderer = MarkdownRenderer(PDF(str(tmp_path / "x.pdf")), MarkdownStyle())
  tokens = renderer.parse("Text[^a] and[^b].\n\n[^a]: First note.\n\n[^b]: Second note.\n")
  kinds = [tokens[start].type for start, _ in top_blocks(tokens)]
  assert kinds == ["paragraph_open", "footnote_block_open"]

#--------------------------------------------------------------------------------------------- Bold

@pytest.fixture
def bold_mode(tmp_path):
  """Mode `**strong**` resolves to inside a paragraph and a heading of the given style."""
  def resolve(**style) -> tuple[str, str]:
    renderer = MarkdownRenderer(PDF(str(tmp_path / "x.pdf")), MarkdownStyle(**style))
    s = renderer.style
    modes = []
    for md, mode in (("Text **strong**", s.body_mode), ("# Head **strong**", s.head_mode)):
      inline = next(t for t in renderer.parse(md) if t.type == "inline")
      base = RichSegment("", family=s.font_body, mode=mode, size=s.body_size)
      segs = renderer._inline_to_segments(inline, base)
      modes.append(next(seg.mode for seg in segs if seg.text == "strong"))
    return tuple(modes)
  return resolve

def bold_in_regular_heading_is_bold(bold_mode):
  assert bold_mode(head_mode="Regular") == ("Bold", "Bold")

def bold_in_bold_heading_escalates(bold_mode):
  assert bold_mode() == ("Bold", "Black")

#------------------------------------------------------------------------------------------ Markers

@needs_fitz
def paren_marker_printed_as_typed(tmp_path, word):
  path = str(tmp_path / "paren.pdf")
  pdf = PDF(path)
  MarkdownRenderer(pdf, MarkdownStyle()).render("1) first\n2) second\n\n1. dot\n")
  pdf.save()
  words = pdf_words(path)
  assert word(words, "1)") and word(words, "2)") and word(words, "1.")

#-------------------------------------------------------------------------------------- Hyphenation

@needs_fitz
def paragraphs_hyphenate_headings_stay_whole(tmp_path):
  pytest.importorskip("pyphen")
  text = "Zleceniodawca przekazuje Zleceniobiorcy dokumentację programistyczną " * 4
  path = str(tmp_path / "hyphen.pdf")
  pdf = PDF(path)
  pdf.columns(2, gap=10) # the narrow measure of a contract
  style = MarkdownStyle(hyphenate="pl", justify=True)
  MarkdownRenderer(pdf, style).render(f"## {text}\n\n{text}\n\n- {text}\n")
  pdf.columns(1)
  pdf.save()
  split = [size for span, _, size, _ in pdf_spans(path)[0] if span.endswith("-")]
  assert len(split) >= 2 and all(size == style.body_size for size in split)

#----------------------------------------------------------------------------------------- Up front

def engine_refuses_a_pdf_in_another_unit(tmp_path):
  with pytest.raises(ValueError, match="unit"):
    MarkdownRenderer(PDF(str(tmp_path / "u.pdf"), unit="cm"))

def unknown_hyphenation_language_fails_up_front(tmp_path):
  pytest.importorskip("pyphen")
  with pytest.raises(ValueError, match="xx"):
    MarkdownRenderer(PDF(str(tmp_path / "h.pdf")), MarkdownStyle(hyphenate="xx"))

@pytest.mark.parametrize("line, rules", [("---", 1), ("===", 0)])
def image_over_a_line_stays_a_figure(tmp_path, monkeypatch, line, rules):
  # CommonMark reads it as a setext heading holding the picture; only `---` is a rule
  from PIL import Image
  Image.new("RGB", (40, 20)).save(tmp_path / "pic.png")
  drawn = []
  monkeypatch.setattr(MarkdownRenderer, "_render_hr", lambda self: drawn.append(1))
  renderer = MarkdownRenderer(PDF(str(tmp_path / "s.pdf")), base_dir=str(tmp_path))
  renderer.render(f"![diagram](pic.png)\n{line}\n")
  assert len(drawn) == rules
