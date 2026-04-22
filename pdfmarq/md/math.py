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

_PRESETS = {"stix", "stixsans", "cm", "dejavusans", "dejavuserif"}
_LAST_FONTSET = "stixsans"

def configure_math_fonts(fontset:str="stixsans", font_dir:str|None=None):
  """Configure matplotlib mathtext fonts.
  Args:
    fontset: Either a matplotlib preset (`"stix"`, `"stixsans"`, `"cm"`,
      `"dejavusans"`, `"dejavuserif"`) or a font family name. When a family
      name is given, the loader looks for `<font_dir>/<family>/<family>-Regular.ttf`
      and registers Regular/Italic/Bold/BoldItalic from that folder.
    font_dir: Root font directory (only used when `fontset` is a family name).
  """
  global _LAST_FONTSET
  if not _HAS_MATPLOTLIB:
    return
  import matplotlib as mpl
  if fontset in _PRESETS:
    mpl.rcParams["mathtext.fontset"] = fontset
    _LAST_FONTSET = fontset
    return
  if not font_dir:
    mpl.rcParams["mathtext.fontset"] = "stixsans"
    _LAST_FONTSET = "stixsans"
    return
  family = fontset
  base = Path(font_dir) / family
  rm_path = base / f"{family}-Regular.ttf"
  if not rm_path.exists():
    mpl.rcParams["mathtext.fontset"] = "stixsans"
    _LAST_FONTSET = "stixsans"
    return
  rm_name = _register_ttf(rm_path)
  it_name = _register_ttf(base / f"{family}-Italic.ttf") or rm_name
  bf_name = _register_ttf(base / f"{family}-Bold.ttf") or rm_name
  bi_name = _register_ttf(base / f"{family}-BoldItalic.ttf") or it_name
  mpl.rcParams["mathtext.fontset"] = "custom"
  mpl.rcParams["mathtext.rm"] = rm_name
  mpl.rcParams["mathtext.it"] = it_name
  mpl.rcParams["mathtext.bf"] = bf_name
  mpl.rcParams["mathtext.sf"] = rm_name
  mpl.rcParams["mathtext.tt"] = rm_name
  mpl.rcParams["mathtext.cal"] = bi_name
  _LAST_FONTSET = "custom"

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

def _ensure_fontset():
  """Re-apply last configured fontset. Call before every render because
  matplotlib's rcParams are global and may have been clobbered by other
  code using matplotlib (e.g. user imported pyplot after us)."""
  if not _HAS_MATPLOTLIB:
    return
  import matplotlib as mpl
  if mpl.rcParams["mathtext.fontset"] != _LAST_FONTSET:
    mpl.rcParams["mathtext.fontset"] = _LAST_FONTSET

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

def render_math_svg(formula:str, fontsize:float=11, color:tuple=(0, 0, 0)):
  """Render a math formula as a reportlab `Drawing` (vector).

  Args:
    formula: LaTeX source (without surrounding `$...$`).
    fontsize: Font size in points.
    color: RGB tuple (0-1 range) for glyph color.

  Returns:
    `reportlab.graphics.shapes.Drawing` object with `.width` and `.height`
    in points. Returns `None` if matplotlib is unavailable or the formula
    fails to parse.
  """
  if not _HAS_MATPLOTLIB:
    return None
  _ensure_fontset()
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
):
  """Render math and return `(drawing, baseline_from_bottom_pt)`.

  Baseline offset = distance from the BOTTOM of the drawing to the text
  baseline, in points. For inline alignment: place the drawing so that
  `drawing.bottom = text_baseline - baseline_from_bottom_pt`.

  Technique: render the formula at (0, 0) with `va='baseline'`, then use
  `get_tightbbox` to find the bbox of the inked region. In matplotlib
  display coords, y=0 is the baseline. The distance from bbox bottom (y_min
  of ink) up to y=0 gives us how far below the baseline the lowest ink
  extends (descent). `baseline_from_bottom = -y_min_of_bbox_display_pt`.

  Returns `(drawing, baseline_from_bottom_pt)` or `(None, 0)` on failure.
  """
  if not _HAS_MATPLOTLIB:
    return None, 0
  _ensure_fontset()
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
