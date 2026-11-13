# tests/test_justify.py

"""
Justified text: lines fill the width, the last line and hard breaks stay left,
words split at the hyphenation points of the text's language
and one-letter words keep to the word after them.
"""

import io, re, sys
import pytest
from pdfmarq import PDF, Align, MM_TO_PT, RichSegment, RichText, render_rich
from pdfmarq.inline import (_Word, _justify_ratio, _spaced_width, _stretches, _JUSTIFY_SHRINK,
  _tokenize, _wrap, measure_extent, wrap_line_heights)
from pdfmarq.md import MarkdownStyle
from conftest import needs_pymupdf, pdf_words, pdf_links, pdf_chars, pdf_text, render_md, tight_mm

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
    render_rich(pdf, RichText(segments, width, align, 1.4), 0, 0)
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
def line_ends(tmp_path):
  """`line_ends(write, name)`: the last word of each line `write(path)` draws, top to bottom."""
  def ends(write, name:str) -> list[str]:
    path = str(tmp_path / name)
    write(path)
    rows: dict[int, list] = {}
    for w in pdf_words(path):
      rows.setdefault(round(w[3]), []).append(w)
    return [max(row, key=lambda w: w[0])[4] for _, row in sorted(rows.items())]
  return ends

@pytest.fixture
def tight():
  """Width (mm) `PHRASE` at the `RichSegment` defaults fills only with its spaces tightened."""
  seg = RichSegment(PHRASE)
  return tight_mm(PHRASE, seg.family, seg.size)

#-------------------------------------------------------------------------------------------- Lines

@needs_pymupdf
def lines_meet_the_right_edge(lines_of):
  lines = lines_of([RichSegment(TEXT)])
  right = LEFT_PT + WIDTH_MM * MM_TO_PT
  assert len(lines) > 2
  for line in lines[:-1]:
    assert line[0][0] == pytest.approx(LEFT_PT, abs=0.5)
    assert line[-1][2] == pytest.approx(right, abs=0.5)
  assert lines[-1][-1][2] < right - 5

@needs_pymupdf
def hard_break_keeps_its_line_left(lines_of):
  lines = lines_of([RichSegment("Short line"), RichSegment("\n"), RichSegment(TEXT)])
  right = LEFT_PT + WIDTH_MM * MM_TO_PT
  assert lines[0][-1][2] < right - 50
  assert lines[1][-1][2] == pytest.approx(right, abs=0.5)

@needs_pymupdf
def left_alignment_stays_ragged(lines_of):
  lines = lines_of([RichSegment(TEXT)], align=Align.LEFT)
  right = LEFT_PT + WIDTH_MM * MM_TO_PT
  assert all(line[-1][2] < right + 0.5 for line in lines)
  assert any(line[-1][2] < right - 2 for line in lines[:-1])

@needs_pymupdf
def link_covers_the_stretched_spaces(tmp_path):
  path = str(tmp_path / "link.pdf")
  pdf = PDF(path)
  segs = [RichSegment("Some words lead in, then "),
    RichSegment("a link with spaces", link_url="https://example.com", underline=True),
    RichSegment(" " + TEXT)]
  render_rich(pdf, RichText(segs, WIDTH_MM, Align.JUSTIFY, 1.4), 0, 0)
  pdf.save()
  rect = pdf_links(path)[0]["from"]
  spaces = next(w for w in pdf_words(path) if w[4] == "spaces")
  assert rect.x1 == pytest.approx(spaces[2], abs=0.5)

#--------------------------------------------------------------------------------------- Tightening

def justified_line_tightens_to_take_a_word(tight):
  pdf = PDF(io.BytesIO())
  segs = [RichSegment(PHRASE)]
  assert len(wrap_line_heights(pdf, RichText(segs, tight, Align.JUSTIFY))) == 1
  assert len(wrap_line_heights(pdf, RichText(segs, tight, Align.LEFT))) == 2

@needs_pymupdf
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

@pytest.mark.filterwarnings("ignore::pdfmarq.GlyphWarning") # Helvetica metrics, its boxes aside
def words_split_at_hyphenation_points(broken):
  pytest.importorskip("pyphen")
  lines = broken([RichSegment(POLISH, hyphenate="pl")])
  assert any(line.endswith("-") for line in lines)
  joined = "".join(line[:-1] if line.endswith("-") else line + " " for line in lines)
  assert joined.strip() == POLISH

def a_word_styled_apart_from_its_stop_splits_as_in_one_style(broken):
  # `*Zleceniodawcy*,` as markdown sets it: the comma after the word stands in a segment of its own
  pytest.importorskip("pyphen")
  styled = ("Zleceniodawcy", "testów")
  apart = [RichSegment(part, italic=part in styled, hyphenate="pl")
    for part in re.split(f"({'|'.join(styled)})", POLISH)]
  for width in range(25, 61):
    assert broken(apart, width) == broken([RichSegment(POLISH, hyphenate="pl")], width), width

def words_stay_whole_without_a_language(broken):
  assert not any(line.endswith("-") for line in broken([RichSegment(POLISH)]))

def a_long_word_no_head_of_which_fits_splits_on_the_next_line(broken):
  # a one-letter word bound to it goes along, and no piece is cut without a hyphen
  pytest.importorskip("pyphen")
  word = "konstantynopolitanczykowianeczka"
  for text in (f"A second paragraph: {word}", f"A second paragraph: a {word}"):
    first, *heads, tail = broken([RichSegment(text, hyphenate="pl", bind_single_letters="a")], 37)
    assert first == "A second paragraph:"
    assert heads and all(head.endswith("-") for head in heads)
    assert f"{first} {''.join(head[:-1] for head in heads)}{tail}" == text

def code_and_links_never_split(broken):
  pytest.importorskip("pyphen")
  for seg in (RichSegment(POLISH, hyphenate="pl", bg_color=(0.9, 0.9, 0.9)),
      RichSegment(POLISH, hyphenate="pl", link_url="https://example.com")):
    assert not any(line.endswith("-") for line in broken([seg]))

@needs_pymupdf
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

@needs_pymupdf
def letter_spacing_is_drawn(tmp_path):
  def span(segment:RichSegment) -> float:
    """Distance (pt) from the first glyph to the last: spaced letters read as words apart."""
    path = str(tmp_path / "spaced.pdf")
    pdf = PDF(path)
    render_rich(pdf, RichText([segment], WIDTH_MM, Align.LEFT, 1.4), 0, 0)
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

#----------------------------------------------------------------------------------- Single letters

ARTICLES = ("We bought a car and a boat, so I said a word to a friend of a friend "
  "who had a plan for a trip to a lake where I saw a bird. ") * 3

def single_letters_keep_to_the_next_word(broken):
  # at some widths a line ends with `a`, and bound to the word after it none does
  def ends_on_a(segment:RichSegment) -> bool:
    lines = [line for width in range(30, 90, 4) for line in broken([segment], width)[:-1]]
    return any(line.split()[-1] == "a" for line in lines if line.strip())
  assert ends_on_a(RichSegment(ARTICLES))
  assert not ends_on_a(RichSegment(ARTICLES, bind_single_letters="a"))

def binds_keeps_a_letter_of_the_language_and_a_number_to_its_unit():
  from pdfmarq.inline import binds
  pl, cs = "aiouwz", "aikosuvz"
  assert binds("supply", "5", "V", pl) and binds("supply", "5", "V.", pl) # a number to its unit
  assert not binds("5", "V", "z", pl) and not binds("50", "W", "at", pl) # the unit to nothing
  assert binds("V", "z", "port", pl) and binds("3", "z", "10", pl) # a letter of the language
  assert not binds("Table", "I", "shows", pl) and not binds("value", "x", "is", pl)
  assert binds("ends.", "W", "home", pl) and binds(None, "W", "home", pl) # a sentence opens
  assert binds("LaTeX:", "A", "Document", pl) # so does a clause after a colon
  assert binds("PLAN", "O", "HOUSE", pl) and not binds("Tabela", "I", "shows", pl) # caps
  assert not binds("5", "s", "then", cs) and binds("x", "s", "them", cs) # a unit, then a word
  assert binds("in", "(w", "case", pl) and binds("x", "„w", "time”", pl) # after an opener
  assert binds("x", "(W", "home", pl) and not binds("point", "a)", "and", pl)
  assert not binds("supply", "5", "V", "") # nothing binds without letters

@needs_pymupdf
def a_unit_keeps_one_plain_space_from_its_number(lines_of):
  # justifying stretches the other spaces of a line, never the one before a unit
  text = "The loss falls by 15 % at 5 V while the board draws 50 mA from a small cell. " * 3
  lines = lines_of([RichSegment(text, bind_single_letters="aiouwz")], width=35)
  pairs = [(a, b) for line in lines[:-1] for a, b in zip(line, line[1:])]
  units = [b[0] - a[2] for a, b in pairs if a[4] in ("15", "5", "50")]
  others = [b[0] - a[2] for a, b in pairs if a[4] not in ("15", "5", "50")]
  assert units and max(units) - min(units) < 0.1 and max(others) > max(units) + 1

def a_number_never_ends_a_line_before_its_unit(broken):
  # nor does the unit pull the word after it along, which would part it from its number
  text = "The board takes 5 V z port and 50 W at most, then 10 mA z cable. " * 3
  segment = RichSegment(text, bind_single_letters="aiouwz")
  for width in range(25, 70, 3):
    rows = [line.split() for line in broken([segment], width)]
    assert not any(row[-1] in ("5", "50", "10", "z") for row in rows[:-1]), width

@pytest.mark.filterwarnings("ignore::pdfmarq.GlyphWarning") # Helvetica metrics, its boxes aside
def binding_changes_only_lines_a_letter_would_end(broken):
  # elsewhere the lines stay as they were, a hyphenated word after the letter included
  pytest.importorskip("pyphen")
  for width in range(30, 90, 2):
    free = broken([RichSegment(POLISH, hyphenate="pl")], width)
    if any(len(line.split()[-1]) == 1 for line in free[:-1]): continue
    bound = broken([RichSegment(POLISH, hyphenate="pl", bind_single_letters="aiouwz")], width)
    assert bound == free, width

@needs_pymupdf
def markdown_binds_single_letters(tmp_path, line_ends):
  # paragraphs follow the style, and copy out with their plain spaces
  def ends(bind:bool) -> list[str]:
    def write(path:str):
      render_md(path, ARTICLES, MarkdownStyle(bind_single_letters="a" if bind else ""))
    return line_ends(write, f"bind{bind}.pdf")[:-1]
  assert "a" in ends(False)
  assert "a" not in ends(True)
  copied = pdf_text(str(tmp_path / "bindTrue.pdf"))
  assert "a car" in copied and "\u00a0" not in copied

@needs_pymupdf
@pytest.mark.parametrize("part", ["title", "heading", "cell"])
def a_heading_a_table_cell_and_the_banner_title_bind_single_letters(line_ends, part):
  from pdfmarq.paper import md_to_pdf, PaperStyle
  text = ARTICLES[:200].strip()
  md = {
    "title": f"---\ntitle: {text}\n---\n\nBody.\n",
    "heading": f"## {text}\n",
    "cell": f"| Cell |\n|---|\n| {text} |\n",
  }[part]
  def ends(bind:bool) -> list[str]:
    def write(path:str):
      md_to_pdf(md, path, style=PaperStyle(bind_single_letters="a" if bind else "",
        page_number_label=None))
    return line_ends(write, f"{part}{bind}.pdf")
  assert "a" in ends(False)
  assert "a" not in ends(True)

@needs_pymupdf
def the_title_of_a_letter_binds_single_letters(line_ends):
  from pdfmarq.legal import md_to_pdf, LegalStyle
  md = f"---\ntitle: {ARTICLES[:200].strip()}\n---\n\nBody.\n"
  def ends(bind:bool) -> list[str]:
    def write(path:str):
      md_to_pdf(md, path, style=LegalStyle(bind_single_letters="a" if bind else "",
        page_number_label=None))
    return line_ends(write, f"letter{bind}.pdf")
  assert "a" in ends(False)
  assert "a" not in ends(True)

def the_polish_czech_and_slovak_presets_bind_single_letters(tmp_path):
  from pdfmarq.md import lang_style
  letters = {lang: lang_style(lang).bind_single_letters for lang in ("pl", "cs", "sk", "en", "de")}
  assert letters == {"pl": "aiouwz", "cs": "aikosuvz", "sk": "aikosuvz", "en": "", "de": ""}
  with pytest.raises(TypeError, match="aiouwz"): # the letters, not a switch
    render_md(str(tmp_path / "t.pdf"), "Text.", MarkdownStyle(bind_single_letters=True))
