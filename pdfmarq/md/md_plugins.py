# pdfmarq/md/md_plugins.py

"""
Custom markdown-it-py plugins for features not in mdit_py_plugins:
- `sup_plugin` - superscript via `^text^`
- `mark_plugin` - highlight via `==text==`

Both are delimiter-based inline rules adapted from the built-in
`sub_plugin` pattern (which handles `~subscript~`).
"""

from __future__ import annotations
import re
from markdown_it import MarkdownIt
from markdown_it.rules_inline import StateInline

WHITESPACE_RE = re.compile(r"(^|[^\\])(\\\\)*\s")
UNESCAPE_RE = re.compile(r'\\([ \\!"#$%&\'()*+,.\/:;<=>?@[\]^_`{|}~-])')

#--------------------------------------------------------------------------- Superscript ^text^

def _tokenize_sup(state: StateInline, silent: bool) -> bool:
  if silent:
    return False
  start = state.pos
  if state.src[start] != "^":
    return False
  maximum = state.posMax
  if start + 2 >= maximum:
    return False
  state.pos = start + 1
  found = False
  while state.pos < maximum:
    if state.src[state.pos] == "^":
      found = True
      break
    state.md.inline.skipToken(state)
  if not found or start + 1 == state.pos:
    state.pos = start
    return False
  content = state.src[start + 1 : state.pos]
  if WHITESPACE_RE.search(content) is not None:
    state.pos = start
    return False
  state.posMax = state.pos
  state.pos = start + 1
  tok = state.push("sup_open", "sup", 1)
  tok.markup = "^"
  tok = state.push("text", "", 0)
  tok.content = UNESCAPE_RE.sub(r"\1", content)
  tok = state.push("sup_close", "sup", -1)
  tok.markup = "^"
  state.pos = state.posMax + 1
  state.posMax = maximum
  return True

def sup_plugin(md: MarkdownIt) -> None:
  """Register superscript `^text^` → sup_open / text / sup_close tokens."""
  md.inline.ruler.after("emphasis", "sup", _tokenize_sup)

#--------------------------------------------------------------------------- Highlight ==text==

def _tokenize_mark(state: StateInline, silent: bool) -> bool:
  if silent:
    return False
  start = state.pos
  maximum = state.posMax
  # Need `==` (two equals signs)
  if start + 4 > maximum:
    return False
  if state.src[start] != "=" or state.src[start + 1] != "=":
    return False
  state.pos = start + 2
  found_end = -1
  while state.pos < maximum - 1:
    if state.src[state.pos] == "=" and state.src[state.pos + 1] == "=":
      found_end = state.pos
      break
    state.md.inline.skipToken(state)
  if found_end < 0 or found_end == start + 2:
    state.pos = start
    return False
  content = state.src[start + 2 : found_end]
  # Disallow starting/ending with whitespace (standard delimiter rule)
  if content[0].isspace() or content[-1].isspace():
    state.pos = start
    return False
  state.posMax = found_end
  state.pos = start + 2
  tok = state.push("mark_open", "mark", 1)
  tok.markup = "=="
  tok = state.push("text", "", 0)
  tok.content = UNESCAPE_RE.sub(r"\1", content)
  tok = state.push("mark_close", "mark", -1)
  tok.markup = "=="
  state.pos = state.posMax + 2
  state.posMax = maximum
  return True

def mark_plugin(md: MarkdownIt) -> None:
  """Register highlight `==text==` → mark_open / text / mark_close tokens."""
  md.inline.ruler.after("emphasis", "mark", _tokenize_mark)
