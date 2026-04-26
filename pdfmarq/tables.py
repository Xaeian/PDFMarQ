# pdfmarq/tables.py

"""Table rendering with page break support."""
from dataclasses import dataclass, field
from .styles import TableStyle
from .text import TextMetrics
from .constants import Align, MM_TO_PT

#----------------------------------------------------------------------------------------- Cell

@dataclass
class Cell:
  """Table cell data."""
  text: str = ""
  colspan: int = 1
  rowspan: int = 1
  align: str|None = None
  style: dict|None = None

#------------------------------------------------------------------------------------ TableData

@dataclass
class TableData:
  """Prepared table data for rendering."""
  header: list[str]|None = None
  header_fitted: list[str]|None = None
  header_height: float = 0
  body: list[list[str]] = field(default_factory=list)
  body_fitted: list[list[str]] = field(default_factory=list)
  body_heights: list[float] = field(default_factory=list)
  column_widths: list[float] = field(default_factory=list)
  column_aligns: list[str] = field(default_factory=list)
  total_width: float = 0
  total_height: float = 0

#--------------------------------------------------------------------------------- TableBuilder

class TableBuilder:
  """Builds and prepares table for rendering."""
  def __init__(self, metrics:TextMetrics, style:TableStyle|None=None):
    self.metrics = metrics
    self.style = style or TableStyle()
    self._header: list[str]|None = None
    self._body: list[list[str]] = []
    self._col_sizes: list[float] = []
    self._col_aligns: list[str] = []
    self._width: float|None = None

  def header(self, cells:list[str]) -> "TableBuilder":
    self._header = cells
    return self

  def row(self, cells:list[str]) -> "TableBuilder":
    self._body.append(cells)
    return self

  def rows(self, rows:list[list[str]]) -> "TableBuilder":
    self._body.extend(rows)
    return self

  def columns(self, sizes:list[float], aligns:list[str]|None=None) -> "TableBuilder":
    self._col_sizes = sizes
    self._col_aligns = aligns or [Align.LEFT] * len(sizes)
    return self

  def width(self, width:float) -> "TableBuilder":
    self._width = width
    return self

  def build(
    self,
    available_width: float,  # mm
    font_family: str = "Helvetica",
    font_mode: str = "Regular",
    font_size: float = 11,
  ) -> TableData:
    """Prepare table data for rendering. Pure - does not mutate builder state."""
    width = self._width if self._width is not None else available_width
    padding = self.style.padding
    fallback_h = font_size * 1.2  # pt: used when `box_fit` flags overflow
    # Local column config - don't mutate self across repeated `build` calls
    col_sizes = list(self._col_sizes)
    if not col_sizes:
      ncols = (len(self._header) if self._header
        else len(self._body[0]) if self._body else 1)
      col_sizes = [1] * ncols
    total_size = sum(col_sizes) or 1
    col_widths = [width * (s / total_size) for s in col_sizes]
    col_aligns = list(self._col_aligns)
    while len(col_aligns) < len(col_widths):
      col_aligns.append(Align.LEFT)
    # mm → pt for text fitting
    widths_pt = [(w - 2 * padding) * MM_TO_PT for w in col_widths]
    data = TableData(
      column_widths=col_widths,
      column_aligns=col_aligns,
      total_width=width,
    )
    if self._header:
      fit = self.metrics.box_fit_array(
        self._header, widths_pt,
        family=font_family,
        mode=self.style.header_font_mode,
        size=font_size,
      )
      data.header = self._header
      data.header_fitted = fit["text"]
      h = _max_height(fit["height"], fallback_h)
      data.header_height = (h / MM_TO_PT) + self.style.cell_vpad + self.style.header_extra
    data.body = self._body
    for row in self._body:
      fit = self.metrics.box_fit_array(
        row, widths_pt,
        family=font_family, mode=font_mode, size=font_size,
      )
      data.body_fitted.append(fit["text"])
      h = _max_height(fit["height"], fallback_h)
      data.body_heights.append((h / MM_TO_PT) + self.style.cell_vpad)
    data.total_height = data.header_height + sum(data.body_heights)
    return data

#-------------------------------------------------------------------------------- Legacy helper

def prepare_table(
  body: list[list[str]],
  header: list[str]|None,
  col_sizes: list[float],
  col_aligns: list[str],
  width: float,
  metrics: TextMetrics,
  style: TableStyle|None = None,
  font_family: str = "Helvetica",
  font_mode: str = "Regular",
  font_size: float = 11,
) -> TableData:
  """Prepare table data - convenience function."""
  builder = TableBuilder(metrics, style)
  if header:
    builder.header(header)
  builder.rows(body).columns(col_sizes, col_aligns).width(width)
  return builder.build(width, font_family, font_mode, font_size)

#-------------------------------------------------------------------------------------- Helpers

def _max_height(heights:list, fallback:float) -> float:
  """Max of heights, filtering None from `box_fit` edge cases."""
  valid = [h for h in heights if h is not None]
  return max(valid) if valid else fallback
