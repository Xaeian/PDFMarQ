# pdfmarq/fonts.py

"""Font management - registration, path resolution, metrics."""
from pathlib import Path
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import stringWidth

#---------------------------------------------------------------------------------- FontManager

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
    """Register font and return reportlab font name. Lazy - only registers once."""
    key = self._font_key(family, mode)
    if key in self._registered:
      return key
    path = self._resolve_path(family, mode)
    pdfmetrics.registerFont(TTFont(key, str(path)))
    self._registered.add(key)
    self._paths[key] = str(path)
    return key

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
    """Get text width in points using reportlab metrics."""
    key = self.register(family, mode)
    return stringWidth(text, key, size)

#-------------------------------------------------------------------------------------- Builtin

# `Times/Regular` aliased to `Times/Roman` for consistency with other families.
# `Times-Roman` aliased to `Times` so users passing the reportlab name still
# get the right modal variant (was a quiet bug: `Times-Roman` + `Bold` fell
# through to "Times-Roman" instead of "Times-Bold").
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
