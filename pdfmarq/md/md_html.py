# pdfmarq/md/md_html.py

"""HTML whitelist for `MarkdownRenderer`.

Only a small subset of raw HTML is recognized; everything else is dropped silently.

Block:
  `<hr>`                 - horizontal rule
  `<!-- pagebreak -->`   - force new page
  `<!-- group -->` ...   - keep-together block (paired with `<!-- /group -->`)

Inline (paired):
  `<b>`, `<strong>` - bold
  `<i>`, `<em>`     - italic
  `<code>`          - inline code (mono family, code colors)

Inline (self-closing):
  `<br>`, `<hr>`    - hard line break

Tags matched case-insensitively; whitespace-tolerant for self-closing form.
Attributes disqualify a tag (`<b class="x">` is dropped, not styled).
Directives reject extra tokens: `<!-- pagebreak xxx -->` is a plain comment.
"""
import re

#---------------------------------------------------------------------------------- Block

_HR_BLOCK_RE = re.compile(r"\s*<hr\s*/?>\s*", re.IGNORECASE)

def is_hr_block(content:str) -> bool:
  """True for `<hr>` / `<hr/>` / `<hr />` html_block content."""
  return bool(_HR_BLOCK_RE.fullmatch(content))

#------------------------------------------------------------------------------ Directives

_PAGEBREAK_RE = re.compile(r"\s*<!--\s*pagebreak\s*-->\s*", re.IGNORECASE)
_GROUP_OPEN_RE = re.compile(r"\s*<!--\s*group\s*-->\s*", re.IGNORECASE)
_GROUP_CLOSE_RE = re.compile(r"\s*<!--\s*/\s*group\s*-->\s*", re.IGNORECASE)

def is_pagebreak_directive(content:str) -> bool:
  """True for `<!-- pagebreak -->` directive; extra tokens disqualify."""
  return bool(_PAGEBREAK_RE.fullmatch(content))

def is_group_open_directive(content:str) -> bool:
  """True for `<!-- group -->` opening directive."""
  return bool(_GROUP_OPEN_RE.fullmatch(content))

def is_group_close_directive(content:str) -> bool:
  """True for `<!-- /group -->` closing directive."""
  return bool(_GROUP_CLOSE_RE.fullmatch(content))

#---------------------------------------------------------------------------------- Inline

BOLD_OPEN    = frozenset(("<b>", "<strong>"))
BOLD_CLOSE   = frozenset(("</b>", "</strong>"))
ITALIC_OPEN  = frozenset(("<i>", "<em>"))
ITALIC_CLOSE = frozenset(("</i>", "</em>"))
CODE_OPEN    = frozenset(("<code>",))
CODE_CLOSE   = frozenset(("</code>",))
BREAK        = frozenset(("<br>", "<br/>", "<br />", "<hr>", "<hr/>", "<hr />"))
