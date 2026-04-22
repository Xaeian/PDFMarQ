# pdfmarq/md/__init__.py

"""
Markdown rendering for `pdfmarq`.

Forces all markdown-related dependencies as a single bundle. Install with:

  pip install pdfmarq[md]

Bundled dependencies (all required, no optional):
  - markdown-it-py     # parser
  - mdit-py-plugins    # tables, footnotes, anchors, deflists
  - PyYAML             # frontmatter
  - Pygments           # syntax highlighting in fenced code blocks
  - matplotlib         # math formula rendering ($x^2$)
  - emoji              # :smile: shortcode resolution
  - mdit-py-emoji      # emoji parser plugin

Optional system tools (not pip-installable):
  - mermaid-cli (npm)  # for ```mermaid``` blocks; auto-detected at runtime

Example:
  >>> from pdfmarq.md import md_to_pdf, MarkdownStyle
  >>> style = MarkdownStyle(body_family="IBMPlexSans")
  >>> md_to_pdf(open("doc.md").read(), "doc.pdf", style=style)
"""

#------------------------------------------------------------------------- Extras for auto-toml

# Tuple form: (extra_name, [packages]). Forces ALL packages on `pdfmarq[md]`
# install - no piecemeal optionals to avoid surprise feature gaps.
__extras__ = ("md", [
  "markdown-it-py",
  "mdit-py-plugins",
  "PyYAML",
  "Pygments",
  "matplotlib",
  "emoji",
  "mdit-py-emoji",
])

#----------------------------------------------------------------------------------- Public API

from .markdown_style import MarkdownStyle
from .markdown import MarkdownRenderer, md_to_pdf

__all__ = [
  "MarkdownStyle",
  "MarkdownRenderer",
  "md_to_pdf",
]
