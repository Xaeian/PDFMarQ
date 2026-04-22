# pdfmarq/md/md_blocks.py

"""
Block-level renderers: headings, paragraphs, code blocks, hr, math, images.

Each method draws one block element and advances `pdf.y` past it. All
methods assume the caller (`_render_tokens`) has positioned the cursor
at the block's top-left corner.
"""

from markdown_it.token import Token
from ..inline import RichSegment, render_rich, measure_rich
from ..constants import Align, MM_TO_PT

#---------------------------------------------------------------------------------- BlocksMixin

class BlocksMixin:
  
  #------------------------------------------------------------------------------------ Heading
  
  def _render_heading(self, level:int, inline_token:Token, lookahead_mm:float=0):
    s = self.style
    size = [s.h1_size, s.h2_size, s.h3_size, s.h4_size, s.h5_size, s.h6_size][level-1]
    # h1 starts a new page when configured; other headings just add top spacing.
    # The frontmatter title is rendered via _render_frontmatter_header so it
    # never goes through this code path - safe to apply unconditionally here.
    if level == 1 and s.page_break_on_h1 and self.pdf.y > 0.5:
      self.pdf.new_page()
    elif self.pdf.y > 0.5:
      self.pdf.enter(s.heading_spacing_top)
    # Keep-with-next: reserve heading + max(lookahead, 3 body lines)
    heading_block_mm = size / MM_TO_PT * 2
    min_followup_mm = s.body_size * s.line_height / MM_TO_PT * 3
    self._ensure_space(heading_block_mm + max(lookahead_mm, min_followup_mm))
    base = RichSegment(
      text="", family=s.heading_family, mode=s.heading_mode,
      size=size, color=s.heading_color,
    )
    segments = self._inline_to_segments(inline_token, base)
    x = self._indent_mm
    y = self.pdf.y
    width = self.pdf.content_width - x
    # Register named destination so `[text](#slug)` links can jump here.
    # Must happen while canvas is on the correct page (after ensure_space).
    slug = self._slugify_inline(inline_token)
    if slug:
      self.pdf._canvas.bookmarkPage(slug)
    self.pdf.cursor(x, y)
    h = render_rich(self.pdf, segments, width, x, y, Align.LEFT, s.line_height)
    new_y = y + h
    if (level == 1 and s.h1_underline) or (level == 2 and s.h2_underline):
      self.pdf.cursor(x, new_y + 0.8)
      self.pdf.stroke_color(*s.hr_color)
      self.pdf.line(width, 0, s.underline_thickness)
      self._reset_stroke()
      new_y += 2
    self.pdf.cursor(x, new_y + s.heading_spacing_bot)

  @staticmethod
  def _slugify_inline(inline_token:Token) -> str:
    """GitHub-style slug from heading's inline token.
    Concatenates text-type children so markdown syntax chars (`*`, `_`, etc.)
    from `.content` don't pollute the slug. Preserves unicode letters (PL/DE/...).
    """
    import re
    children = inline_token.children or []
    parts = [c.content for c in children if c.type == "text" and c.content]
    text = "".join(parts) if parts else (inline_token.content or "")
    s = text.lower().strip()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^\w\-]", "", s, flags=re.UNICODE)
    s = re.sub(r"-+", "-", s).strip("-")
    return s

  #---------------------------------------------------------------------------------- Paragraph
  
  def _render_paragraph(self, inline_token:Token):
    s = self.style
    # Paragraph with just a single image → render as block image
    children = inline_token.children or []
    non_trivial = [c for c in children if c.type not in ("softbreak", "hardbreak")]
    if len(non_trivial) == 1 and non_trivial[0].type == "image":
      img = non_trivial[0]
      src = (img.attrs or {}).get("src", "") if isinstance(img.attrs, dict) else ""
      alt = img.content or ""
      if src and not src.startswith(("http://", "https://")):
        self._render_block_image(src, alt)
        return
    base = RichSegment(
      text="", family=s.body_family, mode=s.body_mode,
      size=s.body_size, color=s.body_color,
    )
    segments = self._inline_to_segments(inline_token, base)
    x = self._indent_mm
    width = self.pdf.content_width - x
    # Measure full paragraph; if it fits on an empty page but not in remaining
    # space here, break to new page first. Very long paragraphs (>90% of page)
    # render in place - `render_rich` is not page-aware and cannot split.
    body_line_mm = s.body_size * s.line_height / MM_TO_PT
    para_h = measure_rich(self.pdf, segments, width, line_gap=s.line_height) or body_line_mm
    page_avail = self.pdf.content_height
    if para_h <= page_avail * 0.9 and para_h > (page_avail - self.pdf.y):
      self.pdf.new_page()
    self._ensure_space(min(para_h, body_line_mm))
    y = self.pdf.y
    self.pdf.cursor(x, y)
    h = render_rich(self.pdf, segments, width, x, y, Align.LEFT, s.line_height)
    spacing = s.list_item_spacing if self._list_depth > 0 else s.paragraph_spacing
    self.pdf.cursor(x, y + h + spacing)

  #--------------------------------------------------------------------------------- Code block
  
  def _render_code_block(self, content:str, lang:str=""):
    s = self.style
    content = content.rstrip("\n")
    # Mermaid renders to image; falls back to plain code block on failure.
    # The mermaid module itself is local but may need PIL or mermaid-cli.
    if lang == "mermaid":
      try:
        from .mermaid import render_mermaid
        result = render_mermaid(content)
      except ImportError:
        from .._warn import warn_missing
        warn_missing("mermaid", "Pillow", "mermaid diagrams")
        result = None
      if result is not None:
        path, w_pt, h_pt = result
        self._render_mermaid_image(path, w_pt, h_pt)
        return
    # Syntax highlighting via pygments. The function returns None when
    # pygments is missing and warns once internally; ImportError handler
    # here is defensive.
    highlighted = None
    if lang:
      try:
        from .highlight import highlight_code
        highlighted = highlight_code(
          content, lang,
          family=s.mono_family, mode=s.mono_mode, bold_mode=s.bold_mode,
          size=s.code_block_size, default_color=s.body_color,
          theme=s.syntax_theme,
        )
      except ImportError:
        highlighted = None
    lines = content.split("\n") if content else [""]
    pad = s.code_block_padding
    left_offset = 2
    top_offset = s.code_block_size * 0.35 / MM_TO_PT
    per_line_segs: list[list[RichSegment]] = []
    for idx in range(len(lines)):
      if highlighted and idx < len(highlighted) and highlighted[idx]:
        line_segs = highlighted[idx]
      else:
        line_segs = [RichSegment(
          text=lines[idx] or " ",
          family=s.mono_family, mode=s.mono_mode,
          size=s.code_block_size, color=s.body_color,
        )]
      per_line_segs.append(line_segs)
    x = self._indent_mm
    w = self.pdf.content_width - x
    text_width_mm = w - 2 * pad - left_offset
    min_line_h_mm = s.code_block_size * s.line_height / MM_TO_PT
    line_heights_mm: list[float] = []
    for line_segs in per_line_segs:
      h = measure_rich(
        self.pdf, line_segs, text_width_mm, line_gap=s.line_height,
        preserve_leading_space=True,
      )
      line_heights_mm.append(max(h, min_line_h_mm))
    content_h_mm = sum(line_heights_mm)
    block_h = content_h_mm + 2 * pad + top_offset
    self._ensure_space(block_h)
    y = self.pdf.y
    radius = s.code_block_radius
    self.pdf.cursor(x, y)
    self.pdf.color(*s.code_block_bg[:3])
    self.pdf.round_rect(w, block_h, radius, fill=True)
    self.pdf.cursor(x, y)
    self.pdf.stroke_color(*s.code_block_border[:3])
    self.pdf.round_rect(w, block_h, radius, thickness=0.4, fill=False)
    self._reset_stroke()
    text_y = y + pad + top_offset
    for idx, line_segs in enumerate(per_line_segs):
      render_rich(
        self.pdf, line_segs, text_width_mm,
        x + pad + left_offset, text_y,
        Align.LEFT, s.line_height,
        preserve_leading_space=True,
      )
      text_y += line_heights_mm[idx]
    self.pdf.cursor(x, y + block_h + s.code_block_spacing)

  #------------------------------------------------------------------------------------- Images
  
  def _load_inline_image(self, src:str, fontsize_pt:float):
    """Load a local image → scaled reportlab Drawing, or None on failure."""
    try:
      import os
      from reportlab.graphics.shapes import Drawing, Image
      if not os.path.exists(src):
        return None
      from PIL import Image as PILImage
      with PILImage.open(src) as im:
        px_w, px_h = im.size
      target_h = fontsize_pt * 2.0
      scale = target_h / px_h
      w_pt = px_w * scale
      d = Drawing(w_pt, target_h)
      d.add(Image(0, 0, w_pt, target_h, src))
      return d
    except Exception:
      return None

  def _render_block_image(self, src:str, alt:str):
    """Render a paragraph-level image centered, scaled to content width."""
    import os
    s = self.style
    pdf = self.pdf
    x_start = self._indent_mm
    avail_w_mm = pdf.content_width - x_start
    if not os.path.exists(src):
      base = RichSegment(
        text=f"[Image not found: {src}]",
        family=s.body_family, mode=s.italic_mode,
        size=s.body_size, color=s.muted_color,
      )
      y = pdf.y
      render_rich(pdf, [base], avail_w_mm, x_start, y, Align.LEFT, s.line_height)
      pdf.cursor(x_start, y + s.body_size * s.line_height / MM_TO_PT + s.paragraph_spacing)
      return
    try:
      from PIL import Image as PILImage
      with PILImage.open(src) as im:
        px_w, px_h = im.size
      dpi = 96
      nat_w_mm = px_w * 25.4 / dpi
      nat_h_mm = px_h * 25.4 / dpi
      if nat_w_mm > avail_w_mm:
        scale = avail_w_mm / nat_w_mm
        nat_w_mm *= scale
        nat_h_mm *= scale
      self._ensure_space(nat_h_mm + s.paragraph_spacing)
      y = pdf.y
      x = x_start + (avail_w_mm - nat_w_mm) / 2
      pdf.cursor(x, y)
      pdf.image(src, nat_w_mm, nat_h_mm)
      pdf.cursor(x_start, y + nat_h_mm + s.paragraph_spacing)
    except Exception:
      pass

  def _render_mermaid_image(self, png_path:str, w_pt:float, h_pt:float):
    """Embed a mermaid PNG, scaled to fit content width + max height, centered."""
    s = self.style
    pdf = self.pdf
    x_start = self._indent_mm
    avail_w_mm = pdf.content_width - x_start
    img_w_mm = w_pt / MM_TO_PT
    img_h_mm = h_pt / MM_TO_PT
    scale_w = avail_w_mm / img_w_mm if img_w_mm > avail_w_mm else 1.0
    scale_h = s.mermaid_max_height / img_h_mm if img_h_mm > s.mermaid_max_height else 1.0
    scale = min(scale_w, scale_h)
    if scale < 1.0:
      img_w_mm *= scale
      img_h_mm *= scale
    self._ensure_space(img_h_mm + s.paragraph_spacing)
    y = pdf.y
    x = x_start + (avail_w_mm - img_w_mm) / 2
    pdf.cursor(x, y)
    pdf.image(png_path, img_w_mm, img_h_mm)
    pdf.cursor(x_start, y + img_h_mm + s.paragraph_spacing)

  #----------------------------------------------------------------------------------------- HR
  
  def _render_hr(self):
    s = self.style
    self.pdf.enter(s.paragraph_spacing / 2)
    x = self._indent_mm
    w = self.pdf.content_width - x
    self.pdf.cursor(x, self.pdf.y)
    self.pdf.stroke_color(*s.hr_color)
    self.pdf.line(w, 0, s.hr_thickness)
    self._reset_stroke()
    self.pdf.enter(s.paragraph_spacing)

  #--------------------------------------------------------------------------------- Math block
  
  def _render_math_block(self, formula:str):
    """Render a block-level math formula centered with auto-numbering."""
    s = self.style
    try:
      from .math import render_math_svg
      from reportlab.graphics import renderPDF
    except ImportError:
      from .._warn import warn_missing
      warn_missing("matplotlib", "matplotlib", "block math formulas")
      self._render_code_block(formula, "")
      return
    drawing = render_math_svg(
      formula.strip(), fontsize=s.body_size * 1.1, color=s.body_color,
    )
    if drawing is None:
      self._render_code_block(formula, "")
      return
    w_pt = drawing.width
    h_pt = drawing.height
    h_mm = h_pt / MM_TO_PT
    self.pdf.enter(s.math_block_spacing)
    self._ensure_space(h_mm + s.math_block_spacing)
    content_w_mm = self.pdf.content_width - self._indent_mm
    content_w_pt = content_w_mm * MM_TO_PT
    x_center_offset_pt = (content_w_pt - w_pt) / 2
    page = self.pdf._page
    x_abs_mm = page.margin_lr + self._indent_mm
    y_abs_mm = page.height - page.margin_top - self.pdf.y - h_mm
    x_pt = x_abs_mm * MM_TO_PT + x_center_offset_pt
    y_pt = y_abs_mm * MM_TO_PT
    renderPDF.draw(drawing, self.pdf._canvas, x_pt, y_pt)
    if s.math_equation_numbering:
      self._eq_counter += 1
      num_seg = RichSegment(
        text=f"({self._eq_counter})", family=s.body_family, mode=s.body_mode,
        size=s.body_size, color=s.body_color,
      )
      num_y = self.pdf.y + h_mm / 2 - s.body_size * 0.35 / MM_TO_PT
      render_rich(
        self.pdf, [num_seg], content_w_mm,
        self._indent_mm, num_y, Align.RIGHT, s.line_height,
      )
    self.pdf.cursor(self._indent_mm, self.pdf.y + h_mm + s.math_block_spacing)
