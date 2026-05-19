# pdfmarq/md/openmoji.py

"""
Color emoji rendering via OpenMoji SVG → svglib → reportlab Drawing.

OpenMoji (https://openmoji.org/) is a CC-BY-SA 4.0 licensed emoji set with
~4500 color SVG icons. We lazy-clone the repo on first use to a user cache
directory, then load individual SVG files per emoji codepoint and convert
to reportlab `Drawing` objects (which reuse the same inline-embedding path
as inline math formulas via `RichSegment.math_drawing`).

Usage:
  >>> from pdfmarq.openmoji import get_emoji_drawing
  >>> drawing = get_emoji_drawing(0x1F44D, fontsize_pt=11) # 👍
  >>> # drawing.width / .height in pt, pre-scaled to fontsize

Single-codepoint emoji only for v1. Multi-codepoint sequences (ZWJ families
like 👨‍👩‍👧, skin-tone modifiers 👍🏾) fall back to the base codepoint.
"""

__extras__ = ("emoji", [])

import os
from pathlib import Path

#---------------------------------------------------------------------------------------- Cache

_CACHE_DIR = Path.home() / ".cache" / "pdfmarq" / "openmoji"
_DRAWING_CACHE: dict = {}  # (codepoint, fontsize_pt) -> Drawing
_SVG_DIR_CACHE: Path|None = None
_CLONE_ATTEMPTED = False

def _ensure_openmoji() -> Path|None:
  """Return path to OpenMoji `color/svg/` directory, cloning repo if needed.

  First call may take a minute (git clone ~150 MB). Subsequent calls are
  instant. Returns None if clone fails (no network, no git, etc.).
  """
  global _SVG_DIR_CACHE, _CLONE_ATTEMPTED
  if _SVG_DIR_CACHE is not None:
    return _SVG_DIR_CACHE
  svg_dir = _CACHE_DIR / "color" / "svg"
  if svg_dir.exists() and any(svg_dir.iterdir()):
    _SVG_DIR_CACHE = svg_dir
    return svg_dir
  if _CLONE_ATTEMPTED:
    return None
  _CLONE_ATTEMPTED = True
  try:
    import subprocess
    _CACHE_DIR.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
      [
        "git", "clone", "--depth=1", "--single-branch",
        "https://github.com/hfg-gmuend/openmoji.git",
        str(_CACHE_DIR),
      ],
      check=True, capture_output=True, timeout=300,
    )
    if svg_dir.exists():
      _SVG_DIR_CACHE = svg_dir
      return svg_dir
  except Exception:
    pass
  return None

#------------------------------------------------------------------------------------ Detection

# Unicode ranges that contain emoji/pictographs. Not exhaustive but covers
# most of what appears in technical docs. We check these ranges to decide
# if a character should be rendered as emoji (via OpenMoji SVG) or as text
# (via the normal font).
_EMOJI_RANGES = [
  (0x1F300, 0x1F5FF),  # Misc Symbols and Pictographs
  (0x1F600, 0x1F64F),  # Emoticons
  (0x1F680, 0x1F6FF),  # Transport and Map
  (0x1F700, 0x1F77F),  # Alchemical
  (0x1F780, 0x1F7FF),  # Geometric Shapes Extended
  (0x1F800, 0x1F8FF),  # Supplemental Arrows-C
  (0x1F900, 0x1F9FF),  # Supplemental Symbols and Pictographs
  (0x1FA00, 0x1FA6F),  # Chess Symbols
  (0x1FA70, 0x1FAFF),  # Symbols and Pictographs Extended-A
  (0x2600,  0x26FF),  # Misc Symbols
  (0x2700,  0x27BF),  # Dingbats
  (0x2B00,  0x2BFF),  # Misc Symbols and Arrows
  (0x24C2,  0x24C2),  # Circled M (Ⓜ)
]

def is_emoji(ch:
  str) -> bool:
  """Check if single character should be rendered as color emoji."""
  if not ch: return False
  code = ord(ch)
  for lo, hi in _EMOJI_RANGES:
    if lo <= code <= hi:
      return True
  return False

def split_text_by_emoji(text:
  str) -> list[tuple[str, bool]]:
  """Split text into runs of (fragment, is_emoji).

  Groups consecutive non-emoji chars into a single text run. Each emoji
  char becomes its own run. Variation selectors (U+FE0F) and zero-width
  joiners (U+200D) are SKIPPED entirely - they're invisible modifiers
  and including them would produce empty text segments.
  """
  if not text:
    return []
  runs: list[tuple[str, bool]] = []
  buf_text: list[str] = []
  for ch in text:
    code = ord(ch)
    # Skip variation selectors (FE0F = emoji presentation, FE0E = text)
    # and ZWJ. These are modifiers - we render only the base char.
    if code in (0xFE0F, 0xFE0E, 0x200D):
      continue
    if is_emoji(ch):
      if buf_text:
        runs.append(("".join(buf_text), False))
        buf_text = []
      runs.append((ch, True))
    else:
      buf_text.append(ch)
  if buf_text:
    runs.append(("".join(buf_text), False))
  return runs

#-------------------------------------------------------------------------------------- Drawing

def get_emoji_drawing(codepoint:
  int, fontsize_pt: float):
  """Return a reportlab `Drawing` for the given emoji codepoint, scaled to
  approximately the given font size. Returns None on any failure (missing
  SVG, clone not attempted, svglib error).

  Scaling: drawing is sized so its height matches `fontsize_pt * 1.1`,
  which places the emoji roughly the same height as cap-height letters.
  """
  key = (codepoint, round(fontsize_pt, 2))
  if key in _DRAWING_CACHE:
    return _DRAWING_CACHE[key]
  svg_dir = _ensure_openmoji()
  if svg_dir is None:
    _DRAWING_CACHE[key] = None
    return None
  svg_path = svg_dir / f"{codepoint:04X}.svg"
  if not svg_path.exists():
    _DRAWING_CACHE[key] = None
    return None
  try:
    from svglib.svglib import svg2rlg
  except ImportError:
    from .._warn import warn_missing
    warn_missing("svglib", "svglib", "color emoji rendering")
    _DRAWING_CACHE[key] = None
    return None
  try:
    d = svg2rlg(str(svg_path))
    if d is None:
      _DRAWING_CACHE[key] = None
      return None
    target = fontsize_pt * 1.32
    scale = target / max(d.width, d.height)
    d.width *= scale
    d.height *= scale
    d.scale(scale, scale)
    _DRAWING_CACHE[key] = d
    return d
  except Exception:
    _DRAWING_CACHE[key] = None
    return None
