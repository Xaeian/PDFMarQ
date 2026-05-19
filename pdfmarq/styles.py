# pdfmarq/styles.py

"""Style system with inheritance support."""
from dataclasses import dataclass, fields, replace
from .constants import Defaults, Align

#----------------------------------------------------------------------------------- Helpers

def _as_rgba(color:tuple) -> tuple[float, float, float, float]:
  """Normalize 3-tuple to 4-tuple by appending alpha=1. Pass-through for 4-tuples.

  `Style.color` is canonically 4-tuple - `PDF.color()` writes 4-tuples, and
  fixing `with_defaults` and `_style.color` reads to expect the same shape
  removes a silent inconsistency flagged in review.md.
  """
  if len(color) == 3:
    return (color[0], color[1], color[2], 1.0)
  if len(color) == 4:
    return tuple(color)  # type: ignore[return-value]
  raise ValueError(f"Color must be 3- or 4-tuple, got {len(color)}: {color}")

#---------------------------------------------------------------------------------------- Style

@dataclass
class Style:
  """Text/element style with inheritance support.

  `None` values inherit from parent style when merged.

  Face weight/slant can be expressed two ways:
    - `font_mode` (`"Regular"`/`"Bold"`/`"Italic"`/`"BoldItalic"`): direct
      TTF lookup, matches reportlab font registration.
    - `bold` / `italic` / `underline` / `strike` flags: symmetric with
      `docmarq.Style` for cross-lib parity. `with_defaults()` derives
      `font_mode` from the flags when both are present.
  """
  font_family: str|None = None
  font_mode: str|None = None
  font_size: float|None = None
  color: tuple|None = None
  align: str|None = None
  line_height: float|None = None
  padding: float|None = None
  bold: bool|None = None
  italic: bool|None = None
  underline: bool|None = None
  strike: bool|None = None

  def merge(self, parent:"Style") -> "Style":
    """Create new style inheriting None values from parent."""
    result = Style()
    for f in fields(self):
      child_val = getattr(self, f.name)
      parent_val = getattr(parent, f.name)
      setattr(result, f.name, child_val if child_val is not None else parent_val)
    return result

  def with_defaults(self) -> "Style":
    """Fill `None` values with defaults. If `bold`/`italic` flags are set and
    `font_mode` was not explicitly given, derive `font_mode` from the flags."""
    mode = self.font_mode
    if mode is None and (self.bold or self.italic):
      if self.bold and self.italic: mode = "BoldItalic"
      elif self.bold: mode = "Bold"
      else: mode = "Italic"
    return Style(
      font_family=self.font_family or Defaults.FONT_FAMILY,
      font_mode=mode or Defaults.FONT_MODE,
      font_size=self.font_size or Defaults.FONT_SIZE,
      color=_as_rgba(self.color) if self.color is not None else (0, 0, 0, 1),
      align=self.align or Align.LEFT,
      line_height=self.line_height or Defaults.LINE_HEIGHT,
      padding=self.padding or 0,
      bold=bool(self.bold),
      italic=bool(self.italic),
      underline=bool(self.underline),
      strike=bool(self.strike),
    )

  def copy(self, **overrides) -> "Style":
    """Create copy with overridden values."""
    valid = {k: v for k, v in overrides.items() if k in {f.name for f in fields(self)}}
    return replace(self, **valid)

#----------------------------------------------------------------------------------- TableStyle

@dataclass
class TableStyle:
  """Table styling. Shape mirrors `docmarq.TableStyle` for cross-lib parity.

  Colors accept either `(r, g, b)` 0-1 floats or `#hex` strings. Default
  palette matches GitHub-light - subtle grey header, near-imperceptible
  zebra, light grey borders.

  Some fields are PDF-specific (`border_size_header`, `border_size_outer`,
  `header_gap`) and have no DOCX equivalent - they tune line thickness
  variations and inter-row gaps unique to canvas drawing.
  """
  # Backgrounds
  header_bg: tuple|str = (0.96, 0.97, 0.98)
  header_color: tuple|str|None = None
  header_bold: bool = True
  row_bg_even: tuple|str|None = None
  row_bg_odd: tuple|str|None = (0.985, 0.99, 0.995)
  # Borders
  border_color: tuple|str = (0.82, 0.84, 0.87)
  border_size: float = 0.33
  border_size_header: float = 1.0
  border_size_outer: float = 0.2
  # Cell padding (mm) - asymmetric vertical mirrors docmarq's optical pushdown.
  cell_pad_top: float = 0.5
  cell_pad_bot: float = 0.5
  cell_pad_h: float = 0.5
  # Layout
  header_gap: float = 0.2
  header_repeat: bool = True
  vertical_align: str = "center"
  font_size: float|None = None
  table_align: str|None = None
  fill_content_width: bool = True

#-------------------------------------------------------------------------------------- Presets

class _Preset:
  """Descriptor returning a fresh `Style` on each access - prevents shared mutation."""
  def __init__(self, **kwargs):
    self._kwargs = kwargs
  def __get__(self, obj, objtype=None) -> Style:
    return Style(**self._kwargs)

class Styles:
  """Predefined style presets. Each access returns a fresh `Style` instance.

  Sizes match `docmarq.Styles` so a heading rendered through both libs
  comes out the same. Use `font_mode` or the `bold`/`italic` flags
  interchangeably.
  """
  DEFAULT = _Preset()
  BOLD = _Preset(bold=True)
  ITALIC = _Preset(italic=True)
  HEADING1 = _Preset(font_size=20, bold=True)
  HEADING2 = _Preset(font_size=16, bold=True)
  HEADING3 = _Preset(font_size=13, bold=True)
  HEADING4 = _Preset(font_size=11, bold=True)
  SMALL = _Preset(font_size=9)
  CAPTION = _Preset(font_size=9, italic=True, color=(0.4, 0.44, 0.5))
  CODE = _Preset(font_family="Courier", font_size=10, color=(0.09, 0.11, 0.13))
