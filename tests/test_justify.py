# tests/test_justify.py

"""
Justified text: lines fill the width, the last line and hard breaks stay left,
and words split at the hyphenation points of the text's language.
"""

import io, sys
import pytest
from pdfmarq import PDF, Align, MM_TO_PT, RichSegment, render_rich
from pdfmarq.inline import measure_extent
from pdfmarq.inline import (_Word, _justify_ratio, _spaced_width, _stretches, _JUSTIFY_SHRINK,
  _tokenize, _wrap, measure_extent, wrap_line_heights)
from conftest import needs_fitz, pdf_words, pdf_links, pdf_chars, tight_mm

TEXT = "Justified text spreads its spaces until every line but the last meets the edge. " * 5
PHRASE = "Tighter spaces fit"
POLISH = ("Zleceniobiorca zobowiązuje się do wykonywania prac programistycznych na rzecz "
  "Zleceniodawcy, w szczególności przygotowywania oprogramowania i prowadzenia testów.")
LEFT_PT = 20 * MM_TO_PT # page margin
WIDTH_MM = 80

#------------------------------------------------------------------------------------------ Helpers

@pytest.fixture
def lines_of(tmp_path):
  """Draw `segments` at `width` mm, return the word boxes grouped per line, top to bottom."""
  def draw(segments:list, align:str=Align.JUSTIFY, width:float=WIDTH_MM) -> list[list]:
    path = str(tmp_path / "justify.pdf")
    pdf = PDF(path)
    render_rich(pdf, segments, width, 0, 0, align, 1.4)
    pdf.save()
    rows: dict[float, list] = {}
    for w in pdf_words(path):
      rows.setdefault(round(w[3], 1), []).append(w)
    return [sorted(rows[y]) for y in sorted(rows)]
  return draw

@pytest.fixture
def broken():
  """Text of each line `segments` wrap into, justified `width` mm wide."""
  pdf = PDF(io.BytesIO())
  def wrap(segments:list, width:float=40) -> list[str]:
    words = _tokenize(segments, pdf._metrics)
    lines = _wrap(words, width * MM_TO_PT, pdf._metrics, shrink=_JUSTIFY_SHRINK).lines
    return ["".join(w.text for w in line) for line in lines]
  return wrap

@pytest.fixture
def tight():
  """Width (mm) `PHRASE` at the `RichSegment` defaults fills only with its spaces tightened."""
  seg = RichSegment(PHRASE)
  return tight_mm(PHRASE, seg.family, seg.size)

#-------------------------------------------------------------------------------------------- Lines

@needs_fitz
def lines_meet_the_right_edge(lines_of):
  lines = lines_of([RichSegment(TEXT)])
  right = LEFT_PT + WIDTH_MM * MM_TO_PT
  assert len(lines) > 2
  for line in lines[:-1]:
    assert line[0][0] == pytest.approx(LEFT_PT, abs=0.5)
    assert line[-1][2] == pytest.approx(right, abs=0.5)
  assert lines[-1][-1][2] < right - 5

@needs_fitz
def hard_break_keeps_its_line_left(lines_of):
  lines = lines_of([RichSegment("Short line"), RichSegment("\n"), RichSegment(TEXT)])
  right = LEFT_PT + WIDTH_MM * MM_TO_PT
  assert lines[0][-1][2] < right - 50
  assert lines[1][-1][2] == pytest.approx(right, abs=0.5)

@needs_fitz
def left_alignment_stays_ragged(lines_of):
  lines = lines_of([RichSegment(TEXT)], align=Align.LEFT)
  right = LEFT_PT + WIDTH_MM * MM_TO_PT
  assert all(line[-1][2] < right + 0.5 for line in lines)
  assert any(line[-1][2] < right - 2 for line in lines[:-1])

@needs_fitz
def link_covers_the_stretched_spaces(tmp_path):
  path = str(tmp_path / "link.pdf")
  pdf = PDF(path)
  segs = [RichSegment("Some words lead in, then "),
    RichSegment("a link with spaces", link_url="https://example.com", underline=True),
    RichSegment(" " + TEXT)]
  render_rich(pdf, segs, WIDTH_MM, 0, 0, Align.JUSTIFY, 1.4)
  pdf.save()
  rect = pdf_links(path)[0]["from"]
  spaces = next(w for w in pdf_words(path) if w[4] == "spaces")
  assert rect.x1 == pytest.approx(spaces[2], abs=0.5)

#--------------------------------------------------------------------------------------- Tightening

def justified_line_tightens_to_take_a_word(tight):
  pdf = PDF(io.BytesIO())
  segs = [RichSegment(PHRASE)]
  assert len(wrap_line_heights(pdf, segs, tight, align=Align.JUSTIFY)) == 1
  assert len(wrap_line_heights(pdf, segs, tight, align=Align.LEFT)) == 2

@needs_fitz
def tightened_line_ends_at_the_edge(lines_of, tight):
  lines = lines_of([RichSegment(PHRASE)], width=tight)
  assert len(lines) == 1
  # the last line too, since it took its word by tightening
  assert lines[0][-1][2] == pytest.approx(LEFT_PT + tight * MM_TO_PT, abs=0.5)

#------------------------------------------------------------------------------------------ Spacing

def spaces_resize_in_proportion():
  narrow, wide = RichSegment("x", size=10), RichSegment("x", size=20)
  line = [_Word("one", narrow, 20, False), _Word(" ", narrow, 2, True),
    _Word("two", wide, 20, False), _Word(" ", wide, 4, True), _Word("three", narrow, 30, False)]
  assert _justify_ratio(line, 12) == pytest.approx(2) # 6pt of spaces, each three times as wide
  assert _justify_ratio(line[:1], 8) == 0
  # the most tightening `_wrap` counts on: no space gives more than its share
  ratio = _justify_ratio(line, -6 * (1 - _JUSTIFY_SHRINK))
  spaced = [_spaced_width(w, ratio) for w in line if w.is_space]
  assert spaced == pytest.approx([2 * _JUSTIFY_SHRINK, 4 * _JUSTIFY_SHRINK])

def code_spaces_never_stretch():
  code = RichSegment("a b", bg_color=(0.9, 0.9, 0.9))
  assert not _stretches(_Word(" ", code, 3, True))
  assert _stretches(_Word(" ", RichSegment("a b"), 3, True))

#-------------------------------------------------------------------------------------- Hyphenation

def words_split_at_hyphenation_points(broken):
  pytest.importorskip("pyphen")
  lines = broken([RichSegment(POLISH, hyphenate="pl")])
  assert any(line.endswith("-") for line in lines)
  joined = "".join(line[:-1] if line.endswith("-") else line + " " for line in lines)
  assert joined.strip() == POLISH

def words_stay_whole_without_a_language(broken):
  assert not any(line.endswith("-") for line in broken([RichSegment(POLISH)]))

def code_and_links_never_split(broken):
  pytest.importorskip("pyphen")
  for seg in (RichSegment(POLISH, hyphenate="pl", bg_color=(0.9, 0.9, 0.9)),
      RichSegment(POLISH, hyphenate="pl", link_url="https://example.com")):
    assert not any(line.endswith("-") for line in broken([seg]))

@needs_fitz
def hyphenated_line_meets_the_edge(lines_of):
  pytest.importorskip("pyphen")
  lines = lines_of([RichSegment(POLISH, hyphenate="pl")], width=40)
  ends = [line[-1] for line in lines[:-1] if line[-1][4].endswith("-")]
  assert ends
  assert all(end[2] == pytest.approx(LEFT_PT + 40 * MM_TO_PT, abs=0.5) for end in ends)

def missing_pyphen_warns_and_keeps_words(broken, monkeypatch):
  monkeypatch.setitem(sys.modules, "pyphen", None) # `import pyphen` fails
  monkeypatch.setattr("pdfmarq.inline._hyphenators", {})
  with pytest.warns(RuntimeWarning, match="pyphen"):
    lines = broken([RichSegment(POLISH, hyphenate="pl")])
  assert not any(line.endswith("-") for line in lines)

def unknown_language_raises(broken, monkeypatch):
  pytest.importorskip("pyphen")
  monkeypatch.setattr("pdfmarq.inline._hyphenators", {})
  with pytest.raises(ValueError, match="xx"):
    broken([RichSegment(POLISH, hyphenate="xx")])

#----------------------------------------------------------------------------------- Letter-spacing

def letter_spacing_widens_the_text():
  pdf = PDF(io.BytesIO())
  plain = measure_extent(pdf, [RichSegment("CAPS")])[1]
  spaced = measure_extent(pdf, [RichSegment("CAPS", char_space=2)])[1]
  assert spaced - plain == pytest.approx(4 * 2 / MM_TO_PT)

@needs_fitz
def letter_spacing_is_drawn(tmp_path):
  def span(segment:RichSegment) -> float:
    """Distance (pt) from the first glyph to the last; spaced letters read as words apart."""
    path = str(tmp_path / "spaced.pdf")
    pdf = PDF(path)
    render_rich(pdf, [segment], WIDTH_MM, 0, 0, Align.LEFT, 1.4)
    pdf.save()
    chars = pdf_chars(path)
    return chars[-1][1] - chars[0][1]
  grown = span(RichSegment("CAPS", char_space=2)) - span(RichSegment("CAPS"))
  assert grown == pytest.approx(3 * 2, abs=0.1)

def no_break_space_binds_its_words(tmp_path):
  # `w\u00a0domu` keeps a one-letter word off the end of a line, as Polish typesetting asks
  pdf = PDF(str(tmp_path / "n.pdf"))
  bound = measure_extent(pdf, [RichSegment("a w\u00a0domu")])[0]
  free = measure_extent(pdf, [RichSegment("a w domu")])[0]
  assert bound > free
