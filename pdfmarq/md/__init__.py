# pdfmarq/md/__init__.py

"""Markdown engine for `pdfmarq`: markdown content drawn into the current frame of a `PDF`.

Pages around the content - banner, footer, signing lines - belong to the packages built on it:
`pdfmarq.paper` for documentation, `pdfmarq.legal` for letters and contracts.

Install the full dependency bundle with ``pip install pdfmarq[md]``.

Bundled (pip):
  - markdown-it-py     # parser
  - mdit-py-plugins    # tables, footnotes, anchors, deflists
  - PyYAML             # frontmatter
  - Pygments           # fenced code syntax highlighting
  - matplotlib         # math formula rendering ($x^2$)
  - emoji              # :smile: shortcode resolution
  - mdit-py-emoji      # emoji parser plugin
  - pyphen             # hyphenation patterns
  - fonttools          # small capitals from a font's own glyphs

Optional system tool (not pip-installable):
  - mermaid-cli (npm)  # ```mermaid``` blocks; auto-detected at runtime

Example:
  >>> from pdfmarq import PDF
  >>> from pdfmarq.md import MarkdownRenderer, lang_style
  >>> pdf = PDF("notes.pdf")
  >>> MarkdownRenderer(pdf, lang_style("pl")).render(open("notes.md").read())
  >>> pdf.save()
"""

#----------------------------------------------------------------------------- Extras for auto-toml

# Declares the `pdfmarq[md]` extra; all packages are required so partial
# installs never produce silent feature gaps.
__extras__ = ("md", [
  "markdown-it-py",
  "mdit-py-plugins",
  "PyYAML",
  "Pygments",
  "matplotlib",
  "emoji",
  "mdit-py-emoji",
  "pyphen",
  "fonttools",
])

#--------------------------------------------------------------------------------------- Public API

from .markdown_style import MarkdownStyle
from .markdown import MarkdownRenderer, top_blocks
from .md_frontmatter import (split_frontmatter, peek_frontmatter, metadata_from_frontmatter,
  pdf_metadata, read_yaml)
from .presets import lang_style, LANG_PRESETS
from .md_html import is_pagebreak_directive, is_group_open_directive

__all__ = [
  "MarkdownStyle",
  "MarkdownRenderer",
  "top_blocks",
  "split_frontmatter",
  "peek_frontmatter",
  "read_yaml",
  "metadata_from_frontmatter",
  "pdf_metadata",
  "lang_style",
  "LANG_PRESETS",
  "is_pagebreak_directive",
  "is_group_open_directive",
]
