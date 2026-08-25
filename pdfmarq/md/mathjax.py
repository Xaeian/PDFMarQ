# pdfmarq/md/mathjax.py

"""
Math rendering through MathJax: TeX → SVG → reportlab vector `Drawing`.

All of the LaTeX math MathJax supports, which is far more than matplotlib's
mathtext: `\\underbrace` with its label, `\\substack`, `\\begin{cases}`,
stretchable delimiters. Formulas read the way a LaTeX document reads and stay
vector all the way into the PDF.

The SVG passes through `svgflat` first. MathJax assembles a stretchy brace
inside nested `<svg>` viewports, svglib does not reproduce that coordinate
system, and the brace arrives in pieces scattered over its label. Flattening
the geometry to absolute coordinates removes the question.

Needs Node plus global npm packages, the same shape as the mermaid backend -
MathJax itself and one package per typeface:

  npm install -g mathjax @mathjax/mathjax-newcm-font

`available()` says whether that is in place and `installed_fonts()` which
typefaces it can offer; `md.math` falls back to matplotlib when it is not.
"""

__extras__ = ("mathjax", [])

import functools
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import warnings
from pathlib import Path

#-------------------------------------------------------------------------------------------- Cache

_CACHE_DIR = Path.home() / ".cache" / "marq" / "mathjax"
_DRIVER = Path(__file__).with_name("tex2svg.mjs")
_TIMEOUT_S = 180

# MathJax lays out in thousandths of an em, with y=0 on the text baseline.
_UNITS_PER_EM = 1000.0

# New Computer Modern carries a smaller x-height than a text sans face -
# 0.453 em against 0.516 em for IBM Plex Sans - so a formula set at the
# body's nominal size reads a step too small beside it. Matching x-heights
# is what makes the two look like one typeface decision.
OPTICAL_SCALE = 0.516 / 0.453

# Font packages MathJax ships, best symbol coverage first - the order a
# picker offers them in. Two are left out for lacking glyphs a technical
# document reaches for: `tex` has no stretchable brace, so `\underbrace`
# comes out broken, and Fira Math misses twenty-one symbols.
FONTS = ("newcm", "stix2", "modern", "termes", "pagella", "dejavu")
DEFAULT_FONT = "newcm"

def _component(font:str) -> str:
  """MathJax component name for a font: `newcm` to `mathjax-newcm`."""
  return f"mathjax-{font}"

def _package(font:str) -> str:
  """npm package holding a font: `newcm` to `@mathjax/mathjax-newcm-font`."""
  return f"@mathjax/mathjax-{font}-font"

@functools.cache
def _driver_key() -> str:
  """Fingerprint of the render driver.

  Part of every cache key, because the driver decides the shape of what the
  cache holds: editing it has to retire the entries it wrote.
  """
  try:
    return hashlib.sha1(_DRIVER.read_bytes()).hexdigest()[:8]
  except OSError:
    return "0"

def _cache_path(tex:str, display:bool, font:str) -> Path:
  """Cache file for one formula. Font size is not part of the key: the SVG is
  measured in em-relative units and scaled when it is drawn. The typeface is,
  since it decides the glyphs."""
  payload = f"{_driver_key()}\x00{font}\x00{display}\x00{tex}".encode("utf-8")
  key = hashlib.sha1(payload).hexdigest()[:16]
  _CACHE_DIR.mkdir(parents=True, exist_ok=True)
  return _CACHE_DIR / f"{key}.svg"

#------------------------------------------------------------------------------------- Availability

_ROOT: str|None = None
_CHECKED = False

def node_modules_root() -> str|None:
  """Directory holding the global `mathjax` package, or `None`.

  `PDFMARQ_NODE_MODULES` wins when set - asking npm costs about a second, so
  a deployment that already knows the path can say so.
  """
  global _ROOT, _CHECKED
  if _CHECKED:
    return _ROOT
  _CHECKED = True
  override = os.environ.get("PDFMARQ_NODE_MODULES")
  if override and (Path(override) / "mathjax").is_dir():
    _ROOT = override
    return _ROOT
  if not shutil.which("node"):
    return None
  try:
    result = subprocess.run(
      ["npm", "root", "-g"], capture_output=True, text=True, timeout=30,
      shell=os.name == "nt", # npm is a shell script on Windows
    )
    root = (result.stdout or "").strip()
  except Exception:
    return None
  if root and (Path(root) / "mathjax").is_dir():
    _ROOT = root
  return _ROOT

def available() -> bool:
  """True when Node and the MathJax packages can render a formula."""
  return node_modules_root() is not None and _DRIVER.is_file()

def installed_fonts() -> tuple[str, ...]:
  """Fonts from `FONTS` whose npm package is actually present.

  What a service can offer: a name outside this list renders in the default
  instead of the typeface that was asked for.
  """
  root = node_modules_root()
  if root is None:
    return ()
  return tuple(f for f in FONTS if (Path(root) / _package(f)).is_dir())

_WARNED: set = set()

def resolve_font(font:str|None) -> str:
  """The font to render with: the one asked for when its package is there.

  An unknown name or a package that is not installed falls back to the
  default and warns once - a formula silently set in another typeface than
  the document asked for is the kind of thing nobody notices until print.
  """
  font = (font or DEFAULT_FONT).strip()
  fonts = installed_fonts()
  if not fonts:
    return DEFAULT_FONT
  if font in fonts:
    return font
  if font not in _WARNED:
    _WARNED.add(font)
    if font in FONTS:
      detail = (f"{_package(font)} is not installed - "
        f"npm install -g {_package(font)}")
    else:
      detail = f"not one of {', '.join(FONTS)}"
    warnings.warn(
      f"math_font={font!r} unavailable, formulas use {DEFAULT_FONT!r}: {detail}",
      RuntimeWarning, stacklevel=3,
    )
  return DEFAULT_FONT

#------------------------------------------------------------------------------------- Render batch

# A glyph the chosen font has no outline for arrives as a `<text>` element in
# a system face - which reportlab then draws as an empty box, since it has no
# such font either.
_GAP_RE = re.compile(r"<text\b")

def _render(jobs:list[tuple[str, bool]], font:str) -> dict[tuple[str, bool], str]:
  """One Node process for the whole list: startup costs more than the
  formulas do. Results are cached on disk as they arrive."""
  root = node_modules_root()
  if root is None:
    return {}
  payload = "\n".join(
    json.dumps({"tex": tex, "display": display}) for tex, display in jobs)
  try:
    result = subprocess.run(
      ["node", str(_DRIVER), root, _component(font)],
      input=payload, capture_output=True, text=True, encoding="utf-8",
      timeout=_TIMEOUT_S,
    )
  except Exception:
    return {}
  out: dict[tuple[str, bool], str] = {}
  lines = [l for l in (result.stdout or "").splitlines() if l.strip()]
  for job, line in zip(jobs, lines):
    try:
      svg = json.loads(line).get("svg")
    except ValueError:
      continue
    if not svg:
      continue
    out[job] = svg
    try:
      _cache_path(*job, font).write_text(svg, encoding="utf-8")
    except OSError:
      pass # a cache that cannot be written just costs the next render
  return out

def render_batch(
  jobs:list[tuple[str, bool]],
  font:str|None=None,
) -> dict[tuple[str, bool], str]:
  """Render `(tex, display)` pairs to SVG, returning what succeeded.

  A formula holding a character the chosen font lacks is rendered again in
  the default, which covers the whole range: one formula in a second
  typeface reads as a choice, an empty box in the middle of a line does not.
  """
  font = resolve_font(font)
  out: dict[tuple[str, bool], str] = {}
  missing: list[tuple[str, bool]] = []
  for job in dict.fromkeys(jobs):
    path = _cache_path(*job, font)
    if path.is_file():
      try:
        out[job] = path.read_text(encoding="utf-8")
        continue
      except OSError:
        pass
    missing.append(job)
  if missing:
    out.update(_render(missing, font))
  if font == DEFAULT_FONT:
    return out
  gaps = [job for job, svg in out.items() if _GAP_RE.search(svg)]
  if not gaps:
    return out
  _warn_gap(font, len(gaps))
  out.update(render_batch(gaps, DEFAULT_FONT))
  return out

def _warn_gap(font:str, count:int) -> None:
  """Say once per font that formulas moved to the default typeface."""
  if font in _WARNED_GAP:
    return
  _WARNED_GAP.add(font)
  warnings.warn(
    f"math_font={font!r} has no glyph for {count} formula(s); "
    f"those are set in {DEFAULT_FONT!r}", RuntimeWarning, stacklevel=3)

_WARNED_GAP: set = set()

def render(tex:str, display:bool=False, font:str|None=None) -> str|None:
  """SVG for one formula, or `None` when MathJax cannot produce it."""
  job = (tex, display)
  return render_batch([job], font).get(job)

#----------------------------------------------------------------------------------------- Geometry

_VIEWBOX_RE = re.compile(
  r'viewBox="\s*([-\d.]+)[ ,]+([-\d.]+)[ ,]+([-\d.]+)[ ,]+([-\d.]+)')

def geometry(svg:str, fontsize:float) -> tuple[float, float, float]|None:
  """`(width_pt, height_pt, baseline_from_bottom_pt)` for `svg` at `fontsize`.

  The depth below the baseline is `minY + height`: both are layout units and
  the baseline sits at y=0 between them.
  """
  # The first viewBox in the fragment is the outermost SVG's; a nested one
  # would describe a glyph assembly, not the formula.
  match = _VIEWBOX_RE.search(svg)
  if not match:
    return None
  _, min_y, width, height = (float(v) for v in match.groups())
  scale = fontsize / _UNITS_PER_EM
  return width * scale, height * scale, (min_y + height) * scale

def _hex(color:tuple) -> str:
  """`#rrggbb` from an RGB triple in 0-1."""
  r, g, b = (max(0, min(255, round(c * 255))) for c in color[:3])
  return f"#{r:02x}{g:02x}{b:02x}"

def to_drawing(svg:str, fontsize:float, color:tuple=(0, 0, 0)):
  """Turn MathJax SVG into `(drawing, baseline_from_bottom_pt)`.

  The root's `ex`-based width and height become points, because svglib has no
  notion of `ex` and would guess. `currentColor` becomes a literal colour for
  the same reason: there is no cascade here to inherit from.
  """
  measured = geometry(svg, fontsize)
  if measured is None:
    return None, 0
  width_pt, height_pt, baseline_pt = measured
  from .svgflat import flatten
  svg = flatten(svg) or svg
  svg = re.sub(r'(<svg\b[^>]*?)\swidth="[^"]*"', r"\1", svg, count=1)
  svg = re.sub(r'(<svg\b[^>]*?)\sheight="[^"]*"', r"\1", svg, count=1)
  svg = re.sub(
    r"<svg\b",
    f'<svg width="{width_pt:.4f}pt" height="{height_pt:.4f}pt"', svg, count=1)
  svg = svg.replace("currentColor", _hex(color))
  try:
    from svglib.svglib import svg2rlg
    drawing = svg2rlg(io.BytesIO(svg.encode("utf-8")))
  except Exception:
    return None, 0
  if drawing is None:
    return None, 0
  return drawing, baseline_pt
