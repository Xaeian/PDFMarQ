# pdfmarq/md/math.py

"""Math rendering: matplotlib.mathtext → SVG → reportlab vector `Drawing`.

Renders LaTeX-subset formulas as true vector graphics (no bitmaps), sharp
at any zoom. `render_math_svg_with_baseline` does the rendering and reports
where the text baseline falls inside the drawing, which inline placement
needs; `render_math_svg` is the same call without that number, for block
formulas that stand on their own.

  >>> from pdfmarq.math import render_math_svg
  >>> drawing = render_math_svg(r"E = mc^2", fontsize=11)
  >>> # drawing.width, drawing.height in pt
  >>> # renderPDF.draw(drawing, canvas, x, y) to place on page
"""

__extras__ = ("math", ["matplotlib"])

import io
from pathlib import Path

from ..fonts import is_builtin

try:
  import matplotlib
  matplotlib.use("Agg")
  from matplotlib.figure import Figure
  from svglib.svglib import svg2rlg
  _HAS_MATPLOTLIB = True
except ImportError:
  _HAS_MATPLOTLIB = False

#----------------------------------------------------------------------------------- Fontset config

from dataclasses import dataclass

_PRESETS = {"stix", "stixsans", "cm", "dejavusans", "dejavuserif"}

@dataclass
class MathFontConfig:
  """Per-renderer matplotlib mathtext settings.

  matplotlib's `rcParams` are process-global, so two `MarkdownRenderer`
  instances with different `math_fontset` would clobber each other if set
  at construction time. Held per-renderer and applied via `apply()` just
  before each render call to keep renderers isolated.
  """
  fontset: str = "stixsans"
  rm: str|None = None
  it: str|None = None
  bf: str|None = None
  bfit: str|None = None
  sf: str|None = None
  tt: str|None = None
  cal: str|None = None

  def apply(self) -> None:
    """Write this config into matplotlib's rcParams."""
    if not _HAS_MATPLOTLIB:
      return
    import matplotlib as mpl
    mpl.rcParams["mathtext.fontset"] = self.fontset
    if self.fontset == "custom":
      for key, val in (("mathtext.rm", self.rm), ("mathtext.it", self.it),
          ("mathtext.bf", self.bf), ("mathtext.bfit", self.bfit),
          ("mathtext.sf", self.sf), ("mathtext.tt", self.tt),
          ("mathtext.cal", self.cal)):
        if val:
          mpl.rcParams[key] = val

def configure_math_fonts(
  fontset:str = "stixsans",
  font_dir:str|None = None,
) -> MathFontConfig:
  """Build a `MathFontConfig` for the given fontset.

  Args:
    fontset: Either a matplotlib preset (`"stix"`, `"stixsans"`, `"cm"`,
      `"dejavusans"`, `"dejavuserif"`) or a font family name. When a family
      name is given, the loader looks for `<font_dir>/<family>/<family>-Regular.ttf`
      and registers Regular/Italic/Bold/BoldItalic from that folder, so
      formulas carry the document's own typeface. A base-14 builtin maps to
      the nearest preset; any other family that cannot be loaded warns and
      falls back to `"stixsans"`.
    font_dir: Root font directory (only used when `fontset` is a family name).

  Returns a `MathFontConfig` the renderer stores and applies before each
  math render. Custom-font TTFs ARE registered with matplotlib at this
  point - that's a one-time global side-effect - but the rcParams
  assignment happens lazily inside `MathFontConfig.apply()`.
  """
  if not _HAS_MATPLOTLIB:
    return MathFontConfig(fontset="stixsans")
  if fontset in _PRESETS:
    return MathFontConfig(fontset=fontset)
  if is_builtin(fontset):
    # Serif text keeps serif math; everything else goes sans.
    serif = fontset.startswith("Times")
    return MathFontConfig(fontset="stix" if serif else "stixsans")
  if not font_dir:
    _warn_fallback(fontset, "no font directory to look in")
    return MathFontConfig(fontset="stixsans")
  family = fontset
  base = Path(font_dir) / family
  rm_path = base / f"{family}-Regular.ttf"
  if not rm_path.exists():
    _warn_fallback(fontset, f"{rm_path} not found")
    return MathFontConfig(fontset="stixsans")
  rm_name = _register_ttf(rm_path)
  it_name = _face_spec(base, family, "Italic", "italic", rm_name)
  bf_name = _face_spec(base, family, "Bold", "bold", rm_name)
  bi_name = _face_spec(base, family, "BoldItalic", "bold:italic", it_name)
  return MathFontConfig(
    fontset="custom",
    rm=rm_name, it=it_name, bf=bf_name, bfit=bi_name,
    sf=rm_name, tt=rm_name, cal=bi_name,
  )

def _warn_fallback(fontset:str, reason:str) -> None:
  """Say that a requested family did not load.

  The fallback is a different typeface from the document body, which is
  obvious in the output and impossible to explain without this line.
  """
  import warnings
  warnings.warn(
    f"math_fontset={fontset!r} could not be loaded ({reason}); formulas "
    f"render in stixsans and will not match the body font. Expected "
    f"<font_dir>/{fontset}/{fontset}-Regular.ttf, or name a matplotlib "
    f"preset: {', '.join(sorted(_PRESETS))}.",
    RuntimeWarning, stacklevel=3,
  )

def _face_spec(
  base:"Path", family:str, mode:str, style:str,
  fallback:str,
) -> str:
  """Registered face as matplotlib's `family:style` selector.

  Every face of a family reports the same `family_name`, so the style has
  to be spelled out or matplotlib serves the regular cut for italic and
  bold alike - and italic variables are the whole point of math type.
  Falls back to `fallback` when the family ships no such face.
  """
  name = _register_ttf(base / f"{family}-{mode}.ttf")
  return f"{name}:{style}" if name else fallback

def _register_ttf(path:"Path") -> str|None:
  """Register a TTF with matplotlib and return its real family name.
  Returns None if the file doesn't exist. matplotlib's `mathtext.*` keys
  expect a font NAME (resolved via font_manager), not a filesystem path.
  Passing a Windows path with `C:` breaks the rcParams parser.
  """
  if not path.exists():
    return None
  from matplotlib import font_manager as fm
  fm.fontManager.addfont(str(path))
  try:
    from matplotlib.ft2font import FT2Font
    return FT2Font(str(path)).family_name
  except Exception:
    return path.stem

#--------------------------------------------------------------------------------------- Preprocess

import re as _re
_BOLD_CMD_RE = _re.compile(r"\\(?:mathbf|boldsymbol|bm)\s*\{")
_CMD_RE = _re.compile(r"\\([A-Za-z]+)")

# Commands matplotlib mathtext rejects, mapped to an accepted spelling of
# the same thing. Only meaning-preserving swaps belong here: the brace
# accents become rules, which still read as "this span is one quantity,
# labelled". Structural commands with no equivalent (`\begin{cases}`,
# `\stackrel`) are left alone rather than quietly changed.
_ALIASES = {
  "\\le": "\\leq",
  "\\ge": "\\geq",
  "\\gets": "\\leftarrow",
  "\\tfrac": "\\frac",
  "\\textrm": "\\mathrm",
  "\\mbox": "\\text",
  "\\lvert": "|",
  "\\rvert": "|",
  "\\ohm": "\\Omega",
  "\\micro": "\\mu",
  "\\underbrace": "\\underline",
  "\\overbrace": "\\overline",
}

def _apply_aliases(formula:str) -> str:
  """Swap unsupported command spellings for supported ones.

  Matching whole command names keeps `\\leq`, `\\left` and `\\leftarrow`
  clear of the `\\le` entry.
  """
  return _CMD_RE.sub(
    lambda m: _ALIASES.get("\\" + m.group(1), m.group(0)), formula)

def _preprocess_formula(formula:str) -> str:
  """Rewrite bold commands to produce bold italic (vector notation).

  matplotlib's mathtext renders `\\mathbf{F}` as bold UPRIGHT (LaTeX default)
  but physics/engineering convention in Europe is bold ITALIC for vectors.
  We rewrite `\\mathbf{...}`, `\\boldsymbol{...}` and `\\bm{...}` to
  matplotlib's `\\mathbfit{...}` which produces bold italic in STIX fontset.

  Line breaks collapse to spaces and unsupported command spellings are
  swapped for accepted ones, see `_ALIASES`.

  Only rewrites when the brace content is balanced - leaves malformed
  formulas untouched so matplotlib's own error handling kicks in.
  """
  # A `$$` block spans several source lines as often as not. mathtext has
  # no multi-line math and renders an expression holding a newline as its
  # own literal source, so the line breaks collapse to the spaces that
  # math mode reads them as anyway.
  formula = " ".join(formula.split())
  formula = _apply_aliases(formula)
  result = []
  i = 0
  while i < len(formula):
    m = _BOLD_CMD_RE.match(formula, i)
    if not m:
      result.append(formula[i])
      i += 1
      continue
    brace_start = m.end()  # position just after `{`
    depth = 1
    j = brace_start
    while j < len(formula) and depth > 0:
      if formula[j] == "{": depth += 1
      elif formula[j] == "}": depth -= 1
      j += 1
    if depth != 0:
      # Unbalanced - leave as-is
      result.append(formula[i])
      i += 1
      continue
    inner = formula[brace_start:j-1]
    result.append(r"\mathbfit{")
    result.append(inner)
    result.append("}")
    i = j
  return "".join(result)

# Breathing room left around the cropped formula. `savefig` pads all four
# sides, which pushes the drawing bottom below the measured baseline, so the
# baseline offset carries the same number.
_CROP_PAD_IN = 0.005

#------------------------------------------------------------------------------------------- Render

def render_math_svg(
  formula:str,
  fontsize:float = 11,
  color:tuple = (0, 0, 0),
  config:MathFontConfig|None = None,
  engine:str = "auto",
  font:str|None = None,
):
  """Render a math formula as a reportlab `Drawing` (vector).

  For block formulas, where the drawing is placed as a whole and no text
  baseline has to line up with it. `render_math_svg_with_baseline` does the
  work and also reports where the baseline sits.

  Args:
    formula: LaTeX source (without surrounding `$...$`).
    fontsize: Font size in points.
    color: RGB tuple (0-1 range) for glyph color.
    config: Per-renderer `MathFontConfig`. Applied to matplotlib's global
      rcParams immediately before rendering, so multiple renderers with
      different fontsets coexist cleanly. Pass `None` to render with
      whatever fontset rcParams currently holds.

  Returns:
    `reportlab.graphics.shapes.Drawing` object with `.width` and `.height`
    in points. Returns `None` if matplotlib is unavailable or the formula
    fails to parse.
  """
  drawing, _ = render_math_svg_with_baseline(
    formula, fontsize=fontsize, color=color, config=config,
    engine=engine, display=True, font=font)
  return drawing

#--------------------------------------------------------------------------------- Measure baseline

def render_with_mathjax(
  formula:str,
  fontsize:float = 11,
  color:tuple = (0, 0, 0),
  display:bool = False,
  font:str|None = None,
):
  """`(drawing, baseline_from_bottom_pt)` from MathJax, or `(None, 0)`.

  MathJax covers the LaTeX that mathtext does not - `\\underbrace` with its
  label, `\\begin{cases}`, stretchable delimiters - and sets it in New
  Computer Modern. Returns `(None, 0)` when Node or the packages are
  missing, which leaves the caller on the mathtext path.
  """
  try:
    from . import mathjax
  except ImportError:
    return None, 0
  if not mathjax.available():
    return None, 0
  svg = mathjax.render(formula.strip(), display=display, font=font)
  if not svg:
    return None, 0
  # Scaled so the formula's x-height matches the text it sits in.
  return mathjax.to_drawing(svg, fontsize * mathjax.OPTICAL_SCALE, color)

def render_math_svg_with_baseline(
  formula:str,
  fontsize:float = 11,
  color:tuple = (0, 0, 0),
  config:MathFontConfig|None = None,
  engine:str = "auto",
  display:bool = False,
  font:str|None = None,
):
  """Render math and return `(drawing, baseline_from_bottom_pt)`.

  Baseline offset = distance from the BOTTOM of the drawing to the text
  baseline, in points. For inline alignment: place the drawing so that
  `drawing.bottom = text_baseline - baseline_from_bottom_pt`.

  See `render_math_svg` for the `config` argument.

  `engine` picks the renderer: `"auto"` uses MathJax when it is installed
  and mathtext otherwise, `"mathtext"` stays with matplotlib, `"mathjax"`
  refuses to fall back. MathJax understands more LaTeX; mathtext needs no
  Node and runs in-process.

  Returns `(drawing, baseline_from_bottom_pt)` or `(None, 0)` on failure.
  """
  if engine in ("auto", "mathjax"):
    drawing, baseline = render_with_mathjax(
      formula, fontsize=fontsize, color=color, display=display, font=font)
    if drawing is not None or engine == "mathjax":
      return drawing, baseline
  if not _HAS_MATPLOTLIB:
    return None, 0
  if config is not None:
    config.apply()
  formula = _preprocess_formula(formula)
  try:
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    # dpi pinned: the crop and the baseline are measured in inches, and a
    # user `matplotlibrc` must not shift either.
    fig = Figure(figsize=(10, 2), dpi=72)
    fig.patch.set_alpha(0)
    canvas_agg = FigureCanvasAgg(fig)
    fig.text(
      0, 0, f"${formula}$",
      fontsize=fontsize,
      color=color,
      ha="left", va="baseline",
    )
    canvas_agg.draw()
    renderer = canvas_agg.get_renderer()
    tight_bbox_inches = fig.get_tightbbox(renderer)
    # Text sits at y=0 and the tight bbox origin is at `tight.y0` (negative),
    # so negating it gives the baseline distance from the bottom of the crop.
    # The saved crop is padded, and that padding is below the glyphs as well.
    baseline_from_bottom_in = -tight_bbox_inches.y0 + _CROP_PAD_IN
    baseline_from_bottom_pt = baseline_from_bottom_in * 72.0
    buf = io.BytesIO()
    fig.savefig(
      buf, format="svg", transparent=True,
      bbox_inches="tight", pad_inches=_CROP_PAD_IN,
    )
    buf.seek(0)
    drawing = svg2rlg(buf)
    return drawing, baseline_from_bottom_pt
  except Exception:
    return None, 0  # math is optional; caller falls back to plain text
