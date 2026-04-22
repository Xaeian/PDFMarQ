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
    key = self._font_key(family, mode)
    if key in self._paths:
      return self._paths[key]
    return str(self._resolve_path(family, mode))

  def is_registered(self, family:str, mode:str="Regular") -> bool:
    return self._font_key(family, mode) in self._registered

  def text_width(self, text:str, family:str, mode:str, size:float) -> float:
    """Get text width in points using reportlab metrics."""
    key = self.register(family, mode)
    return stringWidth(text, key, size)

#-------------------------------------------------------------------------------------- Builtin

# `Times/Regular` aliased to `Times/Roman` for consistency with other families
_BUILTIN_NAMES: dict[tuple[str, str], str] = {
  ("Helvetica", "Regular"):     "Helvetica",
  ("Helvetica", "Bold"):        "Helvetica-Bold",
  ("Helvetica", "Oblique"):     "Helvetica-Oblique",
  ("Helvetica", "BoldOblique"): "Helvetica-BoldOblique",
  ("Times", "Regular"):         "Times-Roman",
  ("Times", "Roman"):           "Times-Roman",
  ("Times", "Bold"):            "Times-Bold",
  ("Times", "Italic"):          "Times-Italic",
  ("Times", "BoldItalic"):      "Times-BoldItalic",
  ("Courier", "Regular"):       "Courier",
  ("Courier", "Bold"):          "Courier-Bold",
  ("Courier", "Oblique"):       "Courier-Oblique",
  ("Courier", "BoldOblique"):   "Courier-BoldOblique",
}

def is_builtin(family:str, mode:str="Regular") -> bool:
  """Check if font is a reportlab built-in."""
  if (family, mode) in _BUILTIN_NAMES: return True
  if family == "Times-Roman": return True
  return False

def builtin_name(family:str, mode:str="Regular") -> str:
  """Get reportlab built-in font name. Returns `family` unchanged when not a builtin."""
  return _BUILTIN_NAMES.get((family, mode), family)
