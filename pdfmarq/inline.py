# pdfmarq/inline.py

"""
Rich text: spans of mixed styles wrapped into lines, measured and drawn alike.

`RichSegment` is one styled span: bold, italic, code, a link, a formula.
`RichText` is a run of them set at a width, with its alignment, leading and first-line indent.
`render_rich`, `measure_rich`, `wrap_line_heights`, `flow_rich`, `split_rich` and `drop_cap`
all take a `RichText`, so they break it at the same words.
The markdown engine draws through them, and `PDF.text()` is a simpler single-style variant.
"""
import itertools, re, warnings
from collections import deque
from dataclasses import dataclass, field, replace
from typing import Callable
from reportlab.lib.colors import Color
from reportlab.graphics import renderPDF
from .constants import Align, MM_TO_PT
from .utils import to_mm
from .fonts import fit_glyphs
from .text import FIT_EPS_PT, split_word, centred_baseline

#------------------------------------------------------------------------------------ Layout ratios

# Vertical metrics relative to glyph size (`rseg.size`). Tuned to GitHub-light look.
# Centralised here so future visual tweaks don't require code-hunting.
_BG_DESCENT_RATIO = 0.32    # how far below baseline the inline-code bg starts
_BG_HEIGHT_RATIO = 1.35     # inline-code bg height in glyph units
_BG_CORNER_RATIO = 0.20     # rounded-corner radius / bg height
_STRIKE_Y_RATIO = 0.28      # strikethrough Y above baseline
_LINK_RECT_DESCENT = 0.25   # link clickable rect: depth below baseline
_LINK_RECT_ASCENT = 0.85    # link clickable rect: height above baseline
_UNDERLINE_OFFSET_PT = 1.0  # underline distance below baseline (pt, size-independent)

# Inline-code shaded background padding (pt - not font-size relative).
_BG_INNER_PAD_PT = 2.5  # bg rect extends this far past glyphs
_BG_OUTER_GAP_PT = 1.2  # extra gap between bg rect and adjacent text
# Total horizontal overhead a single inline-code run draws on top of its glyph width:
# outer gap + inner pad on each side.
# Used by `measure_extent` so table column-width estimation reserves room for the shaded rect.
_BG_RUN_EXTRA_PT = 2 * (_BG_OUTER_GAP_PT + _BG_INNER_PAD_PT)

# Math drawings: tiny breathing room around an inline formula (pt).
_MATH_INLINE_PAD_PT = 1.0

# A justified line takes one more word when its spaces can tighten to this share of their width,
# as page layout programs do with limits between 2/3 and 80%.
# A gap this wide still reads as a space when text is copied out.
# Wrapping, measuring and drawing all use it.
_JUSTIFY_SHRINK = 0.75

# A word splits at a line end only from this many letters, so a short one never does.
_HYPHEN_MIN = 5
# The letters a hyphenation point may split;
# punctuation around them stays whole.
_SPLITTABLE = re.compile(r"(\W*)([^\W\d_]+)(\W*)")

# Superscript / subscript scaling. Industry-standard: glyph at ~70% size,
# baseline raised (sup) or lowered (sub) by a fraction of full size.
_SCRIPT_SIZE_RATIO = 0.70
_SUP_BASELINE_RATIO = 0.40  # raise baseline by this fraction of full size
_SUB_BASELINE_RATIO = 0.15  # lower baseline by this fraction of full size

#-------------------------------------------------------------------------------------- RichSegment

@dataclass
class RichSegment:
  """
  Single span of styled text, inline code, or inline math drawing.

  Multiple segments render on one line with shared baseline.
  Background color draws a filled rect behind the span (used for inline code).

  Two ways to set face weight/slant:
    - `mode`: explicit reportlab font mode (`"Regular"`/`"Bold"`/`"Italic"`/`"BoldItalic"`).
      Direct mapping to TTF lookup.
    - `bold` / `italic`: boolean flags.
      When set, `__post_init__` derives `mode` from them.

  Math mode: if `math_drawing` is set, `text` is ignored
  and the segment is a pre-rendered vector formula (from matplotlib → svglib).
  `math_width_pt` is the full glyph width.
  `math_baseline_from_bottom_pt` is how far the text baseline sits above the drawing's bottom edge,
  for vertical alignment with surrounding text.
  """
  text: str
  family: str = "Helvetica"
  mode: str = "Regular"
  size: float = 11
  color: tuple = (0, 0, 0)
  bg_color: tuple|None = None
  link_url: str|None = None
  link_target: str|None = None # internal bookmark name
  bold: bool = False
  italic: bool = False
  underline: bool = False
  strike: bool = False
  char_space: float = 0 # pt after every character: letter-spacing, as capitals want
  hyphenate: str|None = None # language whose patterns may split a word at a line end
  bind_single_letters: str = "" # one-letter words that keep to the next, as `aiouwz`: `binds`
  code: bool = False # inline code: its spaces keep their width and its words stay whole
  # Soft line break BEFORE this segment.
  # Flag-based rather than a break;
  # an alternative to embedding `\n` in `text`.
  break_line: bool = False
  # Vertical script. Render at smaller size with baseline offset.
  # Useful for footnote refs (sup) and chemical formulae (sub).
  superscript: bool = False
  subscript: bool = False
  math_drawing: object|None = None # reportlab Drawing or None
  math_width_pt: float = 0 # total width of the math glyphs
  math_baseline_from_bottom_pt: float = 0 # baseline offset from drawing bottom

  def __post_init__(self):
    # `bold`/`italic` flags win over `mode` when explicitly set.
    # Lets users write `RichSegment(text="x", bold=True)` without the reportlab mode string.
    if self.bold and self.italic:
      self.mode = "BoldItalic"
    elif self.bold:
      self.mode = "Bold"
    elif self.italic:
      self.mode = "Italic"

#----------------------------------------------------------------------------------------- RichText

@dataclass(frozen=True)
class RichText:
  """
  Segments set at a width: everything that decides where their lines break and how tall they are.
  Measuring, drawing, flowing and splitting take the same one, so they break at the same words.

  Example:
    >>> text = RichText(segs, 80, Align.JUSTIFY, 1.2, indent_mm=3.6)
    >>> height = measure_rich(pdf, text)
    >>> render_rich(pdf, text, 0, pdf.y)
  """
  segments: list[RichSegment]
  width_mm: float
  align: str = Align.LEFT # L, C, R or J, whose lines resize their spaces to fill the width
  line_gap: float = 1.45 # a line's height, of its largest size
  indent_mm: float = 0 # how far in the first line starts, as a paragraph of a book
  preserve_leading_space: bool = False # spaces opening a line kept, as code keeps its indent

#-------------------------------------------------------------------------------------- _Word token
@dataclass
class _Word:
  """Word-level token for wrapping. `is_space` means whitespace token."""
  text: str
  seg: RichSegment
  width_pt: float
  is_space: bool
  is_break: bool = False # hard line break
  origin: "_Word|None" = None # the token a hyphenated or oversized piece was cut from
  start: int = 0 # where in the text of `origin` the piece begins
  rigid: bool = False # a space justifying leaves alone, as the one between a number and its unit

#----------------------------------------------------------------------------------------- Tokenize

def _effective_size(seg:RichSegment) -> float:
  """Glyph size after super/subscript scaling."""
  if seg.superscript or seg.subscript: return seg.size * _SCRIPT_SIZE_RATIO
  return seg.size

def _tokenize(segments:list[RichSegment], metrics) -> list[_Word]:
  """
  Split segments into word tokens preserving per-segment style.
  Codepoints missing from the seg's font get remapped before width measurement,
  to visually-equivalent ones the font has (Ω→Ohm, μ→micro, etc.).
  """
  words = []
  for seg in segments:
    # `break_line` flag emits a hard break before the segment's content.
    if seg.break_line:
      words.append(_Word("", seg, 0, is_space=False, is_break=True))
    # Math segment - single atomic word (no splitting on spaces)
    if seg.math_drawing is not None:
      words.append(_Word("", seg, seg.math_width_pt, is_space=False))
      continue
    if seg.text == "\n":
      words.append(_Word("", seg, 0, is_space=False, is_break=True))
      continue
    eff_size = _effective_size(seg)
    font_name = metrics.font_name(seg.family, seg.mode)
    # a no-break space binds the words around it, as `w\u00a0domu` in Polish text
    for part in re.findall(r"(?:\S|\u00a0)+|[^\S\u00a0]+", seg.text):
      part = fit_glyphs(part, font_name)
      w = _text_pt(part, seg, eff_size, metrics)
      words.append(_Word(part, seg, w, is_space=part.isspace() and "\u00a0" not in part))
  return words

def _indented(words:list[_Word], segments:list[RichSegment], indent_mm:float) -> list[_Word]:
  """
  `words` behind an empty token `indent_mm` wide, which sets the first line in that far.
  It wears the face of the first segment with nothing drawn around it,
  so no shading, underline or link of the first word reaches into the indent.
  """
  if not indent_mm or not segments: return words
  face = replace(segments[0], text="", bg_color=None, link_url=None, link_target=None,
    underline=False, strike=False, break_line=False, math_drawing=None)
  return [_Word("", face, indent_mm * MM_TO_PT, is_space=False)] + words

def _text_pt(text:str, seg:RichSegment, size:float, metrics) -> float:
  """Advance of `text` set in `seg` at `size`, its letter-spacing included."""
  return metrics.text_width(text, seg.family, seg.mode, size) + seg.char_space * len(text)

#--------------------------------------------------------------------------------------------- Wrap
@dataclass
class _WrapResult:
  """
  Output of `_wrap`. `overflow=True` means a chunk still didn't fit
  after the force-break pass (wrap width too narrow for even one glyph).
  `hard` holds the indices of lines a hard break ended, which justifying leaves alone.
  """
  lines: list[list["_Word"]]
  overflow: bool = False
  hard: set[int] = field(default_factory=set)

def _break_oversized(word:_Word, width_pt:float, metrics) -> list[_Word]:
  """
  Cut a token wider than `width_pt` into chunks that each fit, by `split_word`.
  Chunks share the original segment, so link rect, bg, color and font carry across the break.
  """
  seg = word.seg
  eff_size = _effective_size(seg)
  def measure(text:str) -> float:
    return _text_pt(text, seg, eff_size, metrics)
  origin = word.origin or word
  pieces = split_word(word.text, width_pt, measure)
  starts = itertools.accumulate((len(piece) for piece in pieces), initial=word.start)
  return [
    _Word(piece, seg, measure(piece), is_space=False, origin=origin, start=start)
    for piece, start in zip(pieces, starts)
  ]

_hyphenators: dict[str, object] = {}

def hyphenator(lang:str):
  """
  `pyphen` patterns of `lang`, or `None` without `pyphen`, which warns once per language.
  A language with no patterns raises: the style named it, so that is a mistake.
  """
  if lang in _hyphenators: return _hyphenators[lang]
  try:
    import pyphen
  except ModuleNotFoundError:
    warnings.warn("hyphenation needs pyphen (pip install pyphen), words stay whole",
      RuntimeWarning, stacklevel=2)
    _hyphenators[lang] = None
    return None
  if not pyphen.language_fallback(lang): raise ValueError(f"no hyphenation patterns for {lang!r}")
  _hyphenators[lang] = pyphen.Pyphen(lang=lang)
  return _hyphenators[lang]

def _hyphen_split(
  word:_Word, fits:Callable[[float], bool], metrics,
) -> tuple[_Word, _Word]|None:
  """
  `word` cut at its last hyphenation point whose head, hyphen included, still `fits` the line.

  Only plain text whose segment sets `hyphenate` splits: never code, a link or a number.
  A word under `_HYPHEN_MIN` letters or in capitals stays whole, and so does one no cut fits.
  """
  seg = word.seg
  if not seg.hyphenate or seg.code or seg.bg_color is not None or seg.link_url or seg.link_target:
    return None
  match = _SPLITTABLE.fullmatch(word.text)
  if not match or len(match[2]) < _HYPHEN_MIN or match[2].isupper(): return None
  patterns = hyphenator(seg.hyphenate)
  if patterns is None: return None
  lead, letters, trail = match.groups()
  size = _effective_size(seg)
  for cut in reversed(patterns.positions(letters)):
    head = f"{lead}{letters[:cut]}-"
    width = _text_pt(head, seg, size, metrics)
    if fits(width):
      tail = letters[cut:] + trail
      origin = word.origin or word
      rest = _Word(tail, seg, _text_pt(tail, seg, size, metrics), False, origin=origin,
        start=word.start + len(lead) + cut)
      return _Word(head, seg, width, False, origin=origin, start=word.start), rest
  return None

def _hyphen_split_unit(
  unit:list[_Word], fits:Callable[[float], bool], prev:_Word|None, metrics,
) -> tuple[list[_Word], list[_Word]]|None:
  """
  `unit` cut at a hyphenation point of its last word, as `_hyphen_split` cuts it:
  the tokens up to the cut, which still `fit` the line after `prev`, and the tokens after it.
  So a one-letter word bound to the word after it stays on its line with the head of that word.
  A word spanning segments, as `*word*,` sets the comma apart, splits in its last piece that can,
  the pieces after it going on with the rest.
  """
  start = len(unit)
  while start and not unit[start - 1].is_space: start -= 1 # where the last word begins
  for k in range(len(unit) - 1, start - 1, -1):
    lead = unit[:k]
    lead_pt = _extent_pt(lead, prev)
    split = _hyphen_split(unit[k], lambda width: fits(lead_pt + width), metrics)
    if split is None: continue
    head, rest = split
    return [*lead, head], [rest, *unit[k + 1:]]
  return None

def _run_pad_pt(seg:RichSegment) -> float:
  """
  Room a visual run takes beyond its glyphs:
  the inline-code rect with its gaps, or the breathing room around a formula.
  `render_rich` adds it once per run on each line, and wrapping counts it the same way.
  """
  if seg.math_drawing is not None: return 2 * _MATH_INLINE_PAD_PT
  if seg.bg_color is not None: return _BG_RUN_EXTRA_PT
  return 0.0

def _advance_pt(prev:_Word|None, word:_Word) -> float:
  """
  Width `word` adds to a line right after `prev`, which is `None` at line start.
  Its glyphs, plus the run padding when it opens a new visual run.
  """
  # most neighbours come from one segment, and an identity check spares building two keys
  if prev is not None and (prev.seg is word.seg or _run_key(prev.seg) == _run_key(word.seg)):
    return word.width_pt
  return word.width_pt + _run_pad_pt(word.seg)

def _extent_pt(tokens:list[_Word], prev:_Word|None=None) -> float:
  """Width `tokens` add to a line after `prev`, run padding included."""
  total = 0.0
  for token in tokens:
    total += _advance_pt(prev, token)
    prev = token
  return total

def _units(words:list[_Word]) -> list[list[_Word]]:
  """
  Group tokens into wrap units: a hard break, a whitespace run, or a word.

  A word runs to the next whitespace, so it can span segments: `**PP**-1`, `[link](url).`.
  A line never breaks inside a word that fits a line of its own.
  A space `binds` ties takes the word after it into the unit of the word before it:
  a one-letter word of its language keeps to the next word, and a number to its unit.
  """
  bound = _bound_spaces(words)
  units: list[list[_Word]] = []
  for w in words:
    last = units[-1][-1] if units else None
    # a bound space, waiting for the word it joins to the one before it
    waiting = len(units) > 1 and units[-1][0].is_space and id(units[-1][0]) in bound
    joins = last and not (w.is_break or last.is_break) and w.is_space == last.is_space
    if joins and not _is_indent(last): # a word stands apart from the indent, to be hyphenated
      units[-1].append(w)
    elif waiting and not w.is_break:
      space = units.pop()
      units[-1] += space + [w]
    else:
      units.append([w])
  return units

#------------------------------------------------------------------------------------------ Binding

# a number as text writes it: `5`, `3,5`, `1.5`
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
# a word after which a sentence or a clause starts: a full stop or a colon, maybe in quotes
_SENTENCE_END = re.compile(r"""[.!?…:][]"”’')»]*$""")
# the units a number keeps to: a letter after a number is one of them, never a word
_UNITS = frozenset((
  "s", "ms", "µs", "us", "ns", "min", "h",
  "V", "mV", "kV", "A", "mA", "µA", "W", "mW", "kW", "Wh", "kWh",
  "Ω", "kΩ", "MΩ", "F", "µF", "nF", "pF", "H", "mH", "µH",
  "Hz", "kHz", "MHz", "GHz", "dB", "B", "kB", "MB", "GB", "TB", "bit",
  "m", "mm", "cm", "km", "µm", "nm", "g", "kg", "mg", "t", "l", "ml",
  "N", "J", "Pa", "kPa", "bar", "K", "°C", "%", "pt", "px", "rpm",
))
# brackets and quotes a word may open with, as `(w` or `„w`
_OPENERS = "([„«'" + '"'
# a formula, a picture or code within a word, which is neither a letter nor a number
_OBJECT = chr(0xFFFC)

def binds(before:str|None, word:str, after:str, letters:str) -> bool:
  """
  Whether no line may end between `word` and the word `after` it.
  `before` is the word before `word`, `None` where a paragraph or a line starts.
  A one-letter word of `letters` keeps to the next one, as `aiouwz` in Polish,
  and so does one opening a bracket or a quote, as `(w`.
  A unit after a number never does, as `V` in `5 V` or Czech `s` in `5 s`.
  A capital binds where a sentence or a clause opens, after a stop, a colon or a bracket,
  or among capitals, as in a title.
  Where `letters` binds anything, a number keeps to its unit as well.
  """
  if not letters: return False
  if _NUMBER.fullmatch(word): return after.rstrip(".,;:!?)") in _UNITS
  letter = word.lstrip(_OPENERS)
  if len(letter) != 1 or letter.lower() not in letters: return False
  if before is not None and _NUMBER.fullmatch(before) and word in _UNITS: return False
  if letter.islower() or letter != word or before is None: return True
  return bool(_SENTENCE_END.search(before)) or (before + after).isupper()

def _bound_spaces(words:list[_Word]) -> set[int]:
  """
  `id` of each space no line may end at, as `binds` decides from the words around it.
  A word runs across segments to the next space, so a bold one-letter word binds as well,
  and the segment of its last piece names the letters that bind.
  The space between a number and its unit is marked `rigid` on the way.
  """
  found = [] # a word, the segment of its last piece, the space after it, whether it opens a line
  pieces, seg, opens = [], None, True
  for token in words:
    if token.is_space or token.is_break:
      if pieces:
        found.append(("".join(pieces), seg, token if token.is_space else None, opens))
        pieces, opens = [], False
      if token.is_break: opens = True
      continue
    if _is_indent(token): continue
    plain = token.seg.math_drawing is None and not token.seg.code
    pieces.append(token.text if plain else _OBJECT)
    seg = token.seg
  if pieces: found.append(("".join(pieces), seg, None, opens))
  bound = set()
  for k, (word, seg, space, opens) in enumerate(found[:-1]):
    if space is None or found[k + 1][3]: continue
    before = None if opens else found[k - 1][0]
    if not binds(before, word, found[k + 1][0], seg.bind_single_letters): continue
    bound.add(id(space))
    space.rigid = bool(_NUMBER.fullmatch(word)) # a unit stays one space from its number
  return bound

def _is_indent(word:_Word) -> bool:
  """Whether `word` is the empty token of a paragraph's first-line indent."""
  return not (word.text or word.is_space or word.is_break) and word.seg.math_drawing is None

def _blank(word:_Word) -> bool:
  """Whether `word` draws nothing: whitespace, or the indent."""
  return word.is_space or _is_indent(word)

def _wrap(
  words:list[_Word], width_pt:float, metrics,
  preserve_leading_space:bool = False,
  shrink:float = 1.0,
) -> _WrapResult:
  """
  Greedy word-wrap honoring hard breaks.

  Lines break at whitespace, never inside a unit from `_units`,
  unless the segment of its last word sets `hyphenate` and the head of a split fits:
  see `_hyphen_split_unit`.
  A word that does not fit the rest of a line opens the next one if it fits there or splits there.
  Otherwise it breaks between its segments from where the line stands, as long code does,
  and a token still too wide goes to `_break_oversized`, so long links never spill past the edge.
  After an indent alone the word breaks between its segments too, so code keeps its indent,
  and a first piece too wide for the rest of the line starts it at the margin:
  an indent never stands alone, of code or of a paragraph's first line.
  Widths include the run padding `render_rich` draws, via `_advance_pt`.

  Args:
    preserve_leading_space: Keep leading whitespace, for code where indent means something.
      Prose drops it.
    shrink: Share of their width the spaces between words may tighten to, so a word fits.
      `1` keeps them whole;
      justified text passes `_JUSTIFY_SHRINK`.
  """
  limit = width_pt + FIT_EPS_PT
  lines: list[list[_Word]] = []
  hard: set[int] = set()
  current: list[_Word] = []
  current_w = 0.0
  current_sp = 0.0 # width of the spaces on the line justifying may tighten
  overflow = False
  def indent_only() -> bool:
    return all(_blank(w) for w in current)
  def fits(width:float) -> bool:
    return current_w + width - (1 - shrink) * current_sp <= limit
  def reset():
    nonlocal current, current_w, current_sp
    current, current_w, current_sp = [], 0.0, 0.0
  def flush():
    while current and current[-1].is_space:
      current.pop()
    lines.append(current)
    reset()
  def wrap():
    if indent_only(): reset() # an indent alone is no line: the text moves to the margin
    else: flush()
  def append(tokens:list[_Word], width:float):
    nonlocal current_w, current_sp
    current.extend(tokens)
    current_w += width
    current_sp += sum(t.width_pt for t in tokens if _stretches(t))
  def place(token:_Word):
    nonlocal overflow
    alone = _advance_pt(None, token)
    if alone > limit:
      overflow = True # even one glyph wider than wrap width
    after = _advance_pt(current[-1], token) if current else alone
    if current and not fits(after):
      wrap()
      if token.is_space: return # the space of a bound pair opens no line
      after = alone
    append([token], after)
  units = deque(_units(words))
  while units:
    unit = units.popleft()
    head = unit[0]
    if head.is_break:
      flush()
      hard.add(len(lines) - 1)
      continue
    after = _extent_pt(unit, current[-1] if current else None)
    if head.is_space:
      if current or preserve_leading_space: # no leading space in prose
        append(unit, after)
      continue
    if fits(after):
      append(unit, after)
      continue
    prev = current[-1] if current else None
    split = _hyphen_split_unit(unit, fits, prev, metrics)
    if split:
      taken, rest = split
      append(taken, _extent_pt(taken, prev))
      flush()
      units.appendleft(rest) # the rest of the word opens the next line
      continue
    if current and not indent_only():
      fresh = lambda width: width <= limit # a line of its own
      if _extent_pt(unit) <= limit or _hyphen_split_unit(unit, fresh, None, metrics):
        flush()
        units.appendleft(unit) # the next line holds it whole, or splits it from its start
        continue
    for token in unit:
      if token.text and _advance_pt(None, token) > limit:
        room = width_pt - _run_pad_pt(token.seg)
        for chunk in _break_oversized(token, room, metrics):
          place(chunk)
      else:
        place(token)
  flush()
  return _WrapResult(lines, overflow, hard)

#---------------------------------------------------------------------------------- Metrics helpers

def _line_width_pt(line:list[_Word]) -> float:
  """Total horizontal extent of rendered line in pt, run padding included."""
  return _extent_pt(line)

def _run_key(seg:RichSegment) -> tuple:
  """
  Visual-run key: consecutive words with the same key share bg, underline and link.
  A math segment keys on itself, not its drawing, so it always forms its own run:
  two emoji side by side share one cached drawing, yet each must be drawn.
  Script flags count too: a run draws at one baseline, so `x^2^~n~` keeps sup apart from sub.
  """
  math_id = id(seg) if seg.math_drawing is not None else None
  return (
    seg.bg_color, seg.link_url, seg.link_target, seg.underline, seg.strike,
    seg.family, seg.mode, seg.size, seg.color, math_id,
    seg.superscript, seg.subscript,
  )

def _group_runs(line:list[_Word]) -> list[list[_Word]]:
  """Group consecutive words into runs sharing visual properties."""
  runs: list[list[_Word]] = []
  current: list[_Word] = []
  current_key = None
  for w in line:
    key = _run_key(w.seg)
    if key != current_key:
      if current: runs.append(current)
      current = [w]
      current_key = key
    else:
      current.append(w)
  if current: runs.append(current)
  return runs

#------------------------------------------------------------------------------------------ Measure

def measure_extent(pdf, segments:list[RichSegment]) -> tuple[float, float]:
  """
  Return `(min_word_width_mm, total_width_mm)` for word-wrap planning.

  - **min_word_width**: the widest word, which is the narrowest width that breaks none.
    A word may span segments, and a math or image segment is one atom.
  - **total_width**: how wide the content would be if it never wrapped.

  Feeds the table column-width solver, HTML-style auto-layout between `min` and `max`.
  Built on the same tokens, units and run padding as `_wrap`,
  so a column sized to `min_word_width` never breaks a word.
  """
  if not segments: return 0, 0
  widest = total = 0.0
  prev: _Word|None = None
  for unit in _units(_tokenize(segments, pdf.metrics)):
    if unit[0].is_break:
      prev = None
      continue
    if not unit[0].is_space:
      # Any word may end up alone on a wrapped line, opening its own runs.
      widest = max(widest, _extent_pt(unit))
    total += _extent_pt(unit, prev)
    prev = unit[-1]
  return widest / MM_TO_PT, total / MM_TO_PT

def _line_box(line:list[_Word], line_gap:float, metrics) -> tuple[float, float]:
  """
  `(ascent_pt, descent_pt)` of one wrapped line, measured from its baseline.

  The line is `line_gap` times its largest size tall, with its letters in the middle:
  from the top of the tallest capital to the bottom of the deepest descender,
  as `TextMetrics.letter_span` measures them for each face on the line.
  A drawing - a formula, an emoji - carries its own extent,
  and a big operator with limits stands several times taller than the size it was rendered at.

  A drawing that fits inside the text box leaves the box alone,
  so the leading absorbs it and nothing around it shifts.
  One that does not fit pushes the box out: it would otherwise reach into the neighbouring line
  or, inside a table cell, across the row border.
  """
  height = max(w.seg.size for w in line) * line_gap
  faces = {(w.seg.family, w.seg.mode, w.seg.size) for w in line}
  tops, bottoms = zip(*(metrics.letter_span(*face) for face in faces))
  ascent = centred_baseline(height, max(tops), max(bottoms))
  descent = height - ascent
  above = below = 0.0
  for w in line:
    drawing = w.seg.math_drawing
    if drawing is None: continue
    seg_below = w.seg.math_baseline_from_bottom_pt
    below = max(below, seg_below)
    above = max(above, float(getattr(drawing, "height", 0) or 0) - seg_below)
  if above + below <= ascent + descent: return ascent, descent
  return max(ascent, above), max(descent, below)

def _empty_line_mm(segments:list[RichSegment], line_gap:float) -> float:
  """
  Height (mm) of a line with no words, as two hard breaks in a row leave.
  It takes the size of the first segment, the face the block opens in.
  """
  return segments[0].size * line_gap / MM_TO_PT

def _wrap_text(pdf, text:RichText) -> tuple[list[_Word], _WrapResult]:
  """Tokens of `text` and its wrapped lines: measuring, drawing and splitting all wrap here."""
  words = _indented(_tokenize(text.segments, pdf.metrics), text.segments, text.indent_mm)
  return words, _wrap(words, text.width_mm * MM_TO_PT, pdf.metrics,
    preserve_leading_space=text.preserve_leading_space, shrink=_shrink(text.align))

def wrap_line_heights(pdf, text:RichText) -> list[float]:
  """
  Height (mm) of each line of `text` as `render_rich` sets it.
  A long block is cut by these: as many lines as fit the room left,
  drawn by `render_rich` with `first_line` and `max_lines`.
  """
  if not text.segments: return []
  _, wrapped = _wrap_text(pdf, text)
  heights: list[float] = []
  for line in wrapped.lines:
    if not line:
      heights.append(_empty_line_mm(text.segments, text.line_gap))
      continue
    ascent, descent = _line_box(line, text.line_gap, pdf.metrics)
    heights.append((ascent + descent) / MM_TO_PT)
  return heights

def measure_rich(pdf, text:RichText) -> float:
  """Height (mm) `render_rich` takes for the whole of `text`, nothing drawn: a box sized first."""
  return sum(wrap_line_heights(pdf, text))

#------------------------------------------------------------------------------------------ Justify

def _shrink(align:str) -> float:
  """Share of their width spaces may tighten to when wrapping text drawn with `align`."""
  return _JUSTIFY_SHRINK if align == Align.JUSTIFY else 1.0

def _stretches(word:_Word) -> bool:
  """A space justifying may resize: never a `rigid` one, nor one inside inline code."""
  if not word.is_space or word.rigid: return False
  return not word.seg.code and word.seg.bg_color is None

def _spaced_width(word:_Word, ratio:float) -> float:
  """Advance of `word` on a line whose stretchable spaces each change by `ratio` of their width."""
  return word.width_pt * (1 + ratio) if _stretches(word) else word.width_pt

def _justify_ratio(line:list[_Word], extra_pt:float) -> float:
  """
  Share of its width each stretchable space gains, so `line` spends `extra_pt` and fills it.
  Spaces change in proportion to their width, as `_wrap` counted them when tightening.
  Negative when the line took its last word by tightening, `0` when no space can change.
  """
  room = sum(w.width_pt for w in line if _stretches(w))
  return extra_pt / room if room else 0.0

#------------------------------------------------------------------------------------------- Render

def render_rich(
  pdf,
  text:RichText,
  x_mm:float,
  y_mm:float,
  first_line:int = 0,
  max_lines:int|None = None,
) -> float:
  """
  Draw `text` wrapped, its top-left corner at `x_mm`, `y_mm` of the frame, the cursor left alone.
  Returns the mm the lines drawn take.

  Justified lines resize their spaces to fill the width, tightening them for one more word
  as far as `_JUSTIFY_SHRINK` allows.
  The last line and a line a hard break ends stay left, unless they took a word by tightening.
  `first_line` and `max_lines` draw one window of a long block, its top at `y_mm`,
  cut where `wrap_line_heights` says the room ends.
  """
  if not text.segments: return 0
  metrics = pdf.metrics
  canvas = pdf.c
  width_mm = text.width_mm
  width_pt = width_mm * MM_TO_PT
  _, wrapped = _wrap_text(pdf, text)
  lines = wrapped.lines
  last = len(lines) - 1 # the block's own last line, wherever the window falls
  if first_line or max_lines is not None:
    end = None if max_lines is None else first_line + max_lines
    lines = lines[first_line:end]
  # One warning per block: every window shares the same wrap result.
  if wrapped.overflow and not first_line:
    # Wrap width too narrow for even a single glyph after force-break.
    # Pathological - surface it so callers know the column is unusable.
    warnings.warn(
      f"render_rich: wrap width {width_mm:.1f}mm too narrow for one glyph; "
      "content extends past the right edge",
      RuntimeWarning, stacklevel=2,
    )
  # Absolute canvas coords for top-left of text block
  x_base_mm = pdf.margin_left + x_mm
  y_top_mm = pdf.page_height - pdf.margin_top - y_mm
  current_top_mm = y_top_mm # canvas y (grows up) - top of next line
  total_used_mm = 0
  for index, line in enumerate(lines, first_line):
    if not line:
      gap_mm = _empty_line_mm(text.segments, text.line_gap)
      current_top_mm -= gap_mm
      total_used_mm += gap_mm
      continue
    # Ascent positions the baseline below the top edge.
    # Both numbers come from `_line_box`, so the drawn line matches the measured one exactly.
    ascent_pt, descent_pt = _line_box(line, text.line_gap, metrics)
    line_height_mm = (ascent_pt + descent_pt) / MM_TO_PT
    # Baseline canvas y in pt (canvas coords, y grows up)
    baseline_canvas_y_pt = (current_top_mm * MM_TO_PT) - ascent_pt
    # Alignment offset
    line_w_pt = _line_width_pt(line)
    ratio = 0.0
    if text.align == Align.CENTER:
      x_offset_pt = (width_pt - line_w_pt) / 2
    elif text.align == Align.RIGHT:
      x_offset_pt = width_pt - line_w_pt
    else:
      x_offset_pt = 0
      # every line tightened to take a word fits;
      # the last and hard-broken ones stay left
      extra_pt = width_pt - line_w_pt
      fills = extra_pt < 0 or index != last and index not in wrapped.hard
      if text.align == Align.JUSTIFY and fills: ratio = _justify_ratio(line, extra_pt)
    cursor_x_pt = x_base_mm * MM_TO_PT + x_offset_pt
    # Group consecutive words into visual runs by (bg, underline, link_url, color)
    # so backgrounds and underlines are drawn continuously across spaces.
    for run in _group_runs(line):
      rseg = run[0].seg
      # The room `_wrap` counted for this run, half on each side:
      # breathing room around a formula, or the inline-code rect with its outer gap.
      pad_pt = _run_pad_pt(rseg) / 2
      cursor_x_pt += pad_pt
      # Math run - draw vector formula, not text
      if rseg.math_drawing is not None:
        try:
          # Vertical alignment: match text baseline to formula baseline
          draw_y = baseline_canvas_y_pt - rseg.math_baseline_from_bottom_pt
          renderPDF.draw(rseg.math_drawing, canvas, cursor_x_pt, draw_y)
        except Exception:
          pass # a formula that fails to draw leaves its gap: the line keeps its measured width
        cursor_x_pt += rseg.math_width_pt + pad_pt
        continue
      run_start_pt = cursor_x_pt
      run_width_pt = sum(_spaced_width(w, ratio) for w in run)
      # Background (inline code) - rounded rect, reaching `_BG_INNER_PAD_PT` past the glyphs
      if rseg.bg_color is not None:
        canvas.setFillColor(Color(*rseg.bg_color[:3]))
        bg_y_pt = baseline_canvas_y_pt - rseg.size * _BG_DESCENT_RATIO
        bg_h_pt = rseg.size * _BG_HEIGHT_RATIO
        canvas.roundRect(
          run_start_pt - _BG_INNER_PAD_PT, bg_y_pt,
          run_width_pt + 2 * _BG_INNER_PAD_PT, bg_h_pt,
          radius=bg_h_pt * _BG_CORNER_RATIO,
          stroke=0, fill=1,
        )
      # Text - each word in the run (font is the same within a run).
      # Super/subscript shifts the baseline and renders at scaled size.
      eff_size = _effective_size(rseg)
      if rseg.superscript:
        word_baseline_pt = baseline_canvas_y_pt + rseg.size * _SUP_BASELINE_RATIO
      elif rseg.subscript:
        word_baseline_pt = baseline_canvas_y_pt - rseg.size * _SUB_BASELINE_RATIO
      else:
        word_baseline_pt = baseline_canvas_y_pt
      canvas.setFillColor(Color(*rseg.color[:3]))
      for w in run:
        if not w.is_space:
          glyphs, _ = metrics.shaped(w.text, w.seg.family, w.seg.mode, eff_size)
          canvas.setFont(metrics.font_name(w.seg.family, w.seg.mode), eff_size)
          canvas.drawString(cursor_x_pt, word_baseline_pt, glyphs, charSpace=w.seg.char_space)
        cursor_x_pt += _spaced_width(w, ratio)
      # Underline across whole run
      if rseg.underline:
        canvas.setStrokeColor(Color(*rseg.color[:3]))
        canvas.setLineWidth(0.5)
        uy = baseline_canvas_y_pt - _UNDERLINE_OFFSET_PT
        canvas.line(run_start_pt, uy, run_start_pt + run_width_pt, uy)
      # Strikethrough through middle of x-height
      if rseg.strike:
        canvas.setStrokeColor(Color(*rseg.color[:3]))
        canvas.setLineWidth(0.5)
        sy = baseline_canvas_y_pt + rseg.size * _STRIKE_Y_RATIO
        canvas.line(run_start_pt, sy, run_start_pt + run_width_pt, sy)
      # Clickable link rect - external URL or internal PDF bookmark
      if rseg.link_url or rseg.link_target:
        rect = (
          run_start_pt,
          baseline_canvas_y_pt - rseg.size * _LINK_RECT_DESCENT,
          run_start_pt + run_width_pt,
          baseline_canvas_y_pt + rseg.size * _LINK_RECT_ASCENT,
        )
        if rseg.link_url:
          canvas.linkURL(rseg.link_url, rect, relative=0)
        else:
          canvas.linkRect(
            contents="", destinationname=rseg.link_target,
            Rect=rect, relative=0,
          )
      cursor_x_pt += pad_pt
    current_top_mm -= line_height_mm
    total_used_mm += line_height_mm
  # Reset fill AND stroke color and line width for subsequent drawing.
  # Without stroke reset, link underlines leak blue stroke into following elements
  # (e.g. table borders after a link-containing paragraph).
  canvas.setFillColor(Color(0, 0, 0))
  canvas.setStrokeColor(Color(0, 0, 0))
  canvas.setLineWidth(1)
  return total_used_mm

#--------------------------------------------------------------------------------------------- Flow

def fit_lines(heights:list[float], start:int, budget:float) -> tuple[int, float]:
  """
  How many lines from `start` fit `budget`, and their total height.

  Takes at least one line even when it does not fit,
  so a line taller than a whole frame still advances the caller
  instead of spinning on a line that can never be placed.
  """
  count, used = 0, 0.0
  while start + count < len(heights):
    h = heights[start + count]
    if count and used + h > budget: break
    used += h
    count += 1
  return count, used

def _in_unit(pdf, mm:float) -> float:
  """`mm` in the unit of `pdf`, as its `cursor()` and `keep()` read lengths."""
  return mm / to_mm(1, pdf.unit)

def flow_rich(pdf, text:RichText, x_mm:float=0, min_lines:int=1):
  """
  Draw `text` from the cursor down, breaking between lines at the foot of each frame.

  `render_rich` lays a block out from one `y`, so lines past the frame fall off the page.
  This draws one frame of lines at a time, moving on to the next column or page,
  and leaves the cursor at `x_mm`, under the last line drawn.
  `min_lines` is the least a frame holds on either side of a break:
  `1` draws whatever fits, `2` keeps a first or last line from standing alone.
  """
  heights = wrap_line_heights(pdf, text)
  n = len(heights)
  i = 0
  moved = False # the lines from `i` on took their one step to the next frame
  while i < n:
    room = pdf.content_height - pdf.y
    if room < sum(heights[i:i + min_lines]):
      pdf.keep(_in_unit(pdf, sum(heights[i:i + min_lines])))
      room = pdf.content_height - pdf.y
    count, used = fit_lines(heights, i, room)
    short = min_lines - (n - i - count) # lines the next frame would lack
    if 0 < short < min_lines:
      if count - short < min_lines and not pdf.at_top and not moved:
        pdf.next_frame() # neither side can keep `min_lines`: the text starts on the next frame
        moved = True
        continue # fitted again there, a header on it included, or here when no frame follows
      if count - short >= min_lines:
        used -= sum(heights[i + count - short:i + count])
        count -= short
    y = pdf.y
    render_rich(pdf, text, x_mm, y, first_line=i, max_lines=count)
    pdf.cursor(_in_unit(pdf, x_mm), _in_unit(pdf, y + used))
    i += count
    moved = False
    if i < n: pdf.next_frame()

def split_rich(pdf, text:RichText, lines:int) -> list[RichSegment]:
  """
  The segments of `text` that follow its first `lines` lines, for text going on in another shape,
  as the full width under the lines set beside a drop cap.

  The cut is the one `render_rich` makes:
  a word bound to the next by a no-break space stays with it,
  a word hyphenated at the cut goes on whole from there, and an empty line after it stays.
  Empty when the text takes no more than `lines` lines.
  """
  if lines <= 0: return list(text.segments)
  words, wrapped = _wrap_text(pdf, text)
  after = [w for line in wrapped.lines[lines:] for w in line]
  if not after: return []
  first = after[0]
  source = first.origin or first
  at = next(k for k, w in enumerate(words) if w is source)
  ended = sum(1 for line in wrapped.hard if line < lines) # hard breaks that end the first lines
  blank = [k for k, w in enumerate(words[:at]) if w.is_break][ended:] # empty lines after the cut
  lead = words[blank[0]:at] if blank else []
  # a word cut at a line end goes on whole from the cut
  rest = [replace(source, text=source.text[first.start:])] if first.origin else [source]
  return _rejoin(lead + rest + words[at + 1:])

def _rejoin(words:list[_Word]) -> list[RichSegment]:
  """`words` back as segments, a run of words of one segment joined into one, hard breaks kept."""
  runs = []
  broken = False
  for w in words:
    if w.is_break:
      if broken: runs.append((replace(w.seg, math_drawing=None), [], True)) # an empty line
      broken = True
      continue
    if runs and runs[-1][0] is w.seg and not broken and w.seg.math_drawing is None:
      runs[-1][1].append(w.text)
      continue
    runs.append((w.seg, [w.text], broken))
    broken = False
  return [replace(seg, text="".join(texts), break_line=brk) for seg, texts, brk in runs]

def drop_cap(
  pdf,
  text:RichText,
  x_mm:float = 0,
  lines:int = 2,
  gap_mm:float = 1,
  caps:bool = False,
  min_lines:int = 1,
) -> bool:
  """
  Draw `text` from the cursor with its first letter `lines` lines tall, as a chapter opens:
  the letter's top on the capitals of the first line, its foot on the last baseline beside it.
  The lines beside it take the width it leaves, `gap_mm` from it,
  and the rest flows on under it as `flow_rich` sets text, `min_lines` as there.
  `caps` sets the rest of the first word in capitals, as IEEE journals do.
  `False`, with nothing drawn, for text opening with no letter, or with a link, a formula
  or a picture, which the caller then sets as usual.
  """
  segments = text.segments
  # a formula or a picture opening the text holds no letter, and one after it is mid-sentence
  at = next((k for k, s in enumerate(segments)
    if s.text.strip() or s.math_drawing is not None), None)
  if at is None or segments[at].math_drawing is not None: return False
  seg = segments[at]
  if seg.link_url or seg.link_target: return False # the letter, drawn apart, would lose the link
  first = seg.text.lstrip()
  if not first[:1].isalpha(): return False
  cut = re.match(r"\w*", first[1:]).end() if caps else 0
  segments = [*segments[:at], replace(seg, text=first[1:cut + 1].upper() + first[cut + 1:]),
    *segments[at + 1:]]
  letter = first[0].upper()
  metrics = pdf.metrics
  line_pt = seg.size * text.line_gap
  cap_pt, _ = metrics.letter_span(seg.family, seg.mode, seg.size)
  # the letter's capital reaches from the capitals of the first line to the last baseline
  size = ((lines - 1) * line_pt + cap_pt) / (cap_pt / seg.size)
  drop = metrics.text_width(letter, seg.family, seg.mode, size) / MM_TO_PT + gap_mm
  # the lines beside the letter and the rest under it open with no indent of their own
  beside = replace(text, segments=segments, width_mm=text.width_mm - drop, indent_mm=0)
  line_mm = line_pt / MM_TO_PT
  beside_lines = len(wrap_line_heights(pdf, beside))
  # the letter's lines and one more
  pdf.keep(_in_unit(pdf, max(lines, min(beside_lines, lines + 1)) * line_mm))
  y = pdf.y
  ascent, _ = _line_box([_Word("", seg, 0, False)], text.line_gap, metrics) # a line of its face
  baseline = y * MM_TO_PT + ascent + (lines - 1) * line_pt
  canvas = pdf.c
  canvas.setFont(metrics.font_name(seg.family, seg.mode), size)
  canvas.setFillColor(Color(*seg.color[:3]))
  canvas.drawString((pdf.margin_left + x_mm) * MM_TO_PT,
    (pdf.page_height - pdf.margin_top) * MM_TO_PT - baseline, letter)
  used = render_rich(pdf, beside, x_mm + drop, y, max_lines=lines)
  # a short paragraph still clears the letter
  pdf.cursor(_in_unit(pdf, x_mm), _in_unit(pdf, y + max(used, lines * line_mm)))
  rest = split_rich(pdf, beside, lines)
  if rest: flow_rich(pdf, replace(text, segments=rest, indent_mm=0), x_mm, min_lines=min_lines)
  return True
