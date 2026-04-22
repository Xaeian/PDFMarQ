# pdfmarq/md/md_footnotes.py

"""
Footnote and definition-list rendering.

Footnotes: end-of-document collection with a short horizontal rule, each
entry gets a named PDF bookmark so in-body `[^n]` refs navigate to it.

Definition list: `Term` (bold) above `: definition` (indented).
"""

from markdown_it.token import Token
from ..inline import RichSegment, render_rich
from ..constants import Align, MM_TO_PT

#------------------------------------------------------------------------------- FootnotesMixin

class FootnotesMixin:
  
  def _render_footnote_block(self, tokens:list[Token], start:int) -> int:
    """Render footnote collection at end of document."""
    s = self.style
    end = self._find_close(tokens, start, "footnote_block_open", "footnote_block_close")
    # Separator rule above footnotes section (short, GitHub-style)
    self.pdf.enter(s.para_gap)
    x = self._indent_mm
    w = self.pdf.content_width - x
    self.pdf.cursor(x, self.pdf.y)
    self.pdf.stroke_color(*s.hr_color)
    self.pdf.line(w * 0.3, 0, s.hr_thick)
    self._reset_stroke()
    self.pdf.enter(s.para_gap)
    i = start + 1
    while i < end:
      t = tokens[i]
      if t.type == "footnote_open":
        label = (t.meta or {}).get("label", "?")
        j = i + 1
        inline_token: Token|None = None
        while j < end and tokens[j].type != "footnote_close":
          if tokens[j].type == "inline":
            inline_token = tokens[j]
          j += 1
        base = RichSegment(
          text="", family=s.body_family, mode=s.body_mode,
          size=s.body_size * 0.85, color=s.muted_color,
        )
        prefix = RichSegment(
          text=f"[{label}] ", family=s.body_family, mode=s.bold_mode,
          size=s.body_size * 0.85, color=s.body_color,
        )
        segs: list[RichSegment] = [prefix]
        if inline_token is not None:
          segs.extend(self._inline_to_segments(inline_token, base))
        x = self._indent_mm
        width = self.pdf.content_width - x
        self._ensure_space(s.body_size * 0.85 * s.line_height / MM_TO_PT)
        y = self.pdf.y
        # Named dest → [label] refs in body navigate here
        self.pdf._canvas.bookmarkPage(f"fn_{label}")
        self.pdf.cursor(x, y)
        h = render_rich(self.pdf, segs, width, x, y, Align.LEFT, s.line_height)
        self.pdf.cursor(x, y + h + s.list_gap)
        i = j
      i += 1
    return end + 1

  def _render_deflist(self, tokens:list[Token], start:int) -> int:
    """Render a definition list (`Term\\n: def`) - term bold, def indented."""
    s = self.style
    end = self._find_close(tokens, start, "dl_open", "dl_close")
    i = start + 1
    while i < end:
      t = tokens[i]
      if t.type == "dt_open":
        # Term - bold
        j = i + 1
        inline_token: Token|None = None
        while j < end and tokens[j].type != "dt_close":
          if tokens[j].type == "inline":
            inline_token = tokens[j]
          j += 1
        if inline_token is not None:
          base = RichSegment(
            text="", family=s.body_family, mode=s.bold_mode,
            size=s.body_size, color=s.body_color,
          )
          segs = self._inline_to_segments(inline_token, base)
          x = self._indent_mm
          width = self.pdf.content_width - x
          self._ensure_space(s.body_size * s.line_height / MM_TO_PT)
          y = self.pdf.y
          h = render_rich(
            self.pdf, segs, width, x, y, Align.LEFT, s.line_height,
          )
          self.pdf.cursor(x, y + h + s.list_gap)
        i = j + 1
      elif t.type == "dd_open":
        # Definition - indented; walk to matching dd_close
        j = i + 1
        depth_dd = 1
        while j < end and depth_dd > 0:
          if tokens[j].type == "dd_open": depth_dd += 1
          elif tokens[j].type == "dd_close": depth_dd -= 1
          if depth_dd == 0: break
          j += 1
        old_indent = self._indent_mm
        self._indent_mm = old_indent + s.list_indent
        self.pdf.cursor(self._indent_mm, self.pdf.y)
        self._render_tokens(tokens[i+1:j])
        self._indent_mm = old_indent
        self.pdf.cursor(self._indent_mm, self.pdf.y)
        i = j + 1
      else:
        i += 1
    self.pdf.enter(s.para_gap)
    return end + 1
