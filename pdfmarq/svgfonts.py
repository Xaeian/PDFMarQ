# pdfmarq/svgfonts.py

"""Bridge from registered reportlab faces to svglib's font map.

Text inside an SVG is drawn by svglib, which resolves fonts through a registry of
its own and falls back to Helvetica, losing the typeface and every glyph outside
Latin-1. `publish` points that registry at faces already registered here.

Only this module knows svglib exists, which keeps text metrics free of it.
"""
import threading
from typing import Callable

#---------------------------------------------------------------------------------------- Constants

# One face: the reportlab name to draw with, and the TTF it was registered from.
# A base-14 face carries no file, which is all svglib needs to map it.
Face = tuple[str, str|None]
Resolve = Callable[[str], Face|None]

# `font-weight` values an SVG can carry, and the mode fragment serving each. svglib
# keys its map on the literal attribute text, so `700` never reaches the entry under
# `bold` and needs its own alias. `900` is the only address `Black` has.
_WEIGHTS = {
  "normal": "", "100": "", "200": "", "300": "", "400": "", "500": "",
  "bold": "Bold", "600": "Bold", "700": "Bold", "800": "Bold", "900": "Black",
}

# `font-style`, composed onto the weight fragment: bold + italic → `BoldItalic`.
_STYLES = {"normal": "", "italic": "Italic"}

# Every mode the two tables compose, so a caller knows what it may be asked for.
MODES = tuple(dict.fromkeys(
  (weight + style) or "Regular"
  for weight in _WEIGHTS.values() for style in _STYLES.values()
))

#------------------------------------------------------------------------------------------ Publish

_PUBLISHED: set[tuple[str, str]] = set()
_LOCK = threading.Lock()

def publish(family:str, source:str, resolve:Resolve) -> None:
  """Map `family` onto svglib's font map, once per `(source, family)`.

  `resolve` is asked for each mode in `MODES` and may answer `None`. It runs on the
  first publish only, so repeat calls cost nothing.

  Publishing rewrites the reportlab font object behind a name, which a concurrently
  open document may be part-way through subsetting - hence once per process rather
  than once per document, and behind a lock, so no one draws against a half-mapped
  family. `source` keeps two font roots off one family name.

  Silent without svglib: SVG text then draws in svglib's own default.
  """
  if (source, family) in _PUBLISHED:
    return
  try:
    from svglib.fonts import get_global_font_map
  except ImportError:
    return
  with _LOCK:
    if (source, family) in _PUBLISHED:
      return
    font_map = get_global_font_map()
    faces = {mode: resolve(mode) for mode in MODES}
    for weight, weight_mode in _WEIGHTS.items():
      for style, style_mode in _STYLES.items():
        face = faces[(weight_mode + style_mode) or "Regular"]
        if face is None: continue
        rlg_name, path = face
        font_map.register_font(family, path, weight=weight, style=style, rlgFontName=rlg_name)
    _PUBLISHED.add((source, family))
