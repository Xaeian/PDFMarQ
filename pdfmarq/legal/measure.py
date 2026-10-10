# pdfmarq/legal/measure.py

"""
Off-page renders of a parsed document, giving heights the real render reproduces.

A probe draws with the same engine, style and fonts as the real document, from the same `y`,
in a frame of the same width, so what it measures is what gets drawn.
Column balancing and the parallel layout both decide their page breaks from it.
"""
import io
from dataclasses import dataclass
from markdown_it.token import Token
from ..core import PDF
from ..layout import Columns
from ..md import MarkdownRenderer, MarkdownStyle

_SIDE_MM = 10 # margin of an off-page sheet; heights do not depend on it
_TALL_MM = 5000 # an off-page sheet taller than any part it measures

@dataclass
class Region:
  """Text flowing in columns: `part` in `count` of them across `width` mm, `gap` mm apart."""
  part: list[Token]
  width: float
  count: int
  gap: float

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
      renderer = self._tall[width] = self._renderer(width, _TALL_MM)
    renderer.pdf.cursor(0, y)
    renderer.render_tokens(part)
    return renderer.pdf.y - y

  def fits(self, region:Region, height:float) -> bool:
    """
    Whether `region` stays within its columns `height` mm tall.
    The gap after its last block counts too, as it does for what follows the columns.
    """
    pages, end, _ = self.flow(region, height)
    return pages == 1 and end <= height

  def flow(
    self, region:Region, page:float,
    start:float = 0,
    height:float|list|None = None,
  ) -> tuple[int, float, float]:
    """
    How `region` flows on pages `page` mm tall, from `start` on the first,
    its columns capped by `height` as `pdf.columns()` takes it.

    Returns the pages it takes, where its last page ends (mm), the gap after its last block
    included, and how much its last page holds, as one column of it would (mm).
    """
    renderer = self._renderer(region.width, page)
    pdf = renderer.pdf
    pdf.cursor(0, start)
    pdf.columns(region.count, gap=region.gap, height=height)
    renderer.render_tokens(region.part)
    # the columns filled before this one, then what this one holds
    filled = pdf.column_index * pdf.content_height + pdf.y
    pdf.columns(1)
    return pdf.page_num, pdf.y, filled

  def _renderer(self, width:float, height:float) -> MarkdownRenderer:
    """Engine on a fresh off-page sheet whose content area is `width` × `height` mm."""
    pdf = PDF(io.BytesIO(), width=width + 2 * _SIDE_MM, height=height,
      margin=(0, _SIDE_MM), font_dir=self.font_dir)
    renderer = MarkdownRenderer(pdf, self.style, self.base_dir)
    renderer.index(self.tokens)
    return renderer

#---------------------------------------------------------------------------------------- Balancing

def balanced_height(probe:Probe, region:Region, limit:float, step:float) -> float|None:
  """
  Column height (mm) sharing `region` evenly among its columns, `None` when it misses `limit`.

  Starts at an even share of its one-column height and grows by `step`, capped at `limit`.
  The loop ends at the latest on `limit` itself, which the first try already found fits.
  """
  if limit < step or not probe.fits(region, limit): return None
  column = Columns(region.count, region.gap, True, 0).column_width(region.width)
  height = min(max(probe.height(region.part, column) / region.count, step), limit)
  while not probe.fits(region, height):
    height = min(height + step, limit)
  return height

def balanced_pages(
  probe:Probe, region:Region,
  start:float, page:float, limit:float, step:float,
) -> list|None:
  """
  Column heights page by page for `region` flowing from `start` over pages `page` mm tall,
  its last page balanced and ending within `limit`; `None` when that page cannot,
  or when `region` takes one page only.

  As `balanced_height` does for one page, the last page's height starts at an even share
  of what it holds and grows by `step`, capped at `limit`, which the first try found fits.
  """
  pages, _, filled = probe.flow(region, page, start)
  if pages < 2: return None
  caps = [None] * (pages - 1)
  def fits(height:float) -> bool:
    done, end, _ = probe.flow(region, page, start, caps + [height])
    return done == pages and end <= height
  if not fits(limit): return None
  height = min(max(filled / region.count, step), limit)
  while not fits(height):
    height = min(height + step, limit)
  return caps + [height]
