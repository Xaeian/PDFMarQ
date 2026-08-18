# pdfmarq/md/__init__.py

"""Markdown rendering for `pdfmarq`. Install the full dependency bundle with
``pip install pdfmarq[md]``.

Bundled (pip):
  - markdown-it-py     # parser
  - mdit-py-plugins    # tables, footnotes, anchors, deflists
  - PyYAML             # frontmatter
  - Pygments           # fenced code syntax highlighting
  - matplotlib         # math formula rendering ($x^2$)
  - emoji              # :smile: shortcode resolution
  - mdit-py-emoji      # emoji parser plugin

Optional system tool (not pip-installable):
  - mermaid-cli (npm)  # ```mermaid``` blocks; auto-detected at runtime

Example:
  >>> from pdfmarq.md import md_to_pdf, MarkdownStyle
  >>> style = MarkdownStyle(font_body="IBMPlexSans")
  >>> md_to_pdf(open("doc.md").read(), "doc.pdf", style=style)
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
])

#--------------------------------------------------------------------------------------- Public API

from .markdown_style import MarkdownStyle
from .markdown import MarkdownRenderer, md_to_pdf
from .presets import lang_style, LANG_PRESETS

__all__ = [
  "MarkdownStyle",
  "MarkdownRenderer",
  "md_to_pdf",
  "lang_style",
  "LANG_PRESETS",
]
