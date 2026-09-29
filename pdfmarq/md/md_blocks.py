# pdfmarq/md/md_blocks.py

"""
Block-level renderers: headings, paragraphs, code blocks, hr, math, images.

Each method draws one block element and advances `pdf.y` past it. All
methods assume the caller (`_render_tokens`) has positioned the cursor
at the block's top-left corner.
"""

from markdown_it.token import Token
import re
from ..inline import RichSegment, render_rich, measure_rich, wrap_line_heights
from ..constants import Align, MM_TO_PT
from .md_images import (ImageDSL, ImageInfo, apply_dsl, load_image_info,
  size_block, size_inline)

#---------------------------------------------------------------------------------- Image paragraph

_ROW_MIN_SLOT_MM = 20  # figures narrower than this wrap to another row

def _image_row(inline_token:Token) -> list[Token]|None:
  """Image children of a paragraph holding nothing but local images.
  Anything else gives `None`, a remote reference included: it has no file to size."""
  imgs = []
  for c in inline_token.children or []:
    if c.type == "image":
      src = _image_ref(c)[0]
      if not src or src.startswith(("http://", "https://", "data:")): return None
      imgs.append(c)
    elif c.type in ("softbreak", "hardbreak"): continue
    elif c.type == "text" and not c.content.strip(): continue
    else: return None
  return imgs or None

def _image_ref(img:Token) -> tuple[str, str, dict]:
  """`(src, alt, attrs)` of an image token, whatever shape markdown-it left `attrs` in."""
  attrs = img.attrs if isinstance(img.attrs, dict) else dict(img.attrs or [])
  return attrs.get("src", ""), img.content or "", attrs

def _row_columns(avail_mm:float, gap_mm:float) -> int:
  """How many figures fit across before each falls below `_ROW_MIN_SLOT_MM`."""
  return max(1, int((avail_mm + gap_mm) // (_ROW_MIN_SLOT_MM + gap_mm)))

def _split_rows(n:int, cols:int) -> list[int]:
  """Row sizes for `n` figures: balanced, none wider than `cols`.
  Eight figures over seven columns is `4+4`, not `7+1`."""
  rows = -(-n // cols)
  base, extra = divmod(n, rows)
  return [base + (i < extra) for i in range(rows)]

#------------------------------------------------------------------------------------- Line fitting

def _fit_math_width(drawing, max_w_pt:float, formula:str) -> None:
  """Shrink a formula drawing in place until it fits `max_w_pt`.

  Centring a drawing wider than the column yields a negative offset, which
  puts both ends of the formula outside the page. Scaling keeps all of it
  on paper, and the warning says it happened - a long formula reads better
  split across two `$$` blocks than shrunk.
  """
  if drawing.width <= max_w_pt or drawing.width <= 0:
    return
  scale = max_w_pt / drawing.width
  drawing.scale(scale, scale)
  drawing.width *= scale
  drawing.height *= scale
  import warnings
  warnings.warn(
    f"block formula is {1 / scale:.1f}x wider than the column and was "
    f"scaled to fit: {formula.strip()[:60]!r}",
    RuntimeWarning, stacklevel=3,
  )

def _fit_lines(heights:list[float], start:int, budget:float) -> tuple[int, float]:
  """How many lines from `start` fit `budget`, and their total height.

  Takes at least one line even when it does not fit, so a line taller
  than a whole page still advances the caller instead of spinning on a
  chunk that can never be placed.
  """
  count = 0
  used = 0.0
  while start + count < len(heights):
    h = heights[start + count]
    if count and used + h > budget: break
    used += h
    count += 1
  return count, used

#-------------------------------------------------------------------------------------- BlocksMixin

class BlocksMixin:
  """Headings, paragraphs, code blocks, horizontal rules, math blocks,
  and standalone block images. Mixed into `MarkdownRenderer`."""

  #---------------------------------------------------------------------------------------- Heading
  
  def _render_heading(self, level:int, inline_token:Token, lookahead_mm:float=0):
    s = self.style
    size = [s.h1_size, s.h2_size, s.h3_size, s.h4_size, s.h5_size, s.h6_size][level-1]
    # h1 page-break is unconditional here: the frontmatter title goes through
    # _render_frontmatter_header, never this path.
    if level == 1 and s.h1_page_break and self.pdf.y > 0.5:
      self.pdf.new_page()
    elif self.pdf.y > 0.5:
      self.pdf.enter(s.head_gap_top)
    # Keep-with-next: reserve heading height + at least 3 body lines.
    heading_block_mm = size / MM_TO_PT * 2
    min_followup_mm = s.body_size * s.line_height / MM_TO_PT * 3
    self._ensure_space(heading_block_mm + max(lookahead_mm, min_followup_mm))
    base = RichSegment(
      text="", family=s.font_head, mode=s.head_mode,
      size=size, color=s.head_color,
    )
    segments = self._inline_to_segments(inline_token, base)
    x = self._indent_mm
    y = self.pdf.y
    width = self.pdf.content_width - x
    # Named destination for `[text](#slug)` anchor links.
    # Must be registered while the canvas is on the correct page.
    slug = self._slugify_inline(inline_token)
    if slug:
      slug = self.dedupe_slug(slug, self._slug_uses)
      self.pdf.cursor(x, y)
      self.pdf.anchor(slug)
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
  def dedupe_slug(slug:str, seen:dict) -> str:
    """`slug`, suffixed when the document already used it.

    Second use becomes `slug-1`, third `slug-2` (GitHub's convention).
    Without it two headings reading the same share one destination and
    every link to either lands on the first. `seen` counts uses and is
    walked in document order by both the pre-scan and the render pass, so
    the two agree on which heading owns which slug.
    """
    used = seen.get(slug, 0)
    seen[slug] = used + 1
    return slug if used == 0 else f"{slug}-{used}"

  @staticmethod
  def _slugify_inline(inline_token:Token) -> str:
    """GitHub-style slug from heading's inline token.
    Concatenates text and inline-code children so markdown syntax chars
    (`*`, `_`, etc.) from `.content` don't pollute the slug while the words
    inside backticks still count. Preserves unicode letters (PL/DE/...).
    """
    children = inline_token.children or []
    parts = [c.content for c in children
      if c.type in ("text", "code_inline") and c.content]
    text = "".join(parts) if parts else (inline_token.content or "")
    s = text.lower().strip()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^\w\-]", "", s, flags=re.UNICODE)
    s = re.sub(r"-+", "-", s).strip("-")
    return s

  #--------------------------------------------------------------------------------- Page splitting

  def _render_rich_paged(
    self, segments:list, line_h:list[float], x_mm:float, width_mm:float,
    line_gap:float, align:str=Align.LEFT, preserve_leading_space:bool=False,
  ):
    """Draw wrapped text taller than one page, breaking pages between lines.

    `render_rich` lays a block out from a single `y`, so lines past the
    page bottom fall outside the MediaBox and are invisible in the output.
    This walks the wrapped lines one page-sized window at a time. Leaves
    the cursor just below the last line drawn (no trailing block gap).
    """
    n = len(line_h)
    i = 0
    while i < n:
      avail = self.pdf.content_height - self.pdf.y
      if avail < line_h[i] and self.pdf.y > 0.5:
        self.pdf.new_page()
        avail = self.pdf.content_height - self.pdf.y
      count, used = _fit_lines(line_h, i, avail)
      y = self.pdf.y
      self.pdf.cursor(x_mm, y)
      render_rich(
        self.pdf, segments, width_mm, x_mm, y, align, line_gap,
        preserve_leading_space=preserve_leading_space,
        first_line=i, max_lines=count,
      )
      self.pdf.cursor(x_mm, y + used)
      i += count
      if i < n:
        self.pdf.new_page()

  #-------------------------------------------------------------------------------------- Paragraph
  
  def _render_paragraph(self, inline_token:Token):
    s = self.style
    imgs = _image_row(inline_token)
    if imgs:
      self._render_images(imgs)
      return
    base = RichSegment(
      text="", family=s.font_body, mode=s.body_mode,
      size=s.body_size, color=s.body_color,
    )
    segments = self._inline_to_segments(inline_token, base)
    x = self._indent_mm
    width = self.pdf.content_width - x
    spacing = s.list_gap if self._list_depth > 0 else s.para_gap
    body_line_mm = s.body_size * s.line_height / MM_TO_PT
    line_h = wrap_line_heights(self.pdf, segments, width, line_gap=s.line_height)
    para_h = sum(line_h) or body_line_mm
    page_h = self.pdf.content_height
    if para_h > (page_h - self.pdf.y):
      if para_h <= page_h:
        # Fits a page, just not what is left of this one - keep it whole.
        self.pdf.new_page()
      else:
        # Taller than a whole page: split it, otherwise every line past the
        # page bottom is drawn off-page and lost.
        self._render_rich_paged(segments, line_h, x, width, s.line_height)
        self.pdf.cursor(x, self.pdf.y + spacing)
        return
    y = self.pdf.y
    self.pdf.cursor(x, y)
    h = render_rich(self.pdf, segments, width, x, y, Align.LEFT, s.line_height)
    self.pdf.cursor(x, y + h + spacing)

  #------------------------------------------------------------------------------------- Code block
  
  def _render_code_block(self, content:str, lang:str="", info_rest:str=""):
    s = self.style
    content = content.rstrip("\n")
    # Mermaid: render to PNG; `info_rest` carries optional image DSL overrides.
    if lang == "mermaid" and s.mermaid_enable:
      try:
        from .mermaid import render_mermaid
        result = render_mermaid(
          content,
          cli=s.mermaid_cli, theme=s.mermaid_theme,
          background=s.mermaid_background, scale=s.mermaid_scale,
          font_family=s.font_body,
          font_dir=str(self.pdf._fonts.font_dir),
          remote=s.mermaid_remote,
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
    # highlight_code returns None when pygments is absent (warns once);
    # the ImportError guard is defensive against partial installs.
    highlighted = None
    if lang:
      try:
        from .highlight import highlight_code
        highlighted = highlight_code(
          content, lang,
          family=s.font_mono, mode=s.mono_mode, bold_mode=s.bold_mode,
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
          family=s.font_mono, mode=s.mono_mode,
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
    frame_h_mm = 2 * pad + top_offset # padding + border, per drawn chunk
    block_h = content_h_mm + frame_h_mm
    radius = s.code_block_radius
    page_h = self.pdf.content_height
    # Fits a page but not the rest of this one: move it whole.
    if block_h > (page_h - self.pdf.y) and block_h <= page_h and self.pdf.y > 0.5:
      self.pdf.new_page()
    # A taller block is drawn in chunks, one frame per chunk: lines placed
    # below the page bottom fall outside the MediaBox and are invisible.
    n = len(per_line_segs)
    i = 0
    while i < n:
      avail = self.pdf.content_height - self.pdf.y
      if avail < frame_h_mm + line_heights_mm[i] and self.pdf.y > 0.5:
        self.pdf.new_page()
        avail = self.pdf.content_height - self.pdf.y
      count, used = _fit_lines(line_heights_mm, i, avail - frame_h_mm)
      chunk_h = used + frame_h_mm
      y = self.pdf.y
      self.pdf.cursor(x, y)
      self.pdf.color(*s.code_block_bg[:3])
      self.pdf.round_rect(w, chunk_h, radius, fill=True)
      self.pdf.cursor(x, y)
      self.pdf.stroke_color(*s.code_block_border[:3])
      self.pdf.round_rect(w, chunk_h, radius, thickness=0.4, fill=False)
      self._reset_stroke()
      text_y = y + pad + top_offset
      for idx in range(i, i + count):
        render_rich(
          self.pdf, per_line_segs[idx], text_width_mm,
          x + pad + left_offset, text_y,
          Align.LEFT, s.line_height,
          preserve_leading_space=True,
        )
        text_y += line_heights_mm[idx]
      self.pdf.cursor(x, y + chunk_h)
      i += count
      if i < n:
        self.pdf.new_page()
    self.pdf.cursor(x, self.pdf.y + s.code_block_gap)

  #----------------------------------------------------------------------------------------- Images
  
  def _load_inline_image(self, src:str, fontsize_pt:float, attrs:dict|None=None):
    """Load a local image → scaled reportlab Drawing, or `None` on failure.

    Used for inline mid-paragraph images: capped at `inline_image_max_h`
    via `size_inline` so an inline image never blows up line height.
    """
    src = self._resolve_image_path(src)
    info = load_image_info(src, attrs=attrs, default_dpi=self.style.image_dpi)
    if info is None:
      return None
    # `inline_image_max_h` is set for body text; smaller print scales with it.
    inline_cap_mm = self.style.inline_image_max_h * fontsize_pt / self.style.body_size
    w_mm, h_mm = size_inline(info, inline_cap_mm)
    w_pt, h_pt = w_mm * MM_TO_PT, h_mm * MM_TO_PT
    try:
      from reportlab.graphics.shapes import Drawing, Image
      if info.is_svg:
        from ..graphics import load_svg
        src_drawing = load_svg(src)
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
    """Render a paragraph-level image, sized via `size_block` rules."""
    s = self.style
    pdf = self.pdf
    x_start = self._indent_mm
    src = self._resolve_image_path(src)
    info = load_image_info(src, attrs=attrs, alt=alt, default_dpi=s.image_dpi)
    if info is None:
      base = RichSegment(
        text=f"[Image not found: {src}]",
        family=s.font_body, mode=s.italic_mode,
        size=s.body_size, color=s.muted_color,
      )
      y = pdf.y
      render_rich(pdf, [base], pdf.content_width - x_start, x_start, y,
        Align.LEFT, s.line_height)
      pdf.cursor(x_start, y + s.body_size * s.line_height / MM_TO_PT + s.para_gap)
      return
    self._draw_figure(info)

  def _draw_figure(self, info:ImageInfo):
    """Size one block figure to the content width and draw it.
    Centred unless the DSL says `align=L/R`."""
    s = self.style
    pdf = self.pdf
    x_start = self._indent_mm
    avail_w_mm = pdf.content_width - x_start
    w, h = size_block(info, avail_w_mm, s.image_max_h,
      svg_fill_width=s.svg_block_fill_width, min_dpi=s.image_min_dpi)
    self._ensure_space(h + s.para_gap)
    y = pdf.y
    if info.align == "L": x = x_start
    elif info.align == "R": x = x_start + (avail_w_mm - w)
    else: x = x_start + (avail_w_mm - w) / 2
    pdf.cursor(x, y)
    if info.is_svg: pdf.svg(info.src, w, h)
    else: pdf.image(info.src, w, h)
    pdf.cursor(x_start, y + h + s.para_gap)

  def _render_images(self, imgs:list[Token]):
    """Draw an image-only paragraph: one figure, or a balanced grid of rows.
    Never hands it back: a row that cannot be prepared becomes stacked figures."""
    s = self.style
    refs = [_image_ref(img) for img in imgs]
    if len(refs) == 1:
      self._render_block_image(refs[0][0], refs[0][1], attrs=refs[0][2])
      return
    avail_w_mm = self.pdf.content_width - self._indent_mm
    sizes = _split_rows(len(refs), _row_columns(avail_w_mm, s.para_gap))
    slot = (avail_w_mm - s.para_gap * (sizes[0] - 1)) / sizes[0]
    start = 0
    for count in sizes:
      row = refs[start:start + count]
      start += count
      if not self._render_image_row(row, slot):
        for src, alt, attrs in row:
          self._render_block_image(src, alt, attrs=attrs)

  def _render_image_row(self, refs:list[tuple], slot:float) -> bool:
    """Lay one row of figures side by side, each in a `slot`-wide cell.
    All-or-nothing: a file that will not load cancels the row."""
    s = self.style
    pdf = self.pdf
    x_start = self._indent_mm
    avail_w_mm = pdf.content_width - x_start
    boxes = []
    for src, alt, attrs in refs:
      info = load_image_info(self._resolve_image_path(src), attrs=attrs, alt=alt,
        default_dpi=s.image_dpi)
      if info is None:
        return False
      w, h = size_block(info, slot, s.image_max_h,
        svg_fill_width=s.svg_block_fill_width, min_dpi=s.image_min_dpi)
      boxes.append((info, w, h))
    row_h = max(h for _, _, h in boxes)
    row_w = sum(w for _, w, _ in boxes) + s.para_gap * (len(boxes) - 1)
    self._ensure_space(row_h + s.para_gap)
    y = pdf.y
    x = x_start + (avail_w_mm - row_w) / 2
    for info, w, h in boxes:
      pdf.cursor(x, y + (row_h - h) / 2)
      if info.is_svg: pdf.svg(info.src, w, h)
      else: pdf.image(info.src, w, h)
      x += w + s.para_gap
    pdf.cursor(x_start, y + row_h + s.para_gap)
    return True

  def _render_mermaid_image(self, png_path:str, w_pt:float, h_pt:float, dsl=None):
    """Embed a mermaid PNG as a block figure, with `![](src "DSL")` semantics.
    Marked `generated` because the diagram is vector at heart,
    so its raster carries no resolution the width has to respect."""
    info = ImageInfo(src=png_path, is_svg=False, generated=True,
      nat_w_mm=w_pt / MM_TO_PT, nat_h_mm=h_pt / MM_TO_PT)
    self._draw_figure(apply_dsl(info, dsl or ImageDSL()))

  #--------------------------------------------------------------------------------------------- HR
  
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

  #------------------------------------------------------------------------------------- Math block
  
  def _render_math_block(self, formula:str):
    """Render a block-level math formula, centered. Numbered on the right:
    a `\tag{...}` names the label, otherwise the auto counter does."""
    s = self.style
    try:
      from .math import pop_tag, render_math_svg
      from reportlab.graphics import renderPDF
    except ImportError:
      from .._warn import warn_missing
      warn_missing("matplotlib", "matplotlib", "block math formulas")
      self._render_code_block(formula, "")
      return
    formula, tag = pop_tag(formula)
    drawing = render_math_svg(
      formula.strip(), fontsize=s.body_size, color=s.body_color,
      config=getattr(self, "_math_config", None),
      engine=s.math_engine, font=s.math_font,
    )
    if drawing is None:
      self._render_code_block(formula, "")
      return
    content_w_mm = self.pdf.content_width - self._indent_mm
    content_w_pt = content_w_mm * MM_TO_PT
    _fit_math_width(drawing, content_w_pt, formula)
    w_pt = drawing.width
    h_pt = drawing.height
    h_mm = h_pt / MM_TO_PT
    # The paragraph above ends with its line leading; the drawing carries
    # none. A quarter of it is pulled back, so the formula keeps slightly
    # more air above than below without doubling the gap.
    lead_mm = (s.line_height - 1) * s.body_size / MM_TO_PT / 4
    if self.pdf.y > lead_mm:
      self.pdf.cursor(self._indent_mm, self.pdf.y - lead_mm)
    self._ensure_space(h_mm + s.math_block_gap)
    x_center_offset_pt = (content_w_pt - w_pt) / 2
    page = self.pdf._page
    x_abs_mm = page.margin_left + self._indent_mm
    y_abs_mm = page.height - page.margin_top - self.pdf.y - h_mm
    x_pt = x_abs_mm * MM_TO_PT + x_center_offset_pt
    y_pt = y_abs_mm * MM_TO_PT
    renderPDF.draw(drawing, self.pdf._canvas, x_pt, y_pt)
    if tag or s.math_numbering:
      if tag is None:
        self._eq_counter += 1
      num_seg = RichSegment(
        text=tag or f"({self._eq_counter})", family=s.font_body, mode=s.body_mode,
        size=s.body_size, color=s.body_color,
      )
      num_y = self.pdf.y + h_mm / 2 - s.body_size * 0.35 / MM_TO_PT
      render_rich(
        self.pdf, [num_seg], content_w_mm,
        self._indent_mm, num_y, Align.RIGHT, s.line_height,
      )
    self.pdf.cursor(self._indent_mm, self.pdf.y + h_mm + s.math_block_gap)
