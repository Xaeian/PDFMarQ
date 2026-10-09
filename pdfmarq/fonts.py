# pdfmarq/fonts.py

"""Font management - registration, path resolution, metrics.

Every family loaded here is also handed to `svgfonts`,
so SVG text can be set in the same type as the page around it.
"""
import functools, io, warnings
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
    """Register font, return reportlab name.
    Missing variants fall back through `_MODE_FALLBACK`,
    and a base-14 built-in satisfies any step of that chain.
    Raises when nothing in the chain exists.

    The first call for a family also hands it to `svgfonts`,
    so SVG text lands on the same faces as the page around it.
    """
    key = self._register_mode(family, mode)
    self._publish_svg(family)
    return key

  def _register_mode(self, family:str, mode:str) -> str:
    """Register one face and return its reportlab name, walking the fallback chain.

    The built-in check runs per step, not once at the end:
    `Courier` has no `Black`, so `Black` reaches its `Bold` fallback, which the built-in serves.
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
      f"Font not found: {family}-{mode} in {self.font_dir} (no fallback worked)",
    )

  def _publish_svg(self, family:str) -> None:
    """Hand `family` to `svgfonts`, resolving each mode the way the page does.

    An SVG names the family through `font-family`,
    matched case-insensitively but not otherwise normalised:
    `JetBrainsMono` is not `JetBrains Mono`.
    """
    svgfonts.publish(family, str(self.font_dir), lambda mode: self._svg_face(family, mode))

  def _svg_face(self, family:str, mode:str) -> svgfonts.Face|None:
    """One face for `svgfonts.publish`.
    The name is the registered one, so the face is mapped rather than loaded a second time."""
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

  def small_caps(self, family:str, mode:str="Regular") -> str|None:
    """
    Family whose `mode` face draws capitals as the small capitals of `family`, `None` without them.

    reportlab draws by character and applies no OpenType feature,
    so the font's `smcp` substitutions go into a copy of it whose capitals map to small capitals.
    Text set in it still copies out as capitals.
    A letter the font has no small capital for stays a capital.
    """
    small = f"{family}.sc"
    key = self._font_key(small, mode)
    if key in self._registered: return small
    path = self._paths.get(self._register_mode(family, mode)) # `None` for a built-in
    data = _small_caps_font(path) if path else None
    if data is None: return None
    pdfmetrics.registerFont(TTFont(key, io.BytesIO(data)))
    self._registered.add(key)
    return small

  def is_registered(self, family:str, mode:str="Regular") -> bool:
    """True when `(family, mode)` was already loaded into reportlab."""
    return self._font_key(family, mode) in self._registered

  def text_width(self, text:str, family:str, mode:str, size:float) -> float:
    """Return text advance width in points (reportlab `stringWidth`)."""
    key = self.register(family, mode)
    return stringWidth(text, key, size)

def register_fonts(font_dir:str, *families:str) -> None:
  """Make `families` resolvable for text drawn inside an SVG.

  The markdown renderer publishes the families its style names.
  Reach for this when there is no style to read:
  an SVG drawn through the fluent API, or one labelled in a family the document never sets.
  A family with no TTF is skipped.
  """
  manager = FontManager(font_dir)
  for family in families:
    try:
      manager.register(family)
    except FileNotFoundError:
      continue

#----------------------------------------------------------------------------------- Small capitals

def _smcp(font) -> dict[str, str]:
  """Glyph → its small capital, from the single substitutions of the font's `smcp` feature."""
  if "GSUB" not in font: return {}
  gsub = font["GSUB"].table
  if not gsub.FeatureList or not gsub.LookupList: return {}
  small: dict[str, str] = {}
  for record in gsub.FeatureList.FeatureRecord:
    if record.FeatureTag != "smcp": continue
    for index in record.Feature.LookupListIndex:
      lookup = gsub.LookupList.Lookup[index]
      for table in lookup.SubTable:
        if lookup.LookupType == 7: table = table.ExtSubTable # an extension wraps the real one
        small.update(getattr(table, "mapping", None) or {})
  return small

@functools.cache
def _small_caps_font(path:str) -> bytes|None:
  """
  The TrueType font at `path`, each capital mapped to the small capital of its lowercase letter.
  `None` for a font with no small capitals, and without fontTools, which warns once per font.
  """
  try:
    from fontTools.ttLib import TTFont as FontFile
  except ModuleNotFoundError:
    warnings.warn("small capitals need fontTools (pip install fonttools); capitals stand in",
      RuntimeWarning, stacklevel=2)
    return None
  font = FontFile(path)
  small = _smcp(font)
  cmap = font.getBestCmap()
  caps: dict[int, str] = {}
  for code in cmap:
    lower = chr(code).lower()
    if lower == chr(code) or len(lower) != 1: continue # no capital, or no single lowercase letter
    glyph = small.get(cmap.get(ord(lower)))
    if glyph: caps[code] = glyph
  if not caps: return None
  for table in font["cmap"].tables:
    if table.isUnicode():
      table.cmap.update({code: glyph for code, glyph in caps.items() if code in table.cmap})
  # A PostScript name of its own: reportlab hands back a face it already knows by that name.
  for record in font["name"].names:
    if record.nameID == 6: record.string = f"{record.toUnicode()}.sc"
  out = io.BytesIO()
  font.save(out)
  return out.getvalue()

#------------------------------------------------------------------------------------------ Builtin

# `Times/Regular` aliased to `Times/Roman` for consistency with other families.
# `Times-Roman` aliased to `Times`
# so users passing the reportlab canonical name still get the correct modal variant
# (e.g. Bold → "Times-Bold", not "Times-Roman").
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

def builtin_families() -> list[str]:
  """
  Families with PDF core-14 faces, which need no TTF.
  `is_builtin` tells which modes they have.
  """
  return sorted({family for family, _ in _BUILTIN_NAMES})

def is_builtin(family:str, mode:str="Regular") -> bool:
  """Check if `(family, mode)` resolves to a reportlab built-in font."""
  return (family, mode) in _BUILTIN_NAMES

def builtin_name(family:str, mode:str="Regular") -> str:
  """Get reportlab built-in font name. Returns `family` unchanged when not a builtin."""
  return _BUILTIN_NAMES.get((family, mode), family)
