# pdfmarq/utils.py

"""Utility functions - unit conversion, color parsing, helpers."""
from .constants import Unit, MM_TO_PT

#---------------------------------------------------------------------------------------- Units

def to_mm(value:float, unit:str="mm") -> float:
  """Convert value from given unit to millimeters."""
  unit = unit.lower()
  factors = {"mm": Unit.MM, "cm": Unit.CM, "in": Unit.INCH, "inch": Unit.INCH,
    "pt": Unit.PT, "px": Unit.PX}
  if unit not in factors:
    raise ValueError(f"Unknown unit: {unit}. Use: mm, cm, in, pt, px")
  return value * factors[unit]

def to_pt(value_mm:float) -> float:
  """Convert millimeters to points."""
  return value_mm * MM_TO_PT

def mm_to_pt(*values:float) -> list[float]|float:
  """Convert mm values to points. Returns single value or list."""
  result = [v * MM_TO_PT for v in values]
  return result[0] if len(result) == 1 else result

#--------------------------------------------------------------------------- Typographic ladder

# Word's font-size dropdown values - the de facto standard typographic
# ladder. Jumps are non-linear: 12→14→16 skips 13/15 because those don't
# read well in print. "One step smaller" should walk this list, not just
# subtract 1pt and hope for the best.
_SIZE_LADDER = (6, 7, 8, 9, 10, 11, 12, 14, 16, 18, 20, 22, 24, 26, 28, 36, 48, 72)

def smaller_size(body_pt:float, min_pt:float=7) -> float:
  """Next-smaller standard typographic size below `body_pt`. Mirrors
  `docmarq.utils.smaller_size`. Used by tables and bibliography to derive
  a "one step smaller" reading size that hits expected Word ladder values
  (11→10, 12→11, 14→12, 16→14, 18→16) instead of arbitrary `body - 1`
  deltas that produce non-standard sizes like 13. Clamps at `min_pt`."""
  for i, size in enumerate(_SIZE_LADDER):
    if size >= body_pt:
      return min_pt if i == 0 else max(min_pt, _SIZE_LADDER[i - 1])
  return max(min_pt, _SIZE_LADDER[-2])

#--------------------------------------------------------------------------------------- Colors

_HEX_DIGITS = set("0123456789abcdefABCDEF")

def parse_color(color:tuple|str|None) -> tuple[float, float, float]:
  """Parse color from tuple or hex string to (r, g, b) 0-1 range."""
  if color is None:
    return (0, 0, 0)
  if isinstance(color, tuple):
    if len(color) >= 3:
      return (color[0], color[1], color[2])
    raise ValueError("Color tuple must have at least 3 values (r, g, b)")
  if isinstance(color, str):
    raw = color
    hex_str = color.lstrip("#")
    if len(hex_str) == 3:
      hex_str = "".join(c * 2 for c in hex_str)
    if len(hex_str) != 6:
      raise ValueError(
        f"Invalid hex color {raw!r}: expected #RGB or #RRGGBB, got {len(hex_str)} digit(s)"
      )
    if not all(c in _HEX_DIGITS for c in hex_str):
      raise ValueError(f"Invalid hex color {raw!r}: contains non-hex characters")
    r = int(hex_str[0:2], 16) / 255
    g = int(hex_str[2:4], 16) / 255
    b = int(hex_str[4:6], 16) / 255
    return (r, g, b)
  raise ValueError(f"Invalid color type: {type(color)}")

def color_alpha(color:tuple, alpha:float) -> tuple[float, float, float, float]:
  """Add alpha channel to color tuple."""
  r, g, b = parse_color(color)
  return (r, g, b, alpha)

def color_hex(color:tuple|str) -> str:
  """Return `RRGGBB` uppercase hex string (no `#` prefix).

  Symmetric with `docmarq.color_hex` for cross-lib API parity.
  """
  r, g, b = parse_color(color)
  return f"{int(round(r * 255)):02X}{int(round(g * 255)):02X}{int(round(b * 255)):02X}"

#--------------------------------------------------------------------------------------- Margin

def parse_margin(margin:float|tuple|list) -> tuple[float, float, float, float]:
  """Parse margin to `(top, right, bot, left)` tuple. CSS-style.

  Accepts:
    `n`              → all sides `n`
    `(v,)`           → all sides `v`
    `(v, h)`         → vertical `v`, horizontal `h`
    `(t, h, b)`      → top, horizontal, bottom
    `(t, r, b, l)`   → top, right, bottom, left (full CSS form)

  Previously 4-tuples silently dropped the last element (review.md). Now
  honored as CSS-order. Matches `docmarq.parse_margin` shape.
  """
  if isinstance(margin, (int, float)):
    return (margin, margin, margin, margin)
  if isinstance(margin, (tuple, list)):
    n = len(margin)
    if n == 1: return (margin[0], margin[0], margin[0], margin[0])
    if n == 2: return (margin[0], margin[1], margin[0], margin[1])
    if n == 3: return (margin[0], margin[1], margin[2], margin[1])
    if n == 4: return (margin[0], margin[1], margin[2], margin[3])
  raise ValueError(f"Invalid margin: {margin}")

#----------------------------------------------------------------------------------------- Text

def sanitize_text(text:str, link_char:str="·", enter_in:str="\n", enter_out:str="\n") -> str:
  """Prepare text for rendering - handle special chars."""
  text = text.replace(link_char, "¶")
  text = text.replace(enter_in, enter_out)
  return text
