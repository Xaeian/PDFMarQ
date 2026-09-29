# pdfmarq/graphics.py

"""Graphics primitives - shapes, images, SVG."""
import os
from reportlab.lib.utils import ImageReader
from svglib.svglib import svg2rlg, load_svg_file, SvgRenderer
from reportlab.graphics import renderPDF
from . import svgmarkers

#------------------------------------------------------------------------------------------- Shapes

def draw_line(
  canvas,
  x1:float, y1:float,
  x2:float, y2:float,
  width:float = 1,
  dash:tuple|None = None,
):
  """Draw line on canvas (coordinates in pt)."""
  canvas.setLineWidth(width)
  if dash:
    canvas.setDash(dash[0], dash[1])
  else:
    canvas.setDash()
  canvas.line(x1, y1, x2, y2)
  if dash:
    canvas.setDash()  # restore solid stroke for subsequent calls

def draw_rect(
  canvas,
  x:float, y:float,
  width:float, height:float,
  stroke_width:float = 0,
  dash:tuple|None = None,
  fill:bool = True,
):
  """Draw rectangle on canvas (coordinates in pt)."""
  canvas.setLineWidth(stroke_width)
  if dash and stroke_width > 0:
    canvas.setDash(dash[0], dash[1])
  else:
    canvas.setDash()
  canvas.rect(x, y, width, height, stroke=1 if stroke_width else 0, fill=1 if fill else 0)

def draw_round_rect(
  canvas,
  x:float, y:float,
  width:float, height:float,
  radius:float,
  stroke_width:float = 0,
  fill:bool = True,
):
  """Draw rectangle with rounded corners (coordinates in pt)."""
  canvas.setLineWidth(stroke_width)
  canvas.setDash()
  canvas.roundRect(
    x, y, width, height, radius,
    stroke=1 if stroke_width else 0,
    fill=1 if fill else 0,
  )

def draw_circle(
  canvas,
  x:float, y:float,
  radius:float,
  stroke_width:float = 0,
  fill:bool = True,
):
  """Draw circle on canvas (x, y = center, coordinates in pt)."""
  canvas.setLineWidth(stroke_width)
  canvas.setDash()
  canvas.circle(x, y, radius, stroke=1 if stroke_width else 0, fill=1 if fill else 0)

def draw_path(
  canvas,
  points:list[tuple[float, float]],
  close:bool = False,
  stroke_width:float = 1,
  fill:bool = False,
):
  """Draw path through points (coordinates in pt)."""
  if len(points) < 2:
    return
  canvas.setLineWidth(stroke_width)
  canvas.setDash()
  p = canvas.beginPath()
  p.moveTo(points[0][0], points[0][1])
  for pt in points[1:]:
    p.lineTo(pt[0], pt[1])
  if close:
    p.close()
  canvas.drawPath(p, stroke=1 if stroke_width else 0, fill=1 if fill else 0)

#------------------------------------------------------------------------------------------- Images

def draw_image(
  canvas,
  path:str|ImageReader,
  x:float, y:float,
  width:float, height:float,
):
  """Draw image on canvas (coordinates in pt)."""
  canvas.drawImage(path, x, y, width=width, height=height, mask="auto")

def load_svg(path:str|os.PathLike):
  """
  svglib `Drawing` of the SVG file at `path`, arrowheads included, or `None`.

  svglib drops `<marker>` without a word, so markers are expanded into plain shapes first.
  A `Path` becomes a `str`: svglib resolves a relative `<image>` only against a `str`.
  `.svgz` goes to `svg2rlg` as it is, its markers still dropped.
  """
  if isinstance(path, os.PathLike): path = os.fspath(path)
  if isinstance(path, str) and path.lower().endswith(".svgz"): return svg2rlg(path)
  root = load_svg_file(path)
  if root is None: return None
  svgmarkers.expand(root)
  return SvgRenderer(path).render(root)

def draw_svg(
  canvas,
  path:str,
  x:float, y:float,
  width:float, height:float,
):
  """Draw SVG on canvas (coordinates in pt). Uses canvas-level transform
  (`saveState`/`translate`/`scale`/`restoreState`) so target size is
  deterministic on every platform/svglib version - internal `Drawing`
  attributes like `transform` and `scale` are inconsistent across versions,
  especially on Python 3.13 + Windows. Falls back to the union bounding
  box when intrinsic dims are missing."""
  drawing = load_svg(path)
  if drawing is None:
    raise ValueError(f"Could not load SVG: {path}")
  nat_w = float(drawing.width or 0)
  nat_h = float(drawing.height or 0)
  if nat_w <= 0 or nat_h <= 0:
    try:
      x0, y0, x1, y1 = drawing.getBounds()
      nat_w = nat_w if nat_w > 0 else max(x1 - x0, 1.0)
      nat_h = nat_h if nat_h > 0 else max(y1 - y0, 1.0)
    except Exception:
      nat_w = nat_w if nat_w > 0 else width
      nat_h = nat_h if nat_h > 0 else height
  s = min(width / nat_w, height / nat_h)
  canvas.saveState()
  canvas.translate(x, y)
  canvas.scale(s, s)
  renderPDF.draw(drawing, canvas, 0, 0)
  canvas.restoreState()

