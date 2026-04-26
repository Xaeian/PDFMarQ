# pdfmarq/md/md_table.py

"""
Markdown table rendering with HTML auto-layout column widths.

Uses `measure_extent` (widest unbreakable word + total unwrapped width)
to decide column widths: if everything fits, use natural widths; if not,
distribute slack proportionally between `col_min` and `col_max`.

Tables that don't fit on a single page are split across pages with the
header row repeated at the top of each continuation page. A minimum of
2 body rows must fit alongside the header; if there isn't enough space
for that, a page break is inserted first.
"""
from markdown_it.token import Token
from ..inline import RichSegment, render_rich, measure_rich, measure_extent
from ..constants import Align, MM_TO_PT
from .md_images import (
  load_image_info, size_cell, cell_intrinsic_w_mm, ImageInfo,
)

#----------------------------------------------------------------------------------- TableMixin
class TableMixin:

  def _extract_cell_image(self, inline_token:Token|None) -> ImageInfo|None:
    """If a cell contains only a single local image, return its `ImageInfo`.

    Cells with mixed content, multiple images, or remote URLs return `None`
    and flow through the regular `render_rich` path _(inline icon-sized)_.
    """
    if inline_token is None:
      return None
    children = inline_token.children or []
    nontrivial = [c for c in children if c.type not in ("softbreak", "hardbreak")]
    if len(nontrivial) != 1 or nontrivial[0].type != "image":
      return None
    img = nontrivial[0]
    img_attrs = img.attrs if isinstance(img.attrs, dict) else dict(img.attrs or [])
    src = img_attrs.get("src", "")
    if not src or src.startswith(("http://", "https://")):
      return None
    return load_image_info(
      src, attrs=img_attrs, alt=img.content or "",
      default_dpi=self.style.image_dpi,
    )

  def _render_table(self, tokens:list[Token], start:int) -> int:
    s = self.style
    end = self._find_close(tokens, start, "table_open", "table_close")
    header_cells: list[Token|None] = []
    body_rows: list[list[Token|None]] = []
    aligns: list[str] = []
    in_header = False
    current_row: list[Token|None] = []
    j = start + 1
    while j < end:
      t = tokens[j]
      if t.type == "thead_open": in_header = True
      elif t.type == "thead_close": in_header = False
      elif t.type == "tr_open": current_row = []
      elif t.type == "tr_close":
        if in_header: header_cells = current_row
        else: body_rows.append(current_row)
      elif t.type in ("th_open", "td_open"):
        if t.type == "th_open":
          style_attr = self._get_attr(t, "style") or ""
          if "center" in style_attr: aligns.append(Align.CENTER)
          elif "right" in style_attr: aligns.append(Align.RIGHT)
          else: aligns.append(Align.LEFT)
        close_type = "th_close" if t.type == "th_open" else "td_close"
        k = j + 1
        cell_inline: Token|None = None
        while k < end and tokens[k].type != close_type:
          if tokens[k].type == "inline":
            cell_inline = tokens[k]
          k += 1
        current_row.append(cell_inline)
        j = k
      j += 1
    if not aligns:
      ncols = len(header_cells) if header_cells else (
        len(body_rows[0]) if body_rows else 1)
      aligns = [Align.LEFT] * ncols
    # Header-only table (no body rows) is virtually always a headerless layout
    # — markdown tables require a header per spec, so users emulate "card" or
    # "labeled-row" tables by writing one row + separator. Demote to body.
    if header_cells and not body_rows:
      body_rows = [header_cells]
      header_cells = []
    self._reset_stroke()
    self._draw_md_table(header_cells, body_rows, aligns)
    self._reset_stroke()
    self.pdf.enter(s.para_gap)
    return end + 1

  #--------------------------------------------------------------------------------- Layout

  def _draw_md_table(
    self,
    header: list[Token|None],
    body: list[list[Token|None]],
    aligns: list[str],
  ):
    """Draw a markdown table, splitting across pages when needed.
    Header is repeated at the top of each continuation page.
    """
    s = self.style
    pdf = self.pdf
    x_start = self._indent_mm
    total_w = pdf.content_width - x_start
    ncols = len(header) if header else (len(body[0]) if body else 1)
    h_pad = s.table_h_pad
    v_pad = s.table_pad
    text_top_offset = s.body_size * 0.30 / MM_TO_PT

    def cell_data(inline_token:Token|None, bold:bool) -> dict:
      """Convert one cell to a render-ready dict.
      Single-image cells get block-style sizing; everything else is `text` with
      a list of `RichSegment`s for `render_rich`.
      """
      img = self._extract_cell_image(inline_token)
      if img is not None:
        return {"type": "image", "info": img}
      fallback = [RichSegment(
        text=" ", family=s.body_family,
        mode=s.bold_mode if bold else s.body_mode,
        size=s.body_size, color=s.body_color,
      )]
      if inline_token is None:
        return {"type": "text", "segs": fallback}
      base = RichSegment(
        text="", family=s.body_family,
        mode=s.bold_mode if bold else s.body_mode,
        size=s.body_size, color=s.body_color,
      )
      segs = self._inline_to_segments(inline_token, base) or fallback
      return {"type": "text", "segs": segs}

    # Pre-convert all cells (reused across pages)
    header_data: list[dict] = []
    if header:
      header_data = [cell_data(c, bold=True) for c in header]
    body_data: list[list[dict]] = [
      [cell_data(c, bold=False) for c in row] for row in body
    ]

    # Column widths (calculated once from ALL rows, stays constant across pages)
    col_widths, text_width_mm = self._compute_col_widths(
      header_data, body_data, ncols, total_w, h_pad)

    # Row heights (pre-measured, reused)
    min_row_h = s.body_size * s.line_height / MM_TO_PT + v_pad * 2

    # Inline cap reused everywhere — derived from style
    inline_cap_mm = s.inline_image_max_h

    def cell_height(cd:dict, text_w_mm:float) -> float:
      """Height (mm) of a single cell's content at given column text-width."""
      if cd["type"] == "image":
        _, h = size_cell(
          cd["info"], text_w_mm, s.image_max_h, inline_cap_mm,
          cell_image_max_w_mm=s.cell_image_max_w,
          cell_image_scale=s.cell_image_scale,
        )
        return h
      return measure_rich(pdf, cd["segs"], text_w_mm, line_gap=s.line_height)

    def row_height(cells:list[dict]) -> tuple[float, list[float]]:
      per_cell: list[float] = []
      max_h = 0.0
      for idx, cd in enumerate(cells):
        h = cell_height(cd, text_width_mm[idx])
        per_cell.append(h)
        if h > max_h: max_h = h
      return max(max_h + v_pad * 2, min_row_h), per_cell

    header_h = 0.0
    header_cell_h: list[float] = []
    if header_data:
      header_h, header_cell_h = row_height(header_data)

    body_heights: list[float] = []
    body_cell_heights: list[list[float]] = []
    for row in body_data:
      rh, pch = row_height(row)
      body_heights.append(rh)
      body_cell_heights.append(pch)

    # Render in chunks across pages
    row_idx = 0
    total_body = len(body_data)
    min_rows = 2  # minimum body rows per chunk (with header)
    tried_new_page = False  # guard: don't loop forever on rows taller than a page

    while row_idx < total_body:
      avail = pdf.content_height - pdf.y

      # How many rows fit on this page?
      needed = header_h
      fit_count = 0
      for i in range(row_idx, total_body):
        needed += body_heights[i]
        if needed > avail:
          break
        fit_count += 1

      if fit_count >= total_body - row_idx:
        # All remaining rows fit - render final chunk
        pass
      elif fit_count < min_rows and not tried_new_page:
        # Can't fit minimum rows - page break, try again with full page
        pdf.new_page()
        tried_new_page = True
        continue
      # else: fresh page already tried, render what we can (at least 1 row)

      # Force at least 1 row even if it overflows the page; otherwise rows
      # taller than `content_height` would loop forever.
      chunk_count = max(fit_count, 1)
      chunk_count = min(chunk_count, total_body - row_idx)

      chunk_body_data = body_data[row_idx:row_idx + chunk_count]
      chunk_body_heights = body_heights[row_idx:row_idx + chunk_count]
      chunk_body_cell_h = body_cell_heights[row_idx:row_idx + chunk_count]

      self._draw_table_chunk(
        header_data, header_h, header_cell_h,
        chunk_body_data, chunk_body_heights, chunk_body_cell_h,
        aligns, col_widths, text_width_mm,
        x_start, total_w, h_pad, v_pad, text_top_offset,
        row_offset=row_idx,  # for correct zebra striping
      )

      row_idx += chunk_count
      tried_new_page = False

      # Page break between chunks (not after last)
      if row_idx < total_body:
        pdf.new_page()

    # Handle empty table (header only, no body)
    if total_body == 0 and header_data:
      self._ensure_space(header_h)
      self._draw_table_chunk(
        header_data, header_h, header_cell_h,
        [], [], [],
        aligns, col_widths, text_width_mm,
        x_start, total_w, h_pad, v_pad, text_top_offset,
        row_offset=0,
      )

  #----------------------------------------------------------------------------- Column widths

  def _compute_col_widths(
    self,
    header_data: list[dict],
    body_data: list[list[dict]],
    ncols: int,
    total_w: float,
    h_pad: float,
  ) -> tuple[list[float], list[float]]:
    """HTML-style auto layout. Returns (col_widths, text_width_mm).
    Image cells contribute their natural width as both min and max (they
    can scale down when the column is narrower).
    """
    pdf = self.pdf
    s = self.style
    # Separate text vs image contributions per col so a single image-only row
    # can't pin the column's max width when other rows have wider text.
    # Without this, "| ![](icon.png) | x |" + "| long descriptive text | y |"
    # in the same col would force col width to icon size, wrapping the text.
    col_min_text = [0.0] * ncols
    col_max_text = [0.0] * ncols
    col_min_img = [0.0] * ncols
    col_max_img = [0.0] * ncols
    has_text = [False] * ncols
    has_image = [False] * ncols
    all_rows: list[list[dict]] = []
    if header_data:
      all_rows.append(header_data)
    all_rows.extend(body_data)
    for cells in all_rows:
      for i, cd in enumerate(cells):
        if i >= ncols:
          break
        if cd["type"] == "image":
          mw, tw = cell_intrinsic_w_mm(
            cd["info"], s.inline_image_max_h, s.cell_image_max_w,
            cell_image_scale=s.cell_image_scale,
          )
          if mw > col_min_img[i]: col_min_img[i] = mw
          if tw > col_max_img[i]: col_max_img[i] = tw
          has_image[i] = True
        else:
          mw, tw = measure_extent(pdf, cd["segs"])
          if mw > col_min_text[i]: col_min_text[i] = mw
          if tw > col_max_text[i]: col_max_text[i] = tw
          has_text[i] = True
    col_min: list[float] = []
    col_max: list[float] = []
    for i in range(ncols):
      # col_min: largest of either image col_min or text col_min (wider must fit)
      cmin = max(col_min_img[i], col_min_text[i])
      # col_max: prefer text width when both present; pure-image cols use img max
      if has_text[i]:
        cmax = max(col_max_text[i], col_min_img[i])  # text width, but at least image min
      else:
        cmax = col_max_img[i]
      col_min.append(cmin)
      col_max.append(cmax)
    col_min = [m + 2 * h_pad for m in col_min]
    col_max = [m + 2 * h_pad for m in col_max]
    is_image_col = has_image  # used by leftover-distribution to pin pure-image cols
    sum_max = sum(col_max)
    sum_min = sum(col_min)
    if sum_max <= total_w:
      # Distribute leftover only to non-image cols. Image cols stay at col_max
      # — letting them grow makes the image puff up to fill, which is wrong
      # in tables with sparse content.
      col_widths = list(col_max)
      leftover = total_w - sum_max
      growable = [i for i in range(ncols) if not is_image_col[i]]
      if leftover > 0 and growable:
        per = leftover / len(growable)
        for i in growable:
          col_widths[i] += per
      elif leftover > 0:
        per = leftover / ncols
        col_widths = [w + per for w in col_widths]
    elif sum_min >= total_w:
      scale = total_w / sum_min
      col_widths = [m * scale for m in col_min]
    else:
      # Overflow: solver shrinks each col proportionally between min and max.
      # Image cols treated as text — they shrink alongside, but their col_min
      # is icon-scale, so they never go below that floor.
      slack = total_w - sum_min
      diffs = [col_max[i] - col_min[i] for i in range(ncols)]
      sum_diff = sum(diffs)
      if sum_diff <= 0:
        col_widths = [total_w / ncols] * ncols
      else:
        col_widths = [
          col_min[i] + slack * (diffs[i] / sum_diff) for i in range(ncols)
        ]
    text_width_mm = [max(1.0, cw - 2 * h_pad) for cw in col_widths]
    # Balance image cols vs text cols so cell heights match where possible.
    # Solves: image_h(w_img) ≈ text_h(w_text) under fixed budget per image col.
    col_widths, text_width_mm = self._balance_image_cols(
      col_widths, text_width_mm, all_rows, is_image_col, has_text,
      ncols, total_w, h_pad, col_min,
    )
    return col_widths, text_width_mm

  def _balance_image_cols(
    self,
    col_widths: list[float],
    text_width_mm: list[float],
    all_rows: list[list[dict]],
    is_image_col: list[bool],
    has_text: list[bool],
    ncols: int,
    total_w: float,
    h_pad: float,
    col_min: list[float],
  ) -> tuple[list[float], list[float]]:
    """Reflow widths so each pure-image col's rendered height matches the
    height of its widest text-col partner. Skipped for mixed cols (image
    rows + text rows in the same col) — there the col already needs full
    text width and balancing would crush wider text rows.

    Donor cols are non-image cols only.

    Math per image col `i` against partner text col `j`:
      image_h(w_i) = w_text_i × aspect_mean
      text_h(w_j)  ≈ chars_per_row × char_w_avg × line_h / w_text_j
                   = K / w_text_j
    Budget: w_i + w_j = w_i_orig + w_j_orig (preserve sum, redistribute).
    Solve `w_i × aspect = K / (budget - w_i)` → quadratic in w_i.
    """
    if not any(is_image_col) or ncols < 2:
      return col_widths, text_width_mm
    pdf = self.pdf
    s = self.style
    line_h_mm = s.body_size * s.line_height / MM_TO_PT
    char_w_pt = pdf._metrics.text_width("M", s.body_family, s.body_mode, s.body_size)
    char_w_mm = char_w_pt / MM_TO_PT
    for ic in range(ncols):
      if not is_image_col[ic]:
        continue
      if has_text[ic]:
        continue  # Mixed col: text rows need full width, balancer would crush them
      # Aspect (h/w) average of all image cells in this col
      aspects = []
      for row in all_rows:
        if ic < len(row) and row[ic]["type"] == "image":
          info = row[ic]["info"]
          if info.nat_w_mm > 0:
            aspects.append(info.nat_h_mm / info.nat_w_mm)
      if not aspects: continue
      aspect = sum(aspects) / len(aspects)
      # Find partner: widest non-image col with text in same rows
      partners = [j for j in range(ncols) if j != ic and not is_image_col[j]]
      if not partners: continue
      tc = max(partners, key=lambda j: col_widths[j])
      # Estimate text "char-area" K_max across rows (use widest row's text)
      K = 0.0
      for row in all_rows:
        if tc >= len(row) or row[tc]["type"] != "text":
          continue
        # Sum of segment widths approximates char-area: (total_text_w_mm × line_h)
        from ..inline import measure_extent
        _, text_w_mm = measure_extent(pdf, row[tc]["segs"])
        k = text_w_mm * line_h_mm
        if k > K: K = k
      if K <= 0: continue
      # Bias: aim for image_h = text_h × bias. Bias < 1 makes images smaller
      # when text is short. Equivalent to inflating the text-K by 1/bias².
      K = K / (s.cell_image_balance_bias ** 2)
      budget = col_widths[ic] + col_widths[tc]
      pad2 = 2 * h_pad
      # Solve aspect × w_i_text² − aspect × (budget − pad2 × 2) × w_i_text + K = 0
      # where w_i_text = w_i_col − pad2; same for w_j.
      # Easier: work in "text widths" directly: budget_text = budget − 4*h_pad
      budget_text = budget - 2 * pad2
      if budget_text <= 0: continue
      # aspect × w_i² − aspect × budget_text × w_i + K = 0
      a = aspect
      b = -aspect * budget_text
      c = K
      disc = b*b - 4*a*c
      if disc < 0:
        # text dominates - give image its min, text gets rest
        w_i_text = max(col_min[ic] - pad2, 1.0)
      else:
        # Pick smaller root (image not too wide)
        w_i_text = (-b - disc**0.5) / (2 * a)
      # Clamp to [col_min, col_max range derived from current widths]
      img_min_text = col_min[ic] - pad2
      img_max_text = col_widths[ic] - pad2  # don't grow image beyond linear-solver result
      # But allow grow up to half of budget if text is heavy
      img_max_text = max(img_max_text, budget_text * 0.45)
      w_i_text = max(img_min_text, min(w_i_text, img_max_text))
      w_j_text = budget_text - w_i_text
      # Don't shrink partner below its existing min
      partner_min_text = col_min[tc] - pad2
      if w_j_text < partner_min_text:
        w_j_text = partner_min_text
        w_i_text = budget_text - w_j_text
      col_widths[ic] = w_i_text + pad2
      col_widths[tc] = w_j_text + pad2
      text_width_mm[ic] = max(1.0, w_i_text)
      text_width_mm[tc] = max(1.0, w_j_text)
    return col_widths, text_width_mm

  #----------------------------------------------------------------------------- Chunk renderer

  def _draw_table_chunk(
    self,
    header_data: list[dict],
    header_h: float,
    header_cell_h: list[float],
    body_data: list[list[dict]],
    body_heights: list[float],
    body_cell_heights: list[list[float]],
    aligns: list[str],
    col_widths: list[float],
    text_width_mm: list[float],
    x_start: float,
    total_w: float,
    h_pad: float,
    v_pad: float,
    text_top_offset: float,
    row_offset: int = 0,
  ):
    """Render one chunk of a table: header + a subset of body rows.
    `row_offset` is the global row index of the first body row in this chunk,
    used for correct zebra stripe continuity across pages.
    """
    s = self.style
    pdf = self.pdf
    y = pdf.y
    chunk_body_h = sum(body_heights)
    chunk_h = header_h + chunk_body_h

    # Header background
    if header_data:
      pdf.cursor(x_start, y)
      pdf.color(*s.table_header_bg[:3])
      pdf.rect(total_w, header_h)

    # Zebra striping (uses row_offset for global index continuity)
    if s.table_zebra:
      y_zebra = y + header_h
      for idx, rh in enumerate(body_heights):
        global_idx = row_offset + idx
        if global_idx % 2 == 1:
          pdf.cursor(x_start, y_zebra)
          pdf.color(*s.table_zebra_bg[:3])
          pdf.rect(total_w, rh)
        y_zebra += rh
    pdf.color_black()

    # Horizontal lines
    pdf.stroke_color(*s.table_border[:3])
    pdf.cursor(x_start, y)
    pdf.line(total_w, 0, s.table_border_thick)
    if header_data:
      pdf.cursor(x_start, y + header_h)
      pdf.line(total_w, 0, s.table_header_thick)
    y_running = y + header_h
    for rh in body_heights:
      y_running += rh
      pdf.cursor(x_start, y_running)
      pdf.line(total_w, 0, s.table_border_thick)

    # Vertical lines
    x_cursor = x_start
    pdf.cursor(x_cursor, y)
    pdf.line(0, chunk_h, s.table_border_thick)
    for w in col_widths:
      x_cursor += w
      pdf.cursor(x_cursor, y)
      pdf.line(0, chunk_h, s.table_border_thick)
    self._reset_stroke()

    # Header content
    if header_data:
      x_cell = x_start
      for idx, cd in enumerate(header_data):
        cw = col_widths[idx]
        align = aligns[idx] if idx < len(aligns) else Align.LEFT
        cell_h = header_cell_h[idx]
        self._draw_cell(
          cd, x_cell, y, cw, header_h, text_width_mm[idx], cell_h,
          align, h_pad, text_top_offset,
        )
        x_cell += cw

    # Body content
    y_row = y + header_h
    for ri, row in enumerate(body_data):
      x_cell = x_start
      row_h = body_heights[ri]
      for idx, cd in enumerate(row):
        cw = col_widths[idx] if idx < len(col_widths) else col_widths[-1]
        align = aligns[idx] if idx < len(aligns) else Align.LEFT
        cell_h = body_cell_heights[ri][idx]
        self._draw_cell(
          cd, x_cell, y_row, cw, row_h, text_width_mm[idx], cell_h,
          align, h_pad, text_top_offset,
        )
        x_cell += cw
      y_row += row_h

    pdf.cursor(x_start, y + chunk_h)

  def _draw_cell(
    self, cd:dict, x_cell:float, y_cell:float, cw:float, row_h:float,
    text_w_mm:float, cell_h:float, align:str, h_pad:float, text_top_offset:float,
  ):
    """Render one cell. Dispatches on `cd['type']`: text via render_rich,
    image via pdf.image()/pdf.svg() with column alignment respected.
    """
    s = self.style
    pdf = self.pdf
    if cd["type"] == "image":
      info = cd["info"]
      img_w, img_h = size_cell(
        info, text_w_mm, s.image_max_h, s.inline_image_max_h,
        cell_image_max_w_mm=s.cell_image_max_w,
        cell_image_scale=s.cell_image_scale,
      )
      # Position by column alignment (matches GitHub / VSCode preview)
      if align == Align.RIGHT:
        x_img = x_cell + cw - img_w - h_pad
      elif align == Align.CENTER:
        x_img = x_cell + (cw - img_w) / 2
      else:
        x_img = x_cell + h_pad
      y_img = y_cell + (row_h - img_h) / 2
      pdf.cursor(x_img, y_img)
      if info.is_svg:
        pdf.svg(info.src, img_w, img_h)
      else:
        pdf.image(info.src, img_w, img_h)
      return
    v_offset = (row_h - cell_h) / 2
    render_rich(
      pdf, cd["segs"], text_w_mm,
      x_cell + h_pad, y_cell + v_offset + text_top_offset,
      align, s.line_height,
    )