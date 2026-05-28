# pdfmarq/md/md_blocks.py

"""
Block-level renderers: headings, paragraphs, code blocks, hr, math, images.

Each method draws one block element and advances `pdf.y` past it. All
methods assume the caller (`_render_tokens`) has positioned the cursor
at the block's top-left corner.
"""

from markdown_it.token import Token
import re
from ..inline import RichSegment, render_rich, measure_rich
from ..constants import Align, MM_TO_PT
from .md_images import load_image_info, size_block, size_inline, ImageInfo

#---------------------------------------------------------------------------------- BlocksMixin

class BlocksMixin:
  """Headings, paragraphs, code blocks, horizontal rules, math blocks,
  and standalone block images. Mixed into `MarkdownRenderer`."""

  #------------------------------------------------------------------------------------ Heading
  
  def _render_heading(self, level:int, inline_token:Token, lookahead_mm:float=0):
    s = self.style
    size = [s.h1_size, s.h2_size, s.h3_size, s.h4_size, s.h5_size, s.h6_size][level-1]
    # h1 starts a new page when configured; other headings just add top spacing.
    # The frontmatter title is rendered via _render_frontmatter_header so it
    # never goes through this code path - safe to apply unconditionally here.
    if level == 1 and s.h1_page_break and self.pdf.y > 0.5:
      self.pdf.new_page()
    elif self.pdf.y > 0.5:
      self.pdf.enter(s.head_gap_top)
    # Keep-with-next: reserve heading + max(lookahead, 3 body lines)
    heading_block_mm = size / MM_TO_PT * 2
    min_followup_mm = s.body_size * s.line_height / MM_TO_PT * 3
    self._ensure_space(heading_block_mm + max(lookahead_mm, min_followup_mm))
    base = RichSegment(
      text="", family=s.head_family, mode=s.head_mode,
      size=size, color=s.head_color,
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
      self.pdf.line(width, 0, s.underline_thick)
      self._reset_stroke()
      new_y += 2
    self.pdf.cursor(x, new_y + s.head_gap_bot)

  @staticmethod
  def _slugify_inline(inline_token:Token) -> str:
    """GitHub-style slug from heading's inline token.
    Concatenates text-type children so markdown syntax chars (`*`, `_`, etc.)
    from `.content` don't pollute the slug. Preserves unicode letters (PL/DE/...).
    """
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
      img_attrs = img.attrs if isinstance(img.attrs, dict) else dict(img.attrs or [])
      src = img_attrs.get("src", "")
      alt = img.content or ""
      if src and not src.startswith(("http://", "https://")):
        self._render_block_image(src, alt, attrs=img_attrs)
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
    spacing = s.list_gap if self._list_depth > 0 else s.para_gap
    self.pdf.cursor(x, y + h + spacing)

  #--------------------------------------------------------------------------------- Code block
  
  def _render_code_block(self, content:str, lang:str="", info_rest:str=""):
    s = self.style
    content = content.rstrip("\n")
    # Mermaid renders to image. `info_rest` is parsed as image DSL.
    if lang == "mermaid" and s.mermaid_enable:
      try:
        from .mermaid import render_mermaid
        result = render_mermaid(
          content,
          cli=s.mermaid_cli, theme=s.mermaid_theme,
          background=s.mermaid_background, scale=s.mermaid_scale,
          font_family=s.body_family,
          font_dir=str(self.pdf._fonts.font_dir),
        )
      except ImportError:
        from .._warn import warn_missing
        warn_missing("mermaid", "Pillow", "mermaid diagrams")
        result = None
      if result is not None:
        path, w_pt, h_pt = result
        from .md_images import parse_image_dsl
        dsl = parse_image_dsl(info_rest) if info_rest else None
        self._render_mermaid_image(path, w_pt, h_pt, dsl)
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
    pad = s.code_block_pad
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
    self.pdf.cursor(x, y + block_h + s.code_block_gap)

  #------------------------------------------------------------------------------------- Images
  
  def _load_inline_image(self, src:str, fontsize_pt:float, attrs:dict|None=None):
  
    """Load a local image → scaled reportlab Drawing, or `None` on failure.

    Used for inline mid-paragraph images: capped at `inline_image_max_h`
    via `size_inline` so an inline image never blows up line height.
    """
    src = self._resolve_image_path(src)
    info = load_image_info(src, attrs=attrs, default_dpi=self.style.image_dpi)
    if info is None:
      return None
    # Inline cap derives from font size with a 2.0× factor (LaTeX 2ex idiom).
    inline_cap_mm = fontsize_pt * 2.0 / MM_TO_PT
    w_mm, h_mm = size_inline(info, inline_cap_mm)
    w_pt, h_pt = w_mm * MM_TO_PT, h_mm * MM_TO_PT
    try:
      from reportlab.graphics.shapes import Drawing, Image
      if info.is_svg:
        from svglib.svglib import svg2rlg
        src_drawing = svg2rlg(src)
        if src_drawing is None or src_drawing.width <= 0 or src_drawing.height <= 0:
          return None
        sx = h_pt / src_drawing.height
        # Aspect-preserving - for SVGs, width derived from svglib's intrinsic ratio
        target_w_pt = src_drawing.width * sx
        src_drawing.transform = (sx, 0, 0, sx, 0, 0)
        d = Drawing(target_w_pt, h_pt)
        d.add(src_drawing)
        return d
      d = Drawing(w_pt, h_pt)
      d.add(Image(0, 0, w_pt, h_pt, src))
      return d
    except Exception:
      return None

  def _render_block_image(self, src:str, alt:str, attrs:dict|None=None):
    """Render a paragraph-level image, sized via `size_block` rules.
    Centered horizontally in the available content area."""
    s = self.style
    pdf = self.pdf
    x_start = self._indent_mm
    avail_w_mm = pdf.content_width - x_start
    src = self._resolve_image_path(src)
    info = load_image_info(src, attrs=attrs, alt=alt, default_dpi=s.image_dpi)
    if info is None:
      base = RichSegment(
        text=f"[Image not found: {src}]",
        family=s.body_family, mode=s.italic_mode,
        size=s.body_size, color=s.muted_color,
      )
      y = pdf.y
      render_rich(pdf, [base], avail_w_mm, x_start, y, Align.LEFT, s.line_height)
      pdf.cursor(x_start, y + s.body_size * s.line_height / MM_TO_PT + s.para_gap)
      return
    img_w_mm, img_h_mm = size_block(
      info, avail_w_mm, s.image_max_h,
      svg_fill_width=s.svg_block_fill_width,
    )
    self._ensure_space(img_h_mm + s.para_gap)
    y = pdf.y
    # DSL `align=L/C/R` overrides the default center; otherwise center stays.
    if info.align == "L":
      x = x_start
    elif info.align == "R":
      x = x_start + (avail_w_mm - img_w_mm)
    else:
      x = x_start + (avail_w_mm - img_w_mm) / 2
    pdf.cursor(x, y)
    if info.is_svg:
      pdf.svg(info.src, img_w_mm, img_h_mm)
    else:
      pdf.image(info.src, img_w_mm, img_h_mm)
    pdf.cursor(x_start, y + img_h_mm + s.para_gap)

  def _render_mermaid_image(self, png_path:str, w_pt:float, h_pt:float, dsl=None):
    """Embed a mermaid PNG. `dsl` mirrors `![](src "DSL")` image semantics."""
    from .md_images import _clamp_no_upscale
    s = self.style
    pdf = self.pdf
    x_start = self._indent_mm
    avail_w_mm = pdf.content_width - x_start
    nat_w_mm = w_pt / MM_TO_PT
    nat_h_mm = h_pt / MM_TO_PT
    # DSL overrides: scale wins absolutely, else explicit w/h, then max_* caps.
    ew_mm, eh_mm = nat_w_mm, nat_h_mm
    max_w_cap = avail_w_mm
    max_h_cap = s.image_max_h
    align = "C"
    if dsl is not None and getattr(dsl, "is_dsl", False):
      if dsl.scale is not None:
        ew_mm = nat_w_mm * dsl.scale
        eh_mm = nat_h_mm * dsl.scale
      else:
        if dsl.exact_w_mm is not None:
          ew_mm = dsl.exact_w_mm
          eh_mm = nat_h_mm * (dsl.exact_w_mm / nat_w_mm) if nat_w_mm > 0 else eh_mm
        if dsl.exact_h_mm is not None:
          eh_mm = dsl.exact_h_mm
          ew_mm = nat_w_mm * (dsl.exact_h_mm / nat_h_mm) if nat_h_mm > 0 else ew_mm
      if dsl.max_w_mm is not None: max_w_cap = min(max_w_cap, dsl.max_w_mm)
      if dsl.max_h_mm is not None: max_h_cap = min(max_h_cap, dsl.max_h_mm)
      if dsl.align: align = dsl.align
    img_w_mm, img_h_mm = _clamp_no_upscale(ew_mm, eh_mm, max_w_cap, max_h_cap)
    self._ensure_space(img_h_mm + s.para_gap)
    y = pdf.y
    if align == "L": x = x_start
    elif align == "R": x = x_start + (avail_w_mm - img_w_mm)
    else: x = x_start + (avail_w_mm - img_w_mm) / 2
    pdf.cursor(x, y)
    pdf.image(png_path, img_w_mm, img_h_mm)
    pdf.cursor(x_start, y + img_h_mm + s.para_gap)

  #----------------------------------------------------------------------------------------- HR
  
  def _render_hr(self):
    s = self.style
    self.pdf.enter(s.para_gap / 2)
    x = self._indent_mm
    w = self.pdf.content_width - x
    self.pdf.cursor(x, self.pdf.y)
    self.pdf.stroke_color(*s.hr_color)
    self.pdf.line(w, 0, s.hr_thick)
    self._reset_stroke()
    self.pdf.enter(s.para_gap)

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
      config=getattr(self, "_math_config", None),
    )
    if drawing is None:
      self._render_code_block(formula, "")
      return
    w_pt = drawing.width
    h_pt = drawing.height
    h_mm = h_pt / MM_TO_PT
    self.pdf.enter(s.math_block_gap)
    self._ensure_space(h_mm + s.math_block_gap)
    content_w_mm = self.pdf.content_width - self._indent_mm
    content_w_pt = content_w_mm * MM_TO_PT
    x_center_offset_pt = (content_w_pt - w_pt) / 2
    page = self.pdf._page
    x_abs_mm = page.margin_lr + self._indent_mm
    y_abs_mm = page.height - page.margin_top - self.pdf.y - h_mm
    x_pt = x_abs_mm * MM_TO_PT + x_center_offset_pt
    y_pt = y_abs_mm * MM_TO_PT
    renderPDF.draw(drawing, self.pdf._canvas, x_pt, y_pt)
    if s.math_numbering:
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
    self.pdf.cursor(self._indent_mm, self.pdf.y + h_mm + s.math_block_gap)
