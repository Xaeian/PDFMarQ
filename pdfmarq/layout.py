# pdfmarq/layout.py

"""Layout system - cursor positioning, alignment, page geometry."""
from dataclasses import dataclass, replace
from .constants import Align

#--------------------------------------------------------------------------------------- Cursor

@dataclass
class Cursor:
  """Position tracker with alignment and auto-advance."""
  x: float = 0
  y: float = 0
  x_base: float = 0  # x position after enter()
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
    """Advance x past an element of `width` based on alignment.

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

#--------------------------------------------------------------------------------- PageGeometry

@dataclass
class PageGeometry:
  """Page dimensions and margins (all in mm). CSS-style margins - left and
  right can differ. `margin_lr` is a back-compat alias for symmetric setups."""
  width: float
  height: float
  margin_top: float = 20
  margin_right: float = 20
  margin_bot: float = 20
  margin_left: float = 20

  @property
  def margin_lr(self) -> float:
    """Back-compat alias for the symmetric left/right margin. Reads return
    `margin_left`; writes set both sides to the same value."""
    return self.margin_left

  @margin_lr.setter
  def margin_lr(self, value:float) -> None:
    """Set both `margin_left` and `margin_right` to the same value."""
    self.margin_left = value
    self.margin_right = value

  @property
  def content_width(self) -> float:
    """Available width for content."""
    return self.width - self.margin_left - self.margin_right

  @property
  def content_height(self) -> float:
    """Available height for content."""
    return self.height - self.margin_top - self.margin_bot

  def x_for_align(self, width:float, align:str) -> float:
    """Calculate x position for given alignment and element width."""
    if align == Align.LEFT:
      return self.margin_left
    elif align == Align.CENTER:
      return (self.width - width) / 2
    elif align == Align.RIGHT:
      return self.width - self.margin_right - width
    return self.margin_left

  def cursor_to_canvas(self, cursor:Cursor, width:float=0) -> tuple[float, float]:
    """Convert cursor position to canvas coordinates (mm).

    Cursor: origin top-left, y grows down
    Canvas: origin bottom-left, y grows up
    Returns (x_mm, y_mm) in canvas coordinates.
    """
    x = cursor.x
    y = self.height - cursor.y - self.margin_top
    if cursor.align == Align.LEFT:
      x += self.margin_left
    elif cursor.align == Align.CENTER:
      x += (self.width - width) / 2
    elif cursor.align == Align.RIGHT:
      x += self.width - self.margin_right - width
    return x, y
