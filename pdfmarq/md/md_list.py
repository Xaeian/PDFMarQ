# pdfmarq/md/md_list.py

"""
List rendering - bullet + ordered, with keep-together for top-level lists
and custom bullet glyphs drawn via `canvas.circle`.
"""

from markdown_it.token import Token
from reportlab.lib.colors import Color
from ..inline import RichSegment, render_rich, measure_rich
from ..constants import Align, MM_TO_PT

#------------------------------------------------------------------------------------ ListMixin

class ListMixin:
  """
  Bullet and ordered list rendering, including task lists (`[ ]`, `[x]`)
  and nesting. Mixed into `MarkdownRenderer`.
  """

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
    item_num = 1
    j = start + 1
    while j < end:
      if tokens[j].type == "list_item_open":
        item_depth = 1
        k = j + 1
        while k < end:
          if tokens[k].type == "list_item_open": item_depth += 1
          elif tokens[k].type == "list_item_close":
            item_depth -= 1
            if item_depth == 0: break
          k += 1
        if ordered:
          self._render_list_item(f"{item_num}.", tokens[j+1:k], bullet=False)
        else:
          self._render_list_item("", tokens[j+1:k], bullet=True)
        item_num += 1
        j = k + 1
      else:
        j += 1
    self._list_depth -= 1
    if self._list_depth == 0:
      self.pdf.enter(max(0, s.para_gap - s.list_gap))
    return end + 1

  def _render_list_item(self, prefix:str, item_tokens:list[Token], bullet:bool=False):
    s = self.style
    # Pre-measure first paragraph so the prefix (number/bullet) doesn't get
    # orphaned on the previous page when the content wraps to a new one.
    # Without this, `_render_paragraph` triggers its own page-break AFTER the
    # prefix is already drawn - leaving "4." alone on the last line.
    needed = self._measure_item_first_para(item_tokens)
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
      cx_mm = page.margin_lr + x_prefix + 1.5
      cy_mm = page.height - page.margin_top - (y_item + s.body_size * 0.55 / MM_TO_PT)
      canvas = self.pdf._canvas
      canvas.setFillColor(Color(*s.body_color[:3]))
      canvas.circle(cx_mm * _mm, cy_mm * _mm, s.bullet_radius * _mm, stroke=0, fill=1)
      canvas.setFillColor(Color(0, 0, 0))
    else:
      prefix_seg = RichSegment(
        text=prefix, family=s.body_family, mode=s.body_mode,
        size=s.body_size, color=s.body_color,
      )
      render_rich(
        self.pdf, [prefix_seg], s.list_indent, x_prefix, y_item,
        Align.LEFT, s.line_height,
      )
    old_indent = self._indent_mm
    self._indent_mm = old_indent + s.list_indent
    self.pdf.cursor(self._indent_mm, y_item)
    self._render_tokens(item_tokens)
    self._indent_mm = old_indent
    self.pdf.cursor(self._indent_mm, self.pdf.y)

  def _measure_item_first_para(self, item_tokens:list[Token]) -> float:
    """Height (mm) of the first paragraph in a list item - used as the
    keep-together reservation in `_render_list_item`. Falls back to two
    body lines when the item starts with something other than a paragraph
    (nested list, code block, etc.) since those have their own break logic."""
    s = self.style
    body_line_mm = s.body_size * s.line_height / MM_TO_PT
    for j, t in enumerate(item_tokens):
      if t.type == "paragraph_open" and j + 1 < len(item_tokens):
        inline = item_tokens[j + 1]
        if inline.type == "inline":
          base = RichSegment(
            text="", family=s.body_family, mode=s.body_mode,
            size=s.body_size, color=s.body_color,
          )
          try:
            segs = self._inline_to_segments(inline, base)
            width = self.pdf.content_width - self._indent_mm - s.list_indent
            h = measure_rich(self.pdf, segs, width, line_gap=s.line_height)
            return max(h, body_line_mm)
          except Exception:
            pass
        break
      # Non-paragraph leading content (nested list, fence, etc.) - defer to
      # that block's own keep logic; reserve minimum two lines here.
      if t.type not in ("paragraph_close",):
        break
    return body_line_mm * 2
