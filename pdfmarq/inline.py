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
from .constants import Align, MM_TO_PT
from .fonts import is_builtin, builtin_name

#---------------------------------------------------------------------------------- RichSegment

@dataclass
class RichSegment:
  """Single span of styled text, inline code, or inline math drawing.

  Multiple segments render on one line with shared baseline. Background
  color draws a filled rect behind the span (used for inline code).

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
  underline: bool = False
  strikethrough: bool = False
  math_drawing: object|None = None # reportlab Drawing or None
  math_width_pt: float = 0 # total width of the math glyphs
  math_baseline_from_bottom_pt: float = 0 # baseline offset from drawing bottom

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

def _tokenize(segments:list[RichSegment], metrics) -> list[_Word]:
  """Split segments into word tokens preserving per-segment style."""
  words = []
  for seg in segments:
    # Math segment - single atomic word (no splitting on spaces)
    if seg.math_drawing is not None:
      words.append(_Word("", seg, seg.math_width_pt, is_space=False))
      continue
    if seg.text == "\n":
      words.append(_Word("", seg, 0, is_space=False, is_break=True))
      continue
    for part in re.findall(r"\S+|\s+", seg.text):
      w = metrics.text_width(part, seg.family, seg.mode, seg.size)
      words.append(_Word(part, seg, w, is_space=part.isspace()))
  return words

#----------------------------------------------------------------------------------------- Wrap
def _wrap(
  words:list[_Word], width_pt:float, preserve_leading_space:bool=False,
) -> list[list[_Word]]:
  """Greedy word-wrap honoring hard breaks.

  Args:
    preserve_leading_space: If True, leading whitespace on a line is kept
      (for code blocks where indentation is semantic). Default False
      strips leading space (normal prose behavior).
  """
  lines: list[list[_Word]] = []
  current: list[_Word] = []
  current_w = 0
  def flush(line):
    while line and line[-1].is_space:
      line.pop()
    lines.append(line)
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
    if current_w + w.width_pt > width_pt and current:
      flush(current)
      current, current_w = [w], w.width_pt
    else:
      current.append(w)
      current_w += w.width_pt
  flush(current)
  return lines

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
  return (seg.bg_color, seg.link_url, seg.link_target, seg.underline, seg.strikethrough,
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
    for part in re.findall(r"\S+|\s+", seg.text):
      w = metrics.text_width(part, seg.family, seg.mode, seg.size) / MM_TO_PT
      if not part.isspace():
        if w > max_word: max_word = w
      total += w
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
  lines = _wrap(words, width_pt, preserve_leading_space=preserve_leading_space)
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
  lines = _wrap(words, width_pt, preserve_leading_space=preserve_leading_space)
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
    ascent_pt = max_size * 0.8
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
          cursor_x_pt += 1
          draw_x = cursor_x_pt
          # Vertical alignment: match text baseline to formula baseline
          draw_y = baseline_canvas_y_pt - rseg.math_baseline_from_bottom_pt
          renderPDF.draw(rseg.math_drawing, canvas, draw_x, draw_y)
          cursor_x_pt += rseg.math_width_pt + 1
        except Exception:
          cursor_x_pt += rseg.math_width_pt
        continue
      # Runs with background (inline code) get outer breathing room so the
      # shaded rect doesn't butt up against surrounding text. `bg_pad_x` =
      # how far the shaded rect extends past the glyphs; `bg_outer` = extra
      # gap between that rect and the words on either side.
      has_bg = rseg.bg_color is not None
      bg_pad_x = 2.5 if has_bg else 0
      bg_outer = 1.2 if has_bg else 0
      if has_bg:
        cursor_x_pt += bg_outer + bg_pad_x
      run_start_pt = cursor_x_pt
      run_width_pt = sum(w.width_pt for w in run)
      # Background (inline code) - rounded rect
      if has_bg:
        canvas.setFillColor(Color(*rseg.bg_color[:3]))
        bg_y_pt = baseline_canvas_y_pt - rseg.size * 0.32
        bg_h_pt = rseg.size * 1.35
        canvas.roundRect(
          run_start_pt - bg_pad_x, bg_y_pt,
          run_width_pt + 2 * bg_pad_x, bg_h_pt,
          radius=bg_h_pt * 0.2,
          stroke=0, fill=1,
        )
      # Text - each word in the run (font is the same within a run)
      canvas.setFillColor(Color(*rseg.color[:3]))
      for w in run:
        if not w.is_space:
          font_name = _font_name(w.seg, pdf._fonts)
          canvas.setFont(font_name, w.seg.size)
          canvas.drawString(cursor_x_pt, baseline_canvas_y_pt, w.text)
        cursor_x_pt += w.width_pt
      # Underline across whole run
      if rseg.underline:
        canvas.setStrokeColor(Color(*rseg.color[:3]))
        canvas.setLineWidth(0.5)
        uy = baseline_canvas_y_pt - 1
        canvas.line(run_start_pt, uy, run_start_pt + run_width_pt, uy)
      # Strikethrough through middle of x-height
      if rseg.strikethrough:
        canvas.setStrokeColor(Color(*rseg.color[:3]))
        canvas.setLineWidth(0.5)
        sy = baseline_canvas_y_pt + rseg.size * 0.28
        canvas.line(run_start_pt, sy, run_start_pt + run_width_pt, sy)
      # Clickable link rect - external URL or internal PDF bookmark
      if rseg.link_url or rseg.link_target:
        rect = (
          run_start_pt,
          baseline_canvas_y_pt - rseg.size * 0.25,
          run_start_pt + run_width_pt,
          baseline_canvas_y_pt + rseg.size * 0.85,
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
