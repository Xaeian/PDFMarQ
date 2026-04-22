# pdfmarq/md/md_list.py

"""
List rendering - bullet + ordered, with keep-together for top-level lists
and custom bullet glyphs drawn via `canvas.circle`.
"""

from markdown_it.token import Token
from reportlab.lib.colors import Color
from ..inline import RichSegment, render_rich
from ..constants import Align, MM_TO_PT

#------------------------------------------------------------------------------------ ListMixin

class ListMixin:
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
      list_h = n_items * body_line_mm * 1.2 + s.paragraph_spacing
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
      self.pdf.enter(max(0, s.paragraph_spacing - s.list_item_spacing))
    return end + 1

  def _render_list_item(self, prefix:str, item_tokens:list[Token], bullet:bool=False):
    s = self.style
    # Keep-with-next: reserve 2 lines so bullet doesn't orphan
    self._ensure_space(s.body_size * s.line_height / MM_TO_PT * 2)
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
