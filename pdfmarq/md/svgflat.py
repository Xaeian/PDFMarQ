# pdfmarq/md/svgflat.py

"""
Flatten an SVG to absolute coordinates: no transforms, no nested viewports.

MathJax assembles a stretchy brace inside nested `<svg>` elements carrying
their own `x`, `y` and `viewBox`. svglib does not reproduce that coordinate
system, so the pieces of the brace land scattered across its label. Resolving
the geometry here leaves svglib nothing to get wrong, and the result stays
vector.

Deliberately narrow: `translate` and `scale`, absolute `M`/`L`/`C`/`Z` path
data, `path`, `rect` and `text` shapes. That is what MathJax emits. Anything
else returns `None` so the caller keeps the original rather than a drawing
quietly reshaped by a rule this does not implement.

  >>> from pdfmarq.md.svgflat import flatten
  >>> flat = flatten(svg_text)
"""

import re
from typing import NamedTuple
from xml.etree import ElementTree

SVG_NS = "http://www.w3.org/2000/svg"

_NUM = r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?"
_NUM_RE = re.compile(_NUM)
# Only the two forms MathJax writes. A general matrix would need a full 2x3;
# a diagonal scale plus a translation covers all of its output.
_TRANSFORM_RE = re.compile(r"(translate|scale)\s*\(([^)]*)\)")
_PATH_RE = re.compile(r"([A-Za-z])|(" + _NUM + ")")

#---------------------------------------------------------------------------------------- Transform

class Frame(NamedTuple):
  """Coordinate mapping `x' = sx*x + tx`, `y' = sy*y + ty`."""
  sx: float = 1.0
  sy: float = 1.0
  tx: float = 0.0
  ty: float = 0.0

  def then(self, sx=1.0, sy=1.0, tx=0.0, ty=0.0) -> "Frame":
    """This frame with a child transform applied inside it."""
    return Frame(self.sx * sx, self.sy * sy,
      self.sx * tx + self.tx, self.sy * ty + self.ty)

  def point(self, x:float, y:float) -> tuple[float, float]:
    return self.sx * x + self.tx, self.sy * y + self.ty

def _with_transform(frame:Frame, text:str|None) -> Frame:
  """`frame` with an SVG `transform` attribute applied, left to right."""
  if not text:
    return frame
  for name, args in _TRANSFORM_RE.findall(text):
    nums = [float(n) for n in _NUM_RE.findall(args)]
    if name == "translate":
      frame = frame.then(tx=nums[0] if nums else 0.0,
        ty=nums[1] if len(nums) > 1 else 0.0)
    else:
      sx = nums[0] if nums else 1.0
      frame = frame.then(sx=sx, sy=nums[1] if len(nums) > 1 else sx)
  return frame

def _number(node, name:str) -> float:
  """Leading number of an attribute, 0 when absent."""
  found = _NUM_RE.search(node.get(name) or "")
  return float(found.group(0)) if found else 0.0

def _with_viewport(frame:Frame, node) -> Frame:
  """`frame` with a nested `<svg>`: its `x`/`y` placement and `viewBox` mapping.

  A nested viewport also clips, which is ignored: MathJax sizes these boxes to
  the glyph pieces they hold, so nothing reaches an edge.
  """
  frame = frame.then(tx=_number(node, "x"), ty=_number(node, "y"))
  box = _NUM_RE.findall(node.get("viewBox") or "")
  width, height = _number(node, "width"), _number(node, "height")
  if len(box) < 4 or width <= 0 or height <= 0:
    return frame
  min_x, min_y, box_w, box_h = (float(v) for v in box[:4])
  if not box_w or not box_h:
    return frame
  return frame.then(sx=width / box_w, sy=height / box_h).then(tx=-min_x, ty=-min_y)

#---------------------------------------------------------------------------------------- Path data

def _fmt(value:float) -> str:
  """Plain decimal - reportlab's path parser has no use for an exponent."""
  return f"{value:.3f}".rstrip("0").rstrip(".") or "0"

def transform_path(data:str, frame:Frame) -> str|None:
  """Absolute `M`/`L`/`C`/`Z` path data mapped through `frame`, or `None`.

  `None` covers a relative command, an unknown letter and an odd coordinate
  count alike: all of them mean the data says something this cannot restate.
  """
  out: list[str] = []
  pending: list[float] = []
  command = ""

  def emit() -> bool:
    if not command or len(pending) % 2:
      return not pending
    out.append(command)
    for i in range(0, len(pending), 2):
      out.append("%s %s" % tuple(_fmt(v) for v in frame.point(*pending[i:i + 2])))
    return True

  for letter, number in _PATH_RE.findall(data):
    if number:
      pending.append(float(number))
      continue
    if letter not in ("M", "L", "C", "Z") or not emit():
      return None
    pending, command = [], "" if letter == "Z" else letter
    if letter == "Z":
      out.append("Z")
  return " ".join(out) if emit() else None

#------------------------------------------------------------------------------------------ Flatten

_SKIP = ("defs", "title", "desc", "metadata") # only matter with <use>, unused here
# Paint is inherited in SVG, and MathJax sets all of it - including
# `stroke-width="0"` - on one wrapping group. Flattening drops the group,
# so these travel down to the shapes or a renderer strokes every glyph
# with its own default width.
_PAINT = ("fill", "stroke", "stroke-width", "fill-rule", "fill-opacity")

def _tag(node) -> str:
  return node.tag.split("}")[-1]

def _with_paint(paint:dict, node) -> dict:
  """`paint` overlaid with whatever `node` states for itself."""
  own = {key: node.get(key) for key in _PAINT if node.get(key)}
  return {**paint, **own} if own else paint

def _shape(name:str, attrs:dict, paint:dict):
  """A flattened element with the paint in force where it was found."""
  return ElementTree.Element(f"{{{SVG_NS}}}{name}", {**paint, **attrs})

def _flat_rect(node, frame:Frame, paint:dict):
  """A `rect` by its transformed corners, so a negative scale flips it."""
  x0, y0 = frame.point(_number(node, "x"), _number(node, "y"))
  x1, y1 = frame.point(_number(node, "x") + _number(node, "width"),
    _number(node, "y") + _number(node, "height"))
  return _shape("rect", {
    "x": _fmt(min(x0, x1)), "y": _fmt(min(y0, y1)),
    "width": _fmt(abs(x1 - x0)), "height": _fmt(abs(y1 - y0)),
  }, paint)

def _flat_text(node, frame:Frame, paint:dict):
  """A `text` at its transformed anchor, or `None` when the frame turns it.

  MathJax writes one of these in place of a glyph its font does not carry, so
  it stands for a single character set in a system face. Text cannot be
  reduced to coordinates the way a path can - it keeps its own size and
  direction, which only survives an upright scale.
  """
  if frame.sx <= 0 or frame.sy <= 0:
    return None
  x, y = frame.point(_number(node, "x"), _number(node, "y"))
  attrs = {"x": _fmt(x), "y": _fmt(y),
    "font-size": _fmt(_number(node, "font-size") * frame.sy)}
  for key in ("font-family", "font-style", "font-weight", "text-anchor"):
    if node.get(key):
      attrs[key] = node.get(key)
  shape = _shape("text", attrs, paint)
  shape.text = node.text
  return shape

def _walk(node, frame:Frame, paint:dict, out:list) -> bool:
  """Collect flattened shapes from `node`'s children."""
  for child in node:
    name = _tag(child)
    if name in _SKIP:
      continue
    inner = _with_transform(frame, child.get("transform"))
    ink = _with_paint(paint, child)
    if name == "g":
      if not _walk(child, inner, ink, out): return False
    elif name == "svg":
      if not _walk(child, _with_viewport(inner, child), ink, out): return False
    elif name == "path":
      data = transform_path(child.get("d") or "", inner)
      if data is None: return False
      out.append(_shape("path", {"d": data}, ink))
    elif name == "rect":
      out.append(_flat_rect(child, inner, ink))
    elif name == "text":
      shape = _flat_text(child, inner, ink)
      if shape is None: return False
      out.append(shape)
    else:
      return False
  return True

def _root_svg(fragment:str):
  """Outermost `<svg>` in `fragment`, or `None`.

  MathJax hands over a container holding the SVG next to an assistive-MathML
  copy, so the fragment is not one element and the SVG is not reliably the
  first child.
  """
  for candidate in (fragment, f"<wrap>{fragment}</wrap>"):
    try:
      node = ElementTree.fromstring(candidate)
    except ElementTree.ParseError:
      continue
    if _tag(node) == "svg":
      return node
    for child in node:
      if _tag(child) == "svg":
        return child
  return None

def flatten(svg:str) -> str|None:
  """SVG with every transform and nested viewport resolved into coordinates.

  `None` when the fragment holds no SVG, or a construct outside the
  supported set.
  """
  root = _root_svg(svg)
  if root is None:
    return None
  shapes: list = []
  if not _walk(root, _with_transform(Frame(), root.get("transform")),
      _with_paint({}, root), shapes):
    return None
  if not shapes:
    return None
  flat = ElementTree.Element(f"{{{SVG_NS}}}svg")
  for key in ("width", "height", "viewBox"):
    if root.get(key):
      flat.set(key, root.get(key))
  flat.extend(shapes)
  ElementTree.register_namespace("", SVG_NS)
  return ElementTree.tostring(flat, encoding="unicode")
