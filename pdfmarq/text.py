# pdfmarq/text.py

"""Text measurement and box fitting."""
from dataclasses import dataclass
from PIL import ImageFont
from reportlab.pdfbase.pdfmetrics import stringWidth
from .fonts import FontManager, is_builtin, builtin_name

#--------------------------------------------------------------------------------- BoxFitResult

@dataclass
class BoxFitResult:
  """Result of text box fitting."""
  text: str
  font_size: float
  height: float  # total height in pt
  lines: int
  overflow: bool = False

#---------------------------------------------------------------------------------- TextMetrics

class TextMetrics:
  """Text measurement with font support."""
  def __init__(self, font_manager:FontManager):
    self.fonts = font_manager

  def _font_key(self, family:str, mode:str) -> str:
    return f"{family}-{mode}"

  def text_width(self, text:str, family:str, mode:str, size:float) -> float:
    """Get text width in points."""
    if is_builtin(family, mode):
      font_name = builtin_name(family, mode)
    else:
      font_name = self.fonts.register(family, mode)
    return stringWidth(text, font_name, size)

  def line_height(self, family:str, mode:str, size:float) -> float:
    """Get single line height (ascent) in points.

    Note: this returns the line leading ascent used for multi-line layout and
    cell sizing, NOT the real visual ascent. For visual text centering use
    `visual_metrics()`.
    """
    if is_builtin(family, mode): return size * 0.8
    try:
      path = self.fonts.get_path(family, mode)
      font = ImageFont.truetype(path, int(size))
      ascent, _ = font.getmetrics()
      return float(ascent)
    except Exception:
      return size * 0.8

  def lines_height(self, lines:int, family:str, mode:str, size:float) -> float:
    """Get total height for N lines in points (with leading)."""
    if lines <= 0: return self.line_height(family, mode, size)
    if is_builtin(family, mode): return size * 1.2 * lines
    try:
      path = self.fonts.get_path(family, mode)
      font = ImageFont.truetype(path, int(size))
      ascent, descent = font.getmetrics()
      return float(lines * (ascent + descent))
    except Exception:
      return size * 1.2 * lines

  def visual_metrics(self, family:str, mode:str, size:float) -> tuple[float, float]:
    """Real `(ascent, descent)` in points for visual centering.

    Returns line-box ascent and descent from reportlab (builtin) or PIL (TTF).
    Used by `core.text()` for vertical positioning inside fixed-height boxes
    like table cells. The line-box ascent includes a small amount of space
    above capital letters (for accent marks) - this is DESIRED: it makes text
    visually sit in the lower portion of the box rather than cap-top-flush.
    """
    if is_builtin(family, mode):
      from reportlab.pdfbase.pdfmetrics import getAscent, getDescent
      name = builtin_name(family, mode)
      try:
        return float(getAscent(name, size)), float(abs(getDescent(name, size)))
      except Exception:
        return size * 0.8, size * 0.21
    try:
      path = self.fonts.get_path(family, mode)
      font = ImageFont.truetype(path, int(size))
      a, d = font.getmetrics()
      return float(a), float(d)
    except Exception:
      return size * 0.72, size * 0.21

  def box_fit(
    self,
    text: str,
    width: float,  # pt
    height: float = 0,  # pt, 0 = no height constraint
    family: str = "Helvetica",
    mode: str = "Regular",
    size: float = 12,
    autoscale: float|None = None,
    link_char: str = "·",
    enter_in: str = "\n",
    enter_out: str = "\n",
  ) -> BoxFitResult:
    """Fit text into box, wrapping and optionally scaling font.

    Always returns `BoxFitResult`. Check `.overflow` when text cannot fit
    (word too wide to wrap, or height exceeded with no autoscale room).

    Autoscale walks `size -= autoscale` until text fits, a word still won't
    wrap, or `size <= autoscale`. Iterative - was recursive before and could
    hit Python's recursion limit for `size=12, autoscale=0.1`.
    """
    if text is None: text = ""
    text = text.replace(link_char, "¶")
    current_size = size
    overflow = False
    while True:
      input_lines = text.split(enter_in)
      space_width = self.text_width(" ", family, mode, current_size)
      output: list[str] = []
      line_count = 0
      word_overflow = False
      for phrase in input_lines:
        phrase = phrase.strip()
        phrase_width = self.text_width(phrase, family, mode, current_size)
        if phrase_width > width:
          words = phrase.split(" ")
          word_widths = [self.text_width(w, family, mode, current_size) for w in words]
          if any(w > width for w in word_widths):
            word_overflow = True
            output.append(phrase)
            line_count += 1
            continue
          current_line = ""
          current_width = 0
          for i, word in enumerate(words):
            word_w = word_widths[i]
            if current_width + word_w > width and current_line:
              output.append(current_line.strip())
              line_count += 1
              current_line = word + " "
              current_width = word_w + space_width
            else:
              current_line += word + " "
              current_width += word_w + space_width
          if current_line.strip():
            output.append(current_line.strip())
            line_count += 1
        else:
          output.append(phrase)
          line_count += 1
      result_height = self.lines_height(line_count, family, mode, current_size)
      height_overflow = height > 0 and result_height > height
      can_shrink = bool(autoscale) and current_size > autoscale
      if (word_overflow or height_overflow) and can_shrink:
        current_size -= autoscale
        continue
      overflow = word_overflow or height_overflow
      result_text = enter_out.join(output)
      return BoxFitResult(result_text, current_size, result_height, line_count, overflow=overflow)

  def box_fit_array(
    self,
    texts: list[list[str]]|list[str],
    widths: list[float],  # pt per column
    heights: list[float]|float|None = None,
    family: str = "Helvetica",
    mode: str = "Regular",
    size: float = 12,
    autoscale: float|None = None,
  ) -> dict:
    """Fit array of texts into columns. Returns dict with text, font_size, height, lines arrays."""
    if not texts:
      return {"text": [], "font_size": [], "height": [], "lines": []}
    is_1d = isinstance(texts[0], str)
    if is_1d: texts = [texts]
    if heights is None: heights_list = [0] * len(texts)
    elif isinstance(heights, (int, float)): heights_list = [heights] * len(texts)
    else: heights_list = heights
    results = []
    for i, row in enumerate(texts):
      row_results = []
      for j, text in enumerate(row):
        h = heights_list[i] if i < len(heights_list) else 0
        w = widths[j] if j < len(widths) else widths[-1]
        fit = self.box_fit(text, w, h, family, mode, size, autoscale)
        row_results.append(fit)
      results.append(row_results)
    def extract(prop:str):
      return [[getattr(r, prop) if r else None for r in row] for row in results]
    out = {
      "text": extract("text"),
      "font_size": extract("font_size"),
      "height": extract("height"),
      "lines": extract("lines"),
    }
    if is_1d: out = {k: v[0] for k, v in out.items()}
    return out
