# pdfmarq/styles.py

"""Style system with inheritance support."""
from dataclasses import dataclass, fields, replace
from .constants import Defaults, Align

#---------------------------------------------------------------------------------------- Style

@dataclass
class Style:
  """Text/element style with inheritance support.

  None values inherit from parent style when merged.
  """
  font_family: str|None = None
  font_mode: str|None = None
  font_size: float|None = None
  color: tuple|None = None
  align: str|None = None
  line_height: float|None = None
  padding: float|None = None

  def merge(self, parent:"Style") -> "Style":
    """Create new style inheriting None values from parent."""
    result = Style()
    for f in fields(self):
      child_val = getattr(self, f.name)
      parent_val = getattr(parent, f.name)
      setattr(result, f.name, child_val if child_val is not None else parent_val)
    return result

  def with_defaults(self) -> "Style":
    """Fill None values with defaults."""
    return Style(
      font_family=self.font_family or Defaults.FONT_FAMILY,
      font_mode=self.font_mode or Defaults.FONT_MODE,
      font_size=self.font_size or Defaults.FONT_SIZE,
      color=self.color or (0, 0, 0),
      align=self.align or Align.LEFT,
      line_height=self.line_height or Defaults.LINE_HEIGHT,
      padding=self.padding or 0,
    )

  def copy(self, **overrides) -> "Style":
    """Create copy with overridden values."""
    valid = {k: v for k, v in overrides.items() if k in {f.name for f in fields(self)}}
    return replace(self, **valid)

#----------------------------------------------------------------------------------- TableStyle

@dataclass
class TableStyle:
  """Table-specific styling."""
  header_bg: tuple = (0.5, 0.5, 0.5, 0.5)
  header_font_mode: str = "Bold"
  row_bg_even: tuple = (0.9, 0.9, 0.9, 0.5)
  row_bg_odd: tuple = (0.8, 0.8, 0.8, 0.5)
  border_color: tuple = (0, 0, 0) # stroke color for all table lines
  border_width: float = 0.33
  border_width_header: float = 1.0
  border_width_outer: float = 0.2
  padding: float = 0.5 # horizontal cell padding (mm)
  cell_vpad: float = 0.5 # extra vertical padding per cell (mm)
  header_repeat: bool = True

#-------------------------------------------------------------------------------------- Presets

class _Preset:
  """Descriptor returning a fresh `Style` on each access - prevents shared mutation."""
  def __init__(self, **kwargs):
    self._kwargs = kwargs
  def __get__(self, obj, objtype=None) -> Style:
    return Style(**self._kwargs)

class Styles:
  """Predefined style presets. Each access returns a fresh `Style` instance."""
  DEFAULT  = _Preset()
  BOLD     = _Preset(font_mode="Bold")
  ITALIC   = _Preset(font_mode="Italic")
  HEADING1 = _Preset(font_size=24, font_mode="Bold")
  HEADING2 = _Preset(font_size=18, font_mode="Bold")
  HEADING3 = _Preset(font_size=14, font_mode="Bold")
  SMALL    = _Preset(font_size=10)
  CAPTION  = _Preset(font_size=9, font_mode="Italic")
