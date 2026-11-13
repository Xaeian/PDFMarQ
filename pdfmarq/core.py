# pdfmarq/core.py

"""Core PDF class - main facade for document generation."""
import random, warnings
from contextlib import contextmanager
from dataclasses import replace
from importlib.util import find_spec
from typing import Callable
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib.colors import Color

from .constants import Defaults, Align
from .utils import to_mm, parse_margin, parse_color
from .fonts import FontManager, fit_glyphs
from .styles import Style, TableStyle
from .layout import Cursor, PageGeometry, Columns, Frame
from .text import TextMetrics, centred_baseline
from .tables import TableBuilder, TableData
from .structure import Metadata, BookmarkManager, LinkManager
from . import graphics as gfx
from .warn import caller_level, warn_missing

_AT_TOP_MM = 0.5 # a cursor this near the top of a frame stands at its top

#----------------------------------------------------------------------------------- NumberedCanvas

class NumberedCanvas(canvas.Canvas):
  """
  Canvas subclass that buffers pages instead of emitting immediately.

  This enables deferred rendering of content that depends on the total page count
  (e.g. footer "Page 1/5").
  Pages are accumulated in `_saved_pages` during normal `showPage()` calls.
  On `save()` we know the total, then iterate through buffered states
  and let registered final-page callbacks draw their content before each real `showPage()`.

  Also defers named destinations.
  Real `showPage()` never runs during buffered rendering,
  so the underlying `_doc.pageCounter` never increments,
  and a destination registered now would resolve to "Page0" and jump to page 1.
  They are replayed at save time, when each page's counter is correctly advanced.
  Both the page-fit and the position-anchored form go through the same queue.
  """
  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._saved_pages: list[dict] = []
    # Set by PDF.save() before iterating - list of (pdf, callback) pairs.
    # Each callback receives (pdf, page_num, total_pages).
    self._pdf_ref = None
    self._final_page_callbacks: list[Callable] = []
    # (page, canvas method name, key, kwargs) - replayed in `save()`.
    self._deferred_bookmarks: list[tuple[int, str, str, dict]] = []
    self._replaying = False

  def showPage(self):
    """Buffer current page state instead of emitting."""
    self._saved_pages.append(dict(self.__dict__))
    self._startPage()

  def bookmarkPage(self, key, **kwargs):
    """Whole-page destination, registered at save time."""
    return self._defer_bookmark("bookmarkPage", key, kwargs)

  def bookmarkHorizontalAbsolute(self, key, top, **kwargs):
    """Destination at a y position on the page, registered at save time."""
    return self._defer_bookmark(
      "bookmarkHorizontalAbsolute", key, {"top": top, **kwargs})

  def _defer_bookmark(self, method:str, key:str, kwargs:dict):
    """Queue a named destination for the save-time replay of this page."""
    if self._replaying: return getattr(super(), method)(key, **kwargs)
    self._deferred_bookmarks.append((self._pageNumber, method, key, kwargs))
    return None

  def save(self):
    """Replay buffered pages, running final-page callbacks with known total."""
    # Buffer any pending content from the last page
    # (caller may not have called `showPage` on the final page - matches `Canvas.save()` behavior).
    if self._code:
      self.showPage()
    total = len(self._saved_pages)
    bookmarks_by_page: dict[int, list[tuple[str, str, dict]]] = {}
    for page_num, method, key, kwargs in self._deferred_bookmarks:
      bookmarks_by_page.setdefault(page_num, []).append((method, key, kwargs))
    # Links are named by a running count: one a callback draws on a page now takes a number
    # past every page buffered, not the count restored with its page, which a later page took
    annotations = self._annotationCount
    self._replaying = True
    try:
      for state in self._saved_pages:
        self.__dict__.update(state)
        # The saved state carries the flag as it was during buffering,
        # so restoring a page turns it back off.
        # Re-assert it: a destination that reaches `bookmarkPage` again from inside reportlab
        # has to register now, not queue itself for a replay that already runs.
        self._replaying = True
        self._annotationCount = annotations
        page_num = self._pageNumber
        for cb in self._final_page_callbacks:
          cb(self._pdf_ref, page_num, total)
        annotations = self._annotationCount
        for method, key, kwargs in bookmarks_by_page.get(page_num, []):
          getattr(super(), method)(key, **kwargs)
        super().showPage()
    finally:
      self._replaying = False
    super().save()

#---------------------------------------------------------------------------------------------- PDF

class PDF:
  """
  Main PDF generator with fluent API.

  Example:
    >>> with PDF("output.pdf") as pdf:
    ...   pdf.font("Barlow", 12).text("Hello World")
    ...   pdf.enter().text("New line")
    ...   pdf.save()
  """
  def __init__(
    self,
    path:str,
    width:float = Defaults.PAGE_WIDTH,
    height:float = Defaults.PAGE_HEIGHT,
    margin:float|tuple = Defaults.MARGIN,
    unit:str = Defaults.UNIT,
    font_dir:str = "./fonts",
    debug:bool = False,
    gutter:float = 0,
    pictures:bool = True,
    two_sided:bool = False,
  ):
    """
    `gutter` is a binding margin, added to the left one: PDF has no native gutter.
    `two_sided` prints on both sides of the sheet: an even page mirrors the margins,
    so the left one and the gutter stay at the bound edge, its right.
    `pictures=False` leaves the room of each image and SVG empty, for a page drawn only to measure.
    """
    self._path = path
    self._pictures = pictures
    self.debug = debug
    self.unit = unit
    # Page setup
    top, right, bot, left = parse_margin(margin)
    self._gutter = to_mm(gutter, unit) # `margin()` adds it again whenever it moves the margins
    left += gutter
    self._page = PageGeometry(
      width=to_mm(width, unit),
      height=to_mm(height, unit),
      margin_top=to_mm(top, unit),
      margin_right=to_mm(right, unit),
      margin_bot=to_mm(bot, unit),
      margin_left=to_mm(left, unit),
    )
    # `_page` is the frame content is drawn into: the whole page, or the open column.
    self._page_full = self._page
    self._two_sided = two_sided
    self._sides = (self._page.margin_left, self._page.margin_right) # of an odd page
    self._columns: Columns|None = None
    self._frame: Frame|None = None # the box `frame()` lays content out in, while it runs
    self._flow_top = 0.0 # mm where the text of this page began, under what `on_new_page` set
    self._headroom = 0.0 # mm a new page leaves empty above its text, see `headroom`
    self._watchers: list[tuple] = [] # `(enter, leave)` pairs `frames()` holds while its block runs
    # Canvas - `NumberedCanvas` buffers pages
    # so deferred footer (with total page count) can be drawn at `save()` time.
    self._canvas = NumberedCanvas(path)
    self._canvas._pdf_ref = self
    self._canvas.setPageSize((self._page.width * mm, self._page.height * mm))
    # Components
    self._fonts = FontManager(font_dir)
    self._metrics = TextMetrics(self._fonts)
    self._cursor = Cursor()
    self._bookmarks = BookmarkManager()
    self._links = LinkManager()
    self._metadata = Metadata()
    # Current state
    self._style = Style().with_defaults()
    self._page_num = 1
    self._total_pages: int|None = None # set in save() for footer callbacks
    self._saved = False # guards the save-once canvas, see save()
    self._page_callbacks: list[Callable] = [] # before showPage (header/footer)
    self._new_page_callbacks: list[Callable] = [] # after showPage + cursor reset
    self._page_top_callbacks: list[Callable] = [] # after those, under where the text begins
    self._opening = False # a new page runs its callbacks, so it cannot turn until they are done

  #-------------------------------------------------------------------------------- Context manager

  def __enter__(self) -> "PDF":
    return self

  def __exit__(self, exc_type, exc_val, exc_tb):
    if exc_type is None:
      self.save()

  #------------------------------------------------------------------------------------- Properties

  @property
  def x(self) -> float:
    """Cursor X position in mm from page left edge."""
    return self._cursor.x

  @property
  def y(self) -> float:
    """Cursor Y position in mm from page top edge (Y grows down)."""
    return self._cursor.y

  @property
  def at_top(self) -> bool:
    """
    Whether the cursor stands at the top of its frame, the page or the open column,
    where a block skips the gap above it.
    Whether the page is still empty is `page_break()`'s question, and `keep()` asks
    whether moving on gives more room.
    """
    return self._cursor.y <= _AT_TOP_MM

  @property
  def page_top(self) -> float:
    """
    Where the text of this page begins, mm under the top margin:
    under what `on_new_page` set there, `headroom` included.
    A page drawn only to measure takes it over, so it starts as this one did.
    """
    return self._flow_top

  @page_top.setter
  def page_top(self, value:float):
    self._flow_top = to_mm(value, self.unit)

  @property
  def fresh_height(self) -> float:
    """
    Height (mm) of the frame a new page opens, under its `headroom`:
    the most room moving on can give, where a short column gives less.
    In `frame()` it is the frame's, which holds one page.
    """
    if self._frame: return self._page_full.content_height
    return self._page_full.content_height - self._headroom

  @property
  def page_width(self) -> float:
    """Current page width in mm."""
    return self._page.width

  @property
  def page_height(self) -> float:
    """Current page height in mm."""
    return self._page.height

  @property
  def content_width(self) -> float:
    """Drawable width in mm (page width minus left+right margins)."""
    return self._page.content_width

  @property
  def content_height(self) -> float:
    """Drawable height in mm (page height minus top+bottom margins)."""
    return self._page.content_height

  @property
  def margin_left(self) -> float:
    """Left margin of the frame in mm: the page's, or the open column's."""
    return self._page.margin_left

  @property
  def margin_right(self) -> float:
    """Right margin of the frame in mm: the page's, or the open column's."""
    return self._page.margin_right

  @property
  def margin_top(self) -> float:
    """Top margin of the frame in mm: the page's, or the open column's."""
    return self._page.margin_top

  @property
  def margin_bot(self) -> float:
    """Bottom margin of the frame in mm: the page's, or the open column's."""
    return self._page.margin_bot

  @property
  def page_num(self) -> int:
    """1-based index of the current page (incremented by `new_page`)."""
    return self._page_num

  @property
  def headroom(self) -> float:
    """
    Room a new page leaves empty above its text, for a running header drawn there.
    A page drawn only to measure takes it over, so its pages break where these do.
    """
    return self._headroom

  @headroom.setter
  def headroom(self, value:float):
    self._headroom = to_mm(value, self.unit)

  @property
  def in_columns(self) -> bool:
    """Whether a column region or an inset is open, which `columns(1)` and `inset()` close."""
    return self._columns is not None

  @property
  def column_index(self) -> int:
    """Column of the open region the cursor is in, counted from 0, or 0 without one."""
    return self._columns.index if self._columns else 0

  @property
  def column_ends(self) -> list[float]:
    """
    How far down each column of the open region reached on this page, mm from the region's top,
    the one the cursor is in counted to the cursor: where the text of each stands so far.
    Empty without a region.
    """
    region = self._columns
    if not region: return []
    ends = region.ends + [0] * (region.index + 1 - len(region.ends))
    ends[region.index] = max(ends[region.index], self._cursor.y)
    return ends

  @property
  def c(self):
    """
    Direct reportlab `Canvas` access for advanced operations not exposed by the fluent API.
    Use sparingly - bypasses cursor / page tracking.
    """
    return self._canvas

  @property
  def fonts(self) -> FontManager:
    """Font registry: `pdf.fonts.register(family)` loads a TTF family from `font_dir`."""
    return self._fonts

  @property
  def metrics(self) -> TextMetrics:
    """Text measurement in the fonts of this document, kerned as `kerning()` sets it."""
    return self._metrics

  @property
  def output_path(self) -> str:
    """
    Destination file path. Symmetric with `DOCX.output_path`.
    `pdf.path()` is reserved for the polygon-draw method, so use this for filename inspection.
    """
    return self._path

  #------------------------------------------------------------------------------------------- Page

  def page(self, width:float|None=None, height:float|None=None) -> "PDF":
    """Set page size."""
    if self._columns or self._frame:
      raise ValueError("page() cannot resize the page inside columns or a frame")
    if width:
      self._page_full.width = to_mm(width, self.unit)
    if height:
      self._page_full.height = to_mm(height, self.unit)
    self._canvas.setPageSize((self._page_full.width * mm, self._page_full.height * mm))
    return self

  def new_page(self) -> "PDF":
    """
    Add new page and reset cursor.

    An open column region carries on from its first column at the top of the new page,
    below whatever the `on_new_page` callbacks placed there, capped as `columns()` asked.
    A frame holds one page: inside `frame()` the content stays and runs on,
    which the frame warns of.
    """
    if self._frame:
      self._frame.overflow = True
      return self
    if self._opening: return self # what its callbacks set stays on the page they open
    self._leaving()
    self._finalize_page()
    self._canvas.showPage()
    self._page_num += 1
    full = self._page_full
    full.margin_left, full.margin_right = self.sides(self._page_num)
    self._page = full
    self._cursor.set(0, self._headroom)
    self._apply_font() # re-apply font after page break
    self._opening = True
    try:
      for cb in self._new_page_callbacks:
        cb(self, self._page_num)
      self._flow_top = self._cursor.y
      for cb in self._page_top_callbacks:
        cb(self, self._page_num)
    finally:
      self._opening = False
    region = self._columns
    if region:
      region.top = self._cursor.y
      region.height = region.later.pop(0) if region.later else None
      region.bottom, region.ends = 0, []
      self._enter_column(0, 0)
    self._entered()
    return self

  def margin(self, lr:float, top:float|None=None, bot:float|None=None) -> "PDF":
    """
    Set page margins. `lr` sets both left and right symmetrically.

    For asymmetric left/right margins, pass a 4-tuple to the `PDF` constructor:
    `PDF(..., margin=(top, right, bot, left))`.
    """
    if self._columns or self._frame:
      raise ValueError("margin() cannot move margins inside columns or a frame")
    top = top if top is not None else lr
    bot = bot if bot is not None else top
    page = self._page_full
    page.margin_left = page.margin_right = to_mm(lr, self.unit)
    page.margin_left += self._gutter
    page.margin_top = to_mm(top, self.unit)
    page.margin_bot = to_mm(bot, self.unit)
    self._sides = (page.margin_left, page.margin_right)
    page.margin_left, page.margin_right = self.sides(self._page_num)
    return self

  def sides(self, page_num:int) -> tuple[float, float]:
    """
    `(left, right)` margins of page `page_num` in mm, the gutter in them:
    an even page of a two-sided print mirrors those of an odd one.
    """
    left, right = self._sides
    return (right, left) if self._two_sided and page_num % 2 == 0 else (left, right)

  #---------------------------------------------------------------------------------------- Columns

  def columns(
    self,
    count:int,
    gap:float = 8,
    flow:bool = True,
    height:float|list|tuple|None = None,
  ) -> "PDF":
    """
    Lay out what follows in `count` columns, starting at the current height.

    Each column is a narrower page: content width, margins and `y` all refer to it.
    Flowing columns fill left to right as `next_frame()` moves on.
    With `flow=False` the caller places content per column and breaks pages itself.
    `height` caps the columns on this page, which is how a caller balances them.
    A list or a tuple caps them page by page from this one, `None` leaving a page uncapped:
    `[None, 120]` balances the second page of the region only.
    A page given as a list or tuple of its own caps its columns one by one:
    `[(150, None)]` keeps the first clear of a footnote below it.
    `columns(1)` closes the region, below its lowest column.
    A `height` that does not fit `count` fails before the open region closes.
    """
    if count < 1: raise ValueError(f"column count must be at least 1, got {count}")
    def cap_mm(cap:float|None) -> float|None:
      return None if cap is None else to_mm(cap, self.unit)
    caps = []
    for cap in height if isinstance(height, (list, tuple)) else [height]:
      if isinstance(cap, (list, tuple)):
        if len(cap) != count: raise ValueError(f"{len(cap)} column caps for {count} columns")
        caps.append(tuple(cap_mm(c) for c in cap))
      else: caps.append(cap_mm(cap))
    caps = caps or [None]
    self._end_columns()
    if count == 1: return self
    self._open(Columns(count, to_mm(gap, self.unit), flow, self._cursor.y, caps[0],
      later=caps[1:]))
    return self

  def inset(self, left:float=0, right:float=0) -> "PDF":
    """
    Narrow the content area by `left` and `right` from the current height, as one flowing frame.

    Text set beside a logo or a photo wraps this way.
    Like a column, the frame carries on over a page break.
    `inset()` with no insets restores the full width, below what was drawn.
    """
    self._end_columns()
    if not (left or right): return self
    self._open(Columns(1, 0, True, self._cursor.y,
      left=to_mm(left, self.unit), right=to_mm(right, self.unit)))
    return self

  def column(self, index:int) -> "PDF":
    """Move to column `index` of the open region, keeping the current height."""
    region = self._columns
    if not region: raise ValueError("no column region is open, call columns() first")
    if not 0 <= index < region.count:
      raise ValueError(f"column {index} is outside 0..{region.count - 1}")
    self._reach()
    self._enter_column(index, self._cursor.y)
    return self

  def next_frame(self) -> "PDF":
    """
    Continue in the next frame: the next column, or a new page after the last one.

    Without a column region this is `new_page()`.
    Parallel columns (`flow=False`) belong to a caller that breaks pages itself,
    so there it does nothing, as it does while a new page runs its callbacks.
    Inside `frame()` there is no next page: the content stays and runs past the bottom.
    """
    region = self._columns
    if self._opening or (region and not region.flow): return self
    if region and region.index + 1 < region.count:
      self._reach()
      self._leaving()
      self._enter_column(region.index + 1, 0)
      self._entered()
      return self
    return self.new_page()

  @contextmanager
  def frames(self, enter:Callable|None=None, leave:Callable|None=None):
    """
    While the block runs, call `leave(pdf)` as the cursor is about to leave a frame for the next,
    still on it, and `enter(pdf)` once it stands at the top of the next one.
    A frame is a column or a page, so a quote draws its bar on each part this way,
    and columns place the blocks that wait for the top of one.
    Callers inside callers nest: their `enter` runs after the outer one, their `leave` before it.
    """
    watcher = (enter, leave)
    self._watchers.append(watcher)
    try:
      yield self
    finally:
      self._watchers.remove(watcher)

  def _leaving(self):
    """Tell the blocks `frames()` watches for that this frame ends, innermost first."""
    for _, leave in reversed(list(self._watchers)):
      if leave: leave(self)

  def _entered(self):
    """Tell the blocks `frames()` watches for that a new frame begins, outermost first."""
    for enter, _ in list(self._watchers):
      if enter: enter(self)

  def keep(self, height:float) -> "PDF":
    """
    Make room for `height` here: move on frame by frame until the rest of one holds it.
    Something taller than any frame stays at the top of one,
    since moving on cannot give it more room and would only leave frames blank.
    A short column moves it on: one opened low on the page, or one its page caps.
    """
    height = to_mm(height, self.unit)
    while height > self.content_height - self._cursor.y and not self._fresh():
      here = (self._page_num, self.column_index, self._cursor.y)
      self.next_frame()
      if (self._page_num, self.column_index, self._cursor.y) == here: break # nowhere to move on
    return self

  def page_break(self) -> "PDF":
    """
    Start a new page, unless nothing is set on this one yet: a break never leaves a page blank.
    A page is empty while the cursor stands where its text began,
    under what `on_new_page` set there and in the first column of columns opened there.
    """
    if not self._blank(): self.new_page()
    return self

  def _blank(self) -> bool:
    """Whether nothing is set on this page yet: the cursor stands where its text began."""
    region = self._columns
    if region and region.index: return False
    top = (region.top if region else 0) + self._cursor.y
    return top <= self._flow_top + _AT_TOP_MM

  def _fresh(self) -> bool:
    """
    Whether the cursor stands at the top of a frame as tall as any after it:
    moving on gains nothing there.
    Columns opened lower on the page, or capped on it, are shorter than those of the next page.
    """
    region = self._columns
    if not region: return self._cursor.y <= self._flow_top + _AT_TOP_MM
    return (self._cursor.y <= _AT_TOP_MM and region.top <= self._flow_top + _AT_TOP_MM
      and region.height is None)

  def _open(self, region:Columns):
    """Open `region` at its first column. One whose columns get no width is refused."""
    width = region.column_width(self._page_full.content_width)
    if width <= 0:
      raise ValueError(f"columns would be {width:.1f}mm wide: fewer columns, a smaller gap"
        " or smaller insets")
    self._columns = region
    self._enter_column(0, 0)

  def _enter_column(self, index:int, y:float):
    """Make column `index` the frame content is drawn into, cursor at `y` inside it."""
    region = self._columns
    full = self._page_full
    width = region.column_width(full.content_width)
    left = full.margin_left + region.left + index * (width + region.gap)
    height = full.content_height - region.top # down to the page's bottom margin
    cap = region.height[index] if isinstance(region.height, tuple) else region.height
    if cap is not None: height = min(height, cap)
    self._page = full.box(left, full.margin_top + region.top, width, height)
    region.index = index
    self._cursor.set(0, y)

  def _reach(self):
    """Record how far down the current column went, text drawn without `enter()` included."""
    cursor, region = self._cursor, self._columns
    depth = cursor.y + cursor.last_height
    region.bottom = max(region.bottom, depth)
    region.ends += [0] * (region.index + 1 - len(region.ends))
    region.ends[region.index] = max(region.ends[region.index], depth)

  def _end_columns(self):
    """Close the column region: full width again, cursor below the lowest column."""
    region = self._columns
    if not region: return
    self._reach()
    self._columns = None
    self._page = self._page_full
    self._cursor.set(0, region.top + region.bottom)

  #------------------------------------------------------------------------------------------ Frame

  @contextmanager
  def frame(self, x:float, y:float, width:float, height:float):
    """
    Lay out what the block draws in a box `width` by `height`,
    its top left `x`, `y` from the content's top left, as the cursor counts.

    While the block runs the box is the page: content width, margins, `y` and centring refer to it
    and `columns()` divides it, so `text`, `render_rich` and markdown fill it as they fill a page.
    A slide places its title, body and pictures this way.
    The cursor comes back to where it was.

    A frame holds one page: content asking for more room than it has, a page break among it,
    runs on past its bottom, which warns when the block ends.
    """
    if self._columns or self._frame:
      raise ValueError("frame() opens on the page, outside columns and other frames")
    x, y, width, height = (to_mm(value, self.unit) for value in (x, y, width, height))
    if width <= 0 or height <= 0:
      raise ValueError(f"a frame needs a size, got {width:.1f}x{height:.1f}mm")
    page = self._page_full
    self._frame = Frame(page, self._cursor)
    box = page.box(page.margin_left + x, page.margin_top + y, width, height)
    self._page_full = self._page = box
    self._cursor = Cursor()
    flow_top, self._flow_top = self._flow_top, 0
    try:
      yield self
    finally:
      self._end_columns()
      frame, self._frame = self._frame, None
      self._page_full = self._page = frame.page
      self._cursor = frame.cursor
      self._flow_top = flow_top
    if frame.overflow:
      warnings.warn(f"content asked for more room than its {width:.1f}x{height:.1f}mm frame holds",
        RuntimeWarning, stacklevel=caller_level())

  #------------------------------------------------------------------------------------------ Fonts

  def add_font(self, family:str, mode:str="Regular") -> "PDF":
    """Register font for use."""
    self._fonts.register(family, mode)
    return self

  def font(self, family:str|None=None, size:float|None=None, mode:str|None=None) -> "PDF":
    """Set current font."""
    if family:
      self._style.font_family = family
      self._style.font_mode = mode or "Regular"
    elif mode:
      self._style.font_mode = mode
    if size:
      self._style.font_size = size
    self._apply_font()
    return self

  def kerning(self, on:bool=True) -> "PDF":
    """
    Kern the letter pairs of TrueType text drawn from here on, as `AV` and `Ty` want,
    measuring it the same way, so lines wrap where they are drawn.
    It needs uharfbuzz, the `[kerning]` extra, and warns once without it.
    Ligatures and alternate glyphs stay off: they copy out of the PDF as other letters.
    """
    if on and find_spec("uharfbuzz") is None:
      warn_missing("uharfbuzz", "uharfbuzz", "kerning")
    self._metrics.kerning = on
    return self

  def _apply_font(self):
    """Apply current font to canvas."""
    self._canvas.setFont(self._font_name(), self._style.font_size)

  def _font_name(self) -> str:
    """reportlab name of the current face, or of its stand-in for a missing file."""
    return self._metrics.font_name(self._style.font_family, self._style.font_mode)

  #----------------------------------------------------------------------------------------- Cursor

  def cursor(self, x:float|None=None, y:float|None=None, align:str|None=None) -> "PDF":
    """Set cursor position and/or alignment."""
    if x is not None:
      x = to_mm(x, self.unit)
    if y is not None:
      y = to_mm(y, self.unit)
    self._cursor.set(x, y, align)
    return self

  def move(self, dx:float=0, dy:float=0) -> "PDF":
    """Relative cursor movement."""
    self._cursor.move(to_mm(dx, self.unit), to_mm(dy, self.unit))
    return self

  def enter(self, height:float|None=None) -> "PDF":
    """New line - reset x, advance y."""
    h = to_mm(height, self.unit) if height is not None else None
    self._cursor.enter(h)
    return self

  #----------------------------------------------------------------------------------------- Colors

  def color(self, r:float, g:float, b:float, a:float=1) -> "PDF":
    """Set fill color."""
    self._canvas.setFillColor(Color(r, g, b, a))
    self._style.color = (r, g, b, a)
    return self

  def color_hex(self, hex_color:str, a:float=1) -> "PDF":
    """Set fill color from hex string."""
    r, g, b = parse_color(hex_color)
    return self.color(r, g, b, a)

  def color_grey(self, light:float=0, a:float=1) -> "PDF":
    """Set greyscale fill color."""
    return self.color(light, light, light, a)

  def color_black(self) -> "PDF":
    """Reset to black fill."""
    return self.color(0, 0, 0, 1)

  def color_rand(self, offset:float=0.2, a:float=0.5) -> "PDF":
    """Set random fill color (for debug)."""
    r = random.uniform(offset, 1 - offset)
    g = random.uniform(offset, 1 - offset)
    b = random.uniform(offset, 1 - offset)
    return self.color(r, g, b, a)

  def stroke_color(self, r:float, g:float, b:float, a:float=1) -> "PDF":
    """Set stroke color."""
    self._canvas.setStrokeColor(Color(r, g, b, a))
    return self

  #------------------------------------------------------------------------------------------- Text

  def text(
    self,
    content:str,
    width:float = 0,
    height:float = 0,
    align:str|None = None,
    padding:float = 0,
  ) -> "PDF":
    """Draw text at cursor position."""
    if content is None:
      content = ""
    content = fit_glyphs(content, self._font_name())
    width_mm = to_mm(width, self.unit) if width else 0
    height_mm = to_mm(height, self.unit) if height else 0
    padding_mm = to_mm(padding, self.unit)
    align = align or Align.LEFT
    family = self._style.font_family
    mode = self._style.font_mode
    size = self._style.font_size
    width_pt = width_mm * mm if width_mm else 0
    height_pt = height_mm * mm if height_mm else 0
    padding_pt = padding_mm * mm
    # measured first, since the position depends on the width
    if width_pt:
      fit = self._metrics.box_fit(
        content, width_pt - 2 * padding_pt, height_pt,
        family, mode, size, autoscale=0.1 if height_pt else None,
      )
      text = fit.text
      font_size = fit.font_size
      text_height = fit.height
      lines = fit.lines
    else:
      text = content
      font_size = size
      text_height = self._metrics.lines_height(1, size)
      width_pt = self._metrics.text_width(content, family, mode, size)
      width_mm = width_pt / mm
      lines = 1
    if not height_pt:
      height_pt = text_height
      height_mm = height_pt / mm
    x_mm, y_mm = self._page.cursor_to_canvas(self._cursor, width_mm)
    x_pt, y_pt = x_mm * mm, y_mm * mm
    # Debug rectangle
    if self.debug:
      self.color_rand()
      self._canvas.rect(x_pt, y_pt - height_pt, width_pt, height_pt, stroke=0, fill=1)
      self.color_black()
    # Each line is `lines_height(1)` tall, its letters in the middle as `render_rich` sets them,
    # and the lines together sit in the middle of the box.
    line_pt = self._metrics.lines_height(1, font_size)
    above, below = self._metrics.letter_span(family, mode, font_size)
    margin_v = max(0, (height_pt - line_pt * lines) / 2)
    baseline_pt = y_pt - margin_v - centred_baseline(line_pt, above, below)
    text_obj = self._canvas.beginText(x_pt, baseline_pt)
    text_obj.setFont(self._font_name(), font_size, leading=line_pt)
    for line in text.splitlines():
      line, line_width = self._metrics.shaped(line, family, mode, font_size)
      if align == Align.CENTER:
        text_obj.setTextOrigin(x_pt + (width_pt - line_width) / 2, text_obj.getY())
      elif align == Align.RIGHT:
        text_obj.setTextOrigin(x_pt - padding_pt + width_pt - line_width, text_obj.getY())
      else:
        text_obj.setTextOrigin(x_pt + padding_pt, text_obj.getY())
      text_obj.textLine(line)
    self._canvas.drawText(text_obj)
    # Update cursor
    self._cursor.advance_x(width_mm)
    self._cursor.record_height(height_mm)
    return self

  #--------------------------------------------------------------------------------- Lines & Shapes

  def line(self, width:float=0, height:float=0, thickness:float=1, dash:tuple|None=None) -> "PDF":
    """Draw line from cursor."""
    x_mm, y_mm = self._page.cursor_to_canvas(self._cursor)
    w_mm = to_mm(width, self.unit)
    h_mm = to_mm(height, self.unit)
    if self._cursor.align == Align.RIGHT:
      x_mm -= w_mm
    elif self._cursor.align == Align.CENTER:
      x_mm -= w_mm / 2
    gfx.draw_line(self._canvas, x_mm * mm, y_mm * mm,
      (x_mm + w_mm) * mm, (y_mm - h_mm) * mm, thickness, dash)
    return self

  def rect(
    self, width:float, height:float,
    thickness:float = 0, dash:tuple|None = None, fill:bool = True,
  ) -> "PDF":
    """Draw rectangle at cursor."""
    x_mm, y_mm = self._page.cursor_to_canvas(self._cursor)
    w_mm = to_mm(width, self.unit)
    h_mm = to_mm(height, self.unit)
    if self._cursor.align == Align.RIGHT:
      x_mm -= w_mm
    elif self._cursor.align == Align.CENTER:
      x_mm -= w_mm / 2
    gfx.draw_rect(self._canvas, x_mm * mm, (y_mm - h_mm) * mm,
                  w_mm * mm, h_mm * mm, thickness, dash, fill)
    return self

  def round_rect(
    self, width:float, height:float, radius:float,
    thickness:float = 0, fill:bool = True, dash:tuple|None = None,
  ) -> "PDF":
    """Rounded rectangle at cursor, `radius` in the current unit and `dash` as in `rect`."""
    x_mm, y_mm = self._page.cursor_to_canvas(self._cursor)
    w_mm = to_mm(width, self.unit)
    h_mm = to_mm(height, self.unit)
    r_mm = to_mm(radius, self.unit)
    if self._cursor.align == Align.RIGHT:
      x_mm -= w_mm
    elif self._cursor.align == Align.CENTER:
      x_mm -= w_mm / 2
    gfx.draw_round_rect(
      self._canvas, x_mm * mm, (y_mm - h_mm) * mm,
      w_mm * mm, h_mm * mm, r_mm * mm, thickness, dash, fill,
    )
    return self

  def circle(self, radius:float, thickness:float=0, fill:bool=True) -> "PDF":
    """Draw circle at cursor (cursor = center)."""
    x_mm, y_mm = self._page.cursor_to_canvas(self._cursor)
    r_mm = to_mm(radius, self.unit)
    gfx.draw_circle(self._canvas, x_mm * mm, y_mm * mm, r_mm * mm, thickness, fill)
    return self

  def path(
    self, points:list[tuple],
    close:bool = False, thickness:float = 1, fill:bool = False,
  ) -> "PDF":
    """Draw path through points (relative to cursor)."""
    x_mm, y_mm = self._page.cursor_to_canvas(self._cursor)
    pts = [(x_mm * mm + to_mm(p[0], self.unit) * mm,
      y_mm * mm - to_mm(p[1], self.unit) * mm) for p in points]
    gfx.draw_path(self._canvas, pts, close, thickness, fill)
    return self

  #----------------------------------------------------------------------------------------- Images

  def image(self, path:str, width:float, height:float) -> "PDF":
    """Draw image at cursor."""
    x_mm, y_mm = self._page.cursor_to_canvas(self._cursor)
    w_mm = to_mm(width, self.unit)
    h_mm = to_mm(height, self.unit)
    if self._cursor.align == Align.RIGHT:
      x_mm -= w_mm
    elif self._cursor.align == Align.CENTER:
      x_mm -= w_mm / 2
    if self._pictures:
      gfx.draw_image(self._canvas, path, x_mm * mm, (y_mm - h_mm) * mm, w_mm * mm, h_mm * mm)
    self._cursor.record_height(h_mm)
    return self

  def svg(self, path:str, width:float, height:float) -> "PDF":
    """Draw SVG at cursor."""
    x_mm, y_mm = self._page.cursor_to_canvas(self._cursor)
    w_mm = to_mm(width, self.unit)
    h_mm = to_mm(height, self.unit)
    if self._cursor.align == Align.RIGHT:
      x_mm -= w_mm
    elif self._cursor.align == Align.CENTER:
      x_mm -= w_mm / 2
    if self._pictures:
      gfx.draw_svg(self._canvas, path, x_mm * mm, (y_mm - h_mm) * mm, w_mm * mm, h_mm * mm)
    self._cursor.record_height(h_mm)
    return self

  #----------------------------------------------------------------------------------------- Tables

  def table(
    self,
    body:list[list[str]],
    header:list[str]|None = None,
    sizes:list[float]|None = None,
    aligns:list[str]|None = None,
    width:float|None = None,
    style:TableStyle|None = None,
  ) -> "PDF":
    """Draw table at cursor."""
    style = style or TableStyle()
    width_mm = to_mm(width, self.unit) if width else self.content_width - self._cursor.x
    ncols = len(header) if header else len(body[0]) if body else 1
    sizes = sizes or [1] * ncols
    aligns = aligns or [Align.LEFT] * ncols
    builder = TableBuilder(self._metrics, style)
    if header:
      builder.header(header)
    builder.rows(body).columns(sizes, aligns).width(width_mm)
    data = builder.build(
      width_mm,
      self._style.font_family, self._style.font_mode, self._style.font_size,
    )
    self._draw_table(data, style)
    return self

  def _draw_table(self, data:TableData, style:TableStyle):
    """Internal table rendering."""
    x_start = self._cursor.x
    y_start = self._cursor.y
    h_pad = style.cell_pad_h
    header_mode = "Bold" if style.header_bold else self._style.font_mode
    # Backgrounds: solid GitHub-light subtle colors (no alpha trickery).
    if data.header:
      if style.header_bg is not None:
        r, g, b = parse_color(style.header_bg)
        self.color(r, g, b, 1)
        self.rect(data.total_width, data.header_height)
      self.enter(data.header_height).enter(style.header_gap)
    for i, h in enumerate(data.body_heights):
      bg = style.row_bg_odd if i % 2 else style.row_bg_even
      if bg is not None:
        r, g, b = parse_color(bg)
        self.color(r, g, b, 1)
        self.rect(data.total_width, h)
      self.enter(h)
    self.color_black()
    br, bg_, bb = parse_color(style.border_color)
    self.stroke_color(br, bg_, bb)
    # Horizontal lines
    self.cursor(x_start, y_start)
    self.line(data.total_width, 0, style.border_size)
    if data.header:
      self.enter(data.header_height)
      self.line(data.total_width, 0, style.border_size_header)
      self.enter(style.header_gap)
    for h in data.body_heights:
      self.line(data.total_width, 0, style.border_size)
      self.enter(h)
    self.line(data.total_width, 0, style.border_size)
    # Vertical lines
    self.cursor(x_start, y_start)
    total_h = (data.header_height + style.header_gap + sum(data.body_heights)
      if data.header else sum(data.body_heights))
    self.line(0, total_h, style.border_size_outer)
    x_col = x_start
    for w in data.column_widths:
      x_col += w
      self.cursor(x_col, y_start)
      self.line(0, total_h, style.border_size_outer)
    self.stroke_color(0, 0, 0)
    # Text sits between the pads, its capitals in the middle and descenders hanging below:
    # `text` centres descenders with the capitals, which lifts a cell of digits off its row
    def drop_mm(mode:str) -> float:
      _, below = self._metrics.letter_span(self._style.font_family, mode, self._style.font_size)
      return (style.cell_pad_top - style.cell_pad_bot + below / mm) / 2
    # Header text
    self.cursor(x_start, y_start)
    if data.header and data.header_fitted:
      old_mode = self._style.font_mode
      old_color = self._style.color
      if style.header_color is not None:
        hr_, hg_, hb_ = parse_color(style.header_color)
        self.color(hr_, hg_, hb_, 1)
      self.font(mode=header_mode)
      header_drop = drop_mm(header_mode)
      self._cursor.move(dy=header_drop)
      for idx, txt in enumerate(data.header_fitted):
        if txt is None:
          txt = data.header[idx]
        align = data.column_aligns[idx] if idx < len(data.column_aligns) else Align.LEFT
        self.text(txt, data.column_widths[idx], data.header_height, align, h_pad)
      self._cursor.move(dy=-header_drop)
      self.font(mode=old_mode)
      if style.header_color is not None:
        self.color(*old_color)
      self.enter().enter(style.header_gap)
    # Body text
    body_drop = drop_mm(self._style.font_mode)
    self._cursor.move(dy=body_drop)
    for i, row in enumerate(data.body_fitted):
      for idx, txt in enumerate(row):
        if txt is None:
          txt = data.body[i][idx]
        align = data.column_aligns[idx] if idx < len(data.column_aligns) else Align.LEFT
        self.text(txt, data.column_widths[idx], data.body_heights[i], align, h_pad)
      self.enter()
    self._cursor.move(dy=-body_drop)
    return self

  #-------------------------------------------------------------------------------------- Structure

  def anchor(self, key:str) -> "PDF":
    """
    Register a named destination at the current cursor position.

    A viewer following a link to `key` scrolls to this point rather than fitting the whole page,
    which is what makes an anchor useful in a long document.
    """
    _, y_mm = self._page.cursor_to_canvas(self._cursor)
    self._canvas.bookmarkHorizontalAbsolute(key, y_mm * mm)
    return self

  def bookmark(self, title:str, level:int=0) -> "PDF":
    """Add an outline entry pointing at the current position."""
    _, y_mm = self._page.cursor_to_canvas(self._cursor)
    self._bookmarks.add(title, self._page_num, y_mm, level)
    return self

  def link(self, url:str, width:float, height:float) -> "PDF":
    """Add URL link over the `width` × `height` box at the cursor."""
    w_mm = to_mm(width, self.unit)
    h_mm = to_mm(height, self.unit)
    x_mm, y_mm = self._page.cursor_to_canvas(self._cursor, w_mm)
    # `LinkManager` takes the box's top-left corner, measured from the page's top-left corner.
    self._links.add_url(url, x_mm, self._page.height - y_mm, w_mm, h_mm, self._page_num)
    return self

  def metadata(
    self, title:str|None = None, author:str|None = None,
    subject:str|None = None, keywords:str|None = None,
    comments:str|None = None, category:str|None = None,
  ) -> "PDF":
    """
    Set document metadata.
    `comments`/`category` accepted for parity with `DOCX.metadata()`,
    but not emitted to the PDF /Info dict.
    """
    if title: self._metadata.title = title
    if author: self._metadata.author = author
    if subject: self._metadata.subject = subject
    if keywords: self._metadata.keywords = keywords
    if comments: self._metadata.comments = comments
    if category: self._metadata.category = category
    return self

  #-------------------------------------------------------------------------------- Headers/Footers

  def on_page(self, callback:Callable) -> "PDF":
    """
    Register callback to run on each page (for headers/footers).

    Callback receives (pdf, page_num) arguments.
    """
    self._page_callbacks.append(callback)
    return self

  def on_new_page(self, callback:Callable) -> "PDF":
    """
    Register callback to run after a new page is started (after cursor reset).
    Use to draw at the top of the page.
    Room for a header there is `headroom`, which pages drawn only to measure know as well.
    A cursor the callback moves on is honoured on the page, but measuring cannot see it.

    Callback receives (pdf, page_num) arguments.
    """
    self._new_page_callbacks.append(callback)
    return self

  def on_page_top(self, callback:Callable) -> "PDF":
    """
    Register callback to set what belongs at the top of one page, as a figure that waited for it.
    It runs after the `on_new_page` callbacks, across the page, before columns open under it.
    The room it takes is that page's own:
    the text still begins where it began, so `keep()` moves on from the shorter frame under it.
    What it sets must fit the page: while a page opens it cannot turn,
    so `keep()` and `next_frame()` leave the cursor where it stands.

    Callback receives (pdf, page_num) arguments.
    """
    self._page_top_callbacks.append(callback)
    return self

  def on_final_page(self, callback:Callable) -> "PDF":
    """
    Register callback that runs at `save()` time once total page count is known.
    Use for footers like "Page 1/5" that need the final page total.

    Callback receives (pdf, page_num, total_pages).
    Canvas is on the correct page;
    cursor state is saved and restored around each call.
    """
    self._canvas._final_page_callbacks.append(
      lambda pdf, page_num, total: self._wrap_final_callback(callback, pdf, page_num, total),
    )
    return self

  def _wrap_final_callback(self, cb, pdf, page_num, total):
    """Run final-page callback on the whole page, cursor and page state restored."""
    cursor_backup = self._cursor.copy()
    page_backup = self._page_num
    frame = self._page
    left, right = self.sides(page_num) # that page's own, mirrored when even
    self._page = replace(self._page_full, margin_left=left, margin_right=right)
    self._page_num = page_num
    self._total_pages = total
    try:
      cb(self, page_num, total)
    finally:
      self._cursor = cursor_backup
      self._page_num = page_backup
      self._page = frame

  def _apply_page_callbacks(self):
    """Run page callbacks on the whole page, whatever column is open."""
    cursor_backup = self._cursor.copy()
    frame = self._page
    self._page = self._page_full
    try:
      for cb in self._page_callbacks:
        cb(self, self._page_num)
    finally:
      self._page = frame
      self._cursor = cursor_backup

  def _finalize_page(self):
    """
    Run page callbacks and flush bookmarks/links for the current page.

    Must be called while the canvas is still on this page:
    both `bookmarkPage()` and `linkURL()` bind to the current canvas page.
    """
    self._apply_page_callbacks()
    self._bookmarks.apply_page(self._canvas, self._page_num)
    self._links.apply(self._canvas, self._page.height, self._page_num)

  #----------------------------------------------------------------------------------------- Output

  def save(self) -> "PDF":
    """
    Render and save PDF. Idempotent - a second call is a no-op.

    Keeps `pdf.save()` inside a `with` block legal: `__exit__` saves too,
    and reportlab's canvas can only be saved once.
    """
    if self._saved: return self
    self._saved = True
    self._finalize_page() # finalize last page
    self._metadata.apply(self._canvas)
    self._bookmarks.apply_outline(self._canvas) # add outline entries once, at the end
    self._canvas.save()
    return self
