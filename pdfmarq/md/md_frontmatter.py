# pdfmarq/md/md_frontmatter.py

"""YAML frontmatter parsing and document banner rendering.

Detects ``---\\n...\\n---`` block at the top of markdown text, parses with
PyYAML, and renders:

- Full document banner on page 1 (logo + entity/address/title/dates/status)
- Compact mini-banner on continuation pages (when configured)
- Optional signature block at the end (``sign: true``)

Supported YAML keys (all optional):
  id        Document code in code-style box (e.g. "MD-001")
  title     Main title (centered, large)
  version   Version in code-style box (e.g. "1.2.3")
  author    Author name
  status    Badge label: draft/review/approved/deprecated/archived
  entity    Organization name (left of banner, bold)
  address   Address (right of banner, muted)
  created   ISO date YYYY-MM-DD (formatted via style.date_format)
  updated   Same as created
  sign      True adds a dashed signature line + label at end
  landscape True flips page to landscape orientation (consumed by md_to_pdf)
  logo      Path to logo (.svg, .png, .jpg) - resolved from markdown file dir
  subject   Not rendered, written to PDF metadata `/Subject`.
  keywords  Not rendered, written to PDF metadata `/Keywords`. String or list.

Aliases: `code` -> `id`, `company` -> `entity` (legacy compatibility).
"""
import os, re
from datetime import date, datetime
from reportlab.lib.colors import Color
from reportlab.graphics import renderPDF
from svglib.svglib import svg2rlg
from ..inline import RichSegment, render_rich
from ..constants import MM_TO_PT, Align

#------------------------------------------------------------------------------------ Constants

_FM_RE = re.compile(r"\A---\s*\n(.*?\n)---\s*(?:\n|$)", re.DOTALL)

#---------------------------------------------------------------------------------- Public util

def peek_frontmatter(md_text:str) -> dict|None:
  """Lightweight YAML frontmatter parse without markdown rendering.
  Returns the parsed dict or None if no frontmatter / parse failure.
  Used by `md_to_pdf` to read page-setup fields (e.g. `landscape`) before
  instantiating the `PDF` object.
  """
  m = _FM_RE.match(md_text)
  if not m: return None
  try:
    import yaml
    data = yaml.safe_load(m.group(1))
    return data if isinstance(data, dict) else None
  except Exception:
    return None

#----------------------------------------------------------------------------- FrontmatterMixin

class FrontmatterMixin:
  """
  YAML frontmatter banner rendering and metadata extraction
  (title / author / dates / status badges). Mixed into `MarkdownRenderer`.
  """

  def _extract_frontmatter(self, md_text:str) -> tuple[dict|None, str]:
    """Strip YAML frontmatter from `md_text` and return (data, remainder).
    Returns `(None, md_text)` if no frontmatter or YAML parsing fails.
    """
    m = _FM_RE.match(md_text)
    if not m:
      return None, md_text
    block = m.group(1)
    try:
      import yaml
      data = yaml.safe_load(block)
    except ImportError:
      from .._warn import warn_missing
      warn_missing("yaml", "PyYAML", "YAML frontmatter")
      return None, md_text[m.end():]
    except Exception:
      return None, md_text[m.end():]
    if not isinstance(data, dict):
      return None, md_text[m.end():]
    return data, md_text[m.end():]

  def _format_date(self, value) -> str:
    """Format a date value (str, date, datetime) using `style.date_format`."""
    if value is None:
      return ""
    fmt = self.style.date_format
    if isinstance(value, (date, datetime)):
      return value.strftime(fmt)
    if isinstance(value, str):
      try:
        d = datetime.strptime(value, "%Y-%m-%d").date()
        return d.strftime(fmt)
      except ValueError:
        return value
    return str(value)

  #------------------------------------------------------------------------------------- Header
  
  def _render_frontmatter_header(self, data:dict):
  
    """Render the full document header on the current (first) page.
    Iteratively shrinks the logo column when the text column is shorter
    than `banner_logo_max_h`, giving the text more horizontal space.
    Convergence is fast (1-2 passes for typical content).
    """
    s = self.style
    pdf = self.pdf
    pdf.enter(s.banner_pad_top)
    self._frontmatter_data = data
    content_w = pdf.content_width
    logo_path = data.get("logo")
    if logo_path and not os.path.isfile(logo_path):
      raise FileNotFoundError(
        f"frontmatter `logo: {logo_path}` not found. "
        f"Use a path relative to the markdown file (e.g. `./logo.svg`) "
        f"or an absolute path that exists. cwd={os.getcwd()}"
      )
    has_logo = bool(logo_path)
    # Logo aspect ratio (w/h). 1.0 = square, <1.0 = tall, >1.0 = wide.
    logo_aspect = self._get_logo_aspect(logo_path) if has_logo else 1.0
    gutter = 4.0 if has_logo else 0
    y_start = pdf.y
    # ---- Measure optimal logo box ----
    # logo_h capped at banner_logo_max_h, then logo_w = logo_h * aspect
    # capped at banner_logo_max_w (wide logos scale height down proportionally).
    logo_h = s.banner_logo_max_h if has_logo else 0
    if has_logo:
      logo_h = self._measure_optimal_logo_height(data, content_w, gutter, y_start, logo_aspect)
    logo_w = logo_h * logo_aspect
    if has_logo and logo_w > s.banner_logo_max_w:
      logo_w = s.banner_logo_max_w
      logo_h = logo_w / logo_aspect
    right_x = logo_w + gutter
    right_w = content_w - right_x
    # Top rule across the whole content width
    pdf.cursor(0, y_start)
    self._fm_rule_at(0, content_w)
    pdf.enter(3)
    rule_top_y = y_start
    # Render the text column for real
    pdf.cursor(right_x, pdf.y)
    self._fm_render_text_column(data, right_x, right_w)
    pdf.enter(2)
    rule_bot_y = pdf.y
    # Bottom rule across the whole content width
    self._fm_rule_at(0, content_w)
    if has_logo:
      actual_h = rule_bot_y - rule_top_y
      # Use aspect-correct dimensions, capped by available height AND max_width
      draw_h = min(logo_h, actual_h)
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

  def _get_logo_aspect(self, path:str) -> float:
    """Return width/height ratio of a logo file. 1.0 = square, <1 = tall.
    SVG: parsed from viewBox/dimensions via svglib.
    Raster: read with PIL.
    Falls back to 1.0 (square) if anything fails. Cached per-renderer.
    """
    if not hasattr(self, "_aspect_cache"):
      self._aspect_cache = {}
    if path in self._aspect_cache:
      return self._aspect_cache[path]
    aspect = 1.0
    try:
      if path.lower().endswith(".svg"):
        d = svg2rlg(path)
        if d and d.height:
          aspect = d.width / d.height
      else:
        from PIL import Image
        with Image.open(path) as im:
          if im.height:
            aspect = im.width / im.height
    except Exception:
      pass
    self._aspect_cache[path] = aspect
    return aspect

  def _measure_optimal_logo_height(self, data:dict, content_w:float,
    gutter:float, y_start:float, aspect:float) -> float:
    """Find optimal logo HEIGHT iteratively. Logo width = height * aspect.
    Text column gets `right_w = content_w - logo_w - gutter`. Each iteration
    measures text height with current logo_w; new logo_h = min(cap, text_h).
    For tall logos (aspect < 1) the logo width is naturally smaller, so text
    column gets more space without sacrificing logo height.
    """
    s = self.style
    pdf = self.pdf
    max_h = s.banner_logo_max_h
    max_w = s.banner_logo_max_w
    # Cap height so width never exceeds max_w (wide logos land here).
    if aspect > 0 and max_h * aspect > max_w:
      max_h = max_w / aspect
    logo_h = max_h
    for _ in range(4):
      logo_w = logo_h * aspect
      right_w = content_w - logo_w - gutter
      text_h = self._dry_measure_text_column(data, logo_w + gutter, right_w, y_start)
      # Logo height should match text height (so they align between rules),
      # but capped at max_h. Width follows aspect.
      new_h = min(max_h, text_h)
      if abs(new_h - logo_h) < 0.5:
        logo_h = new_h
        break
      logo_h = new_h
    return logo_h

  def _dry_measure_text_column(self, data:dict, x_offset:float, width:float,
    y_start:float) -> float:
    """Estimate text column height analytically without any drawing.
    Mirrors the structure in `_fm_render_text_column` but only computes
    `pdf.enter()` advances based on font metrics and word-wrap.
    """
    s = self.style
    pdf = self.pdf
    h_mm = 0
    entity = data.get("entity") or data.get("company")
    address = data.get("address")
    if entity or address:
      # entity + address single row, max 1 line each side
      h_mm += s.banner_meta_size / MM_TO_PT * 1.3 + 2
    doc_id = data.get("id") or data.get("code")
    version = data.get("version")
    status = data.get("status")
    if doc_id or version or status:
      h_mm += s.banner_id_size / MM_TO_PT * 1.6 + 3
    title = data.get("title")
    if title:
      # estimate title line wrap by string width vs available width
      title_lines = self._estimate_lines(str(title), s.head_family,
        s.head_mode, s.banner_title_size, width)
      h_mm += s.banner_title_size / MM_TO_PT * title_lines * 1.0 + 2
    author = data.get("author")
    created = self._format_date(data.get("created"))
    updated = self._format_date(data.get("updated"))
    if author or created or updated:
      h_mm += 1
      meta_lines = int(bool(created)) + int(bool(author or updated))
      h_mm += s.banner_meta_size / MM_TO_PT * 1.3 * max(1, meta_lines)
    return h_mm

  def _estimate_lines(self, text:str, family:str, mode:str,
    size_pt:float, width_mm:float) -> int:
    """Estimate how many lines `text` will wrap to in `width_mm` at the given
    font/size. Uses canvas.stringWidth for accurate measurement.
    """
    pdf = self.pdf
    try:
      font = pdf._fonts.register(family, mode)
    except Exception:
      return 1
    text_w_pt = pdf._canvas.stringWidth(text, font, size_pt)
    width_pt = width_mm * MM_TO_PT
    if text_w_pt <= width_pt:
      return 1
    return max(1, int(text_w_pt / width_pt) + 1)

  def _fm_render_text_column(self, data:dict, x_offset:float, width:float):
    """Render the text content of the header (no rules - drawn by caller).
    Layout:
      Row 1: entity (left) | address (right)
      Row 2: [status] id (left) | v<version> (right)
      Row 3: title (centered, big)
      Row 4: author (left) | created/updated dates (right)
    """
    s = self.style
    pdf = self.pdf
    entity = data.get("entity") or data.get("company")
    address = data.get("address")
    if entity or address:
      h = self._fm_entity_address_row(entity, address, x_offset, width)
      pdf.enter(h + 2)
    doc_id = data.get("id") or data.get("code")
    version = data.get("version")
    status = data.get("status")
    if doc_id or version or status:
      h = self._fm_id_version_row(doc_id, version, status, x_offset, width)
      pdf.enter(h + 3)
    title = data.get("title")
    if title:
      h = self._fm_centered_text(str(title), s.banner_title_size, s.head_family,
        s.head_mode, s.head_color, x_offset, width)
      pdf.enter(h + 2)
    author = data.get("author")
    created = self._format_date(data.get("created"))
    updated = self._format_date(data.get("updated"))
    if author or created or updated:
      pdf.enter(1)
      self._fm_meta_row(author, created, updated, x_offset, width)

  def _fm_entity_address_row(self, entity:str|None, address:str|None,
      x_offset:float, width:float) -> float:
    """Single-row layout: entity (left, bold) + address (right, muted).
    Returns max actual height in mm.
    """
    pdf = self.pdf
    s = self.style
    y = pdf.y
    h = s.banner_meta_size / MM_TO_PT
    if entity:
      segs = [RichSegment(text=str(entity), family=s.body_family, mode=s.bold_mode,
        size=s.banner_meta_size, color=s.body_color)]
      h = max(h, render_rich(pdf, segs, width, x_offset, y, Align.LEFT, 1.3) or h)
    if address:
      segs = [RichSegment(text=str(address), family=s.body_family, mode=s.body_mode,
        size=s.banner_meta_size, color=s.muted_color)]
      h = max(h, render_rich(pdf, segs, width, x_offset, y, Align.RIGHT, 1.3) or h)
    return h

  def _fm_id_version_row(self, doc_id:str|None, version:str|None, status:str|None,
      x_offset:float, width:float) -> float:
    """Render: [STATUS BADGE]  id  ...  version
    `id` and `version` use the inline-code style (mono on light bg with border),
    matching how `<code>` is rendered in markdown body. They sit 1.2mm higher
    than the badge baseline for visual alignment.
    Returns: row height in mm.
    """
    pdf = self.pdf
    s = self.style
    c = pdf._canvas
    y = pdf.y
    x_left_pt = (pdf._page.margin_lr + x_offset) * MM_TO_PT
    badge_baseline_y_pt = (pdf._page.height - pdf._page.margin_top - y - s.banner_id_size
      / MM_TO_PT * 0.7) * MM_TO_PT
    code_baseline_y_pt = badge_baseline_y_pt + 0.5 * MM_TO_PT
    badge_w_pt = 0
    if status:
      badge_w_pt = self._draw_status_badge(
        c, str(status), x_left_pt, badge_baseline_y_pt, anchor="left",
      )
    if doc_id:
      font = pdf._fonts.register(s.mono_family, s.mono_mode)
      gap = 6 if status else 0
      self._draw_code_inline(c, str(doc_id), font, s.banner_id_size, x_left_pt + badge_w_pt + gap,
        code_baseline_y_pt, anchor="left")
    if version:
      x_right_pt = (pdf._page.margin_lr + x_offset + width) * MM_TO_PT
      font = pdf._fonts.register(s.mono_family, s.mono_mode)
      self._draw_code_inline(c, str(version), font, s.banner_version_size, x_right_pt,
        code_baseline_y_pt, anchor="right")
    return s.banner_id_size / MM_TO_PT * 1.6

  def _fm_centered_text(self, text:str, size_pt:float, family:str, mode:str, color:tuple,
    x_offset:float, width:float) -> float:
    """Centered text. Returns actual rendered height in mm."""
    pdf = self.pdf
    segs = [RichSegment(text=text, family=family, mode=mode, size=size_pt, color=color)]
    h = render_rich(pdf, segs, width, x_offset, pdf.y, Align.CENTER, 1.0)
    return h or (size_pt / MM_TO_PT)

  def _fm_meta_row(self, author:str|None, created:str, updated:str,
      x_offset:float, width:float) -> float:
    """Two-row meta block:
      Row 1: (right) Utworzono: <created>
      Row 2: (left) Autor: <author> (right) Zaktualizowano: <updated>
    Returns total height in mm.
    """
    pdf = self.pdf
    s = self.style
    line_h = s.banner_meta_size / MM_TO_PT * 1.3
    h_total = 0
    # Row 1: created (right-aligned, by itself)
    if created:
      y = pdf.y
      segs = [RichSegment(text=f"{s.banner_label_created}: {created}", family=s.body_family,
        mode=s.body_mode, size=s.banner_meta_size, color=s.muted_color)]
      render_rich(pdf, segs, width, x_offset, y, Align.RIGHT, 1.3)
      pdf.cursor(x_offset, y + line_h)
      h_total += line_h
    # Row 2: author (left) + updated (right)
    if author or updated:
      y = pdf.y
      if author:
        segs = [RichSegment(text=f"{s.banner_label_author}: {author}", family=s.body_family, mode=s.body_mode,
          size=s.banner_meta_size, color=s.body_color)]
        render_rich(pdf, segs, width, x_offset, y, Align.LEFT, 1.3)
      if updated:
        segs = [RichSegment(text=f"{s.banner_label_updated}: {updated}", family=s.body_family,
          mode=s.body_mode, size=s.banner_meta_size, color=s.muted_color)]
        render_rich(pdf, segs, width, x_offset, y, Align.RIGHT, 1.3)
      pdf.cursor(x_offset, y + line_h)
      h_total += line_h
    return max(h_total, line_h)

  def _fm_rule_at(self, x_offset:float, width:float):
    """Horizontal rule from `x_offset` (mm from content left) of given `width`."""
    s = self.style
    pdf = self.pdf
    pdf.cursor(x_offset, pdf.y)
    pdf.stroke_color(*s.hr_color[:3])
    pdf.line(width, 0, s.banner_rule)
    pdf.cursor(0, pdf.y)

  #-------------------------------------------------------------------------- Page chrome
  
  def _render_page_chrome(self, pdf, page_num:int):
  
    """Per-page callback. Mini-header on pages 2+ only.
    Page number is drawn via `_render_page_number` registered as on_final_page
    (deferred) so it can include the total page count.
    """
    s = self.style
    if page_num > 1 and s.mini_banner_render and self._frontmatter_data:
      self._render_mini_header(pdf)

  def _offset_body_for_mini_header(self, pdf, page_num:int):
    """on_new_page hook. Advances the cursor on pages 2+ so body content
    starts below the mini-header with a comfortable gap.
    """
    s = self.style
    if page_num > 1 and s.mini_banner_render and self._frontmatter_data:
      pdf.enter(s.mini_banner_gap)

  def _render_mini_header(self, pdf):
    """Compact 2-line header on continuation pages.
    Layout (3 zones, no status badge):
      | Logo  | id    | version |
      |       | title | <date>  |
    Logo is sized to fit between the top edge and the separator line,
    raised 0.1mm above the top text baseline so it never overflows below.
    """
    s = self.style
    data = self._frontmatter_data
    doc_id = data.get("id") or data.get("code") or ""
    title = data.get("title") or ""
    logo_path = data.get("logo")
    version = data.get("version")
    updated = self._format_date(data.get("updated"))
    c = pdf._canvas
    y_top_mm = s.mini_banner_top
    line_h_pt = s.mini_banner_size * 1.25
    line1_y_pt = (pdf._page.height - y_top_mm - s.mini_banner_size / MM_TO_PT * 0.7) * MM_TO_PT
    line2_y_pt = line1_y_pt - line_h_pt
    x_left_pt = pdf._page.margin_lr * MM_TO_PT
    x_right_pt = (pdf._page.width - pdf._page.margin_lr) * MM_TO_PT
    sep_y_pt = line2_y_pt - 4
    # ---- LEFT: logo + (id top, title bottom) ----
    cursor_x = x_left_pt
    if logo_path:
      # Logo top is 1.5mm above the line1 ascent, bottom never crosses sep,
      # final size shrunk by 1mm (0.5mm top + 0.5mm bottom) for breathing room
      logo_top_pt = (pdf._page.height - y_top_mm + 1.0) * MM_TO_PT
      avail_pt = logo_top_pt - sep_y_pt
      max_size_pt = s.mini_banner_logo_max_h * MM_TO_PT
      logo_h_pt = min(max_size_pt, avail_pt) - 1.0 * MM_TO_PT
      # Width follows aspect: tall logos take less horizontal space, leaving
      # more room for id/title text to start closer to the left edge.
      aspect = self._get_logo_aspect(logo_path)
      logo_w_pt = logo_h_pt * aspect
      max_w_pt = s.mini_banner_logo_max_w * MM_TO_PT
      if logo_w_pt > max_w_pt and aspect > 0:
        logo_w_pt = max_w_pt
        logo_h_pt = logo_w_pt / aspect
      img_y_pt = logo_top_pt - logo_h_pt
      if logo_path.lower().endswith(".svg"):
        self._draw_svg_at_pt(c, logo_path, cursor_x, img_y_pt, logo_w_pt, logo_h_pt)
      else:
        c.drawImage(logo_path, cursor_x, img_y_pt, width=logo_w_pt, height=logo_h_pt,
          mask="auto", preserveAspectRatio=True)
      cursor_x += logo_w_pt + 4
    text_x = cursor_x
    # id (top line) - code style: mono on light-grey rounded background
    if doc_id:
      try:
        font = pdf._fonts.register(s.mono_family, s.mono_mode)
        self._draw_code_inline(c, str(doc_id), font, s.mini_banner_size,
          text_x, line1_y_pt, anchor="left")
      except Exception:
        pass
    # title (bottom line, trimmed)
    if title:
      try:
        font = pdf._fonts.register(s.body_family, s.bold_mode)
        # Allow title to use up to right zone start minus a gap
        avail_pt = (x_right_pt - text_x) * 0.55
        shown = self._fit_text(c, str(title), font, s.mini_banner_size, avail_pt)
        c.setFont(font, s.mini_banner_size)
        c.setFillColor(Color(*s.body_color[:3]))
        c.drawString(text_x, line2_y_pt, shown)
      except Exception:
        pass
    # ---- RIGHT: version (top), date (bottom) ----
    if version:
      try:
        font = pdf._fonts.register(s.mono_family, s.mono_mode)
        self._draw_code_inline(c, str(version), font, s.mini_banner_size,
          x_right_pt, line1_y_pt, anchor="right")
      except Exception:
        pass
    if updated:
      try:
        font = pdf._fonts.register(s.body_family, s.body_mode)
        c.setFont(font, s.mini_banner_size)
        c.setFillColor(Color(*s.muted_color[:3]))
        c.drawRightString(x_right_pt, line2_y_pt, updated)
      except Exception:
        pass
    # Separator below the 2 lines (computed earlier so logo can be sized to fit)
    c.setStrokeColor(Color(*s.hr_color[:3]))
    c.setLineWidth(0.3)
    c.setDash() # ensure solid line - prior canvas state may have dash set
    c.line(x_left_pt, sep_y_pt, x_right_pt, sep_y_pt)

  @staticmethod
  def _draw_svg_at_pt(c, path:str, x_pt:float, y_pt:float, w_pt:float, h_pt:float):
    """Render SVG file onto canvas at canvas-pt coordinates (bottom-left origin).
    Uses the same approach as `pdf.svg()` - no centering, just scale-to-fit.
    """
    drawing = svg2rlg(path)
    if drawing is None:
      raise ValueError(f"could not load SVG: {path}")
    scale_x = w_pt / drawing.width
    scale_y = h_pt / drawing.height
    scale = min(scale_x, scale_y)
    drawing.scale(scale, scale)
    renderPDF.draw(drawing, c, x_pt, y_pt)

  def _draw_code_inline(self, c, text:str, font:str, size:float,
    x_pt:float, baseline_y_pt:float, anchor:str="left"):
    """Draw text in inline-code style: rounded light-grey background,
    code_inline_color foreground, mono font. Anchor is `"left"` or `"right"`.
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

  def _draw_status_badge(self, c, status:str, x_pt:float, y_pt:float,
    anchor:str="center") -> float:
    """Draw a small colored badge with the status text.
    Args:
      c: reportlab Canvas
      status: status name (lowercase looked up in `style.banner_status_colors`)
      x_pt: horizontal anchor in canvas pt
      y_pt: text baseline in canvas pt
      anchor: `"center"` or `"left"`
    Returns:
      Badge width in pt.
    """
    s = self.style
    key = status.lower()
    palette = s.banner_status_colors
    bg, fg = palette.get(key, ((0.93, 0.93, 0.95), (0.40, 0.44, 0.50)))
    pdf = self.pdf
    font = pdf._fonts.register(s.body_family, s.bold_mode)
    label = status.upper()
    pad_x = 4
    pad_y = 2
    text_w = c.stringWidth(label, font, s.mini_banner_size - 1)
    badge_w = text_w + pad_x * 2
    badge_h = s.mini_banner_size + pad_y * 2 - 1
    if anchor == "center": bx = x_pt - badge_w / 2
    else:
      bx = x_pt
    # Whole badge raised 0.2mm
    by = y_pt - pad_y + 0.2 * MM_TO_PT
    c.setFillColor(Color(*bg))
    c.setStrokeColor(Color(*bg))
    c.roundRect(bx, by, badge_w, badge_h, badge_h * 0.3, fill=1, stroke=0)
    c.setFillColor(Color(*fg))
    c.setFont(font, s.mini_banner_size - 1)
    # Text centered vertically in badge: baseline = by + (badge_h - cap_height) / 2
    # Approximate cap height as 0.7 * font size, so offset = (badge_h - 0.7*size) / 2
    text_size = s.mini_banner_size - 1
    text_y = by + (badge_h - text_size * 0.7) / 2
    c.drawString(bx + pad_x, text_y, label)
    return badge_w

  def _render_page_number(self, pdf, page_num:int, total:int):
    """Footer page number. Format depends on `style.page_number_total`:
      True (default):  `<label> N/M` (e.g. `Page 1/5`, `Strona 3/12`)
      False:           `<label> N`
    Registered as `on_final_page` callback so total is known at draw time.
    """
    s = self.style
    if not s.page_number_label:
      return
    if s.page_number_total:
      text = f"{s.page_number_label} {page_num}/{total}"
    else:
      text = f"{s.page_number_label} {page_num}"
    y_mm = pdf._page.height - pdf._page.margin_bot * 0.5
    y_pt = (pdf._page.height - y_mm) * MM_TO_PT
    x_center = (pdf._page.width / 2) * MM_TO_PT
    c = pdf._canvas
    c.setFillColor(Color(*s.muted_color[:3]))
    try:
      font = pdf._fonts.register(s.body_family, s.body_mode)
      c.setFont(font, s.banner_meta_size)
      c.drawCentredString(x_center, y_pt, text)
    except Exception:
      pass

  #---------------------------------------------------------------------------------- Signature
  
  def _render_signature_block(self):
  
    """Right-aligned signature line + italic label, at the end of the document.
    Line uses the same color and thickness as other rules in the header.
    Extra ~1cm vertical space is reserved above the line for the actual signature.
    """
    s = self.style
    pdf = self.pdf
    self._ensure_space(35)
    pdf.enter(25)  # ~25mm space above line for the signature
    line_w = s.banner_sign_w
    content_w = pdf.content_width
    x_left = content_w - line_w
    pdf.cursor(x_left, pdf.y)
    pdf.stroke_color(*s.muted_color[:3])
    pdf.line(line_w, 0, s.banner_rule, dash=(2, 2))
    pdf.cursor(x_left, pdf.y + 1)
    segs = [RichSegment(text=s.banner_label_signature, family=s.body_family, mode=s.italic_mode,
      size=s.banner_sign_size, color=s.muted_color)]
    render_rich(pdf, segs, line_w, x_left, pdf.y, Align.CENTER, 1.0)
