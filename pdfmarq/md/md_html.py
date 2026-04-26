# pdfmarq/md/md_html.py

"""HTML whitelist for `MarkdownRenderer`.

`pdfmarq` recognizes only a small subset of raw HTML embedded in markdown.
Everything else _(`<table>`, `<div>`, `<span>`, `<style>`, attributes, etc.)_
is dropped silently.

Block:
  `<hr>`            — horizontal rule

Inline _(paired)_:
  `<b>`, `<strong>` — bold
  `<i>`, `<em>`     — italic
  `<code>`          — inline code _(mono family, code colors)_

Inline _(self-closing)_:
  `<br>`, `<hr>`    — hard line break

Tags are matched case-insensitively, with whitespace tolerance for the
self-closing form (`<br/>`, `<br />`). Attributes disqualify a tag from
the whitelist — `<b class="x">` is dropped, not styled.
"""
import re

#---------------------------------------------------------------------------------- Block

_HR_BLOCK_RE = re.compile(r"\s*<hr\s*/?>\s*", re.IGNORECASE)

def is_hr_block(content:str) -> bool:
  """True for `<hr>` / `<hr/>` / `<hr />` html_block content."""
  return bool(_HR_BLOCK_RE.fullmatch(content))

#---------------------------------------------------------------------------------- Inline

BOLD_OPEN    = frozenset(("<b>", "<strong>"))
BOLD_CLOSE   = frozenset(("</b>", "</strong>"))
ITALIC_OPEN  = frozenset(("<i>", "<em>"))
ITALIC_CLOSE = frozenset(("</i>", "</em>"))
CODE_OPEN    = frozenset(("<code>",))
CODE_CLOSE   = frozenset(("</code>",))
BREAK        = frozenset(("<br>", "<br/>", "<br />", "<hr>", "<hr/>", "<hr />"))
