# pdfmarq/md/md_blockquote.py

"""
Blockquote rendering with GitHub-style callout support.

Blockquotes are drawn as a left colored bar + indented content. GitHub
callouts (`> [!NOTE]`, `> [!WARNING]`, etc.) override the bar color and
prepend a bold title. Both variants pre-measure content so the entire
blockquote fits on one page if possible.
"""

from markdown_it.token import Token
import re
from ..inline import RichSegment, render_rich, measure_rich
from ..constants import Align, MM_TO_PT

#---------------------------------------------------------------------------------- Callout types

# Per-type metadata that's NOT user-configurable (regex routing + emoji
# icon + style-field name for label). Colors come from
# `MarkdownStyle.callout_colors` (override there for theming).
CALLOUT_TYPES = {
  "NOTE": ("ℹ", "callout_label_note"),
  "TIP": ("💡", "callout_label_tip"),
  "IMPORTANT": ("❗", "callout_label_important"),
  "WARNING": ("⚠", "callout_label_warning"),
  "CAUTION": ("🛑", "callout_label_caution"),
}
_CALLOUT_MARKER_RE = re.compile(rf"^\[!({'|'.join(CALLOUT_TYPES)})\]\s*")

def _callout_palette(style, name:str) -> tuple[tuple, tuple]:
  """Return `(border_rgb, text_rgb)` for callout `name`. Looks up
  `MarkdownStyle.callout_colors` (lowercase key); falls back to NOTE
  blue when the type is missing."""
  default = ((0.035, 0.41, 0.855), (0.035, 0.41, 0.855))
  pal = (style.callout_colors or {}).get(name.lower())
  return pal if pal else default

#------------------------------------------------------------------------------ BlockquoteMixin

class BlockquoteMixin:
  """
  Blockquote rendering plus GitHub-style callouts (`> [!NOTE]`, `> [!TIP]`,
  `> [!IMPORTANT]`, `> [!WARNING]`, `> [!CAUTION]`). Mixed into
  `MarkdownRenderer`.
  """

  def _detect_callout(self, tokens:list[Token], start:int, end:int) -> tuple[str, int]|None:
    """Check if blockquote starts with `[!TYPE]` marker. Returns (type, idx) or None."""
    for j in range(start + 1, end):
      if tokens[j].type == "inline":
        content = tokens[j].content or ""
        m = _CALLOUT_MARKER_RE.match(content)
        if m:
          # Strip prefix in-place so it doesn't render
          marker_len = len(m.group(0))
          tokens[j].content = content[marker_len:]
          if tokens[j].children:
            for c in tokens[j].children:
              if c.type == "text":
                c.content = _CALLOUT_MARKER_RE.sub("", c.content)
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
    content_w_mm = self.pdf.content_width - self._indent_mm - s.quote_pad
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
        total_h += max(h, body_line_mm) + s.list_gap
    callout = self._detect_callout(tokens, start, end)
    if callout:
      total_h += body_line_mm * 1.2  # title line
      total_h += s.body_size * (s.line_height - 1.0) / MM_TO_PT  # title→content gap
    total_h += body_line_mm * 0.5  # padding
    page_avail = self.pdf.content_height
    if total_h <= page_avail * 0.9 and total_h > (page_avail - self.pdf.y):
      self.pdf.new_page()
    x_start = self._indent_mm
    y_start = self.pdf.y
    # Callout overrides bar color + adds a bold title line at top
    if callout:
      bar_color, text_color = _callout_palette(s, callout[0])
      bar_width = s.quote_border_w * 1.5
    else:
      bar_color = s.quote_border[:3]
      text_color = bar_color
      bar_width = s.quote_border_w
    top_offset = s.body_size * 0.25 / MM_TO_PT + 1
    old_indent = self._indent_mm
    self._indent_mm = old_indent + s.quote_pad
    inner_x = self._indent_mm
    inner_w = self.pdf.content_width - inner_x
    if callout:
      _icon, label_field = CALLOUT_TYPES[callout[0]]
      title_text = getattr(s, label_field)
      title_seg = RichSegment(
        text=title_text, family=s.body_family, mode=s.bold_mode,
        size=s.body_size, color=text_color,
      )
      y_title = self.pdf.y
      h_title = render_rich(
        self.pdf, [title_seg], inner_w, inner_x, y_title + top_offset,
        Align.LEFT, s.line_height,
      )
      # Gap matched to body line_height extra space (≈ leading inside a
      # paragraph). `list_gap` is too tight - works for one-line callouts
      # but reads as a glued title against multi-line content.
      title_content_gap = s.body_size * (s.line_height - 1.0) / MM_TO_PT
      self.pdf.cursor(inner_x, y_title + h_title + title_content_gap)
    else:
      self.pdf.cursor(inner_x, y_start + top_offset)
    # Callout is a tightly-bound visual unit (left bar + title bind it as one
    # card). Inside, use list-style spacing so paragraphs/lists/hardbreaks
    # don't read as airy as top-level prose. Faked via `_list_depth` because
    # `_render_paragraph` and `_render_list` already key off it.
    if callout:
      self._list_depth += 1
    self._render_tokens(tokens[start+1:end])
    if callout:
      self._list_depth -= 1
    self._indent_mm = old_indent
    y_after_content = self.pdf.y
    # Last child added either `list_gap` (callout, due to faked `_list_depth`)
    # or `para_gap` (normal blockquote) as trailing spacing. Subtract the
    # right one so the left bar ends flush with the actual last text line.
    trailing = s.list_gap if callout else s.para_gap
    bar_h = max(y_after_content - trailing - y_start, s.body_size / MM_TO_PT)
    self.pdf.cursor(x_start + 1, y_start)
    self.pdf.color(*bar_color)
    self.pdf.rect(bar_width, bar_h)
    self._reset_stroke()
    # Top up trailing for callouts: inside used `list_gap` (tight), but
    # outside flow expects `para_gap` before the next element.
    final_y = y_after_content + (s.para_gap - s.list_gap) if callout else y_after_content
    self.pdf.cursor(x_start, final_y)
    return end + 1
