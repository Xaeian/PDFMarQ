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
  """
  Block height estimation used by the heading-lookahead page-break logic
  to avoid widowed headings. Mixed into `MarkdownRenderer`.
  """

  def _estimate_next_block(self, tokens:list[Token], start:int) -> float:
    """Estimate minimum height (mm) of next block - used by heading lookahead."""
    if start >= len(tokens):
      return 0
    s = self.style
    body_line_mm = s.body_size * s.line_height / MM_TO_PT
    t = tokens[start]
    ttype = t.type
    if ttype == "paragraph_open":
      # Measure actual wrapped height - `body_line_mm * 2` was a flat lower
      # bound that under-reserved for long paragraphs and pushed headings
      # apart from their following content.
      if start + 1 < len(tokens) and tokens[start+1].type == "inline":
        from ..inline import RichSegment, measure_rich
        inline = tokens[start+1]
        base = RichSegment(
          text="", family=s.body_family, mode=s.body_mode,
          size=s.body_size, color=s.body_color,
        )
        try:
          segs = self._inline_to_segments(inline, base)
          width = self.pdf.content_width - self._indent_mm
          page_avail = self.pdf.content_height
          h = measure_rich(self.pdf, segs, width, line_gap=s.line_height)
          # Cap at 90% page so an oversized paragraph doesn't force a break
          # for the heading when it would split anyway.
          return max(min(h, page_avail * 0.9), body_line_mm * 2)
        except Exception:
          pass
      return body_line_mm * 2
    if ttype in ("bullet_list_open", "ordered_list_open"):
      close_type = "bullet_list_close" if "bullet" in ttype else "ordered_list_close"
      end = self._find_close(tokens, start, ttype, close_type)
      list_h = self._estimate_list_height(tokens, start, end)
      page_avail = self.pdf.content_height
      # Cap at 90% page so a giant list doesn't force a page break for the
      # heading when it would just split anyway.
      if list_h <= page_avail * 0.9:
        return list_h
      return body_line_mm * s.line_height * 3
    if ttype == "table_open":
      end = self._find_close(tokens, start, "table_open", "table_close")
      n_rows = sum(1 for j in range(start, end) if tokens[j].type == "tr_open")
      return min(n_rows, 5) * 8
    if ttype in ("fence", "code_block"):
      lang = (t.info or "").strip().split()[0] if t.info else ""
      if lang == "mermaid": return 60 # mermaid renders to image - reserve ~60mm
      lines = (t.content or "").count("\n") + 1
      pad = s.code_block_pad * 2
      return min(lines, 6) * (s.code_block_size * s.line_height / MM_TO_PT) + pad
    if ttype == "math_block": return s.body_size * 2 / MM_TO_PT
    if ttype == "blockquote_open":
      end = self._find_close(tokens, start, "blockquote_open", "blockquote_close")
      n_inline = sum(
        1 for j in range(start, end + 1) if tokens[j].type == "inline"
      )
      # Each inline ≈ 1 line; add 1 extra for callout title + padding
      return max(body_line_mm * (n_inline + 1) * 1.1, body_line_mm * 3)
    if ttype == "dl_open": return body_line_mm * 2
    if ttype == "hr": return 3
    return body_line_mm * 2

  def _estimate_list_height(self, tokens:list[Token], start:int, end:int) -> float:
    """Sum estimated height of each list item - used for heading lookahead.
    Each item's first paragraph is measured by `measure_rich`; nested blocks
    fall back to a flat 2-line approximation. Used only for break planning,
    not for actual layout."""
    from ..inline import RichSegment, measure_rich
    s = self.style
    body_line_mm = s.body_size * s.line_height / MM_TO_PT
    width = self.pdf.content_width - self._indent_mm - s.list_indent
    base = RichSegment(
      text="", family=s.body_family, mode=s.body_mode,
      size=s.body_size, color=s.body_color,
    )
    total = 0.0
    j = start + 1
    while j < end:
      if tokens[j].type == "list_item_open":
        # First inline inside this item drives the estimate
        item_h = body_line_mm
        for k in range(j + 1, min(j + 6, end)):
          if tokens[k].type == "inline":
            try:
              segs = self._inline_to_segments(tokens[k], base)
              item_h = max(measure_rich(self.pdf, segs, width, line_gap=s.line_height), body_line_mm)
            except Exception:
              pass
            break
          if tokens[k].type == "list_item_close": break
        total += item_h + s.list_gap
      j += 1
    return total + s.para_gap
