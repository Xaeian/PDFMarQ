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
from ..utils import smaller_size

#------------------------------------------------------------------------------- FootnotesMixin

class FootnotesMixin:
  """Footnote section rendering and definition lists. Mixed into `MarkdownRenderer`."""

  def _render_footnote_heading(self, label:str):
    """Emit an h2-styled standalone heading above the footnote section."""
    s = self.style
    seg = RichSegment(
      text=label, family=s.head_family, mode=s.head_mode,
      size=s.h2_size, color=s.head_color,
    )
    x = self._indent_mm
    width = self.pdf.content_width - x
    self._ensure_space(s.h2_size / MM_TO_PT * 2)
    self.pdf.enter(s.head_gap_top)
    y = self.pdf.y
    h = render_rich(self.pdf, [seg], width, x, y, Align.LEFT, s.line_height)
    self.pdf.cursor(x, y + h + s.head_gap_bot)

  def _render_footnote_block(self, tokens:list[Token], start:int) -> int:
    """Render footnote collection at end of document.

    When `style.footnote_label` is set, emits a heading above the section
    (e.g. `"References"`, `"Bibliografia"`). When `None`, just draws a thin
    HR - the smaller font signals reference matter on its own.
    """
    s = self.style
    end = self._find_close(tokens, start, "footnote_block_open", "footnote_block_close")
    self.pdf.enter(s.para_gap)
    if s.footnote_label:
      self._render_footnote_heading(s.footnote_label)
    else:
      # Full-width HR separator. Mirrors `docmarq` which calls `doc.hr()` at
      # this point; previously this was 30% width but read as "broken line".
      x = self._indent_mm
      w = self.pdf.content_width - x
      self.pdf.cursor(x, self.pdf.y)
      self.pdf.stroke_color(*s.hr_color)
      self.pdf.line(w, 0, s.hr_thick)
      self._reset_stroke()
      self.pdf.enter(s.para_gap)
    # One step below body on the typographic ladder. Same derivation as
    # `docmarq.md._render_footnote_block` so the bibliography reads at the
    # same relative weight in both formats (e.g. body=11pt → footnote=10pt).
    biblio_pt = smaller_size(s.body_size)
    i = start + 1
    while i < end:
      t = tokens[i]
      if t.type == "footnote_open":
        label = (t.meta or {}).get("label", "?")
        j = i + 1
        inline_token: Token|None = None
        while j < end and tokens[j].type != "footnote_close":
          if tokens[j].type == "inline": inline_token = tokens[j]
          j += 1
        base = RichSegment(
          text="", family=s.body_family, mode=s.body_mode,
          size=biblio_pt, color=s.muted_color,
        )
        prefix = RichSegment(
          text=f"[{label}] ", family=s.body_family, mode=s.bold_mode,
          size=biblio_pt, color=s.body_color,
        )
        segs: list[RichSegment] = [prefix]
        if inline_token is not None:
          segs.extend(self._inline_to_segments(inline_token, base))
        x = self._indent_mm
        width = self.pdf.content_width - x
        self._ensure_space(biblio_pt * s.line_height / MM_TO_PT)
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
          if tokens[j].type == "inline": inline_token = tokens[j]
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
