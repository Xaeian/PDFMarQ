# pdfmarq/legal/measure.py

"""
Off-page renders of a parsed document, giving heights the real render reproduces.

A probe draws with the same engine, style and fonts as the real document, from the same `y`,
in a frame of the same width, so what it measures is what gets drawn.
The parallel layout decides its page breaks from it.
Columns the engine balances itself.
"""
from markdown_it.token import Token
from ..core import PDF
from ..md import MarkdownRenderer, MarkdownStyle

#-------------------------------------------------------------------------------------------- Probe

class Probe:
  """Measures parts of one parsed document, drawn off the page in the fonts of `pdf`."""
  def __init__(self, pdf:PDF, style:MarkdownStyle, tokens:list[Token], base_dir:str|None):
    self.style = style
    self.tokens = tokens # the whole document, so links to its headings resolve as they will
    self.base_dir = base_dir
    self.font_dir = str(pdf.fonts.font_dir)
    self._tall: dict[float, MarkdownRenderer] = {}

  def height(self, part:list[Token], width:float, y:float=0) -> float:
    """
    Height (mm) `part` takes in a frame `width` mm wide, drawn from `y`.
    Drawn from the same `y` as for real, a heading or a formula spaces itself the same way.
    """
    renderer = self._tall.get(width)
    if renderer is None:
      renderer = self._tall[width] = self._renderer(width)
    renderer.pdf.cursor(0, y)
    renderer.render_tokens(part)
    return renderer.pdf.y - y

  def _renderer(self, width:float, height:float|None=None) -> MarkdownRenderer:
    """The engine off the page, `width` mm wide, knowing the headings of the whole document."""
    renderer = MarkdownRenderer.off_page(width, self.style, self.base_dir, self.font_dir, height)
    renderer.index(self.tokens)
    return renderer
