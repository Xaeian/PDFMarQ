# pdfmarq/md/highlight.py

"""
Syntax highlighting for code blocks via `pygments`.

Converts a source string + language hint into a list of lines, where each
line is a list of `RichSegment` with colors/weights from a pygments style.

Falls back gracefully: if pygments is missing, the language is unknown, or
any other error occurs, `highlight_code()` returns `None` and the caller
should render the code as plain monospace.

Example:
  >>> from pdfmarq.highlight import highlight_code
  >>> lines = highlight_code("def f(): return 1", lang="python",
  ...                        family="Courier", mode="Regular", size=10)
  >>> # lines is list[list[RichSegment]], one inner list per source line
"""

__extras__ = ("highlight", ["pygments"])

from ..inline import RichSegment

try:
  from pygments import lex
  from pygments.lexers import get_lexer_by_name
  from pygments.styles import get_style_by_name
  from pygments.util import ClassNotFound
  _HAS_PYGMENTS = True
except ImportError:
  _HAS_PYGMENTS = False

#-------------------------------------------------------------------------------- Color helpers

def _hex_to_rgb(hex_str:str) -> tuple[float, float, float]:
  """Parse 6-char hex color to (r, g, b) 0-1."""
  hex_str = hex_str.lstrip("#")
  if len(hex_str) != 6:
    return (0, 0, 0)
  r = int(hex_str[0:2], 16) / 255
  g = int(hex_str[2:4], 16) / 255
  b = int(hex_str[4:6], 16) / 255
  return (r, g, b)

#------------------------------------------------------------------ Markdown custom highlighter

# Pygments' markdown lexer has known bugs (e.g. only tags `1.` and `2.` as
# Keyword but not `3.`+). Simple regex-based highlighter instead.
_MD_COLORS = {
  "heading":     (0.035, 0.368, 0.855),
  "list_marker": (0.0,   0.502, 0.0),
  "code":        (0.729, 0.129, 0.129),
  "fence":       (0.502, 0.502, 0.502),
  "link":        (0.035, 0.368, 0.855),
  "quote":       (0.502, 0.502, 0.502),
  "default":     (0.13,  0.13,  0.13),
}

import re as _re

# Block-level markers: (regex, color_key, marker_mode)
#   marker_sep_content - 3 groups: bold marker + neutral sep + content
#   full_line          - full line in one color, no inline tokenization
#   quote              - 2 groups: marker+ws + content (content is quoted)
_MD_BLOCKS = [
  (_re.compile(r"^(#{1,6})(\s+)(.*)$"),   "heading",     "marker_sep_content"),
  (_re.compile(r"^(```+|~~~+)(.*)$"),     "fence",       "full_line"),
  (_re.compile(r"^([-*+])(\s+)(.*)$"),    "list_marker", "marker_sep_content"),
  (_re.compile(r"^(\d+\.)(\s+)(.*)$"),    "list_marker", "marker_sep_content"),
  (_re.compile(r"^(>+\s*)(.*)$"),         "quote",       "quote"),
]

def _highlight_md(
  code: str, family: str, mode: str, bold_mode: str, size: float,
  default_color: tuple,
) -> list[list[RichSegment]]:
  """Regex-based markdown highlighter - correct, simple, no pygments dependency."""
  def seg(text: str, color: tuple, bold: bool = False) -> RichSegment:
    return RichSegment(
      text=text, family=family, mode=bold_mode if bold else mode,
      size=size, color=color,
    )
  lines_out: list[list[RichSegment]] = []
  for src in code.split("\n"):
    line_segs: list[RichSegment] = []
    m_indent = _re.match(r"^(\s*)", src)
    indent = m_indent.group(1) if m_indent else ""
    rest = src[len(indent):]
    if indent:
      line_segs.append(seg(indent, default_color))
    content = rest
    is_quote = False
    # Match first block-level pattern (if any)
    for pat, color_key, marker_mode in _MD_BLOCKS:
      m = pat.match(rest)
      if not m:
        continue
      color = _MD_COLORS[color_key]
      if marker_mode == "full_line":
        line_segs.append(seg(rest, color))
        content = ""
      elif marker_mode == "marker_sep_content":
        line_segs.append(seg(m.group(1), color, bold=True))
        line_segs.append(seg(m.group(2), default_color))
        content = m.group(3)
      elif marker_mode == "quote":
        line_segs.append(seg(m.group(1), color, bold=True))
        content = m.group(2)
        is_quote = True
      break
    if content:
      _tokenize_md_inline(
        content, line_segs, family, mode, bold_mode, size, default_color,
        quote=is_quote,
      )
    if not line_segs:
      line_segs.append(seg(" ", default_color))
    lines_out.append(line_segs)
  return lines_out

# Inline tokens: `code`, **bold**, *italic*, ~~strike~~, [text](url)
# Each alternative's group index → (color_key, bold). `code`/`link` use
# their own colors; others use the surrounding base_color.
_MD_INLINE_PAT = _re.compile(
  r"(`+)([^`]*?)\1"                     # 1: code
  r"|(\*\*)([^*]+?)\*\*"                # 3: **bold**
  r"|(__)([^_]+?)__"                    # 5: __bold__
  r"|(\*)([^*]+?)\*"                    # 7: *italic*
  r"|(_)([^_]+?)_"                      # 9: _italic_
  r"|(~~)([^~]+?)~~"                    # 11: ~~strike~~
  r"|(\[)([^\]]+?)(\])(\()([^)]+?)(\))" # 13: [text](url)
)
_MD_INLINE_GROUPS = [
  (1,  "code",    False),
  (3,  None,      True),   # **bold**
  (5,  None,      True),   # __bold__
  (7,  None,      False),  # *italic*
  (9,  None,      False),  # _italic_
  (11, None,      False),  # ~~strike~~
  (13, "link",    False),
]

def _tokenize_md_inline(
  text: str, out: list[RichSegment], family: str, mode: str, bold_mode: str,
  size: float, default_color: tuple, quote: bool = False,
):
  """Parse inline markdown into colored segments."""
  base_color = _MD_COLORS["quote"] if quote else default_color
  def seg(t: str, c: tuple, bold: bool = False) -> RichSegment:
    return RichSegment(
      text=t, family=family, mode=bold_mode if bold else mode,
      size=size, color=c,
    )
  pos = 0
  for m in _MD_INLINE_PAT.finditer(text):
    if m.start() > pos:
      out.append(seg(text[pos:m.start()], base_color))
    for group_idx, color_key, bold in _MD_INLINE_GROUPS:
      if m.group(group_idx):
        color = _MD_COLORS[color_key] if color_key else base_color
        out.append(seg(m.group(0), color, bold=bold))
        break
    pos = m.end()
  if pos < len(text):
    out.append(seg(text[pos:], base_color))

#------------------------------------------------------------------------------------ Highlight

def highlight_code(
  code: str,
  lang: str,
  family: str = "Courier",
  mode: str = "Regular",
  bold_mode: str = "Bold",
  size: float = 10,
  default_color: tuple = (0.13, 0.13, 0.13),
  theme: str = "default",
) -> list[list[RichSegment]] | None:
  """Tokenize and style `code` using pygments. Return list of styled lines.

  Args:
    code: Source code string.
    lang: Language hint (e.g. `"python"`, `"javascript"`, `"c"`).
    family: Monospace font family for output segments.
    mode: Regular font mode.
    bold_mode: Bold font mode (used for bold tokens like keywords).
    size: Font size in points.
    default_color: Fallback color for tokens without a style color.
    theme: Pygments style name (e.g. `"default"`, `"friendly"`, `"github-dark"`).

  Returns:
    `list[list[RichSegment]]` - outer = source lines, inner = colored spans;
    or `None` if pygments is unavailable or the language is unknown.
  """
  if not lang:
    return None
  # Custom markdown highlighter (pygments md lexer has bugs with list
  # markers - only tags `1.` and `2.` as Keyword, not `3.`+).
  if lang in ("md", "markdown"):
    return _highlight_md(
      code, family=family, mode=mode, bold_mode=bold_mode, size=size,
      default_color=default_color,
    )
  if not _HAS_PYGMENTS:
    from .._warn import warn_missing
    warn_missing("pygments", "pygments", "syntax highlighting in code blocks")
    return None
  try:
    lexer = get_lexer_by_name(lang, stripnl=False, ensurenl=False)
  except ClassNotFound:
    return None
  try:
    style = get_style_by_name(theme)
  except ClassNotFound:
    style = get_style_by_name("default")
  lines: list[list[RichSegment]] = [[]]
  for token_type, text in lex(code, lexer):
    if not text:
      continue
    try:
      tstyle = style.style_for_token(token_type)
    except KeyError:
      tstyle = {"color": None, "bold": False}
    color = _hex_to_rgb(tstyle["color"]) if tstyle["color"] else default_color
    tmode = bold_mode if tstyle["bold"] else mode
    # Split by \n so each source line is its own inner list
    parts = text.split("\n")
    for idx, part in enumerate(parts):
      if part:
        lines[-1].append(RichSegment(
          text=part, family=family, mode=tmode, size=size, color=color,
        ))
      if idx < len(parts) - 1:
        lines.append([])
  # Drop trailing empty line if code ended with \n
  if lines and not lines[-1]:
    lines.pop()
  return lines or None
