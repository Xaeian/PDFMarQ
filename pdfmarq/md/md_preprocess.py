# pdfmarq/md/md_preprocess.py

"""
Source text preprocessors for markdown rendering.

- `_iter_content_lines` - fence-aware line iterator used by other preprocessors
- `_normalize_list_indent` - 2-space list indent → 4-space (markdown-it needs 4)
- `_emojize_outside_code` - `:shortcode:` → Unicode emoji, respecting code blocks
"""
import re

#------------------------------------------------------------------------------ PreprocessMixin

class PreprocessMixin:
  """
  Source text preprocessing (list indent normalization, emoji shortcode
  replacement) run before markdown-it parsing. Mixed into
  `MarkdownRenderer`.
  """

  @staticmethod
  def _iter_content_lines(md_text:str):
    """Yield `(line, is_content)` for each line. `is_content` is False for
    lines inside fenced code blocks AND for the fence delimiter lines."""
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

  @staticmethod
  def _normalize_list_indent(md_text:str) -> str:
    """2-space list indents → 4-space (markdown-it needs 4 for nesting)."""
    list_item_re = re.compile(r"^(\s*)([-*+]|\d+\.)\s")
    out: list[str] = []
    for line, is_content in PreprocessMixin._iter_content_lines(md_text):
      if not is_content:
        out.append(line)
        continue
      m = list_item_re.match(line)
      if m:
        leading = m.group(1)
        if "\t" not in leading and 0 < len(leading) < 8:
          out.append(" " * (len(leading) * 2) + line[len(leading):])
          continue
      out.append(line)
    return "\n".join(out)

  @staticmethod
  def _emojize_outside_code(md_text:str) -> str:
    """Replace `:name:` emoji shortcodes with Unicode chars outside code."""
    try:
      import emoji as _emoji
    except ImportError:
      from .._warn import warn_missing
      warn_missing("emoji", "emoji", "emoji shortcodes (:name:)")
      return md_text
    out: list[str] = []
    for line, is_content in PreprocessMixin._iter_content_lines(md_text):
      if not is_content:
        out.append(line)
        continue
      parts = line.split("`")
      for i in range(0, len(parts), 2):
        parts[i] = _emoji.emojize(parts[i], language="alias")
      out.append("`".join(parts))
    return "\n".join(out)
