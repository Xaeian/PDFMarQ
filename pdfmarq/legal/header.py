# pdfmarq/legal/header.py

"""
Letter header and attachment list of a legal document, both drawn from frontmatter.

Header rows, each drawn only when its keys are set:

  1. `logo`, aligned by `style.logo_align`
  2. `from` on the left, `place` and `date` on the right of its first line
  3. `to` flush with the right margin, or the left one with `style.to_align`,
     then `ref` under it: the case number, in bold after `style.ref_label`
  4. `title`, centred

A logo at the side shares the title's row when nothing stands between them, as on a contract,
and the preamble after the title runs beside it.
Values are plain text. A YAML block (`|`) or a list gives one line per entry,
or entries joined by commas for `place` and `ref`, which keep to one line.
"""
from dataclasses import dataclass
from ..core import PDF
from ..constants import Align
from ..graphics import image_aspect
from ..inline import RichSegment, render_rich, measure_extent, wrap_line_heights
from ..utils import format_date
from .style import LegalStyle

_ROW_GAP_MM = 6 # below every header row
_LIST_GAP_MM = 6 # above the attachments
_SIDE_GAP_MM = 5 # between text and what stands beside it: the date, a logo
_SMALL_CAPS = 0.8 # a font with no small capitals: lowercase letters as capitals this much smaller
# Capitals scaled down come out narrower than drawn small capitals:
# letter-spacing, in em, gives them back their width, as typography asks of small capitals anyway.
_SMALL_CAPS_SPACE = 0.07

@dataclass
class Side:
  """A logo at the side of the title, which the preamble runs beside."""
  top: float # mm below the top margin, where the logo and the title start
  bottom: float # mm below the top margin, where the logo ends
  width: float # mm the text gives way: the logo and the gap beside it
  align: str # the side it stands on, `L` or `R`

#------------------------------------------------------------------------------------------- Values

def lines_of(value) -> list[str]:
  """
  A YAML block text or list as lines, blank and empty entries dropped. `None` gives none.
  A mapping is refused: no header value has named parts.
  """
  if value is None: return []
  if isinstance(value, dict):
    raise ValueError(f"a frontmatter value here is text or a list, got a mapping: {value!r}")
  items = value if isinstance(value, (list, tuple)) else str(value).splitlines()
  return [str(item).strip() for item in items if item is not None and str(item).strip()]

def _one_line(value) -> str:
  """A YAML value on one line: the entries of a block or a list joined by commas."""
  return ", ".join(lines_of(value))

def _seg(style:LegalStyle, text:str, mode:str|None=None) -> RichSegment:
  """Header-size text in the face of the page around the text."""
  return RichSegment(text, family=style.page_font, mode=mode or style.body_mode,
    size=style.header_size, color=style.body_color)

def _lines(
  pdf:PDF, style:LegalStyle, lines:list,
  x:float, y:float, width:float, align:str,
) -> float:
  """
  Draw `lines` one under another at header size, each a text or its own segments.
  Returns their height (mm).
  """
  segs = []
  for i, line in enumerate(lines):
    if i: segs.append(_seg(style, "\n"))
    segs += [_seg(style, line)] if isinstance(line, str) else line
  return render_rich(pdf, segs, width, x, y, align, style.line_height)

#------------------------------------------------------------------------------------------- Header

def draw_header(
  pdf:PDF, style:LegalStyle, fm:dict, logo:str|None,
  beside:bool = True,
) -> Side|None:
  """
  Draw the header rows at the cursor, in the current frame, and leave the cursor below them.

  `logo` is the resolved path of an existing file, or `None`.
  A logo at the side of a lone title stands beside it, and the cursor stops below the title:
  the returned `Side` tells the caller where the logo is, for the preamble to run beside it.
  `beside=False` keeps the logo in a row of its own, as in a column of a parallel document.
  """
  width = pdf.content_width
  top = y = pdf.y
  sender = lines_of(fm.get("from"))
  place = _one_line(fm.get("place"))
  stamp = ", ".join(t for t in (place, format_date(fm.get("date"), style.date_format)) if t)
  recipient: list = lines_of(fm.get("to")) # texts, then the case number as segments
  ref = _one_line(fm.get("ref"))
  if ref:
    recipient.append([_seg(style, f"{style.ref_label}: "), _seg(style, ref, style.bold_mode)])
  title = _title_segments(pdf, style, lines_of(fm.get("title")))
  box = _logo_box(style, logo) if logo else None
  # beside a lone title only, kept clear on both sides so the title stays centred
  clear = box[0] + _SIDE_GAP_MM if box else 0
  beside_title = bool(beside and box and title and style.logo_align != "C"
    and not (sender or stamp or recipient)
    and width - 2 * clear >= measure_extent(pdf, title)[0])
  if box and not beside_title:
    _draw_logo(pdf, style, logo, box, y, width)
    y += box[1] + _ROW_GAP_MM
  if sender or stamp:
    height = 0.0
    room = width
    if stamp:
      height = _lines(pdf, style, [stamp], 0, y, width, Align.RIGHT)
      room = width - measure_extent(pdf, [_seg(style, stamp)])[1] - _SIDE_GAP_MM
      if sender and room < measure_extent(pdf, [_seg(style, line) for line in sender])[0]:
        y += height # no room beside the stamp: the sender goes under it
        height, room = 0.0, width
    if sender:
      height = max(height, _lines(pdf, style, sender, 0, y, room, Align.LEFT))
    y += height + _ROW_GAP_MM
  if recipient:
    right = style.to_align == "R"
    y += _lines(pdf, style, recipient, width / 2 if right else 0, y, width / 2,
      Align.RIGHT if right else Align.LEFT) + _ROW_GAP_MM
  side = None
  if title:
    if y > top: y += style.title_gap - _ROW_GAP_MM
    if beside_title:
      _draw_logo(pdf, style, logo, box, y, width)
      side = Side(y, y + box[1], clear, style.logo_align)
      y += _title(pdf, title, clear, y, width - 2 * clear) + style.title_gap
    else:
      y += _title(pdf, title, 0, y, width) + style.title_gap
  pdf.cursor(0, y)
  return side

def _title(pdf:PDF, segs:list[RichSegment], x:float, y:float, width:float) -> float:
  """Title centred in the `width` from `x`. Returns its height (mm)."""
  return render_rich(pdf, segs, width, x, y, Align.CENTER, 1.2)

def _title_segments(pdf:PDF, style:LegalStyle, lines:list[str]) -> list[RichSegment]:
  """
  The title in the header face, or the heading face when the style sets none, a line per entry.
  With `title_caps` lowercase letters come out as small capitals, one segment per run:
  the font's own, or capitals scaled down and spaced out when it has none.
  """
  family = style.header_font or style.font_head
  drawn = pdf.fonts.small_caps(family, style.head_mode) if style.title_caps else None
  def seg(text:str, small:bool) -> RichSegment:
    face, size, space = family, style.title_size, 0.0
    if small and drawn: face = drawn
    elif small: size, space = size * _SMALL_CAPS, size * _SMALL_CAPS * _SMALL_CAPS_SPACE
    return RichSegment(text, family=face, mode=style.head_mode, size=size,
      color=style.head_color, char_space=space)
  segs: list[RichSegment] = []
  for i, line in enumerate(lines):
    if i: segs.append(seg("\n", False))
    if not style.title_caps:
      segs.append(seg(line, False))
      continue
    small = None
    for ch in line:
      if small == ch.islower(): segs[-1].text += ch.upper()
      else: segs.append(seg(ch.upper(), ch.islower()))
      small = ch.islower()
  return segs

def _logo_box(style:LegalStyle, path:str) -> tuple[float, float]:
  """`(width, height)` of the logo in mm, within `logo_max_w` × `logo_max_h`, aspect kept."""
  aspect = image_aspect(path)
  w, h = style.logo_max_h * aspect, style.logo_max_h
  if w > style.logo_max_w:
    w, h = style.logo_max_w, style.logo_max_w / aspect
  return w, h

def _draw_logo(
  pdf:PDF, style:LegalStyle, path:str, box:tuple[float, float],
  y:float, width:float,
):
  """Logo of size `box` at `y`, aligned across `width` by `logo_align`."""
  w, h = box
  x = {"L": 0.0, "C": (width - w) / 2, "R": width - w}[style.logo_align]
  pdf.cursor(x, y)
  if path.lower().endswith(".svg"): pdf.svg(path, w, h)
  else: pdf.image(path, w, h)

#-------------------------------------------------------------------------------------- Attachments

def _attachment_segments(style:LegalStyle, items:list[str]) -> list[RichSegment]:
  """The label in bold, then one numbered line per attachment."""
  segs = [_seg(style, f"{style.attachments_label}:", style.bold_mode)]
  for i, item in enumerate(items, 1):
    segs += [_seg(style, "\n"), _seg(style, f"{i}. {item}")]
  return segs

def attachments_height(pdf:PDF, style:LegalStyle, items:list[str]) -> float:
  """Height (mm) `draw_attachments` takes in the current frame, the gap above included."""
  if not items: return 0.0
  segs = _attachment_segments(style, items)
  return _LIST_GAP_MM + sum(wrap_line_heights(pdf, segs, pdf.content_width, style.line_height))

def draw_attachments(pdf:PDF, style:LegalStyle, items:list[str]):
  """Attachment list at the cursor: its label, then the items numbered. Cursor left below it."""
  if not items: return
  y = pdf.y + _LIST_GAP_MM
  h = render_rich(pdf, _attachment_segments(style, items), pdf.content_width, 0, y,
    Align.LEFT, style.line_height)
  pdf.cursor(0, y + h)
