# pdfmarq/md/md_fonts.py

"""Font auto-registration for `MarkdownRenderer`.

Tries DejaVu Sans/Mono from common system paths (Linux, Homebrew, Windows),
then the copy matplotlib ships, which the `[md]` extra installs.
Falls back to Vera bundled with reportlab, which has no ą ę ś ź ż ń.
Updates `MarkdownStyle` defaults only when the user has not overridden the family.
"""

import os
import reportlab
from .markdown_style import MarkdownStyle

#---------------------------------------------------------------------------------------- Constants

_FONT_FILES = {
  "Regular": "{family}.ttf",
  "Bold": "{family}-Bold.ttf",
  "Italic": "{family}-Oblique.ttf",
  "BoldItalic": "{family}-BoldOblique.ttf",
}
_FONT_DIRS = [
  "/usr/share/fonts/truetype/dejavu",
  "/opt/homebrew/share/fonts",
  "C:/Windows/Fonts",
]

def _font_dirs() -> list[str]:
  """`_FONT_DIRS`, then matplotlib's DejaVu: a system without DejaVu, as Windows, still gets it."""
  try:
    import matplotlib # optional, and the math setup loads it anyway
  except ImportError:
    return _FONT_DIRS
  return [*_FONT_DIRS, os.path.join(matplotlib.get_data_path(), "fonts", "ttf")]

#--------------------------------------------------------------------------------------- FontsMixin

class FontsMixin:
  """Font auto-registration mixin for `MarkdownRenderer`.
  Loads body/heading/mono families before the first draw."""
  _FONT_FILES = _FONT_FILES
  _FONT_DIRS = _FONT_DIRS

  def _ensure_default_font(self):
    """Register DejaVu sans + mono TTFs (Polish/Latin-Ext coverage); fall back to Vera."""
    def family_paths(family:str, base:str) -> dict:
      return {
        mode: os.path.join(base, tmpl.format(family=family))
        for mode, tmpl in _FONT_FILES.items()
      }
    dirs = _font_dirs()
    sans_candidates = [
      ("DejaVuSans", family_paths("DejaVuSans", d)) for d in dirs
    ]
    sans_candidates.append(("Vera", self._vera_paths()))
    mono_candidates = [
      ("DejaVuSansMono", family_paths("DejaVuSansMono", d)) for d in dirs
    ]
    sans_name = self._try_register_family(sans_candidates)
    mono_name = self._try_register_family(mono_candidates)
    default_style = MarkdownStyle()
    if sans_name and self.style.font_body == default_style.font_body:
      self.style.font_body = sans_name
      self.style.font_head = sans_name
    if mono_name and self.style.font_mono == default_style.font_mono:
      self.style.font_mono = mono_name

  @staticmethod
  def _vera_paths() -> dict:
    """Paths to Vera TTFs bundled with reportlab (fallback font)."""
    try:
      base = os.path.join(os.path.dirname(reportlab.__file__), "fonts")
      return {
        "Regular": os.path.join(base, "Vera.ttf"),
        "Bold": os.path.join(base, "VeraBd.ttf"),
        "Italic": os.path.join(base, "VeraIt.ttf"),
        "BoldItalic": os.path.join(base, "VeraBI.ttf"),
      }
    except Exception:
      return {}

  def _try_register_family(self, candidates:list) -> str|None:
    """Register first candidate where Regular exists; return family name or None."""
    fm = self.pdf.fonts
    for family_name, mode_paths in candidates:
      reg_path = mode_paths.get("Regular")
      if not reg_path or not os.path.exists(reg_path):
        continue
      registered_any = False
      for mode, path in mode_paths.items():
        try:
          fm.register_file(family_name, mode, path) # a missing file raises, as a broken one does
          registered_any = True
        except Exception:
          pass
      if registered_any:
        return family_name
    return None
