# pdfmarq/paper/banner.py

"""
Documentation banner: the page-1 header and the compact header of continuation pages.

Both are drawn from these frontmatter keys, all optional:

  id        Document code in code-style box (e.g. "MD-001")
  title     Main title (centered, large)
  version   Version in code-style box (e.g. "1.2.3")
  author    Author name
  status    Badge label: draft/review/approved/deprecated/archived
  entity    Organization name (left of banner, bold)
  address   Address (right of banner, muted)
  created   ISO date YYYY-MM-DD (formatted via `style.date_format`)
  updated   Same as created
  logo      Path to logo (.svg, .png, .jpg), resolved by the caller
"""
from reportlab.lib.colors import Color
from ..inline import RichSegment, render_rich
from ..graphics import draw_svg, image_aspect
from ..constants import MM_TO_PT, Align
from ..utils import format_date
from .style import UNKNOWN_STATUS

#------------------------------------------------------------------------------------------- Banner

class Banner:
  """
  Banner of one document: drawn once on page 1, compact on every page after it.

  `logo` is the resolved path of an existing file, or `None`.
  """
  def __init__(self, pdf, style, data:dict, logo:str|None):
    self.pdf = pdf
    self.style = style
    self.data = data
    self.logo = logo
    self.aspect = image_aspect(logo) if logo else 1.0 # width over height
    self.created = format_date(data.get("created"), style.date_format)
    self.updated = format_date(data.get("updated"), style.date_format)

  #----------------------------------------------------------------------------------------- Page 1

  def draw(self):
    """
    Draw the full banner at the cursor, on the first page.
    The logo column shrinks while the text needs more width; one or two passes settle it.
    """
    s = self.style
    pdf = self.pdf
    pdf.enter(s.banner_pad_top)
    content_w = pdf.content_width
    logo_path = self.logo
    has_logo = bool(logo_path)
    logo_aspect = self.aspect
    gutter = 4.0 if has_logo else 0
    y_start = pdf.y
    # `logo_h` up to `banner_logo_max_h`, `logo_w = logo_h * aspect` up to `banner_logo_max_w`.
    logo_h = s.banner_logo_max_h if has_logo else 0
    if has_logo:
      logo_h = self._logo_height(content_w, gutter, logo_aspect)
    logo_w = logo_h * logo_aspect
    if has_logo and logo_w > s.banner_logo_max_w:
      logo_w = s.banner_logo_max_w
      logo_h = logo_w / logo_aspect
    right_x = logo_w + gutter
    right_w = content_w - right_x
    # Top rule across the whole content width
    pdf.cursor(0, y_start)
    self._rule(0, content_w)
    pdf.enter(3)
    rule_top_y = y_start
    # Render the text column for real
    pdf.cursor(right_x, pdf.y)
    self._text_column(right_x, right_w)
    pdf.enter(2)
    rule_bot_y = pdf.y
    # Bottom rule across the whole content width
    self._rule(0, content_w)
    if has_logo:
      actual_h = rule_bot_y - rule_top_y
      draw_h = min(logo_h, actual_h) # fit within rule band
      draw_w = draw_h * logo_aspect
      if draw_w > s.banner_logo_max_w:
        draw_w = s.banner_logo_max_w
        draw_h = draw_w / logo_aspect
      logo_y = rule_top_y + (actual_h - draw_h) / 2
      pdf.cursor(0, logo_y)
      if logo_path.lower().endswith(".svg"):
        pdf.svg(logo_path, draw_w, draw_h)
      else:
        pdf.image(logo_path, draw_w, draw_h)
    pdf.cursor(0, rule_bot_y)
    pdf.enter(s.banner_pad_bot)

  def _logo_height(self, content_w:float, gutter:float, aspect:float) -> float:
    """
    The logo height that makes the logo and text column the same height.
    Each iteration measures the text height given the current logo width,
    then sets `logo_h = min(cap, text_h)`.
    Tall logos (aspect < 1) take less width, giving the text more room without losing height.
    """
    s = self.style
    max_h = s.banner_logo_max_h
    max_w = s.banner_logo_max_w
    if aspect > 0 and max_h * aspect > max_w: # wide logos: cap height to keep width in `max_w`
      max_h = max_w / aspect
    logo_h = max_h
    for _ in range(4):
      logo_w = logo_h * aspect
      text_h = self._text_column_height(content_w - logo_w - gutter)
      new_h = min(max_h, text_h) # align logo bottom to text bottom, capped at `max_h`
      if abs(new_h - logo_h) < 0.5:
        logo_h = new_h
        break
      logo_h = new_h
    return logo_h

  def _text_column_height(self, width:float) -> float:
    """Height (mm) `_text_column` takes at `width`, estimated from font metrics, nothing drawn."""
    s = self.style
    data = self.data
    h_mm = 0
    if data.get("entity") or data.get("address"):
      h_mm += s.banner_meta_size / MM_TO_PT * 1.3 + 2 # single row, one line each side
    if data.get("id") or data.get("version") or data.get("status"):
      h_mm += s.banner_id_size / MM_TO_PT * 1.6 + 3
    title = data.get("title")
    if title:
      title_lines = self._estimate_lines(str(title), s.font_head,
        s.head_mode, s.banner_title_size, width)
      h_mm += s.banner_title_size / MM_TO_PT * title_lines * 1.0 + 2
    if data.get("author") or self.created or self.updated:
      h_mm += 1
      meta_lines = int(bool(self.created)) + int(bool(data.get("author") or self.updated))
      h_mm += s.banner_meta_size / MM_TO_PT * 1.3 * max(1, meta_lines)
    return h_mm

  def _estimate_lines(
    self, text:str, family:str, mode:str,
    size_pt:float, width_mm:float,
  ) -> int:
    """Lines `text` wraps to in `width_mm` at the given font and size."""
    pdf = self.pdf
    try:
      font = pdf.fonts.register(family, mode)
    except Exception:
      return 1
    text_w_pt = pdf.c.stringWidth(text, font, size_pt)
    width_pt = width_mm * MM_TO_PT
    if text_w_pt <= width_pt:
      return 1
    return max(1, int(text_w_pt / width_pt) + 1)

  def _text_column(self, x_offset:float, width:float):
    """
    The text of the header between its rules, which the caller draws:
      entity (left) | address (right)
      [status] id (left) | version (right)
      title (centered, big)
      created (right)
      author (left) | updated (right)
    """
    s = self.style
    pdf = self.pdf
    data = self.data
    entity = data.get("entity")
    address = data.get("address")
    if entity or address:
      h = self._entity_row(entity, address, x_offset, width)
      pdf.enter(h + 2)
    doc_id = data.get("id")
    version = data.get("version")
    status = str(data.get("status") or "").strip()
    if doc_id or version or status:
      h = self._id_row(doc_id, version, status, x_offset, width)
      pdf.enter(h + 3)
    title = data.get("title")
    if title:
      h = self._centered(str(title), s.banner_title_size, s.font_head,
        s.head_mode, s.head_color, x_offset, width)
      pdf.enter(h + 2)
    author = data.get("author")
    if author or self.created or self.updated:
      pdf.enter(1)
      self._meta_rows(author, x_offset, width)

  def _entity_row(
    self, entity:str|None, address:str|None,
    x_offset:float, width:float,
  ) -> float:
    """Entity (left, bold) and address (right, muted) on one row. Returns its height (mm)."""
    pdf = self.pdf
    s = self.style
    y = pdf.y
    h = s.banner_meta_size / MM_TO_PT
    if entity:
      segs = [RichSegment(text=str(entity), family=s.font_body, mode=s.bold_mode,
        size=s.banner_meta_size, color=s.body_color)]
      h = max(h, render_rich(pdf, segs, width, x_offset, y, Align.LEFT, 1.3) or h)
    if address:
      segs = [RichSegment(text=str(address), family=s.font_body, mode=s.body_mode,
        size=s.banner_meta_size, color=s.muted_color)]
      h = max(h, render_rich(pdf, segs, width, x_offset, y, Align.RIGHT, 1.3) or h)
    return h

  def _id_row(
    self, doc_id:str|None, version:str|None, status:str|None,
    x_offset:float, width:float,
  ) -> float:
    """
    `[STATUS BADGE]  id  ...  version`, returning the row height (mm).
    `id` and `version` take the inline-code style of the markdown body (mono, light background,
    border), set 0.5mm higher than the badge baseline for visual alignment.
    """
    pdf = self.pdf
    s = self.style
    c = pdf.c
    y = pdf.y
    x_left_pt = (pdf.margin_left + x_offset) * MM_TO_PT
    badge_baseline_y_pt = (pdf.page_height - pdf.margin_top - y - s.banner_id_size
      / MM_TO_PT * 0.7) * MM_TO_PT
    code_baseline_y_pt = badge_baseline_y_pt + 0.5 * MM_TO_PT
    badge_w_pt = 0
    if status:
      badge_w_pt = self._draw_status_badge(c, str(status), x_left_pt, badge_baseline_y_pt)
    if doc_id:
      font = pdf.fonts.register(s.font_mono, s.mono_mode)
      gap = 6 if status else 0
      self._draw_code_inline(c, str(doc_id), font, s.banner_id_size, x_left_pt + badge_w_pt + gap,
        code_baseline_y_pt, anchor="left")
    if version:
      x_right_pt = (pdf.margin_left + x_offset + width) * MM_TO_PT
      font = pdf.fonts.register(s.font_mono, s.mono_mode)
      self._draw_code_inline(c, str(version), font, s.banner_version_size, x_right_pt,
        code_baseline_y_pt, anchor="right")
    return s.banner_id_size / MM_TO_PT * 1.6

  def _centered(
    self, text:str, size_pt:float, family:str, mode:str, color:tuple,
    x_offset:float, width:float,
  ) -> float:
    """Centered text. Returns its height (mm) as drawn."""
    pdf = self.pdf
    segs = [RichSegment(text=text, family=family, mode=mode, size=size_pt, color=color)]
    h = render_rich(pdf, segs, width, x_offset, pdf.y, Align.CENTER, 1.0)
    return h or (size_pt / MM_TO_PT)

  def _meta_rows(self, author:str|None, x_offset:float, width:float):
    """`created` alone at the right, then `author` at the left and `updated` at the right."""
    pdf = self.pdf
    s = self.style
    line_h = s.banner_meta_size / MM_TO_PT * 1.3
    if self.created:
      y = pdf.y
      segs = [RichSegment(text=f"{s.banner_label_created}: {self.created}", family=s.font_body,
        mode=s.body_mode, size=s.banner_meta_size, color=s.muted_color)]
      render_rich(pdf, segs, width, x_offset, y, Align.RIGHT, 1.3)
      pdf.cursor(x_offset, y + line_h)
    if author or self.updated:
      y = pdf.y
      if author:
        segs = [RichSegment(text=f"{s.banner_label_author}: {author}",
          family=s.font_body, mode=s.body_mode,
          size=s.banner_meta_size, color=s.body_color)]
        render_rich(pdf, segs, width, x_offset, y, Align.LEFT, 1.3)
      if self.updated:
        segs = [RichSegment(text=f"{s.banner_label_updated}: {self.updated}", family=s.font_body,
          mode=s.body_mode, size=s.banner_meta_size, color=s.muted_color)]
        render_rich(pdf, segs, width, x_offset, y, Align.RIGHT, 1.3)
      pdf.cursor(x_offset, y + line_h)

  def _rule(self, x_offset:float, width:float):
    """Horizontal rule from `x_offset` (mm from content left) of given `width`."""
    s = self.style
    pdf = self.pdf
    pdf.cursor(x_offset, pdf.y)
    pdf.stroke_color(*s.hr_color[:3])
    pdf.line(width, 0, s.banner_rule)
    pdf.cursor(0, pdf.y)

  #----------------------------------------------------------------------------- Continuation pages

  def draw_compact(self):
    """
    Compact 2-line header on continuation pages, without the status badge:
      | Logo  | id    | version |
      |       | title | updated |
    The logo top sits 1mm above `banner_compact_top`, its bottom 1mm clear of the separator.
    """
    s = self.style
    pdf = self.pdf
    data = self.data
    doc_id = data.get("id") or ""
    title = data.get("title") or ""
    logo_path = self.logo
    version = data.get("version")
    c = pdf.c
    y_top_mm = s.banner_compact_top
    line_h_pt = s.banner_compact_size * 1.25
    line1_y_pt = (pdf.page_height - y_top_mm - s.banner_compact_size / MM_TO_PT * 0.7) * MM_TO_PT
    line2_y_pt = line1_y_pt - line_h_pt
    x_left_pt = pdf.margin_left * MM_TO_PT
    x_right_pt = (pdf.page_width - pdf.margin_right) * MM_TO_PT
    sep_y_pt = line2_y_pt - 4
    # ---- LEFT: logo + (id top, title bottom) ----
    cursor_x = x_left_pt
    if logo_path:
      logo_top_pt = (pdf.page_height - y_top_mm + 1.0) * MM_TO_PT
      avail_pt = logo_top_pt - sep_y_pt
      max_size_pt = s.banner_compact_logo_max_h * MM_TO_PT
      logo_h_pt = min(max_size_pt, avail_pt) - 1.0 * MM_TO_PT
      # Tall logos (aspect < 1) take less horizontal space, leaving more room for id/title.
      aspect = self.aspect
      logo_w_pt = logo_h_pt * aspect
      max_w_pt = s.banner_compact_logo_max_w * MM_TO_PT
      if logo_w_pt > max_w_pt and aspect > 0:
        logo_w_pt = max_w_pt
        logo_h_pt = logo_w_pt / aspect
      img_y_pt = logo_top_pt - logo_h_pt
      if logo_path.lower().endswith(".svg"):
        draw_svg(c, logo_path, cursor_x, img_y_pt, logo_w_pt, logo_h_pt)
      else:
        c.drawImage(logo_path, cursor_x, img_y_pt, width=logo_w_pt, height=logo_h_pt,
          mask="auto", preserveAspectRatio=True)
      cursor_x += logo_w_pt + 4
    text_x = cursor_x
    if doc_id: # top line - mono on light-grey rounded background
      try:
        font = pdf.fonts.register(s.font_mono, s.mono_mode)
        self._draw_code_inline(c, str(doc_id), font, s.banner_compact_size,
          text_x, line1_y_pt, anchor="left")
      except Exception:
        pass
    if title: # bottom line, ellipsis-trimmed
      try:
        font = pdf.fonts.register(s.font_body, s.bold_mode)
        avail_pt = (x_right_pt - text_x) * 0.55 # leave room for right zone
        shown = self._fit_text(c, str(title), font, s.banner_compact_size, avail_pt)
        c.setFont(font, s.banner_compact_size)
        c.setFillColor(Color(*s.body_color[:3]))
        c.drawString(text_x, line2_y_pt, shown)
      except Exception:
        pass
    # ---- RIGHT: version (top), date (bottom) ----
    if version:
      try:
        font = pdf.fonts.register(s.font_mono, s.mono_mode)
        self._draw_code_inline(c, str(version), font, s.banner_compact_size,
          x_right_pt, line1_y_pt, anchor="right")
      except Exception:
        pass
    if self.updated:
      try:
        font = pdf.fonts.register(s.font_body, s.body_mode)
        c.setFont(font, s.banner_compact_size)
        c.setFillColor(Color(*s.muted_color[:3]))
        c.drawRightString(x_right_pt, line2_y_pt, self.updated)
      except Exception:
        pass
    # Separator below the 2 lines
    c.setStrokeColor(Color(*s.hr_color[:3]))
    c.setLineWidth(0.3)
    c.setDash() # reset any dash from prior canvas state
    c.line(x_left_pt, sep_y_pt, x_right_pt, sep_y_pt)

  def _draw_code_inline(
    self, c, text:str, font:str, size:float,
    x_pt:float, baseline_y_pt:float,
    anchor:str = "left",
  ):
    """
    Draw text in inline-code style: rounded light-grey background,
    `code_inline_color` foreground, mono font. Anchor is `"left"` or `"right"`.
    """
    s = self.style
    text_w = c.stringWidth(text, font, size)
    pad_x = 2
    pad_y = 1.2
    bg_h = size + pad_y * 2
    bg_w = text_w + pad_x * 2
    if anchor == "right":
      bg_x = x_pt - bg_w
      text_x_pt = x_pt - pad_x - text_w
    else:
      bg_x = x_pt
      text_x_pt = x_pt + pad_x
    bg_y = baseline_y_pt - pad_y - 1
    c.setFillColor(Color(*s.code_inline_bg[:3]))
    c.setStrokeColor(Color(*s.code_block_border[:3]))
    c.setLineWidth(0.3)
    c.roundRect(bg_x, bg_y, bg_w, bg_h, 1.5, fill=1, stroke=1)
    c.setFillColor(Color(*s.code_inline_color[:3]))
    c.setFont(font, size)
    c.drawString(text_x_pt, baseline_y_pt, text)

  @staticmethod
  def _fit_text(c, text:str, font:str, size:float, max_w:float) -> str:
    """Return text trimmed with ellipsis to fit within `max_w` pt."""
    if c.stringWidth(text, font, size) <= max_w:
      return text
    ellipsis = "..."
    ell_w = c.stringWidth(ellipsis, font, size)
    if ell_w >= max_w:
      return ""
    # Binary search for fitting prefix
    lo, hi = 0, len(text)
    while lo < hi:
      mid = (lo + hi + 1) // 2
      if c.stringWidth(text[:mid], font, size) + ell_w <= max_w:
        lo = mid
      else:
        hi = mid - 1
    return text[:lo].rstrip() + ellipsis

  def _draw_status_badge(self, c, status:str, x_pt:float, y_pt:float) -> float:
    """
    A small colored badge with the status text, its left edge at `x_pt`.
    `status` is lowercased to look up `style.banner_status_colors`.
    Returns the badge width in pt.
    """
    s = self.style
    palette = s.banner_status_colors
    bg, fg = palette.get(status.lower(), UNKNOWN_STATUS)
    font = self.pdf.fonts.register(s.font_body, s.bold_mode)
    label = status.upper()
    pad_x = 4
    pad_y = 2
    text_w = c.stringWidth(label, font, s.banner_compact_size - 1)
    badge_w = text_w + pad_x * 2
    badge_h = s.banner_compact_size + pad_y * 2 - 1
    by = y_pt - pad_y + 0.2 * MM_TO_PT # raised 0.2mm for visual baseline alignment
    c.setFillColor(Color(*bg))
    c.setStrokeColor(Color(*bg))
    c.roundRect(x_pt, by, badge_w, badge_h, badge_h * 0.3, fill=1, stroke=0)
    c.setFillColor(Color(*fg))
    c.setFont(font, s.banner_compact_size - 1)
    # Vertical centre: `baseline = by + (badge_h - cap_height) / 2`, `cap_height ≈ 0.7 * size`.
    text_size = s.banner_compact_size - 1
    text_y = by + (badge_h - text_size * 0.7) / 2
    c.drawString(x_pt + pad_x, text_y, label)
    return badge_w
