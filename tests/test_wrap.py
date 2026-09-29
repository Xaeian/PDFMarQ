# tests/test_wrap.py

"""
Line wrapping keeps text inside its box.

Words spanning styled segments stay whole, and code keeps its indent.
Inline-code padding counts toward the line.
Table columns never squeeze short codes.
`box_fit` cuts a long word rather than shrink it past legibility.
"""

import re, warnings
import pytest
from reportlab.graphics.shapes import Drawing
from conftest import render_md, pdf_words, pdf_glyphs_past
from pdfmarq import PDF
from pdfmarq.constants import MM_TO_PT
from pdfmarq.fonts import FontManager
from pdfmarq.inline import (
  RichSegment, measure_extent,
  _tokenize, _wrap, _group_runs, _line_width_pt,
)
from pdfmarq.text import TextMetrics, FIT_EPS_PT, READABLE_MIN_PT, split_word
from pdfmarq.md.md_table import _cap_widths

LONG = "opis ktory jest na tyle dlugi ze musi sie zawinac w komorce tabeli " * 2
CODE_BG = (0.9, 0.9, 0.9)

@pytest.fixture
def pdf(tmp_path):
  return PDF(str(tmp_path / "wrap.pdf"))

@pytest.fixture
def measure(pdf):
  """Width in pt of text set in 11pt Helvetica, the default segment font."""
  return lambda text: pdf._metrics.text_width(text, "Helvetica", "Regular", 11)

@pytest.fixture
def wrap(pdf):
  """Wrapped lines of `segs` at `width_pt`, each joined back into its text."""
  def run(segs:list, width_pt:float, code:bool=False) -> list[str]:
    words = _tokenize(segs, pdf._metrics)
    lines = _wrap(words, width_pt, pdf._metrics, preserve_leading_space=code).lines
    return ["".join(w.text for w in line) for line in lines]
  return run

@pytest.fixture
def joined():
  """
  `joined(path, head, tail)`: every `head` has `tail` right after it on the same line.
  The extractor may still report two words, since an inline-code rect leaves a gap.
  """
  def check(path, head:str, tail:str) -> bool:
    ws = pdf_words(str(path))
    whole = re.compile(re.escape(head) + "(" + re.escape(tail) + r")?[.,]?")
    heads = [(w, m) for w in ws if (m := whole.fullmatch(w[4]))]
    def followed(w) -> bool: # `tail` on the same baseline, within 8pt after `w`
      return any(v[4].startswith(tail) and abs(v[3] - w[3]) < 1.5 and 0 <= v[0] - w[2] < 8
        for v in ws)
    # a head without its tail in the same word must have the tail right beside it
    return bool(heads) and all(m.group(1) or followed(w) for w, m in heads)
  return check

#-------------------------------------------------------------------------------------------- Words

def word_spanning_segments_moves_whole(measure, wrap):
  # `**PP**-1`: "PP" fits after "slowo", "-1" would not - the line must not break between them
  segs = [RichSegment("slowo "), RichSegment("PP", bold=True), RichSegment("-1")]
  assert wrap(segs, measure("slowo PP")) == ["slowo", "PP-1"]

def extent_min_covers_word_across_segments(pdf, measure, wrap):
  segs = [RichSegment("PP", bold=True), RichSegment("-1"), RichSegment(" x")]
  whole = pdf._metrics.text_width("PP", "Helvetica", "Bold", 11) + measure("-1")
  widest, _ = measure_extent(pdf, segs)
  assert widest * MM_TO_PT == pytest.approx(whole)
  assert wrap(segs, widest * MM_TO_PT) == ["PP-1", "x"]

def word_at_exact_width_survives_rounding(measure, wrap):
  # a column sized to its widest word comes back through mm→pt a hair narrower
  assert wrap([RichSegment("PP-1")], measure("PP-1") - 1e-9) == ["PP-1"]

def oversized_word_still_breaks(wrap):
  url = "https://example.com/a/b/c/d/e/f"
  lines = wrap([RichSegment(url)], 60)
  assert len(lines) > 1 and "".join(lines) == url

def break_takes_the_last_delimiter_in_reach(measure):
  assert split_word("abc/def/ghijkl", measure("abc/def/"), measure)[0] == "abc/def/"

def delimiter_opening_a_chunk_stays_with_it(measure):
  chunks = split_word("ABCDEFGHIJ/KLMNOPQRSTUVWXYZ", measure("ABCDEFGHIJ"), measure)
  assert "/" not in chunks and "".join(chunks) == "ABCDEFGHIJ/KLMNOPQRSTUVWXYZ"

#-------------------------------------------------------------------------------------- Code indent

def indented_code_fills_its_line(pdf, wrap):
  # the word fits a line alone but not after the indent: no blank line, the indent stays
  code = ["        ", "self"] + [f".part{i}" for i in range(12)]
  segs = [RichSegment(text, family="Courier") for text in code]
  width = pdf._metrics.text_width("x" * 85, "Courier", "Regular", 11)
  lines = wrap(segs, width, code=True)
  assert len(lines) == 2 and lines[0].startswith("        self")

def token_too_wide_after_indent_drops_the_indent(pdf, wrap):
  segs = [RichSegment("    ", family="Courier"), RichSegment("x" * 40, family="Courier")]
  width = pdf._metrics.text_width("x" * 42, "Courier", "Regular", 11)
  assert wrap(segs, width, code=True) == ["x" * 40]

#-------------------------------------------------------------------------------------- Run padding

def inline_code_padding_counts_toward_line(pdf):
  segs = []
  for i in range(40):
    code = RichSegment(f"kod{i}", family="Courier", bg_color=CODE_BG)
    segs += [RichSegment("slowo "), code, RichSegment(" ")]
  width = 120 * MM_TO_PT
  for line in _wrap(_tokenize(segs, pdf._metrics), width, pdf._metrics).lines:
    assert _line_width_pt(line) <= width + FIT_EPS_PT

def paragraph_with_inline_code_stays_in_margin(tmp_path):
  path = str(tmp_path / "code.pdf")
  pdf = render_md(path, " ".join(f"slowo `kod{i}`" for i in range(60)))
  right = (pdf._page.width - pdf._page.margin_right) * MM_TO_PT
  assert pdf_glyphs_past(path, right) == []

def right_aligned_code_column_stays_in_table(tmp_path):
  path = str(tmp_path / "right.pdf")
  cells = " ".join(f"`0x{i:04X}`" for i in range(8))
  pdf = render_md(path, f"| Nazwa | Wartosc |\n|---|---:|\n| param | {cells} |\n")
  right = (pdf._page.width - pdf._page.margin_right) * MM_TO_PT
  assert pdf_glyphs_past(path, right) == []

def aligned_line_counts_run_padding(pdf):
  # centre and right alignment offset the line by this width
  seg = RichSegment("kod", family="Courier", bg_color=CODE_BG)
  line = _wrap(_tokenize([seg], pdf._metrics), 500, pdf._metrics).lines[0]
  assert _line_width_pt(line) > line[0].width_pt

def repeated_drawing_is_its_own_run(pdf):
  # two emoji side by side share one cached drawing, yet each must be drawn
  d = Drawing(10, 10)
  segs = [RichSegment("", math_drawing=d, math_width_pt=10) for _ in range(2)]
  line = _wrap(_tokenize(segs, pdf._metrics), 500, pdf._metrics).lines[0]
  assert len(_group_runs(line)) == 2

#------------------------------------------------------------------------------------------- Tables

@pytest.mark.parametrize("cell", ["PP-1", "**PP**-1", "`PP`-1", "[PP](https://x.pl)-1"])
def short_code_cell_stays_whole(tmp_path, joined, cell):
  path = tmp_path / "cell.pdf"
  render_md(str(path), f"| Kod | Opis |\n|---|---|\n| {cell} | {LONG} |\n| {cell} | {LONG} |\n")
  assert joined(path, "PP", "-1")

def long_url_does_not_squeeze_other_columns(tmp_path, joined):
  # column minimums overflow the page: only the URL columns may give way
  path = tmp_path / "urls.pdf"
  url = "https://example.com/very/long/path/to/some/resource/file.pdf"
  render_md(str(path), f"| A | B | C | D |\n|---|---|---|---|\n| PP-1 | {url} | {url} | OK |\n")
  assert joined(path, "PP", "-1") and joined(path, "O", "K")

def cap_widths_cuts_only_the_widest():
  assert _cap_widths([10, 12, 150], 100) == pytest.approx([10, 12, 78])
  assert _cap_widths([50, 60, 70], 90) == pytest.approx([30, 30, 30])
  assert sum(_cap_widths([5, 80, 120, 7], 150)) == pytest.approx(150)

#------------------------------------------------------------------------------------------ box_fit

def box_fit_breaks_oversized_word_and_wraps_the_rest():
  text = "Lorem Pneumonoultramicroscopicsilicovolcanoconiosis dolor sit"
  metrics = TextMetrics(FontManager())
  fit = metrics.box_fit(text, 60)
  lines = fit.text.split("\n")
  assert fit.overflow and len(lines) > 2 and lines[0] == "Lorem"
  for line in lines:
    assert metrics.text_width(line, "Helvetica", "Regular", 12) <= 60 + FIT_EPS_PT
  assert "".join(lines).replace(" ", "") == text.replace(" ", "")

def box_fit_survives_a_box_narrower_than_its_padding():
  # a column narrower than its cell padding leaves a negative width, and a cell may be empty
  metrics = TextMetrics(FontManager())
  assert metrics.box_fit("", -5).text == ""
  assert metrics.box_fit("a  b", -5).overflow

def box_fit_cuts_a_long_url_at_a_readable_size():
  url = "https://example.com/very/long/path/to/some/resource/file.pdf"
  metrics = TextMetrics(FontManager())
  with warnings.catch_warnings():
    warnings.simplefilter("error") # shrinking past legibility warns
    fit = metrics.box_fit(url, 40 * MM_TO_PT, 20 * MM_TO_PT, autoscale=0.1)
  assert fit.font_size >= READABLE_MIN_PT and fit.lines > 1
