# pdfmarq/legal/__init__.py

"""
Letters, statements and contracts: markdown content with a letter header and a signed end.

Frontmatter holds the facts of the document: `title`, `place`, `date`, `from`, `to`, `ref`,
`logo`, `attachments`. The style holds the look: columns, justification, signing lines, fonts.
The content itself is drawn by `pdfmarq.md`. Needs ``pip install pdfmarq[md]``.

Example:
  >>> from pdfmarq.legal import md_to_pdf, md_parallel_to_pdf, lang_style
  >>> style = lang_style("pl", columns=2, sign="contract")
  >>> md_to_pdf(open("contract.md").read(), "contract.pdf", style=style)
  >>> md_parallel_to_pdf([pl_text, en_text], "contract-pl-en.pdf",
  ...   styles=[lang_style("pl"), lang_style("en")])
"""

from .style import LegalStyle
from .presets import lang_style, LANG_PRESETS
from .render import md_to_pdf, md_parallel_to_pdf

__all__ = [
  "LegalStyle",
  "md_to_pdf",
  "md_parallel_to_pdf",
  "lang_style",
  "LANG_PRESETS",
]
