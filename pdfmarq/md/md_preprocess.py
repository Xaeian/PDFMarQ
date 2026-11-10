# pdfmarq/md/md_preprocess.py

r"""
Source text preprocessors run before markdown-it parsing.

- `_iter_content_lines`   fence-aware line iterator used by other preprocessors
- `_normalize_list_indent` 2-space list indent → 4-space (markdown-it requires 4)
- `_emojize_outside_code`  `:shortcode:` → Unicode emoji, respecting code blocks
- `normalize_math_delimiters` LaTeX `\[...\]` / `\(...\)` → `$$` / `$...$`
"""
import re
from ..warn import warn_missing

#---------------------------------------------------------------------------------- PreprocessMixin

# A shortcode as the warning knows one, a name with a letter in it:
# a time as `12:30:45` or a table's `|:---:|` is no shortcode.
_SHORTCODE = re.compile(r":[\w+-]*[a-z][\w+-]*:")

class PreprocessMixin:
  """
  Source text preprocessing mixed into `MarkdownRenderer`.
  Runs before markdown-it parsing: list indent normalization and emoji expansion.
  """
  @staticmethod
  def _iter_content_lines(md_text:str):
    """
    Yield `(line, is_content)` for each line.
    `is_content` is `False` for lines inside fenced code blocks
    AND for the fence delimiter lines.
    """
    in_fence = False
    marker = ""
    for line in md_text.split("\n"):
      stripped = line.lstrip()
      if in_fence:
        yield line, False
        if stripped.startswith(marker):
          in_fence = False
          marker = ""
        continue
      if stripped.startswith("```"):
        in_fence = True; marker = "```"
        yield line, False
        continue
      if stripped.startswith("~~~"):
        in_fence = True; marker = "~~~"
        yield line, False
        continue
      yield line, True

  # A sub-item nests only when indented to the parent's content column (2 for `- `, 3 for `1. `).
  # Below that it gets doubled;
  # from 3 up it already clears the bar,
  # and doubling would push it past the 4-space code threshold.
  _NEST_PROMOTE_BELOW = 3

  @staticmethod
  def _normalize_list_indent(md_text:str) -> str:
    """Promote a too-shallow list indent to one markdown-it accepts as nesting."""
    list_item_re = re.compile(r"^(\s*)([-*+]|\d+\.)\s")
    limit = PreprocessMixin._NEST_PROMOTE_BELOW
    out: list[str] = []
    for line, is_content in PreprocessMixin._iter_content_lines(md_text):
      if not is_content:
        out.append(line)
        continue
      m = list_item_re.match(line)
      if m:
        leading = m.group(1)
        if "\t" not in leading and 0 < len(leading) < limit:
          out.append(" " * (len(leading) * 2) + line[len(leading):])
          continue
      out.append(line)
    return "\n".join(out)

  @staticmethod
  def _emojize_outside_code(md_text:str) -> str:
    """
    Replace `:name:` emoji shortcodes with Unicode chars outside code.
    Without the `emoji` package the text stays as written, and only a shortcode in it warns.
    """
    try:
      import emoji
    except ImportError:
      emoji = None
    out: list[str] = []
    for line, is_content in PreprocessMixin._iter_content_lines(md_text):
      if not is_content:
        out.append(line)
        continue
      parts = line.split("`")
      for i in range(0, len(parts), 2):
        if emoji:
          parts[i] = emoji.emojize(parts[i], language="alias")
        elif _SHORTCODE.search(parts[i]):
          warn_missing("emoji", "emoji", "emoji shortcodes (:name:)")
      out.append("`".join(parts))
    return "\n".join(out)

#---------------------------------------------------------------------------------- Math delimiters

_MATH_INLINE_RE = re.compile(r"\\\((.+?)\\\)")
_MATH_BLOCK_LINE_RE = re.compile(r"^(\s*)\\\[\s*(.+?)\s*\\\]\s*$")

def normalize_math_delimiters(md_text:str) -> str:
  r"""
  LaTeX math delimiters `\[...\]` / `\(...\)` become `$$` / `$...$`.

  The bracket forms are what LaTeX sources and AI assistants emit;
  only the dollar forms reach the parser.
  Fenced code passes through untouched and inline code spans keep their backslashes.
  """
  out: list[str] = []
  in_fence = False
  for line in md_text.split("\n"):
    stripped = line.strip()
    if in_fence:
      out.append(line)
      if stripped.startswith(("```", "~~~")): in_fence = False
      continue
    if stripped.startswith(("```", "~~~")):
      in_fence = True
      out.append(line)
      continue
    indent = line[:len(line) - len(line.lstrip())]
    if stripped in ("\\[", "\\]"):
      out.append(indent + "$$")
      continue
    m = _MATH_BLOCK_LINE_RE.match(line)
    if m:
      out.extend([m.group(1) + "$$", m.group(1) + m.group(2), m.group(1) + "$$"])
      continue
    parts = line.split("`")
    for i in range(0, len(parts), 2):
      parts[i] = _MATH_INLINE_RE.sub(lambda x: "$" + x.group(1).strip() + "$", parts[i])
    out.append("`".join(parts))
  return "\n".join(out)
