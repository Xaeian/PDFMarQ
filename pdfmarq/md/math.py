# pdfmarq/md/math.py

"""
Math formula rendering via matplotlib.mathtext → SVG → reportlab vector.

Uses matplotlib's mathtext parser (LaTeX subset) to render formulas, then
converts the SVG output to a reportlab `Drawing` via svglib. The result is
a **true vector** embedded in the PDF (no bitmaps), sharp at any zoom.

Example:
  >>> from pdfmarq.math import render_math_svg
  >>> drawing = render_math_svg(r"E = mc^2", fontsize=11)
  >>> # drawing.width, drawing.height in pt
  >>> # renderPDF.draw(drawing, canvas, x, y) to place on page
"""

__extras__ = ("math", ["matplotlib"])

import io
from pathlib import Path

try:
  import matplotlib
  matplotlib.use("Agg")
  from matplotlib.figure import Figure
  from svglib.svglib import svg2rlg
  _HAS_MATPLOTLIB = True
except ImportError:
  _HAS_MATPLOTLIB = False

#------------------------------------------------------------------------------- Fontset config

from dataclasses import dataclass

_PRESETS = {"stix", "stixsans", "cm", "dejavusans", "dejavuserif"}

@dataclass
class MathFontConfig:
  """Per-renderer matplotlib mathtext settings.

  matplotlib's `rcParams` are process-global, so two `MarkdownRenderer`
  instances with different `math_fontset` would clobber each other if we
  set rcParams at construction time. We now hold the config per-renderer
  and apply it via `apply()` immediately before each math render call.
  """
  fontset: str = "stixsans"
  rm: str|None = None
  it: str|None = None
  bf: str|None = None
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
          ("mathtext.bf", self.bf), ("mathtext.sf", self.sf),
          ("mathtext.tt", self.tt), ("mathtext.cal", self.cal)):
        if val:
          mpl.rcParams[key] = val

def configure_math_fonts(
  fontset: str = "stixsans",
  font_dir: str|None = None,
) -> MathFontConfig:
  """Build a `MathFontConfig` for the given fontset.

  Args:
    fontset: Either a matplotlib preset (`"stix"`, `"stixsans"`, `"cm"`,
      `"dejavusans"`, `"dejavuserif"`) or a font family name. When a family
      name is given, the loader looks for `<font_dir>/<family>/<family>-Regular.ttf`
      and registers Regular/Italic/Bold/BoldItalic from that folder.
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
  if not font_dir:
    return MathFontConfig(fontset="stixsans")
  family = fontset
  base = Path(font_dir) / family
  rm_path = base / f"{family}-Regular.ttf"
  if not rm_path.exists():
    return MathFontConfig(fontset="stixsans")
  rm_name = _register_ttf(rm_path)
  it_name = _register_ttf(base / f"{family}-Italic.ttf") or rm_name
  bf_name = _register_ttf(base / f"{family}-Bold.ttf") or rm_name
  bi_name = _register_ttf(base / f"{family}-BoldItalic.ttf") or it_name
  return MathFontConfig(
    fontset="custom",
    rm=rm_name, it=it_name, bf=bf_name,
    sf=rm_name, tt=rm_name, cal=bi_name,
  )

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

#----------------------------------------------------------------------------------- Preprocess

import re as _re
_BOLD_CMD_RE = _re.compile(r"\\(?:mathbf|boldsymbol|bm)\s*\{")

def _preprocess_formula(formula:str) -> str:
  """Rewrite bold commands to produce bold italic (vector notation).

  matplotlib's mathtext renders `\\mathbf{F}` as bold UPRIGHT (LaTeX default)
  but physics/engineering convention in Europe is bold ITALIC for vectors.
  We rewrite `\\mathbf{...}`, `\\boldsymbol{...}` and `\\bm{...}` to
  matplotlib's `\\mathbfit{...}` which produces bold italic in STIX fontset.

  Only rewrites when the brace content is balanced - leaves malformed
  formulas untouched so matplotlib's own error handling kicks in.
  """
  result = []
  i = 0
  while i < len(formula):
    m = _BOLD_CMD_RE.match(formula, i)
    if not m:
      result.append(formula[i])
      i += 1
      continue
    # Found a bold command - find matching closing brace
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

#--------------------------------------------------------------------------------------- Render

def render_math_svg(
  formula: str,
  fontsize: float = 11,
  color: tuple = (0, 0, 0),
  config: MathFontConfig|None = None,
):
  """Render a math formula as a reportlab `Drawing` (vector).

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
  if not _HAS_MATPLOTLIB:
    return None
  if config is not None:
    config.apply()
  formula = _preprocess_formula(formula)
  try:
    fig = Figure(figsize=(10, 2))
    fig.patch.set_alpha(0)
    fig.text(
      0, 0, f"${formula}$",
      fontsize=fontsize,
      color=color,
      ha="left", va="baseline",
    )
    buf = io.BytesIO()
    fig.savefig(
      buf, format="svg", transparent=True,
      bbox_inches="tight", pad_inches=0.005,
    )
    buf.seek(0)
    drawing = svg2rlg(buf)
    return drawing
  except Exception:
    return None

#----------------------------------------------------------------------------- Measure baseline

def render_math_svg_with_baseline(
  formula: str,
  fontsize: float = 11,
  color: tuple = (0, 0, 0),
  config: MathFontConfig|None = None,
):
  """Render math and return `(drawing, baseline_from_bottom_pt)`.

  Baseline offset = distance from the BOTTOM of the drawing to the text
  baseline, in points. For inline alignment: place the drawing so that
  `drawing.bottom = text_baseline - baseline_from_bottom_pt`.

  See `render_math_svg` for the `config` argument.

  Returns `(drawing, baseline_from_bottom_pt)` or `(None, 0)` on failure.
  """
  if not _HAS_MATPLOTLIB:
    return None, 0
  if config is not None:
    config.apply()
  formula = _preprocess_formula(formula)
  try:
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    fig = Figure(figsize=(10, 2), dpi=72)
    fig.patch.set_alpha(0)
    canvas_agg = FigureCanvasAgg(fig)
    txt = fig.text(
      0, 0, f"${formula}$",
      fontsize=fontsize,
      color=color,
      ha="left", va="baseline",
    )
    canvas_agg.draw()
    renderer = canvas_agg.get_renderer()
    tight_bbox_inches = fig.get_tightbbox(renderer)
    # baseline at y=0 in figure coord; tight bbox origin is at tight.y0 inches
    baseline_from_bottom_in = -tight_bbox_inches.y0
    baseline_from_bottom_pt = baseline_from_bottom_in * 72.0
    # Save SVG with tight bbox
    buf = io.BytesIO()
    fig.savefig(
      buf, format="svg", transparent=True,
      bbox_inches="tight", pad_inches=0.005,
    )
    buf.seek(0)
    drawing = svg2rlg(buf)
    return drawing, baseline_from_bottom_pt
  except Exception:
    pass  # silent failure - math is optional
    return None, 0
