# pdfmarq/paper/__init__.py

"""
Documentation-style PDFs: markdown content with a frontmatter banner around it.

Page 1 gets the banner (id, version, status, dates, logo), later pages a compact one,
every page a page number, and the end optional signing lines.
The content itself is drawn by `pdfmarq.md`. Needs ``pip install pdfmarq[md]``.

Example:
  >>> from pdfmarq.paper import md_to_pdf, lang_style
  >>> md_to_pdf(open("doc.md").read(), "doc.pdf", style=lang_style("pl"))
"""

from .style import PaperStyle
from .presets import lang_style, LANG_PRESETS
from .render import md_to_pdf, md_into

__all__ = [
  "PaperStyle",
  "md_to_pdf",
  "md_into",
  "lang_style",
  "LANG_PRESETS",
]
