# pdfmarq/md/md_inline.py

"""
Inline token → RichSegment conversion for MarkdownRenderer.

Walks children of a `markdown_it` inline token and produces a flat list of
styled `RichSegment`s, handling: bold/italic/strike, sub/sup/mark, inline
code (with heading-size scaling), links, inline math, emoji, inline
images, footnote refs, task-list checkboxes, soft/hard breaks, and the
small whitelist of inline HTML tags defined in `md_html`.
"""

from markdown_it.token import Token
from ..inline import RichSegment
from . import md_html

#----------------------------------------------------------------------------- Helpers

def _mono_inline_size(s, base_size:float) -> float:
  """Mono size (pt) for inline code embedded at `base_size`.
  Heading-sized contexts use a 0.95 factor to avoid line-box overflow;
  body-size uses the configured `mono_size`/`body_size` ratio."""
  if base_size >= 14: return base_size * 0.95
  return base_size * (s.mono_size / s.body_size)

# Named highlight colors matching Word's `WD_COLOR_INDEX` palette so the
# same `mark_bg="yellow"` produces a comparable visual in both libs. PDF
# rendering uses these RGB values for the rounded background rect drawn
# behind `==marked==` text.
_NAMED_HIGHLIGHTS = {
  "yellow": (1.0, 0.93, 0.3),
  "green": (0.65, 0.95, 0.50),
  "cyan": (0.55, 0.95, 0.95),
  "magenta": (0.95, 0.60, 0.85),
  "pink": (0.95, 0.60, 0.85),
  "blue": (0.55, 0.75, 0.98),
  "red": (0.98, 0.55, 0.55),
  "grey": (0.78, 0.78, 0.78),
  "gray": (0.78, 0.78, 0.78),
}

def _resolve_highlight(color) -> tuple:
  """Map a named highlight string to an RGB tuple. Pass-through for
  tuples; unknown names fall back to yellow."""
  if isinstance(color, str):
    return _NAMED_HIGHLIGHTS.get(color.lower(), _NAMED_HIGHLIGHTS["yellow"])
  return color

#---------------------------------------------------------------------------------- InlineMixin

class InlineMixin:
  """
  Conversion from markdown-it inline tokens to a list of `RichSegment`
  for rendering. Handles bold / italic / code / links / math / emoji /
  images. Mixed into `MarkdownRenderer`.
  """

  def _inline_to_segments(
    self, inline_token:Token, base:RichSegment,
  ) -> list[RichSegment]:
    s = self.style
    segments: list[RichSegment] = []
    is_bold = is_italic = is_strike = False
    is_sub = is_sup = is_mark = False
    is_html_code = False  # `<code>...</code>` inline html - distinct from md `code_inline`
    link_url = None
    link_target = None
    # `in_link` tracks visual link styling independently of actionable target.
    # A local link without `style.link_root` has no action but still renders
    # with link color + underline (so the doc reads correctly).
    in_link = False
    def resolve_mode():
      if is_bold and is_italic: return s.bold_italic_mode
      if is_bold:
        # Escalate inside bold base (heading); fallback drops to Bold.
        if base.mode in (s.head_mode, s.bold_mode): return s.heavy_mode
        return s.bold_mode
      if is_italic: return s.italic_mode
      return base.mode
    def make(text):
      size = base.size
      color = s.link_color if in_link else base.color
      bg = None
      family = base.family
      mode = resolve_mode()
      if is_html_code:
        # Mirrors `code_inline` styling: mono family, code colors, scaled size
        family = s.mono_family
        mode = s.mono_mode
        color = s.code_inline_color
        bg = s.code_inline_bg
        size = _mono_inline_size(s, base.size)
      if is_sub or is_sup:
        size = base.size * 0.7
      if is_mark:
        bg = _resolve_highlight(s.mark_bg)
      return RichSegment(
        text=text,
        family=family,
        mode=mode,
        size=size,
        color=color,
        bg_color=bg,
        underline=in_link,
        strike=is_strike,
        link_url=link_url,
        link_target=link_target,
      )
    def make_emoji(ch):
      """OpenMoji drawing for an emoji char, fallback to raw glyph."""
      try:
        from .openmoji import get_emoji_drawing
        d = get_emoji_drawing(ord(ch), fontsize_pt=base.size)
      except ImportError:
        d = None
      if d is None:
        return make(ch)
      return RichSegment(
        text="",
        family=base.family, mode=base.mode, size=base.size,
        color=base.color,
        math_drawing=d,
        math_width_pt=float(d.width),
        # Emoji center ↔ cap-center alignment (drawing_bottom = baseline - 0.24*size)
        math_baseline_from_bottom_pt=base.size * 0.24,
      )
    def make_text_with_emoji(text):
      """Split text on emoji boundaries → text + emoji segments."""
      try:
        from .openmoji import split_text_by_emoji
        runs = split_text_by_emoji(text)
      except ImportError:
        segments.append(make(text))
        return
      for frag, is_emo in runs:
        if is_emo:
          segments.append(make_emoji(frag))
        elif frag:
          segments.append(make(frag))
    for child in (inline_token.children or []):
      ct = child.type
      if ct == "text": make_text_with_emoji(child.content)
      elif ct == "strong_open": is_bold = True
      elif ct == "strong_close": is_bold = False
      elif ct == "em_open": is_italic = True
      elif ct == "em_close": is_italic = False
      elif ct == "s_open": is_strike = True
      elif ct == "s_close": is_strike = False
      elif ct == "sub_open": is_sub = True
      elif ct == "sub_close": is_sub = False
      elif ct == "sup_open": is_sup = True
      elif ct == "sup_close": is_sup = False
      elif ct == "mark_open": is_mark = True
      elif ct == "mark_close": is_mark = False
      elif ct == "code_inline":
        segments.append(RichSegment(
          text=child.content,
          family=s.mono_family, mode=s.mono_mode, size=_mono_inline_size(s, base.size),
          color=s.code_inline_color, bg_color=s.code_inline_bg,
          link_url=link_url, link_target=link_target,
        ))
      elif ct == "link_open":
        href = self._get_attr(child, "href") or ""
        link_url, link_target = self._resolve_link(href)
        in_link = True
      elif ct == "link_close":
        link_url = None
        link_target = None
        in_link = False
      elif ct == "math_inline":
        # Formula → vector Drawing, embedded via math_drawing slot
        try:
          from .math import render_math_svg_with_baseline
          drawing, baseline_pt = render_math_svg_with_baseline(
            child.content, fontsize=s.body_size, color=s.body_color,
            config=getattr(self, "_math_config", None),
          )
        except ImportError:
          from .._warn import warn_missing
          warn_missing("matplotlib", "matplotlib", "inline math formulas")
          drawing, baseline_pt = None, 0
        if drawing is not None:
          segments.append(RichSegment(
            text="",
            family=s.body_family, mode=base.mode, size=s.body_size,
            color=s.body_color,
            math_drawing=drawing,
            math_width_pt=float(drawing.width),
            math_baseline_from_bottom_pt=float(baseline_pt),
          ))
        else:
          segments.append(RichSegment(
            text=child.content,
            family=s.mono_family, mode=s.italic_mode, size=s.body_size,
            color=s.body_color,
          ))
      elif ct == "emoji":
        emoji_ch = child.content or ""
        if emoji_ch:
          make_text_with_emoji(emoji_ch)
      elif ct == "image":
        img_attrs = child.attrs if isinstance(child.attrs, dict) else dict(child.attrs or [])
        src = img_attrs.get("src", "")
        alt = child.content or ""
        img_drawing = None
        if src and not src.startswith(("http://", "https://")):
          img_drawing = self._load_inline_image(src, base.size, attrs=img_attrs)
        if img_drawing is not None:
          segments.append(RichSegment(
            text="",
            family=base.family, mode=base.mode, size=base.size,
            color=base.color,
            math_drawing=img_drawing,
            math_width_pt=float(img_drawing.width),
            math_baseline_from_bottom_pt=base.size * 0.24,
          ))
        else:
          segments.append(RichSegment(
            text=f"[{alt or src}]",
            family=base.family, mode=s.italic_mode,
            size=base.size, color=s.muted_color,
          ))
      elif ct == "footnote_ref":
        # Superscript label with internal link to footnote block at doc end
        label = (child.meta or {}).get("label", "?")
        segments.append(RichSegment(
          text=f"[{label}]",
          family=base.family, mode=base.mode,
          size=base.size * 0.7, color=s.link_color,
          underline=True,
          link_target=f"fn_{label}",
        ))
      elif ct == "html_inline":
        html = child.content or ""
        tag = html.strip().lower()
        # Task-list checkbox escape hatch (legacy GFM extension marker)
        if "task-list-item-checkbox" in html:
          checked = "checked" in html
          drawing = _make_checkbox(base.size, checked, base.color, s.link_color)
          segments.append(RichSegment(
            text="",
            family=base.family, mode=base.mode, size=base.size,
            color=base.color,
            math_drawing=drawing,
            math_width_pt=float(drawing.width),
            math_baseline_from_bottom_pt=base.size * 0.10,
          ))
        # Whitelisted style toggles (depth-1, no nested same-tag tracking).
        # Tag set defined in md_html.
        elif tag in md_html.BOLD_OPEN: is_bold = True
        elif tag in md_html.BOLD_CLOSE: is_bold = False
        elif tag in md_html.ITALIC_OPEN: is_italic = True
        elif tag in md_html.ITALIC_CLOSE: is_italic = False
        elif tag in md_html.CODE_OPEN: is_html_code = True
        elif tag in md_html.CODE_CLOSE: is_html_code = False
        elif tag in md_html.BREAK: segments.append(make("\n"))
        # Anything else (raw HTML we don't recognize) is silently dropped.
      elif ct == "softbreak": segments.append(make(" "))
      elif ct == "hardbreak": segments.append(make("\n"))
    return segments

  @staticmethod
  def _get_attr(token:Token, name:str) -> str|None:
    attrs = getattr(token, "attrs", None)
    if not attrs: return None
    if isinstance(attrs, dict): return attrs.get(name)
    for k, v in attrs:
      if k == name: return v
    return None

  # Any of these schema prefixes marks an href as external. Anything else
  # without a `#` prefix is treated as a local (file-path-like) link.
  _EXTERNAL_SCHEMAS = (
    "http://", "https://", "mailto:", "tel:", "ftp://", "ftps://",
    "file://", "data:", "sms:",
  )

  def _resolve_link(self, href:str) -> tuple[str|None, str|None]:
    """Resolve a link href into `(link_url, link_target)` for `RichSegment`.
    - `#anchor`    -> internal target if slug is a known heading, else neither
    - schema url   -> external url
    - local path   -> external url under `style.link_root` (if set), else
      neither (renders as styled-but-dead link)
    Local hrefs without `link_root` intentionally get NO action - a PDF
    cannot follow a relative filesystem link, so leaving it un-clickable
    avoids broken behavior. The link STYLE (blue, underline) still applies.
    """
    if not href:
      return None, None
    if href.startswith("#"):
      import urllib.parse
      target = urllib.parse.unquote(href[1:])
      # Unknown anchors would crash reportlab at save() time
      if target in getattr(self, "_known_slugs", set()):
        return None, target
      return None, None
    if href.startswith(self._EXTERNAL_SCHEMAS):
      return href, None
    # Local link - only clickable if link_root is configured
    root = self.style.link_root
    if not root:
      return None, None
    root = root.rstrip("/")
    if href.startswith("/"):
      return f"{root}{href}", None
    base = self.style.link_base or ""
    base = base.strip("/")
    if base:
      return f"{root}/{base}/{href}", None
    return f"{root}/{href}", None

#----------------------------------------------------------------------------- Checkbox drawing

def _make_checkbox(fontsize_pt:float, checked:bool, fg:tuple, accent:tuple):
  """Draw a GitHub-style task-list checkbox as a vector reportlab `Drawing`.

  Font-independent - uses primitive shapes only (no glyph lookup). Box size
  is roughly cap-height; checked state shows a filled accent-colored square
  with a white checkmark inside (two strokes forming a `√`).
  """
  from reportlab.graphics.shapes import Drawing, Rect, PolyLine
  from reportlab.lib.colors import Color
  s = fontsize_pt * 0.85  # box edge length, slightly under cap-height
  pad_right = fontsize_pt * 0.15  # trailing breathing room before next glyph
  w = s + pad_right
  d = Drawing(w, s)
  fg_c = Color(*fg[:3])
  if checked:
    accent_c = Color(*accent[:3])
    box = Rect(0, 0, s, s, rx=s * 0.18, ry=s * 0.18,
      fillColor=accent_c, strokeColor=accent_c, strokeWidth=0)
    d.add(box)
    # White checkmark - two-segment polyline forming a √
    check = PolyLine(
      [s * 0.22, s * 0.50,
       s * 0.42, s * 0.28,
       s * 0.78, s * 0.72],
      strokeColor=Color(1, 1, 1), strokeWidth=s * 0.16,
      strokeLineCap=1, strokeLineJoin=1,
    )
    d.add(check)
  else:
    # Empty box, gray border
    border = Color(min(fg[0] + 0.45, 1), min(fg[1] + 0.45, 1), min(fg[2] + 0.45, 1))
    box = Rect(0, 0, s, s, rx=s * 0.18, ry=s * 0.18,
      fillColor=None, strokeColor=border, strokeWidth=fontsize_pt * 0.08)
    d.add(box)
  return d
