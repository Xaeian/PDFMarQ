# pdfmarq/constants.py

"""Constants for PDF library - units, colors, defaults."""
from dataclasses import dataclass

# Exact mm ↔ pt conversion (1 inch = 72pt = 25.4mm)
MM_TO_PT = 72 / 25.4  # ≈ 2.8346456692913384

#-------------------------------------------------------------------------------------------- Units

class Unit:
  """Unit conversion factors to millimeters."""
  MM = 1.0
  CM = 10.0
  INCH = 25.4
  PT = 25.4 / 72  # ≈ 0.35278 mm - exact
  PX = 25.4 / 96  # ≈ 0.26458 mm - 96 DPI

#----------------------------------------------------------------------------------------- PageSize

@dataclass
class PageSize:
  """Common page sizes in mm."""
  width: float
  height: float
  def landscape(self) -> "PageSize":
    """Return a copy with width/height swapped (landscape orientation)."""
    return PageSize(self.height, self.width)

A4 = PageSize(210, 297)
A3 = PageSize(297, 420)
A5 = PageSize(148, 210)
LETTER = PageSize(215.9, 279.4)
LEGAL = PageSize(215.9, 355.6)

# Named presets are the only page sizes callers can select by string. Arbitrary
# `[w, h]` stays available through `PageSize(w, h)`, where the units are
# explicit and a typo cannot silently produce a 5x5000mm page.
PAGE_PRESETS: dict[str, PageSize] = {
  "A4": A4, "A3": A3, "A5": A5, "LETTER": LETTER, "LEGAL": LEGAL,
}

def page_size(name:str) -> PageSize:
  """Resolve a preset name to a `PageSize`, case-insensitively.

  Raises `ValueError` for an unknown name - callers validate user input at
  their own boundary, so reaching here with a bad name is a programming error.
  """
  key = str(name).strip().upper()
  if key not in PAGE_PRESETS:
    raise ValueError(f"Unknown page preset {name!r}; supported: {sorted(PAGE_PRESETS)}")
  return PAGE_PRESETS[key]

#-------------------------------------------------------------------------------------------- Align

class Align:
  """Text/element alignment constants."""
  LEFT = "L"
  RIGHT = "R"
  CENTER = "C"
  JUSTIFY = "J"

#------------------------------------------------------------------------------------------- Colors

class Colors:
  """Predefined colors as (r, g, b) tuples (0-1 range)."""
  BLACK = (0, 0, 0)
  WHITE = (1, 1, 1)
  RED = (1, 0, 0)
  GREEN = (0, 1, 0)
  BLUE = (0, 0, 1)
  GREY = (0.5, 0.5, 0.5)
  LIGHT_GREY = (0.8, 0.8, 0.8)
  DARK_GREY = (0.3, 0.3, 0.3)

#----------------------------------------------------------------------------------------- Defaults

class Defaults:
  """Default values for PDF generation."""
  PAGE_WIDTH = 210
  PAGE_HEIGHT = 297
  MARGIN = 20
  FONT_FAMILY = "Helvetica"
  FONT_SIZE = 11
  FONT_MODE = "Regular"
  LINE_HEIGHT = 1.15
  UNIT = "mm"
