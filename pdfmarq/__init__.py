# pdfmarq/__init__.py

"""
PDF generation with fluent API. Built on reportlab.

Low-level drawing only - no markdown. For markdown rendering install
the `[md]` extra and import from `pdfmarq.md`:

  pip install pdfmarq[md]
  from pdfmarq.md import md_to_pdf, MarkdownStyle

Example:
  >>> from pdfmarq import PDF, Align
  >>> with PDF("output.pdf") as pdf:
  ...   pdf.font("Helvetica", 12, "Bold")
  ...   pdf.text("Hello World", align=Align.CENTER)
"""

#----------------------------------------------------------------------- Metadata for auto-toml

__version__ = "0.2.0"
__repo__ = "Xaeian/PDFMarQ"
__python__ = ">=3.10"
__description__ = "PDF generation library with fluent API and optional markdown support"
__author__ = "Xaeian"
__keywords__ = ["pdf", "reportlab", "document", "generation", "markdown"]
__dependencies__ = ["reportlab", "Pillow", "svglib"]

#----------------------------------------------------------------------------------- Public API

from .constants import (
  Unit, PageSize, Align, Colors, Defaults, MM_TO_PT,
  A4, A3, A5, LETTER, LEGAL,
)
from .styles import Style, TableStyle, Styles
from .layout import Cursor, PageGeometry
from .text import TextMetrics, BoxFitResult
from .tables import TableBuilder, TableData, Cell
from .fonts import FontManager
from .structure import Metadata, Bookmark, TOCEntry, BookmarkManager, LinkManager
from .utils import to_mm, to_pt, mm_to_pt, parse_color, color_alpha, parse_margin
from .inline import RichSegment, render_rich
from .core import PDF

__all__ = [
  "PDF",
  "Unit", "PageSize", "Align", "Colors", "Defaults", "MM_TO_PT",
  "A4", "A3", "A5", "LETTER", "LEGAL",
  "Style", "TableStyle", "Styles",
  "Cursor", "PageGeometry",
  "TextMetrics", "BoxFitResult",
  "TableBuilder", "TableData", "Cell",
  "FontManager",
  "Metadata", "Bookmark", "TOCEntry", "BookmarkManager", "LinkManager",
  "to_mm", "to_pt", "mm_to_pt", "parse_color", "color_alpha", "parse_margin",
  "RichSegment", "render_rich",
]
