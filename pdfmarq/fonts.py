# pdfmarq/fonts.py

"""Font management - registration, path resolution, metrics.

Every family loaded here is also handed to `svgfonts`, so SVG text can be set in
the same type as the page around it.
"""
from pathlib import Path
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import stringWidth
from . import svgfonts

# Mode fallback when a variant TTF is missing (drops styling, keeps content).
_MODE_FALLBACK = {
  "Italic": ["Regular"],
  "Bold": ["Regular"],
  "BoldItalic": ["Bold", "Italic", "Regular"],
  "Black": ["Bold", "Regular"],
  "BlackItalic": ["BoldItalic", "Black", "Bold", "Italic", "Regular"],
  "Oblique": ["Italic", "Regular"],
  "BoldOblique": ["BoldItalic", "Bold", "Italic", "Regular"],
}

#-------------------------------------------------------------------------------------- FontManager

class FontManager:
  """Font registry with lazy loading and path resolution."""
  def __init__(self, font_dir:str="./fonts"):
    self.font_dir = Path(font_dir)
    self._registered: set[str] = set()
    self._paths: dict[str, str] = {}

  def _font_key(self, family:str, mode:str) -> str:
    return f"{family}-{mode}"

  def _resolve_path(self, family:str, mode:str) -> Path:
    # Try subfolder named after family - both lowercase (web convention)
    # and as-is (PascalCase, PascalCase mode).
    for sub in (family.lower(), family):
      path = self.font_dir / sub / f"{family}-{mode}.ttf"
      if path.exists():
        return path
    path = self.font_dir / f"{family}-{mode}.ttf"
    if path.exists():
      return path
    if mode == "Regular":
      path = self.font_dir / f"{family}.ttf"
      if path.exists():
        return path
    raise FileNotFoundError(f"Font not found: {family}-{mode} in {self.font_dir}")

  def register(self, family:str, mode:str="Regular") -> str:
    """Register font, return reportlab name. Missing variants fall back
    through `_MODE_FALLBACK`, and a base-14 built-in satisfies any step of that
    chain. Raises when nothing in the chain exists.

    The first call for a family also hands it to `svgfonts`, so SVG text lands on
    the same faces as the page around it.
    """
    key = self._register_mode(family, mode)
    self._publish_svg(family)
    return key

  def _register_mode(self, family:str, mode:str) -> str:
    """Register one face and return its reportlab name, walking the fallback chain.

    The built-in check runs per step, not once at the end: `Courier` has no
    `Black`, so `Black` reaches its `Bold` fallback, which the built-in serves.
    """
    for try_mode in [mode] + _MODE_FALLBACK.get(mode, []):
      key = self._font_key(family, try_mode)
      if key in self._registered:
        return key
      if is_builtin(family, try_mode):
        return builtin_name(family, try_mode)
      try:
        path = self._resolve_path(family, try_mode)
      except FileNotFoundError:
        continue
      pdfmetrics.registerFont(TTFont(key, str(path)))
      self._registered.add(key)
      self._paths[key] = str(path)
      return key
    raise FileNotFoundError(
      f"Font not found: {family}-{mode} in {self.font_dir} (no fallback worked)"
    )

  def _publish_svg(self, family:str) -> None:
    """Hand `family` to `svgfonts`, resolving each mode the way the page does.

    An SVG names the family through `font-family`, matched case-insensitively but
    not otherwise normalised: `JetBrainsMono` is not `JetBrains Mono`.
    """
    svgfonts.publish(family, str(self.font_dir), lambda mode: self._svg_face(family, mode))

  def _svg_face(self, family:str, mode:str) -> svgfonts.Face|None:
    """One face for `svgfonts.publish`. The name is the registered one, so the face
    is mapped rather than loaded a second time."""
    try:
      key = self._register_mode(family, mode)
    except FileNotFoundError:
      return None
    return key, self._paths.get(key)

  def get_path(self, family:str, mode:str="Regular") -> str:
    """Return absolute filesystem path of the TTF for `(family, mode)`.
    Hits the registration cache first; falls back to fresh disk lookup.
    Raises `FileNotFoundError` if the font isn't installed."""
    key = self._font_key(family, mode)
    if key in self._paths:
      return self._paths[key]
    return str(self._resolve_path(family, mode))

  def is_registered(self, family:str, mode:str="Regular") -> bool:
    """True when `(family, mode)` was already loaded into reportlab."""
    return self._font_key(family, mode) in self._registered

  def text_width(self, text:str, family:str, mode:str, size:float) -> float:
    """Return text advance width in points (reportlab `stringWidth`)."""
    key = self.register(family, mode)
    return stringWidth(text, key, size)

def register_fonts(font_dir:str, *families:str) -> None:
  """Make `families` resolvable for text drawn inside an SVG.

  The markdown renderer publishes the families its style names. Reach for this when
  there is no style to read: an SVG drawn through the fluent API, or one labelled in
  a family the document never sets. A family with no TTF is skipped.
  """
  manager = FontManager(font_dir)
  for family in families:
    try:
      manager.register(family)
    except FileNotFoundError:
      continue

#------------------------------------------------------------------------------------------ Builtin

# `Times/Regular` aliased to `Times/Roman` for consistency with other families.
# `Times-Roman` aliased to `Times` so users passing the reportlab canonical name
# still get the correct modal variant (e.g. Bold → "Times-Bold", not "Times-Roman").
_BUILTIN_NAMES: dict[tuple[str, str], str] = {
  ("Helvetica", "Regular"): "Helvetica",
  ("Helvetica", "Bold"): "Helvetica-Bold",
  ("Helvetica", "Oblique"): "Helvetica-Oblique",
  ("Helvetica", "Italic"): "Helvetica-Oblique",
  ("Helvetica", "BoldOblique"): "Helvetica-BoldOblique",
  ("Helvetica", "BoldItalic"): "Helvetica-BoldOblique",
  ("Times", "Regular"): "Times-Roman",
  ("Times", "Roman"): "Times-Roman",
  ("Times", "Bold"): "Times-Bold",
  ("Times", "Italic"): "Times-Italic",
  ("Times", "Oblique"): "Times-Italic",
  ("Times", "BoldItalic"): "Times-BoldItalic",
  ("Times", "BoldOblique"): "Times-BoldItalic",
  ("Times-Roman", "Regular"): "Times-Roman",
  ("Times-Roman", "Bold"): "Times-Bold",
  ("Times-Roman", "Italic"): "Times-Italic",
  ("Times-Roman", "Oblique"): "Times-Italic",
  ("Times-Roman", "BoldItalic"): "Times-BoldItalic",
  ("Times-Roman", "BoldOblique"): "Times-BoldItalic",
  ("Courier", "Regular"): "Courier",
  ("Courier", "Bold"): "Courier-Bold",
  ("Courier", "Oblique"): "Courier-Oblique",
  ("Courier", "Italic"): "Courier-Oblique",
  ("Courier", "BoldOblique"): "Courier-BoldOblique",
  ("Courier", "BoldItalic"): "Courier-BoldOblique",
}

def is_builtin(family:str, mode:str="Regular") -> bool:
  """Check if `(family, mode)` resolves to a reportlab built-in font."""
  return (family, mode) in _BUILTIN_NAMES

def builtin_name(family:str, mode:str="Regular") -> str:
  """Get reportlab built-in font name. Returns `family` unchanged when not a builtin."""
  return _BUILTIN_NAMES.get((family, mode), family)
