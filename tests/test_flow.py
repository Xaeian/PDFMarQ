# tests/test_flow.py

"""
Engine options for flowing documents: `keep_together`, hyphenation, heading sizes, bold,
list markers, parts drawn in a style of their own.
"""

import dataclasses
import pytest
from pdfmarq import PDF, MM_TO_PT, Align
from pdfmarq.inline import (RichSegment, RichText, render_rich, wrap_line_heights, flow_rich,
  split_rich, drop_cap)
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
    return len(wrap_line_heights(pdf, RichText([seg], width, line_gap=s.line_height)))
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
      segs = renderer.segments(inline, base)
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

def table_rules_fail_before_anything_is_drawn(tmp_path):
  with pytest.raises(ValueError, match="table_rules"):
    MarkdownRenderer(PDF(str(tmp_path / "t.pdf")), MarkdownStyle(table_rules="box"))

@pytest.mark.parametrize("line, rules", [("---", 1), ("===", 0)])
def image_over_a_line_stays_a_figure(tmp_path, monkeypatch, line, rules):
  # CommonMark reads it as a setext heading holding the picture;
  # only `---` is a rule
  from PIL import Image
  Image.new("RGB", (40, 20)).save(tmp_path / "pic.png")
  drawn = []
  monkeypatch.setattr(MarkdownRenderer, "_render_hr", lambda self: drawn.append(1))
  renderer = MarkdownRenderer(PDF(str(tmp_path / "s.pdf")), base_dir=str(tmp_path))
  renderer.render(f"![diagram](pic.png)\n{line}\n")
  assert len(drawn) == rules

#------------------------------------------------------------------------------ Journal typesetting

@needs_fitz
def first_indent_sets_the_first_line_of_a_body_paragraph_in(tmp_path):
  path = str(tmp_path / "indent.pdf")
  pdf = PDF(path)
  MarkdownRenderer(pdf, MarkdownStyle(first_indent=10)).render(f"{BODY}\n\n- Itemmark\n")
  pdf.save()
  words = pdf_page_words(path)[0]
  first, item = (next(w for w in words if w[4] == text) for text in ("Startmark", "Itemmark"))
  lines = sorted({round(w[1]) for w in words if w[4] != "Itemmark"})
  second = min(w[0] for w in words if round(w[1]) == lines[1])
  assert first[0] == pytest.approx(30 * MM_TO_PT, abs=0.5)
  assert second == pytest.approx(20 * MM_TO_PT, abs=0.5)
  assert item[0] > 20 * MM_TO_PT # a list item keeps its own indent, none on top of it

def first_indent_takes_room_on_the_first_line_but_never_stands_alone(tmp_path):
  pdf = PDF(str(tmp_path / "w.pdf"))
  two = [RichSegment("Startmark endmark", family="Helvetica", size=11)]
  width = pdf.metrics.text_width("Startmark endmark", "Helvetica", "Regular", 11) / MM_TO_PT + 1
  assert len(wrap_line_heights(pdf, RichText(two, width))) == 1
  assert len(wrap_line_heights(pdf, RichText(two, width, indent_mm=5))) == 2
  # a word that fits the line but not behind the indent starts it at the margin
  one = [RichSegment("Startmark", family="Helvetica", size=11)]
  assert len(wrap_line_heights(pdf, RichText(one, 60, indent_mm=59))) == 1

@needs_fitz
@pytest.mark.parametrize("rules, double, verticals, rows", [
  ("grid", False, True, 4), ("rows", False, False, 4), ("head", True, False, 5)])
def table_rules_draw_the_lines_they_name(tmp_path, rules, double, verticals, rows):
  import fitz
  path = str(tmp_path / f"{rules}.pdf")
  pdf = PDF(path)
  MarkdownRenderer(pdf, MarkdownStyle(table_rules=rules, table_double=double)).render(
    "| a | b |\n| - | - |\n| 1 | 2 |\n| 3 | 4 |\n")
  pdf.save()
  with fitz.open(path) as doc:
    lines = [item for d in doc[0].get_drawings() for item in d["items"] if item[0] == "l"]
  upright = [l for l in lines if abs(l[1].x - l[2].x) < 0.01]
  across = {round(l[1].y, 1) for l in lines if abs(l[1].y - l[2].y) < 0.01}
  assert bool(upright) == verticals
  assert len(across) == rows

@needs_fitz
def a_double_rule_leaves_the_rows_their_padding(tmp_path):
  # its second line stands outside the rows, so text keeps the gaps a single rule leaves it
  import fitz
  def gaps(double:bool) -> tuple[float, float]:
    path = str(tmp_path / f"double{double}.pdf")
    pdf = PDF(path)
    MarkdownRenderer(pdf, MarkdownStyle(table_rules="head", table_double=double)).render(
      "| Head | b |\n| - | - |\n| 1 | 2 |\n| last | 4 |\n")
    pdf.save()
    with fitz.open(path) as doc:
      lines = [item for d in doc[0].get_drawings() for item in d["items"] if item[0] == "l"]
      words = {w[4]: w for w in doc[0].get_text("words")}
    across = {line[1].y for line in lines if abs(line[1].y - line[2].y) < 0.01}
    head, last = words["Head"], words["last"]
    above = head[1] - max(y for y in across if y < head[1])
    below = min(y for y in across if y > last[3]) - last[3]
    return above, below
  assert gaps(True) == pytest.approx(gaps(False), abs=0.05)

def segments_grow_an_inline_token_from_a_base(tmp_path):
  renderer = MarkdownRenderer(PDF(str(tmp_path / "s.pdf")))
  inline = renderer.parse("Plain **bold** `code`\n")[1]
  segs = renderer.segments(inline, RichSegment("", family="Helvetica", size=8))
  assert [s.text for s in segs][:2] == ["Plain ", "bold"]
  assert segs[1].mode == "Bold" and {s.size for s in segs[:2]} == {8}

def flow_rich_moves_a_lone_first_line_to_the_next_frame(tmp_path):
  pdf = PDF(str(tmp_path / "f.pdf"))
  segs = [RichSegment(BODY, family="Helvetica", size=11)]
  heights = wrap_line_heights(pdf, RichText(segs, 60))
  pdf.cursor(0, pdf.content_height - 1.5 * heights[0]) # room for one line
  flow_rich(pdf, RichText(segs, 60), min_lines=2)
  assert pdf.page_num == 2 and pdf.y == pytest.approx(sum(heights))

def flow_rich_leaves_the_next_frame_two_lines(tmp_path):
  pdf = PDF(str(tmp_path / "f.pdf"))
  segs = [RichSegment(BODY, family="Helvetica", size=11)]
  heights = wrap_line_heights(pdf, RichText(segs, 60))
  assert len(heights) >= 4
  pdf.cursor(0, pdf.content_height - sum(heights[:-1]) - 0.1) # room for all lines but the last
  flow_rich(pdf, RichText(segs, 60), min_lines=2)
  assert pdf.page_num == 2 and pdf.y == pytest.approx(sum(heights[-2:]))

def split_rich_goes_on_where_the_line_broke(tmp_path):
  pdf = PDF(str(tmp_path / "s.pdf"))
  nbsp = chr(0xA0)
  seg = RichSegment(f"aaa bbb alphaword{nbsp}[1] ccc ddd", family="Helvetica", size=11)
  width = pdf.metrics.text_width("aaa bbb alphaword", "Helvetica", "Regular", 11) / MM_TO_PT + 1
  rest = split_rich(pdf, RichText([seg], width), 1)
  assert "".join(s.text for s in rest) == f"alphaword{nbsp}[1] ccc ddd" # the bound pair whole
  assert rest[0].family == "Helvetica" and not rest[0].break_line
  assert split_rich(pdf, RichText([seg], 500), 1) == []

def split_rich_hands_on_the_rest_of_a_hyphenated_word(tmp_path):
  pytest.importorskip("pyphen")
  pdf = PDF(str(tmp_path / "h.pdf"))
  seg = RichSegment("aaa dokumentacji bbb", family="Helvetica", size=11, hyphenate="pl")
  width = pdf.metrics.text_width("aaa dokumen-", "Helvetica", "Regular", 11) / MM_TO_PT + 0.5
  rest = "".join(s.text for s in split_rich(pdf, RichText([seg], width), 1))
  tail = rest.removesuffix(" bbb")
  assert tail != rest and tail != "dokumentacji" and "dokumentacji".endswith(tail)

def split_rich_hands_on_a_word_hyphenated_twice_whole(tmp_path):
  pytest.importorskip("pyphen")
  pdf = PDF(str(tmp_path / "h.pdf"))
  word = "konstantynopolitanczykowianeczka"
  seg = RichSegment(f"aaa {word}", family="Helvetica", size=11, hyphenate="pl")
  width = pdf.metrics.text_width("aaa konstan-", "Helvetica", "Regular", 11) / MM_TO_PT + 0.5
  assert len(wrap_line_heights(pdf, RichText([seg], width))) > 2 # cut on the first line and again
  rest = "".join(s.text for s in split_rich(pdf, RichText([seg], width), 1))
  assert "-" not in rest and word.endswith(rest) and rest != word

def split_rich_keeps_an_empty_line_after_the_cut(tmp_path):
  pdf = PDF(str(tmp_path / "b.pdf"))
  face = dict(family="Helvetica", size=11)
  segs = [RichSegment("aaa", **face), RichSegment("", break_line=True, **face),
    RichSegment("bbb", break_line=True, **face)]
  rest = split_rich(pdf, RichText(segs, 60), 1)
  assert len(wrap_line_heights(pdf, RichText(rest, 60))) == 2 # the empty line, then `bbb`

def split_rich_keeps_an_empty_line_before_a_cut_word(tmp_path):
  pytest.importorskip("pyphen")
  pdf = PDF(str(tmp_path / "b.pdf"))
  face = dict(family="Helvetica", size=11, hyphenate="pl")
  word = "konstantynopolitanczykowianeczka"
  segs = [RichSegment("aaa", **face), RichSegment("", break_line=True, **face),
    RichSegment(word, break_line=True, **face)]
  width = pdf.metrics.text_width("aaa konstan-", "Helvetica", "Regular", 11) / MM_TO_PT + 0.5
  rest = split_rich(pdf, RichText(segs, width), 1)
  assert rest[0].break_line and "".join(s.text for s in rest) == word

@needs_fitz
def drop_cap_sets_its_letter_beside_two_lines_and_the_rest_under_it(tmp_path):
  path = str(tmp_path / "d.pdf")
  pdf = PDF(path)
  segs = [RichSegment(BODY, family="Helvetica", size=11)]
  assert drop_cap(pdf, RichText(segs, 60, line_gap=1.2), caps=True)
  pdf.save()
  spans = pdf_spans(path)[0]
  letter = max(spans, key=lambda s: s[2])
  words = [s for s in spans if s is not letter]
  tops = sorted({round(s[3][1]) for s in words})
  lefts = [min(s[3][0] for s in words if round(s[3][1]) == top) for top in tops[:3]]
  assert letter[0] == "S" and letter[2] > 2 * 11
  assert words[0][0].startswith("TARTMARK ") # the rest of the first word in capitals
  assert lefts[0] == pytest.approx(lefts[1]) and lefts[2] < lefts[0] - 5
  assert pdf.y > 0

def drop_cap_leaves_text_opening_with_no_letter(tmp_path):
  pdf = PDF(str(tmp_path / "n.pdf"))
  assert not drop_cap(pdf, RichText([RichSegment("[1] cited", family="Helvetica", size=11)], 60))
  assert pdf.y == 0

def drop_cap_takes_no_letter_after_an_opening_formula(tmp_path):
  from reportlab.graphics.shapes import Drawing
  pdf = PDF(str(tmp_path / "f.pdf"))
  face = dict(family="Helvetica", size=11)
  segs = [RichSegment("", math_drawing=Drawing(20, 10), **face), RichSegment(" is it", **face)]
  assert not drop_cap(pdf, RichText(segs, 60))

def drop_cap_takes_no_letter_of_an_opening_link(tmp_path):
  pdf = PDF(str(tmp_path / "l.pdf"))
  face = dict(family="Helvetica", size=11)
  link = RichSegment("Linked", link_url="https://example.com", **face) # as docmarq, no letter
  assert not drop_cap(pdf, RichText([link, RichSegment(" words", **face)], 60))

def html_code_stays_whole_in_hyphenated_text(tmp_path):
  pytest.importorskip("pyphen")
  renderer = MarkdownRenderer(PDF(str(tmp_path / "c.pdf")),
    MarkdownStyle(hyphenate="pl", code_inline_bg=None))
  inline = renderer.parse("Text <code>konstantynopolitanczykowianeczka</code> here\n")[1]
  segs = renderer.segments(inline, RichSegment("", family="Helvetica", size=11, hyphenate="pl"))
  code = next(s for s in segs if "konstantynopolitanczykowianeczka" in s.text)
  assert code.code # code, as in backticks, shaded or not

def code_keeps_its_words_whole_and_its_spaces_unstretched(tmp_path):
  pytest.importorskip("pyphen")
  path = str(tmp_path / "code.pdf")
  pdf = PDF(path)
  face = dict(family="Helvetica", size=11, hyphenate="pl")
  word = "konstantynopolitanczykowianeczka"
  width = pdf.metrics.text_width(f"aaa {word}", "Helvetica", "Regular", 11) / MM_TO_PT - 5
  whole = RichText([RichSegment("aaa ", **face), RichSegment(word, code=True, **face)], width)
  assert "".join(s.text for s in split_rich(pdf, whole, 1)) == word # moved on, not hyphenated
  segs = [RichSegment("words then ", **face), RichSegment("a b", family="Courier", size=11,
    code=True), RichSegment(" and more words to fill a justified line well enough", **face)]
  render_rich(pdf, RichText(segs, 60, Align.JUSTIFY), 0, 0)
  pdf.save()
  a, b = [w for w in pdf_page_words(path)[0] if w[4] in ("a", "b")][:2]
  space = pdf.metrics.text_width(" ", "Courier", "Regular", 11)
  assert b[0] - a[2] == pytest.approx(space, abs=0.05) # a code space keeps its width

def flow_rich_ends_where_no_frame_follows():
  # in `frame()` and in parallel columns `next_frame()` stays put: the text runs past the foot
  import io, threading, warnings
  from pdfmarq.md import MarkdownRenderer, MarkdownStyle
  failed = []
  def run(case:str):
    try:
      warnings.simplefilter("ignore")
      pdf = PDF(io.BytesIO())
      text = RichText([RichSegment("word " * 400)], 50)
      if case == "columns":
        pdf.columns(2, flow=False)
        pdf.cursor(0, pdf.content_height - 12)
        flow_rich(pdf, text, min_lines=2)
        return
      with pdf.frame(10, 10, 60, 40):
        pdf.cursor(0, 30)
        if case == "frame": flow_rich(pdf, text, min_lines=2)
        else: MarkdownRenderer(pdf, MarkdownStyle(keep_together=False)).render("word " * 400)
    except Exception as e:
      failed.append(f"{case}: {e}")
  for case in ("frame", "columns", "markdown"):
    worker = threading.Thread(target=run, args=(case,), daemon=True)
    worker.start()
    worker.join(20)
    assert not worker.is_alive(), f"{case} never returned"
  assert not failed

def flow_rich_moves_a_text_once_where_a_page_header_takes_the_top():
  # three lines with room for two go whole to page 2, below the header, not two there and one on 3
  import io
  pdf = PDF(io.BytesIO())
  pdf.on_new_page(lambda page, number: page.cursor(0, 30))
  words = 1
  while len(wrap_line_heights(pdf, RichText([RichSegment("word " * words)], 60))) < 3: words += 1
  text = RichText([RichSegment("word " * words)], 60)
  heights = wrap_line_heights(pdf, text)
  pdf.cursor(0, pdf.content_height - sum(heights[:2]) - 0.1)
  flow_rich(pdf, text, min_lines=2)
  assert pdf.page_num == 2

def flow_rich_moves_a_text_it_cannot_split_to_the_next_frame(tmp_path):
  pdf = PDF(str(tmp_path / "w.pdf"))
  face = dict(family="Helvetica", size=11)
  text = next(t for t in (RichText([RichSegment(" ".join(["word"] * n), **face)], 40)
    for n in range(4, 40)) if len(wrap_line_heights(pdf, t)) == 3)
  heights = wrap_line_heights(pdf, text)
  pdf.cursor(0, pdf.content_height - heights[0] - heights[1] - 0.1) # room for two of three lines
  flow_rich(pdf, text, min_lines=2)
  assert pdf.page_num == 2 and pdf.y == pytest.approx(sum(heights)) # all three together

def flow_rich_and_drop_cap_keep_to_a_pdf_in_points(tmp_path):
  pdf = PDF(str(tmp_path / "pt.pdf"), unit="pt")
  text = RichText([RichSegment(BODY, family="Helvetica", size=11)], 60)
  flow_rich(pdf, text, x_mm=10)
  assert (pdf.x, pdf.y) == (pytest.approx(10), pytest.approx(sum(wrap_line_heights(pdf, text))))
  y = pdf.y
  assert drop_cap(pdf, text, x_mm=10)
  assert pdf.x == pytest.approx(10) and y < pdf.y < y + 40 # mm, not points read as mm

def an_indented_first_word_too_long_for_its_line_is_hyphenated(tmp_path):
  pytest.importorskip("pyphen")
  pdf = PDF(str(tmp_path / "i.pdf"))
  word = "konstantynopolitanczykowianeczka"
  seg = RichSegment(f"{word} end", family="Helvetica", size=11, hyphenate="pl")
  for indent in (0, 5):
    rest = "".join(s.text for s in split_rich(pdf, RichText([seg], 40, indent_mm=indent), 1))
    assert rest.endswith(" end") and word.endswith(rest[:-4]) and rest[:-4] != word
