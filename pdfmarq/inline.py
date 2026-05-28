# pdfmarq/inline.py

"""
Rich inline text rendering - mixed styles within a single line.

Provides `RichSegment` and `render_rich()` for drawing a sequence of
styled text spans (bold, italic, code, links) with word-wrap. This is
the low-level engine used by `markdown.py`; `core.PDF.text()` is a
simpler single-style variant and is unchanged.
"""
from dataclasses import dataclass
import re
from reportlab.lib.colors import Color
from reportlab.pdfbase import pdfmetrics
from .constants import Align, MM_TO_PT
from .fonts import is_builtin, builtin_name

#-------------------------------------------------------------------------------- Layout ratios

# Vertical metrics relative to glyph size (`rseg.size`). Tuned to GitHub-light
# look. Centralised here so future visual tweaks don't require code-hunting.
_ASCENT_RATIO = 0.80  # line-box ascent: positions baseline below top edge
_BG_DESCENT_RATIO = 0.32  # how far below baseline the inline-code bg starts
_BG_HEIGHT_RATIO = 1.35  # inline-code bg height in glyph units
_BG_CORNER_RATIO = 0.20  # rounded-corner radius / bg height
_STRIKE_Y_RATIO = 0.28  # strikethrough Y above baseline
_LINK_RECT_DESCENT = 0.25  # link clickable rect: depth below baseline
_LINK_RECT_ASCENT = 0.85  # link clickable rect: height above baseline
_UNDERLINE_OFFSET_PT = 1.0  # underline distance below baseline (pt, size-independent)

# Inline-code shaded background padding (pt - not font-size relative).
_BG_INNER_PAD_PT = 2.5  # bg rect extends this far past glyphs
_BG_OUTER_GAP_PT = 1.2  # extra gap between bg rect and adjacent text
# Total horizontal overhead a single inline-code run draws on top of its
# glyph width (outer gap + inner pad on each side). Used by `measure_extent`
# so table column-width estimation reserves room for the shaded rect.
_BG_RUN_EXTRA_PT = 2 * (_BG_OUTER_GAP_PT + _BG_INNER_PAD_PT)

# Preferred break points inside a token wider than the wrap width
# (URLs, long file paths). Break happens AFTER one of these chars so the
# delimiter stays attached to the preceding chunk - matches how readers
# scan URLs. Falls back to character-level break when none is reachable.
_BREAK_CHARS = "/?&=._-:,;"

# Math drawings: tiny breathing room around an inline formula (pt).
_MATH_INLINE_PAD_PT = 1.0

# Superscript / subscript scaling. Industry-standard: glyph at ~70% size,
# baseline raised (sup) or lowered (sub) by a fraction of full size.
_SCRIPT_SIZE_RATIO = 0.70
_SUP_BASELINE_RATIO = 0.40  # raise baseline by this fraction of full size
_SUB_BASELINE_RATIO = 0.15  # lower baseline by this fraction of full size

#---------------------------------------------------------------------------------- RichSegment

@dataclass
class RichSegment:
  """Single span of styled text, inline code, or inline math drawing.

  Multiple segments render on one line with shared baseline. Background
  color draws a filled rect behind the span (used for inline code).

  Two ways to set face weight/slant:
    - `mode`: explicit reportlab font mode (`"Regular"`/`"Bold"`/`"Italic"`/
      `"BoldItalic"`). Direct mapping to TTF lookup.
    - `bold` / `italic`: boolean flags. When set, `__post_init__` derives
      `mode` from them. Symmetric with `docmarq.RichSegment` so the same
      construction works in both libraries.

  Math mode: if `math_drawing` is set, the segment is a pre-rendered vector
  formula (from matplotlib → svglib). `text` is ignored, `math_width_pt` is
  the full glyph width, and `math_baseline_from_bottom_pt` is how far the
  text baseline sits above the bottom edge of the drawing (for vertical
  alignment with surrounding text).
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
  # Soft line break BEFORE this segment. Symmetric with docmarq's flag-based
  # break; an alternative to embedding `\n` in `text`.
  break_line: bool = False
  # Vertical script. Render at smaller size with baseline offset. Useful for
  # footnote refs (sup) and chemical formulae (sub).
  superscript: bool = False
  subscript: bool = False
  math_drawing: object|None = None # reportlab Drawing or None
  math_width_pt: float = 0 # total width of the math glyphs
  math_baseline_from_bottom_pt: float = 0 # baseline offset from drawing bottom

  def __post_init__(self):
    # `bold`/`italic` flags win over `mode` when explicitly set. Lets users
    # write `RichSegment(text="x", bold=True)` (docmarq-style) without
    # spelling out the reportlab mode string.
    if self.bold and self.italic:
      self.mode = "BoldItalic"
    elif self.bold:
      self.mode = "Bold"
    elif self.italic:
      self.mode = "Italic"

#---------------------------------------------------------------------------- Glyph fallback

# Visually-equivalent codepoints. Many fonts (IBM Plex, Inter, ...) ship the
# glyph under one of these but not the other; e.g. IBM Plex Sans has Ω only
# at U+2126 (Ohm sign), not U+03A9 (Greek capital Omega) which is what most
# editors emit. We remap to whichever codepoint the font actually has so the
# user sees the glyph instead of a `.notdef` box.
_GLYPH_EQUIVALENTS: dict[int, int] = {
  0x03A9: 0x2126, 0x2126: 0x03A9,  # Greek Omega ↔ Ohm sign
  0x03BC: 0x00B5, 0x00B5: 0x03BC,  # Greek mu ↔ micro sign
  0x0394: 0x2206, 0x2206: 0x0394,  # Greek Delta ↔ Increment
  0x03A3: 0x2211, 0x2211: 0x03A3,  # Greek Sigma ↔ N-ary summation
  0x03A0: 0x220F, 0x220F: 0x03A0,  # Greek Pi ↔ N-ary product
  0x2212: 0x002D,                  # Minus sign → hyphen-minus
}

_cmap_cache: dict[str, dict|None] = {}
_remap_cache: dict[tuple[str, str], str] = {}

def _font_cmap(font_name:str) -> dict|None:
  """Return the char→glyph dict for a registered TTF font, or None for
  builtins / unregistered. Result cached - the dict identity is stable
  for the lifetime of the process."""
  cached = _cmap_cache.get(font_name)
  if cached is not None or font_name in _cmap_cache:
    return cached
  try:
    face = pdfmetrics.getFont(font_name).face
    cmap = getattr(face, "charToGlyph", None)
  except Exception:
    cmap = None
  _cmap_cache[font_name] = cmap
  return cmap

def _remap_for_font(text:str, font_name:str) -> str:
  """Substitute codepoints missing from `font_name` with visually-equivalent
  ones the font does have. Returns `text` unchanged when no substitution is
  needed (the common case)."""
  if not text:
    return text
  cmap = _font_cmap(font_name)
  if cmap is None:
    return text
  key = (font_name, text)
  cached = _remap_cache.get(key)
  if cached is not None:
    return cached
  out = None
  for i, c in enumerate(text):
    cp = ord(c)
    if cp in cmap:
      continue
    alt = _GLYPH_EQUIVALENTS.get(cp)
    if alt is not None and alt in cmap:
      if out is None:
        out = list(text)
      out[i] = chr(alt)
  result = "".join(out) if out is not None else text
  _remap_cache[key] = result
  return result

#---------------------------------------------------------------------------------- _Word token
@dataclass
class _Word:
  """Word-level token for wrapping. `is_space` means whitespace token."""
  text: str
  seg: RichSegment
  width_pt: float
  is_space: bool
  is_break: bool = False  # hard line break

#------------------------------------------------------------------------------------- Tokenize

def _effective_size(seg:RichSegment) -> float:
  """Glyph size after super/subscript scaling."""
  if seg.superscript or seg.subscript:
    return seg.size * _SCRIPT_SIZE_RATIO
  return seg.size

def _tokenize(segments:list[RichSegment], metrics) -> list[_Word]:
  """Split segments into word tokens preserving per-segment style.
  Codepoints missing from the seg's font get remapped to visually-equivalent
  ones the font has (Ω→Ohm, μ→micro, etc.) before width measurement."""
  words = []
  for seg in segments:
    # `break_line` flag emits a hard break before the segment's content,
    # symmetric with `docmarq.RichSegment.break_line`.
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
    font_name = _font_name(seg, metrics.fonts)
    for part in re.findall(r"\S+|\s+", seg.text):
      part = _remap_for_font(part, font_name)
      w = metrics.text_width(part, seg.family, seg.mode, eff_size)
      words.append(_Word(part, seg, w, is_space=part.isspace()))
  return words

#----------------------------------------------------------------------------------------- Wrap
@dataclass
class _WrapResult:
  """Output of `_wrap`. `overflow=True` means a chunk still didn't fit
  after the force-break pass (wrap width too narrow for even one glyph)."""
  lines: list[list["_Word"]]
  overflow: bool = False

def _break_oversized(word:_Word, width_pt:float, metrics) -> list[_Word]:
  """Split a token wider than `width_pt` into chunks each fitting the width.
  Prefers a URL/path delimiter from `_BREAK_CHARS` as the break boundary;
  falls back to character-level break. All chunks share the original
  segment so link rect, bg, color, and font stay continuous across the
  break."""
  seg = word.seg
  eff_size = _effective_size(seg)
  text = word.text
  if not text:
    return [word]
  tw = metrics.text_width
  family, mode = seg.family, seg.mode
  chunks: list[_Word] = []
  i, n = 0, len(text)
  while i < n:
    j, last_fit = i + 1, i + 1
    while j <= n:
      if tw(text[i:j], family, mode, eff_size) > width_pt:
        break
      last_fit = j
      j += 1
    if last_fit == i:
      last_fit = i + 1  # single glyph still > width_pt, emit it anyway
    if last_fit < n:
      for k in range(last_fit - 1, i, -1):
        if text[k-1] in _BREAK_CHARS:
          last_fit = k
          break
    piece = text[i:last_fit]
    chunks.append(_Word(piece, seg, tw(piece, family, mode, eff_size), is_space=False))
    i = last_fit
  return chunks

def _wrap(
  words:list[_Word], width_pt:float, metrics,
  preserve_leading_space:bool=False,
) -> _WrapResult:
  """Greedy word-wrap honoring hard breaks. Tokens wider than `width_pt`
  are force-broken via `_break_oversized` (preferred at URL delimiters),
  so long links and paths don't spill past the right edge.

  Args:
    preserve_leading_space: If True, leading whitespace on a line is kept
      (for code blocks where indentation is semantic). Default False
      strips leading space (normal prose behavior).
  """
  lines: list[list[_Word]] = []
  current: list[_Word] = []
  current_w = 0
  overflow = False
  def flush(line):
    while line and line[-1].is_space:
      line.pop()
    lines.append(line)
  def place(w):
    nonlocal current, current_w, overflow
    if w.width_pt > width_pt:
      overflow = True  # even one glyph wider than wrap width
    if current_w + w.width_pt > width_pt and current:
      flush(current)
      current, current_w = [w], w.width_pt
    else:
      current.append(w)
      current_w += w.width_pt
  for w in words:
    if w.is_break:
      flush(current)
      current, current_w = [], 0
      continue
    if w.is_space:
      if not current and not preserve_leading_space:
        continue  # no leading space in prose
      current.append(w)
      current_w += w.width_pt
      continue
    if w.width_pt > width_pt and w.text:
      for chunk in _break_oversized(w, width_pt, metrics):
        place(chunk)
      continue
    place(w)
  flush(current)
  return _WrapResult(lines, overflow)

#------------------------------------------------------------------------------ Metrics helpers

def _font_name(seg:RichSegment, font_manager) -> str:
  """Resolve reportlab font name for segment."""
  if is_builtin(seg.family, seg.mode):
    return builtin_name(seg.family, seg.mode)
  return font_manager.register(seg.family, seg.mode)

def _line_width_pt(line:list[_Word]) -> float:
  """Total horizontal extent of rendered line in pt."""
  return sum(w.width_pt for w in line)

def _run_key(seg:RichSegment) -> tuple:
  """Visual-run key: consecutive words with same key share bg/underline/link.
  Math segments get a unique id so they always form their own run."""
  math_id = id(seg.math_drawing) if seg.math_drawing is not None else None
  return (seg.bg_color, seg.link_url, seg.link_target, seg.underline, seg.strike,
          seg.family, seg.mode, seg.size, seg.color, math_id)

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

#-------------------------------------------------------------------------------------- Measure

def measure_extent(pdf, segments:list[RichSegment]) -> tuple[float, float]:
  """Return `(min_word_width_mm, total_width_mm)` for word-wrap planning.

  - **min_word_width**: width of the widest single unbreakable token (the
    narrowest column width at which this content can fit without breaking
    any word). Math/image segments count as single atoms.
  - **total_width**: sum of all token widths - how wide this content would
    be if it never wrapped.

  Used by the table column-width solver to compute HTML-style auto-layout
  (distribute available space proportionally between `min` and `max` per
  column).
  """
  if not segments:
    return 0, 0
  metrics = pdf._metrics
  max_word = 0
  total = 0
  for seg in segments:
    if seg.math_drawing is not None:
      w = seg.math_width_pt / MM_TO_PT
      if w > max_word: max_word = w
      total += w
      continue
    if not seg.text:
      continue
    if seg.text == "\n":
      continue
    # Inline-code draws a shaded rect with outer gap + inner pad on each
    # side. That overhead must show up here or table columns sized for
    # `` `x` `` clip the bg rect against the cell border.
    bg_extra_mm = (_BG_RUN_EXTRA_PT / MM_TO_PT) if seg.bg_color is not None else 0
    font_name = _font_name(seg, metrics.fonts)
    for part in re.findall(r"\S+|\s+", seg.text):
      part = _remap_for_font(part, font_name)
      w = metrics.text_width(part, seg.family, seg.mode, seg.size) / MM_TO_PT
      if not part.isspace():
        word_w = w + bg_extra_mm  # any word may end up alone on a wrapped line
        if word_w > max_word: max_word = word_w
      total += w
    total += bg_extra_mm
  return max_word, total

def measure_rich(
  pdf,
  segments: list[RichSegment],
  width_mm: float,
  line_gap: float = 1.45,
  preserve_leading_space: bool = False,
) -> float:
  """Calculate how much vertical space `render_rich` would use, without
  actually drawing anything. Uses the same tokenization + wrap logic as
  `render_rich` so the number is accurate to the pixel.

  Used for pre-computing heights of cells and boxes (code blocks, table
  cells) before drawing, so backgrounds and borders can be sized correctly.
  """
  if not segments: return 0
  metrics = pdf._metrics
  width_pt = width_mm * MM_TO_PT
  words = _tokenize(segments, metrics)
  wrapped = _wrap(words, width_pt, metrics, preserve_leading_space=preserve_leading_space)
  lines = wrapped.lines
  total_used_mm = 0
  for line in lines:
    if not line:
      total_used_mm += 11 * line_gap / MM_TO_PT
      continue
    max_size = max(w.seg.size for w in line)
    total_used_mm += max_size * line_gap / MM_TO_PT
  return total_used_mm

#--------------------------------------------------------------------------------------- Render

def render_rich(
  pdf,
  segments: list[RichSegment],
  width_mm: float,
  x_mm: float,
  y_mm: float,
  align: str = Align.LEFT,
  line_gap: float = 1.45,
  preserve_leading_space: bool = False,
) -> float:
  """Render mixed-style text with word wrap. Does not modify cursor.

  Args:
    pdf: `PDF` instance (uses `_canvas`, `_metrics`, `_fonts`, `_page`, `_links`).
    segments: List of `RichSegment` to render in sequence.
    width_mm: Wrap width (from left edge `x_mm`).
    x_mm: Left edge in cursor coords (from content area left margin).
    y_mm: Top edge in cursor coords (from content area top margin).
    align: `L` / `C` / `R`.
    line_gap: Line height multiplier (e.g. 1.45 = 145% of font size).
    preserve_leading_space: Keep leading whitespace on each line (for code).

  Returns:
    Total vertical space used, in mm.
  """
  if not segments: return 0
  metrics = pdf._metrics
  canvas = pdf._canvas
  page = pdf._page
  width_pt = width_mm * MM_TO_PT
  words = _tokenize(segments, metrics)
  wrapped = _wrap(words, width_pt, metrics, preserve_leading_space=preserve_leading_space)
  lines = wrapped.lines
  if wrapped.overflow:
    # Wrap width too narrow for even a single glyph after force-break.
    # Pathological - surface it so callers know the column is unusable.
    import warnings
    warnings.warn(
      f"render_rich: wrap width {width_mm:.1f}mm too narrow for one glyph; "
      "content extends past the right edge",
      RuntimeWarning, stacklevel=2,
    )
  # Absolute canvas coords for top-left of text block
  x_base_mm = page.margin_lr + x_mm
  y_top_mm = page.height - page.margin_top - y_mm
  current_top_mm = y_top_mm  # canvas y (grows up) - top of next line
  total_used_mm = 0
  for line in lines:
    # Line metrics - use max size to determine baseline and height
    if not line:
      # Empty line from hard break
      gap_mm = 11 * line_gap / MM_TO_PT
      current_top_mm -= gap_mm
      total_used_mm += gap_mm
      continue
    max_size = max(w.seg.size for w in line)
    line_height_pt = max_size * line_gap
    line_height_mm = line_height_pt / MM_TO_PT
    # Line-box ascent - positions baseline at cap+accent distance below top
    ascent_pt = max_size * _ASCENT_RATIO
    # Baseline canvas y in pt (canvas coords, y grows up)
    baseline_canvas_y_pt = (current_top_mm * MM_TO_PT) - ascent_pt
    # Alignment offset
    line_w_pt = _line_width_pt(line)
    if align == Align.CENTER:
      x_offset_pt = (width_pt - line_w_pt) / 2
    elif align == Align.RIGHT:
      x_offset_pt = width_pt - line_w_pt
    else:
      x_offset_pt = 0
    cursor_x_pt = x_base_mm * MM_TO_PT + x_offset_pt
    # Group consecutive words into visual runs by (bg, underline, link_url, color)
    # so backgrounds and underlines are drawn continuously across spaces.
    for run in _group_runs(line):
      rseg = run[0].seg
      # Math run - draw vector formula, not text
      if rseg.math_drawing is not None:
        try:
          from reportlab.graphics import renderPDF
          # Small breathing room before and after math
          cursor_x_pt += _MATH_INLINE_PAD_PT
          draw_x = cursor_x_pt
          # Vertical alignment: match text baseline to formula baseline
          draw_y = baseline_canvas_y_pt - rseg.math_baseline_from_bottom_pt
          renderPDF.draw(rseg.math_drawing, canvas, draw_x, draw_y)
          cursor_x_pt += rseg.math_width_pt + _MATH_INLINE_PAD_PT
        except Exception:
          cursor_x_pt += rseg.math_width_pt
        continue
      # Runs with background (inline code) get outer breathing room so the
      # shaded rect doesn't butt up against surrounding text. `bg_pad_x` =
      # how far the shaded rect extends past the glyphs; `bg_outer` = extra
      # gap between that rect and the words on either side.
      has_bg = rseg.bg_color is not None
      bg_pad_x = _BG_INNER_PAD_PT if has_bg else 0
      bg_outer = _BG_OUTER_GAP_PT if has_bg else 0
      if has_bg:
        cursor_x_pt += bg_outer + bg_pad_x
      run_start_pt = cursor_x_pt
      run_width_pt = sum(w.width_pt for w in run)
      # Background (inline code) - rounded rect
      if has_bg:
        canvas.setFillColor(Color(*rseg.bg_color[:3]))
        bg_y_pt = baseline_canvas_y_pt - rseg.size * _BG_DESCENT_RATIO
        bg_h_pt = rseg.size * _BG_HEIGHT_RATIO
        canvas.roundRect(
          run_start_pt - bg_pad_x, bg_y_pt,
          run_width_pt + 2 * bg_pad_x, bg_h_pt,
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
          font_name = _font_name(w.seg, pdf._fonts)
          canvas.setFont(font_name, eff_size)
          canvas.drawString(cursor_x_pt, word_baseline_pt, w.text)
        cursor_x_pt += w.width_pt
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
      # Push cursor past the outer margin on the right side
      if has_bg:
        cursor_x_pt += bg_pad_x + bg_outer
    current_top_mm -= line_height_mm
    total_used_mm += line_height_mm
  # Reset fill AND stroke color and line width for subsequent drawing.
  # Without stroke reset, link underlines leak blue stroke into following
  # elements (e.g. table borders after a link-containing paragraph).
  canvas.setFillColor(Color(0, 0, 0))
  canvas.setStrokeColor(Color(0, 0, 0))
  canvas.setLineWidth(1)
  return total_used_mm
