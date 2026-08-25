# pdfmarq/md/md_list.py

"""List rendering - bullet and ordered, with keep-together for top-level lists
and custom bullet glyphs drawn via `canvas.circle`."""

from markdown_it.token import Token
from reportlab.lib.colors import Color
from ..inline import RichSegment, render_rich, measure_rich, measure_extent
from ..constants import Align, MM_TO_PT

#----------------------------------------------------------------------------------- Item numbering

def _item_ranges(tokens:list[Token], start:int, end:int) -> list[tuple[int, int]]:
  """`(open, close)` index pair per direct child item; nested items skipped."""
  items = []
  j = start + 1
  while j < end:
    if tokens[j].type != "list_item_open":
      j += 1
      continue
    depth, k = 1, j + 1
    while k < end:
      if tokens[k].type == "list_item_open": depth += 1
      elif tokens[k].type == "list_item_close":
        depth -= 1
        if depth == 0: break
      k += 1
    items.append((j, k))
    j = k + 1
  return items

def _first_number(raw:str|int|None) -> int:
  """`start` attribute as int; 1 when absent or malformed."""
  try: return int(raw)
  except (TypeError, ValueError): return 1

def _author_numbers(item_tokens:list[Token], first:int) -> list[int]:
  """Markers to print. Author's own numbers when strictly increasing, so
  `1. 2. 4.` stays `1 2 4`; otherwise count from `first`, which keeps the
  lazy `1. 1. 1.` idiom rendering as `1 2 3`."""
  typed = []
  for t in item_tokens:
    info = (t.info or "").strip()
    if not info.isdigit(): break
    typed.append(int(info))
  n = len(item_tokens)
  if len(typed) == n and all(typed[i] < typed[i+1] for i in range(n - 1)):
    return typed
  return [first + i for i in range(n)]

def _marker_column_mm(pdf, style, numbers:list[int]) -> float:
  """Marker column: widest `N. ` or `list_indent`, whichever is wider. At 11pt
  `10.` needs 6.17mm against a 6mm indent and used to wrap onto two lines."""
  if not numbers: return style.list_indent
  widest = max(numbers, key=lambda n: len(str(n)))
  seg = RichSegment(text=f"{widest}. ", family=style.font_body,
    mode=style.body_mode, size=style.body_size, color=style.body_color)
  return max(style.list_indent, measure_extent(pdf, [seg])[1])

#---------------------------------------------------------------------------------------- ListMixin

class ListMixin:
  """Bullet/ordered list rendering (task lists, nesting). Mixed into `MarkdownRenderer`."""

  def _render_list(self, tokens:list[Token], start:int, ordered:bool) -> int:
    s = self.style
    open_type = "ordered_list_open" if ordered else "bullet_list_open"
    close_type = "ordered_list_close" if ordered else "bullet_list_close"
    end = self._find_close(tokens, start, open_type, close_type)
    # Keep-together: top-level list, if it fits on empty page but not here → new page
    if self._list_depth == 0:
      body_line_mm = s.body_size * s.line_height / MM_TO_PT
      n_items = sum(
        1 for j in range(start, end + 1)
        if tokens[j].type == "list_item_open"
      )
      list_h = n_items * body_line_mm * 1.2 + s.para_gap
      page_avail = self.pdf.content_height
      if list_h <= page_avail * 0.9 and list_h > (page_avail - self.pdf.y):
        self.pdf.new_page()
    if self._list_depth == 0:
      self.pdf.enter(1)
    self._list_depth += 1
    try:
      items = _item_ranges(tokens, start, end)
      numbers: list[int] = []
      column = s.list_indent
      if ordered:
        first = _first_number(self._get_attr(tokens[start], "start"))
        numbers = _author_numbers([tokens[j] for j, _ in items], first)
        column = _marker_column_mm(self.pdf, s, numbers)
      for idx, (j, k) in enumerate(items):
        if ordered:
          self._render_list_item(f"{numbers[idx]}.", tokens[j+1:k], column=column)
        else:
          self._render_list_item("", tokens[j+1:k], bullet=True, column=column)
    finally:
      # Unwind even if a nested block raises, or every later list on the
      # page renders at the wrong depth and indent.
      self._list_depth -= 1
    if self._list_depth == 0:
      self.pdf.enter(max(0, s.para_gap - s.list_gap))
    return end + 1

  def _render_list_item(
    self, prefix:str, item_tokens:list[Token],
    bullet:bool=False, column:float|None=None,
  ):
    s = self.style
    if column is None:
      column = s.list_indent
    # Pre-measure first paragraph so the prefix (number/bullet) isn't orphaned
    # when the item wraps to a new page - `_render_paragraph`'s own break fires
    # too late (after the prefix is already drawn).
    needed = self._measure_item_first_para(item_tokens, column)
    page_avail = self.pdf.content_height
    if needed <= page_avail * 0.9 and needed > (page_avail - self.pdf.y):
      self.pdf.new_page()
    self._ensure_space(needed)
    x_prefix = self._indent_mm
    y_item = self.pdf.y
    if bullet:
      # Solid disc via canvas.circle - cleaner than glyph `•`
      from reportlab.lib.units import mm as _mm
      page = self.pdf._page
      cx_mm = page.margin_left + x_prefix + 1.5
      cy_mm = page.height - page.margin_top - (y_item + s.body_size * 0.55 / MM_TO_PT)
      canvas = self.pdf._canvas
      canvas.setFillColor(Color(*s.body_color[:3]))
      canvas.circle(cx_mm * _mm, cy_mm * _mm, s.bullet_radius * _mm, stroke=0, fill=1)
      canvas.setFillColor(Color(0, 0, 0))
    else:
      prefix_seg = RichSegment(
        text=prefix, family=s.font_body, mode=s.body_mode,
        size=s.body_size, color=s.body_color,
      )
      render_rich(
        self.pdf, [prefix_seg], column, x_prefix, y_item,
        Align.LEFT, s.line_height,
      )
    old_indent = self._indent_mm
    self._indent_mm = old_indent + column
    self.pdf.cursor(self._indent_mm, y_item)
    try:
      self._render_tokens(item_tokens)
    finally:
      self._indent_mm = old_indent
      self.pdf.cursor(self._indent_mm, self.pdf.y)

  def _measure_item_first_para(
    self, item_tokens:list[Token],
    column:float|None=None,
  ) -> float:
    """Height (mm) of the first paragraph - keep-together reservation for
    `_render_list_item`. Falls back to two body lines for non-paragraph
    leading content (nested list, code block) which have their own break logic."""
    s = self.style
    if column is None:
      column = s.list_indent
    body_line_mm = s.body_size * s.line_height / MM_TO_PT
    for j, t in enumerate(item_tokens):
      if t.type == "paragraph_open" and j + 1 < len(item_tokens):
        inline = item_tokens[j + 1]
        if inline.type == "inline":
          base = RichSegment(
            text="", family=s.font_body, mode=s.body_mode,
            size=s.body_size, color=s.body_color,
          )
          try:
            segs = self._inline_to_segments(inline, base)
            width = self.pdf.content_width - self._indent_mm - column
            h = measure_rich(self.pdf, segs, width, line_gap=s.line_height)
            return max(h, body_line_mm)
          except Exception:
            pass
        break
      # Non-paragraph leading content (nested list, fence, etc.) - each block
      # has its own keep logic; reserve two lines as a minimum here.
      if t.type not in ("paragraph_close",):
        break
    return body_line_mm * 2
