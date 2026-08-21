# pdfmarq/structure.py

"""Document structure - bookmarks, TOC, metadata, hyperlinks."""
from dataclasses import dataclass, field
from reportlab.lib.units import mm as RL_MM

#----------------------------------------------------------------------------------------- Bookmark

@dataclass
class Bookmark:
  """PDF bookmark/outline entry."""
  title: str
  page: int
  y: float # destination height in canvas mm, measured from the page bottom
  level: int = 0
  children: list["Bookmark"] = field(default_factory=list)

#----------------------------------------------------------------------------------------- TOCEntry

@dataclass
class TOCEntry:
  """Table of contents entry."""
  title: str
  page: int
  level: int = 0

#----------------------------------------------------------------------------------------- Metadata

@dataclass
class Metadata:
  """PDF document metadata.

  `comments` and `category` are accepted and stored but NOT applied to the PDF /Info
  dictionary because reportlab's `Canvas` has no native setter for them.
  Round-tripping through the dataclass works; the resulting PDF file
  won't carry those fields.
  """
  title: str|None = None
  author: str|None = None
  subject: str|None = None
  keywords: str|None = None
  comments: str|None = None
  category: str|None = None
  creator: str = "pdfmarq"
  producer: str|None = None

  def apply(self, canvas):
    """Write available metadata fields to the canvas /Info dictionary."""
    if self.title: canvas.setTitle(self.title)
    if self.author: canvas.setAuthor(self.author)
    if self.subject: canvas.setSubject(self.subject)
    if self.keywords: canvas.setKeywords(self.keywords)
    if self.creator: canvas.setCreator(self.creator)
    if self.producer: canvas.setProducer(self.producer)

#---------------------------------------------------------------------------------- BookmarkManager

class BookmarkManager:
  """Manages PDF bookmarks/outlines.

  Call order: `apply_page` during each page render, then `apply_outline`
  once before `canvas.save()`. Order matters - anchors must exist before
  the outline references them.
  """
  def __init__(self):
    self._bookmarks: list[Bookmark] = []

  def add(self, title:str, page:int, y:float, level:int=0) -> str:
    """Add bookmark, return anchor key. `y` is canvas mm from the page bottom."""
    key = f"bm_{len(self._bookmarks)}"
    self._bookmarks.append(Bookmark(title, page, y, level))
    return key

  def apply_page(self, canvas, page:int):
    """Register anchors for all bookmarks on this page. Canvas must be on that page.

    Each destination carries its entry's own height, so following the
    outline scrolls to the heading rather than fitting the whole page.
    """
    for i, bm in enumerate(self._bookmarks):
      if bm.page == page:
        canvas.bookmarkHorizontalAbsolute(f"bm_{i}", bm.y * RL_MM)

  def apply_outline(self, canvas):
    """Add outline entries for all bookmarks. Call once, after all pages are rendered."""
    for i, bm in enumerate(self._bookmarks):
      canvas.addOutlineEntry(bm.title, f"bm_{i}", level=bm.level)

  def get_toc(self) -> list[TOCEntry]:
    """Generate TOC entries from bookmarks."""
    return [TOCEntry(bm.title, bm.page, bm.level) for bm in self._bookmarks]

#-------------------------------------------------------------------------------------- LinkManager

class LinkManager:
  """Manages hyperlinks."""
  def __init__(self):
    self._links: list[dict] = []

  def add_url(self, url:str, x:float, y:float, width:float, height:float, page:int=1):
    """Add external URL link."""
    self._links.append({
      "type": "url", "url": url,
      "x": x, "y": y, "width": width, "height": height, "page": page,
    })

  def add_internal(self, dest:str, x:float, y:float, width:float, height:float, page:int=1):
    """Add internal document link."""
    self._links.append({
      "type": "internal", "dest": dest,
      "x": x, "y": y, "width": width, "height": height, "page": page,
    })

  def apply(self, canvas, page_height:float, current_page:int=1):
    """Apply links for current page."""
    for link in self._links:
      if link["page"] != current_page:
        continue
      x = link["x"] * RL_MM
      y = (page_height - link["y"] - link["height"]) * RL_MM
      w = link["width"] * RL_MM
      h = link["height"] * RL_MM
      if link["type"] == "url": canvas.linkURL(link["url"], (x, y, x + w, y + h), relative=0)
      else:
        canvas.linkAbsolute(link["dest"], (x, y, x + w, y + h))
