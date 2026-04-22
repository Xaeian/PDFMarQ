# pdfmarq/md/md_estimate.py

"""
Block height estimation for heading keep-with-next lookahead.

`_estimate_next_block` returns an approximate minimum height (mm) for
whatever block token comes after a heading, so `_render_heading` can
reserve enough space to keep them on the same page.
"""

from markdown_it.token import Token
from ..constants import MM_TO_PT

#-------------------------------------------------------------------------------- EstimateMixin

class EstimateMixin:
  def _estimate_next_block(self, tokens:list[Token], start:int) -> float:
    """Estimate minimum height (mm) of next block - used by heading lookahead."""
    if start >= len(tokens):
      return 0
    s = self.style
    body_line_mm = s.body_size * s.line_height / MM_TO_PT
    t = tokens[start]
    ttype = t.type
    if ttype == "paragraph_open":
      return body_line_mm * 2
    if ttype in ("bullet_list_open", "ordered_list_open"):
      close_type = "bullet_list_close" if "bullet" in ttype else "ordered_list_close"
      end = self._find_close(tokens, start, ttype, close_type)
      n_items = sum(
        1 for j in range(start, end + 1)
        if tokens[j].type == "list_item_open"
      )
      list_h = n_items * body_line_mm * 1.2 + s.paragraph_spacing
      page_avail = self.pdf.content_height
      if list_h <= page_avail * 0.9:
        return list_h
      return body_line_mm * s.line_height * 3
    if ttype == "table_open":
      end = self._find_close(tokens, start, "table_open", "table_close")
      n_rows = sum(1 for j in range(start, end) if tokens[j].type == "tr_open")
      return min(n_rows, 5) * 8
    if ttype in ("fence", "code_block"):
      lang = (t.info or "").strip().split()[0] if t.info else ""
      if lang == "mermaid":
        return 60 # mermaid renders to image - reserve ~60mm
      lines = (t.content or "").count("\n") + 1
      pad = s.code_block_padding * 2
      return min(lines, 6) * (s.code_block_size * s.line_height / MM_TO_PT) + pad
    if ttype == "math_block":
      return s.body_size * 2 / MM_TO_PT
    if ttype == "blockquote_open":
      end = self._find_close(tokens, start, "blockquote_open", "blockquote_close")
      n_inline = sum(
        1 for j in range(start, end + 1) if tokens[j].type == "inline"
      )
      # Each inline ≈ 1 line; add 1 extra for callout title + padding
      return max(body_line_mm * (n_inline + 1) * 1.1, body_line_mm * 3)
    if ttype == "dl_open":
      return body_line_mm * 2
    if ttype == "hr":
      return 3
    return body_line_mm * 2
