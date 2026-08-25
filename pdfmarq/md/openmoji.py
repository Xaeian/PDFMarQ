# pdfmarq/md/openmoji.py

"""
Color emoji rendering via OpenMoji SVG → svglib → reportlab Drawing.

OpenMoji (https://openmoji.org/) is a CC-BY-SA 4.0 licensed emoji set with
~4500 color SVG icons. We lazy-clone the repo on first use to a user cache
directory, then load individual SVG files per emoji codepoint and convert
to reportlab `Drawing` objects (which reuse the same inline-embedding path
as inline math formulas via `RichSegment.math_drawing`).

Usage:
  >>> from pdfmarq.md.openmoji import get_emoji_drawing
  >>> drawing = get_emoji_drawing(0x1F44D, fontsize_pt=11) # 👍
  >>> # drawing.width / .height in pt, pre-scaled to fontsize

Single-codepoint emoji only for v1. Multi-codepoint sequences (ZWJ families
like 👨‍👩‍👧, skin-tone modifiers 👍🏾) fall back to the base codepoint.
"""

__extras__ = ("emoji", [])

from pathlib import Path

#-------------------------------------------------------------------------------------------- Cache

_CACHE_DIR = Path.home() / ".cache" / "pdfmarq" / "openmoji"
_DRAWING_CACHE: dict = {}  # (codepoint, fontsize_pt) → Drawing
_SVG_DIR_CACHE: Path|None = None
_CLONE_ATTEMPTED = False

_REPO_URL = "https://github.com/hfg-gmuend/openmoji.git"
# Pinned release. The SVGs from this checkout are embedded in generated
# PDFs, so tracking a moving branch tip would make the output depend on
# whatever upstream pushed today.
_REPO_TAG = "17.0.0"
# OpenMoji ships ~4500 colour SVGs. A checkout holding a handful of files
# is an interrupted clone, not a usable emoji set.
_MIN_SVG_COUNT = 1000
_DOWNLOAD_WARNED = False

def allow_download(enabled:bool=True) -> None:
  """Enable or disable the one-time OpenMoji clone at runtime.

  Equivalent to the `PDFMARQ_NO_EMOJI_DOWNLOAD` environment variable.
  With downloads off, emoji fall back to the text glyph of the font.
  """
  global _CLONE_ATTEMPTED
  # Blocking is expressed by marking the clone as already attempted, so
  # the existing cached-checkout path keeps working either way.
  _CLONE_ATTEMPTED = not enabled

def _download_blocked() -> bool:
  import os
  return os.environ.get("PDFMARQ_NO_EMOJI_DOWNLOAD", "").strip() not in ("", "0")

def _warn_download_once() -> None:
  """Announce the clone before it starts - it is large and it is a network
  fetch that the caller never explicitly asked for."""
  global _DOWNLOAD_WARNED
  if _DOWNLOAD_WARNED:
    return
  _DOWNLOAD_WARNED = True
  import warnings
  warnings.warn(
    f"openmoji: downloading the colour emoji set (~150 MB, git clone of "
    f"{_REPO_URL} at tag {_REPO_TAG}) into {_CACHE_DIR}. This happens once. "
    f"Set PDFMARQ_NO_EMOJI_DOWNLOAD=1 to skip it and render emoji as plain "
    f"text glyphs.",
    RuntimeWarning, stacklevel=3,
  )

def _has_enough_svgs(svg_dir:Path) -> bool:
  """True when the checkout looks complete. Counting stops at the
  threshold, so this stays cheap on a full ~4500-file directory."""
  if not svg_dir.is_dir():
    return False
  n = 0
  try:
    for _ in svg_dir.glob("*.svg"):
      n += 1
      if n >= _MIN_SVG_COUNT:
        return True
  except OSError:
    return False
  return False

def _ensure_openmoji() -> Path|None:
  """Return path to OpenMoji `color/svg/` directory, cloning repo if needed.

  First call may take a minute (git clone ~150 MB, pinned to tag
  `_REPO_TAG`) and warns once before starting. Subsequent calls are
  instant. Returns None when the download is disabled or fails (no
  network, no git, interrupted clone).
  """
  global _SVG_DIR_CACHE, _CLONE_ATTEMPTED
  if _SVG_DIR_CACHE is not None:
    return _SVG_DIR_CACHE
  svg_dir = _CACHE_DIR / "color" / "svg"
  if _has_enough_svgs(svg_dir):
    _SVG_DIR_CACHE = svg_dir
    return svg_dir
  if _CLONE_ATTEMPTED or _download_blocked():
    return None
  _CLONE_ATTEMPTED = True
  _warn_download_once()
  try:
    import subprocess
    _CACHE_DIR.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
      [
        "git", "clone", "--depth=1", "--single-branch",
        "--branch", _REPO_TAG, _REPO_URL,
        str(_CACHE_DIR),
      ],
      check=True, capture_output=True, timeout=300,
    )
    # A clone killed halfway leaves a directory that exists but holds a
    # random subset of the icons, so the count decides, not the path.
    if _has_enough_svgs(svg_dir):
      _SVG_DIR_CACHE = svg_dir
      return svg_dir
    import warnings
    warnings.warn(
      f"openmoji: clone into {_CACHE_DIR} looks incomplete "
      f"(<{_MIN_SVG_COUNT} SVGs); emoji fall back to text glyphs. "
      f"Delete that directory to retry.",
      RuntimeWarning, stacklevel=3,
    )
  except Exception:
    pass
  return None

#---------------------------------------------------------------------------------------- Detection

# Unicode ranges containing emoji/pictographs common in technical docs.
# Not exhaustive - covers the practical set without a full Unicode lookup.
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

def is_emoji(ch:str) -> bool:
  """Check if single character should be rendered as color emoji."""
  if not ch: return False
  code = ord(ch)
  return any(lo <= code <= hi for lo, hi in _EMOJI_RANGES)

def split_text_by_emoji(text:str) -> list[tuple[str, bool]]:
  """Split text into runs of (fragment, is_emoji).

  Groups consecutive non-emoji chars into a single text run. Each emoji
  char becomes its own run. Variation selectors (U+FE0F/U+FE0E), zero-width
  joiners (U+200D) and skin-tone modifiers (U+1F3FB-U+1F3FF) are SKIPPED
  entirely - they are modifiers, not standalone glyphs, and emitting them
  would produce a second drawing next to the base emoji.
  """
  if not text:
    return []
  runs: list[tuple[str, bool]] = []
  buf_text: list[str] = []
  for ch in text:
    code = ord(ch)
    # FE0F/FE0E = variation selectors, 200D = ZWJ, 1F3FB-1F3FF = skin-tone
    # modifiers. None of them stands alone, and the skin tones sit inside
    # the Misc-Pictographs range that `is_emoji` accepts, so they are
    # dropped here and only the base codepoint is rendered.
    if code in (0xFE0F, 0xFE0E, 0x200D) or 0x1F3FB <= code <= 0x1F3FF:
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

#------------------------------------------------------------------------------------------ Drawing

def get_emoji_drawing(codepoint:int, fontsize_pt:float):
  """Return a reportlab `Drawing` for the given emoji codepoint, scaled to
  approximately the given font size. Returns None on any failure (missing
  SVG, clone not attempted, svglib error).

  Scaling: drawing is sized so its height matches `fontsize_pt * 1.32`,
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
