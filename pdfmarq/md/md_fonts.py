# pdfmarq/md/md_fonts.py

"""
Font auto-registration for MarkdownRenderer.

Tries DejaVu Sans/Mono from common system paths (Linux, Homebrew, Windows),
falls back to Vera bundled with reportlab. Updates `MarkdownStyle` defaults
if the user didn't explicitly override the family.
"""

from .markdown_style import MarkdownStyle

#------------------------------------------------------------------------------------ Constants

_FONT_FILES = {
  "Regular":    "{family}.ttf",
  "Bold":       "{family}-Bold.ttf",
  "Italic":     "{family}-Oblique.ttf",
  "BoldItalic": "{family}-BoldOblique.ttf",
}
_FONT_DIRS = [
  "/usr/share/fonts/truetype/dejavu",
  "/opt/homebrew/share/fonts",
  "C:/Windows/Fonts",
]

#----------------------------------------------------------------------------------- FontsMixin

class FontsMixin:
  _FONT_FILES = _FONT_FILES
  _FONT_DIRS = _FONT_DIRS

  def _ensure_default_font(self):
    """Register default sans + mono TTFs with full Polish/Latin-Ext coverage."""
    def family_paths(family:str, base:str) -> dict:
      import os
      return {
        mode: os.path.join(base, tmpl.format(family=family))
        for mode, tmpl in _FONT_FILES.items()
      }
    sans_candidates = [
      ("DejaVuSans", family_paths("DejaVuSans", d)) for d in _FONT_DIRS
    ]
    sans_candidates.append(("Vera", self._vera_paths()))
    mono_candidates = [
      ("DejaVuSansMono", family_paths("DejaVuSansMono", d)) for d in _FONT_DIRS
    ]
    sans_name = self._try_register_family(sans_candidates)
    mono_name = self._try_register_family(mono_candidates)
    default_style = MarkdownStyle()
    if sans_name and self.style.body_family == default_style.body_family:
      self.style.body_family = sans_name
      self.style.head_family = sans_name
    if mono_name and self.style.mono_family == default_style.mono_family:
      self.style.mono_family = mono_name

  @staticmethod
  def _vera_paths() -> dict:
    """Paths to Vera TTFs bundled with reportlab (fallback font)."""
    try:
      import reportlab, os
      base = os.path.join(os.path.dirname(reportlab.__file__), "fonts")
      return {
        "Regular":    os.path.join(base, "Vera.ttf"),
        "Bold":       os.path.join(base, "VeraBd.ttf"),
        "Italic":     os.path.join(base, "VeraIt.ttf"),
        "BoldItalic": os.path.join(base, "VeraBI.ttf"),
      }
    except Exception:
      return {}

  def _try_register_family(self, candidates:list) -> str|None:
    """Register first candidate where Regular exists; return family name or None."""
    import os
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    fm = self.pdf._fonts
    for family_name, mode_paths in candidates:
      reg_path = mode_paths.get("Regular")
      if not reg_path or not os.path.exists(reg_path):
        continue
      registered_any = False
      for mode, path in mode_paths.items():
        key = f"{family_name}-{mode}"
        if key in fm._registered:
          registered_any = True
          continue
        if not path or not os.path.exists(path):
          continue
        try:
          pdfmetrics.registerFont(TTFont(key, path))
          fm._registered.add(key)
          fm._paths[key] = path
          registered_any = True
        except Exception:
          pass
      if registered_any:
        return family_name
    return None
