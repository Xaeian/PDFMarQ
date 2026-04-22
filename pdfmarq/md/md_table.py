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

#----------------------------------------------------------------------------------- TableMixin
class TableMixin:

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
    h_pad = 2
    v_pad = s.table_pad
    text_top_offset = s.body_size * 0.30 / MM_TO_PT

    def cell_segments(inline_token:Token|None, bold:bool) -> list[RichSegment]:
      fallback = [RichSegment(
        text=" ", family=s.body_family,
        mode=s.bold_mode if bold else s.body_mode,
        size=s.body_size, color=s.body_color,
      )]
      if inline_token is None:
        return fallback
      base = RichSegment(
        text="", family=s.body_family,
        mode=s.bold_mode if bold else s.body_mode,
        size=s.body_size, color=s.body_color,
      )
      return self._inline_to_segments(inline_token, base) or fallback

    # Pre-convert all cells to segments (reused across pages)
    header_segs: list[list[RichSegment]] = []
    if header:
      header_segs = [cell_segments(cell, bold=True) for cell in header]
    body_segs: list[list[list[RichSegment]]] = [
      [cell_segments(cell, bold=False) for cell in row] for row in body
    ]

    # Column widths (calculated once from ALL rows, stays constant across pages)
    col_widths, text_width_mm = self._compute_col_widths(
      header_segs, body_segs, ncols, total_w, h_pad)

    # Row heights (pre-measured, reused)
    min_row_h = s.body_size * 1.2 / MM_TO_PT + v_pad * 2

    def row_height(cells:list[list[RichSegment]]) -> tuple[float, list[float]]:
      per_cell: list[float] = []
      max_h = 0.0
      for idx, segs in enumerate(cells):
        h = measure_rich(pdf, segs, text_width_mm[idx], line_gap=s.line_height)
        per_cell.append(h)
        if h > max_h: max_h = h
      return max(max_h + v_pad * 2, min_row_h), per_cell

    header_h = 0.0
    header_cell_h: list[float] = []
    if header_segs:
      header_h, header_cell_h = row_height(header_segs)

    body_heights: list[float] = []
    body_cell_heights: list[list[float]] = []
    for segs in body_segs:
      rh, pch = row_height(segs)
      body_heights.append(rh)
      body_cell_heights.append(pch)

    # Render in chunks across pages
    row_idx = 0
    total_body = len(body_segs)
    min_rows = 2  # minimum body rows per chunk (with header)

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
      elif fit_count < min_rows:
        # Can't fit minimum rows - page break, try again with full page
        pdf.new_page()
        continue

      # Clamp to at least min_rows (already guaranteed by check above)
      chunk_count = max(fit_count, min_rows) if fit_count > 0 else total_body - row_idx
      chunk_count = min(chunk_count, total_body - row_idx)

      chunk_body_segs = body_segs[row_idx:row_idx + chunk_count]
      chunk_body_heights = body_heights[row_idx:row_idx + chunk_count]
      chunk_body_cell_h = body_cell_heights[row_idx:row_idx + chunk_count]

      self._draw_table_chunk(
        header_segs, header_h, header_cell_h,
        chunk_body_segs, chunk_body_heights, chunk_body_cell_h,
        aligns, col_widths, text_width_mm,
        x_start, total_w, h_pad, v_pad, text_top_offset,
        row_offset=row_idx,  # for correct zebra striping
      )

      row_idx += chunk_count

      # Page break between chunks (not after last)
      if row_idx < total_body:
        pdf.new_page()

    # Handle empty table (header only, no body)
    if total_body == 0 and header_segs:
      self._ensure_space(header_h)
      self._draw_table_chunk(
        header_segs, header_h, header_cell_h,
        [], [], [],
        aligns, col_widths, text_width_mm,
        x_start, total_w, h_pad, v_pad, text_top_offset,
        row_offset=0,
      )

  #----------------------------------------------------------------------------- Column widths

  def _compute_col_widths(
    self,
    header_segs: list[list[RichSegment]],
    body_segs: list[list[list[RichSegment]]],
    ncols: int,
    total_w: float,
    h_pad: float,
  ) -> tuple[list[float], list[float]]:
    """HTML-style auto layout. Returns (col_widths, text_width_mm)."""
    pdf = self.pdf
    col_min = [0.0] * ncols
    col_max = [0.0] * ncols
    all_rows: list[list[list[RichSegment]]] = []
    if header_segs:
      all_rows.append(header_segs)
    all_rows.extend(body_segs)
    for cells in all_rows:
      for i, cell in enumerate(cells):
        if i >= ncols:
          break
        mw, tw = measure_extent(pdf, cell)
        if mw > col_min[i]: col_min[i] = mw
        if tw > col_max[i]: col_max[i] = tw
    col_min = [m + 2 * h_pad for m in col_min]
    col_max = [m + 2 * h_pad for m in col_max]
    sum_max = sum(col_max)
    sum_min = sum(col_min)
    if sum_max <= total_w:
      col_widths = list(col_max)
      leftover = total_w - sum_max
      if leftover > 0 and ncols > 0:
        per = leftover / ncols
        col_widths = [w + per for w in col_widths]
    elif sum_min >= total_w:
      scale = total_w / sum_min
      col_widths = [m * scale for m in col_min]
    else:
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
    return col_widths, text_width_mm

  #----------------------------------------------------------------------------- Chunk renderer

  def _draw_table_chunk(
    self,
    header_segs: list[list[RichSegment]],
    header_h: float,
    header_cell_h: list[float],
    body_segs: list[list[list[RichSegment]]],
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
    if header_segs:
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
    pdf.line(total_w, 0, 0.3)
    if header_segs:
      pdf.cursor(x_start, y + header_h)
      pdf.line(total_w, 0, 0.5)
    y_running = y + header_h
    for rh in body_heights:
      y_running += rh
      pdf.cursor(x_start, y_running)
      pdf.line(total_w, 0, 0.3)

    # Vertical lines
    x_cursor = x_start
    pdf.cursor(x_cursor, y)
    pdf.line(0, chunk_h, 0.3)
    for w in col_widths:
      x_cursor += w
      pdf.cursor(x_cursor, y)
      pdf.line(0, chunk_h, 0.3)
    self._reset_stroke()

    # Header text
    if header_segs:
      x_cell = x_start
      for idx, segs in enumerate(header_segs):
        cw = col_widths[idx]
        align = aligns[idx] if idx < len(aligns) else Align.LEFT
        cell_h = header_cell_h[idx]
        v_offset = (header_h - cell_h) / 2
        render_rich(
          pdf, segs, text_width_mm[idx],
          x_cell + h_pad, y + v_offset + text_top_offset,
          align, s.line_height,
        )
        x_cell += cw

    # Body text
    y_row = y + header_h
    for ri, row_segs in enumerate(body_segs):
      x_cell = x_start
      row_h = body_heights[ri]
      for idx, segs in enumerate(row_segs):
        cw = col_widths[idx] if idx < len(col_widths) else col_widths[-1]
        align = aligns[idx] if idx < len(aligns) else Align.LEFT
        cell_h = body_cell_heights[ri][idx]
        v_offset = (row_h - cell_h) / 2
        render_rich(
          pdf, segs, text_width_mm[idx],
          x_cell + h_pad, y_row + v_offset + text_top_offset,
          align, s.line_height,
        )
        x_cell += cw
      y_row += row_h

    pdf.cursor(x_start, y + chunk_h)