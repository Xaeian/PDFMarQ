# pdfmarq/layout.py

"""Layout system - cursor positioning, alignment, page geometry."""
from dataclasses import dataclass, field, replace
from typing import Callable
from .constants import Align

#------------------------------------------------------------------------------------------- Cursor

@dataclass
class Cursor:
  """Position tracker with alignment and auto-advance."""
  x: float = 0
  y: float = 0
  x_base: float = 0 # x position after enter()
  align: str = Align.LEFT
  last_height: float = 0
  last_width: float = 0

  def set(self, x:float|None=None, y:float|None=None, align:str|None=None) -> "Cursor":
    """Set cursor position and/or alignment."""
    if x is not None:
      self.x = x
      self.x_base = x
    if y is not None:
      self.y = y
    if align is not None:
      self.align = align
    self.last_height = 0
    self.last_width = 0
    return self

  def move(self, dx:float=0, dy:float=0) -> "Cursor":
    """Relative cursor movement."""
    self.x += dx
    self.y += dy
    return self

  def enter(self, height:float|None=None) -> "Cursor":
    """Move to new line - reset x to base, advance y."""
    self.x = self.x_base
    self.y += height if height is not None else self.last_height
    self.last_height = 0
    return self

  def advance_x(self, width:float) -> "Cursor":
    """
    Advance x past an element of `width` based on alignment.

    `CENTER` intentionally leaves x untouched: a centered element is anchored
    to the page midline, so the cursor's logical "current x" doesn't change
    after drawing it. Callers chain `enter()` or set a new cursor instead.
    """
    if self.align == Align.LEFT:
      self.x += width
    elif self.align == Align.RIGHT:
      self.x -= width
    # CENTER: no-op by design
    self.last_width = width
    return self

  def record_height(self, height:float) -> "Cursor":
    """Record element height for auto-enter."""
    self.last_height = height
    return self

  def copy(self) -> "Cursor":
    """Create cursor copy."""
    return replace(self)

#------------------------------------------------------------------------------------- PageGeometry

_DIGITS = 9 # places of mm a size keeps: far below a dot, above the noise of float sums

@dataclass
class PageGeometry:
  """
  Page dimensions and margins (all in mm). CSS-style margins - left and right can differ.

  A column is a copy with its margins moved in to the column edges,
  so everything drawn relative to the margins lands inside it.
  `axis` is the line `Align.CENTER` centres on: the page centre when `None`.
  """
  width: float
  height: float
  margin_top: float = 20
  margin_right: float = 20
  margin_bot: float = 20
  margin_left: float = 20
  axis: float|None = None

  @property
  def content_width(self) -> float:
    """
    Available width for content, to `_DIGITS` places: a box `box` cuts out of a sheet
    is as wide on any sheet, so measuring off the page and drawing on it agree.
    """
    return round(self.width - self.margin_left - self.margin_right, _DIGITS)

  @property
  def content_height(self) -> float:
    """Available height for content, to `_DIGITS` places, as `content_width`."""
    return round(self.height - self.margin_top - self.margin_bot, _DIGITS)

  def box(self, left:float, top:float, width:float, height:float) -> "PageGeometry":
    """
    The page narrowed to a box `width` by `height` mm, `left` and `top` from the page's edges:
    its margins move in to the box, so whatever draws relative to them lands inside it.
    """
    return replace(self, margin_left=left, margin_right=self.width - left - width,
      margin_top=top, margin_bot=self.height - top - height, axis=left + width / 2)

  def centered_x(self, width:float) -> float:
    """Left edge of an element of `width` placed on the centre line."""
    if self.axis is None: return (self.width - width) / 2
    return self.axis - width / 2

  def x_for_align(self, width:float, align:str) -> float:
    """Canvas x origin for an element of `width` at the requested alignment."""
    if align == Align.LEFT:
      return self.margin_left
    elif align == Align.CENTER:
      return self.centered_x(width)
    elif align == Align.RIGHT:
      return self.width - self.margin_right - width
    return self.margin_left

  def cursor_to_canvas(self, cursor:Cursor, width:float=0) -> tuple[float, float]:
    """
    Convert cursor position to canvas coordinates (mm).

    Cursor: origin top-left, y grows down
    Canvas: origin bottom-left, y grows up
    Returns (x_mm, y_mm) in canvas coordinates.
    """
    x = cursor.x
    y = self.height - cursor.y - self.margin_top
    if cursor.align == Align.LEFT:
      x += self.margin_left
    elif cursor.align == Align.CENTER:
      x += self.centered_x(width)
    elif cursor.align == Align.RIGHT:
      x += self.width - self.margin_right - width
    return x, y

#------------------------------------------------------------------------------------------ Columns

@dataclass
class Columns:
  """
  Column region open on the current page.

  `top` is where the region starts, in mm below the page's top margin.
  `height` caps the columns on the current page, and `later` on each page after it in turn,
  `None` leaving a page uncapped and a tuple capping each column of it on its own.
  `left` and `right` narrow the region inside the page margins (mm).
  `bottom` is the lowest point any column reached, measured from `top`,
  and `ends` how far down each column of the current page reached, by the time it was left.
  """
  count: int
  gap: float
  flow: bool
  top: float
  height: float|tuple|None = None
  left: float = 0
  right: float = 0
  index: int = 0
  bottom: float = 0
  ends: list = field(default_factory=list)
  later: list = field(default_factory=list)

  def column_width(self, content_width:float) -> float:
    """Width (mm) of each column on a page whose content is `content_width` mm wide."""
    inner = content_width - self.left - self.right
    return (inner - self.gap * (self.count - 1)) / self.count

def lowest_fit(fits:Callable[[float], bool], low:float, high:float, step:float) -> float|None:
  """
  The lowest of `low`, `low + step`, `low + 2 * step` and on up to `high` that `fits`,
  `None` when none does.

  Balanced columns ask it for the height of their last page, `fits` drawing them off the page.
  The heights go one by one from `low`, the even share, near which the answer most often lies,
  since `fits` need not hold above a height that fits:
  a block that does not split, as a bibliography entry, misses a little higher again.
  No height below a block held whole is ruled out: in a lower column it may split.
  """
  height = low
  while not fits(height):
    if height >= high: return None
    height = min(height + step, high)
  return height

#-------------------------------------------------------------------------------------------- Frame

@dataclass
class Frame:
  """
  Box `PDF.frame()` lays content out in, as a page of its own.
  `page` and `cursor` are the page and the cursor it stands in for, put back when it closes.
  `overflow` records content asking for more room than the box holds.
  """
  page: PageGeometry
  cursor: Cursor
  overflow: bool = False
