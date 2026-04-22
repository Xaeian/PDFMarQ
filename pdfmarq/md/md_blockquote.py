# pdfmarq/md/md_blockquote.py

"""
Blockquote rendering with GitHub-style callout support.

Blockquotes are drawn as a left colored bar + indented content. GitHub
callouts (`> [!NOTE]`, `> [!WARNING]`, etc.) override the bar color and
prepend a bold title. Both variants pre-measure content so the entire
blockquote fits on one page if possible.
"""

from markdown_it.token import Token
from ..inline import RichSegment, render_rich, measure_rich
from ..constants import Align, MM_TO_PT

#------------------------------------------------------------------------------ BlockquoteMixin

class BlockquoteMixin:

  # GitHub-style callout types - color + title for each type
  _CALLOUT_STYLES = {
    "NOTE":      {"color": (0.035, 0.368, 0.855), "title": "Note",      "icon": "ℹ"},
    "TIP":       {"color": (0.105, 0.580, 0.250), "title": "Tip",       "icon": "💡"},
    "IMPORTANT": {"color": (0.549, 0.270, 0.780), "title": "Important", "icon": "❗"},
    "WARNING":   {"color": (0.800, 0.545, 0.000), "title": "Warning",   "icon": "⚠"},
    "CAUTION":   {"color": (0.819, 0.192, 0.192), "title": "Caution",   "icon": "🛑"},
  }

  def _detect_callout(self, tokens:list[Token], start:int, end:int) -> tuple[str, int]|None:
    """Check if blockquote starts with `[!TYPE]` marker. Returns (type, idx) or None."""
    import re
    for j in range(start + 1, end):
      if tokens[j].type == "inline":
        content = tokens[j].content or ""
        m = re.match(r"^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*", content)
        if m:
          # Strip prefix in-place so it doesn't render
          marker_len = len(m.group(0))
          tokens[j].content = content[marker_len:]
          if tokens[j].children:
            for c in tokens[j].children:
              if c.type == "text":
                c.content = re.sub(
                  r"^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*", "", c.content
                )
                break
          return m.group(1), j
      if tokens[j].type in ("heading_open", "code_block", "fence"):
        break
    return None

  def _render_blockquote(self, tokens:list[Token], start:int) -> int:
    s = self.style
    end = self._find_close(tokens, start, "blockquote_open", "blockquote_close")
    # Pre-measure so we can `ensure_space` atomically - otherwise the left
    # bar (drawn post-factum) would be split across a page break.
    content_w_mm = self.pdf.content_width - self._indent_mm - s.blockquote_padding
    body_line_mm = s.body_size * s.line_height / MM_TO_PT
    total_h = 0.0
    for j in range(start + 1, end):
      tk = tokens[j]
      if tk.type == "inline":
        base = RichSegment(
          text="", family=s.body_family, mode=s.body_mode,
          size=s.body_size, color=s.body_color,
        )
        try:
          segs = self._inline_to_segments(tk, base)
          h = measure_rich(self.pdf, segs, content_w_mm, line_gap=s.line_height)
        except Exception:
          h = body_line_mm
        total_h += max(h, body_line_mm) + s.list_item_spacing
    callout = self._detect_callout(tokens, start, end)
    if callout:
      total_h += body_line_mm * 1.2  # title line
    total_h += body_line_mm * 0.5  # padding
    page_avail = self.pdf.content_height
    if total_h <= page_avail * 0.9 and total_h > (page_avail - self.pdf.y):
      self.pdf.new_page()
    x_start = self._indent_mm
    y_start = self.pdf.y
    # Callout overrides bar color + adds a bold title line at top
    if callout:
      cfg = self._CALLOUT_STYLES[callout[0]]
      bar_color = cfg["color"]
      bar_width = s.blockquote_border_width * 1.5
    else:
      bar_color = s.blockquote_border[:3]
      bar_width = s.blockquote_border_width
    top_offset = s.body_size * 0.25 / MM_TO_PT + 1
    old_indent = self._indent_mm
    self._indent_mm = old_indent + s.blockquote_padding
    inner_x = self._indent_mm
    inner_w = self.pdf.content_width - inner_x
    if callout:
      title_seg = RichSegment(
        text=cfg["title"], family=s.body_family, mode=s.bold_mode,
        size=s.body_size, color=bar_color,
      )
      y_title = self.pdf.y
      h_title = render_rich(
        self.pdf, [title_seg], inner_w, inner_x, y_title + top_offset,
        Align.LEFT, s.line_height,
      )
      self.pdf.cursor(inner_x, y_title + h_title + s.list_item_spacing)
    else:
      self.pdf.cursor(inner_x, y_start + top_offset)
    self._render_tokens(tokens[start+1:end])
    self._indent_mm = old_indent
    y_after_content = self.pdf.y
    bar_h = max(y_after_content - s.paragraph_spacing - y_start, s.body_size / MM_TO_PT)
    self.pdf.cursor(x_start + 1, y_start)
    self.pdf.color(*bar_color)
    self.pdf.rect(bar_width, bar_h)
    self._reset_stroke()
    self.pdf.cursor(x_start, y_after_content)
    return end + 1
