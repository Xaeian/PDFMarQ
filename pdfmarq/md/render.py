"""Frontmatter `render:` block - geometry, typography, chrome, locale.

User-facing field names are short and friendly (`font`, `head_font`, `banner`,
`page_number`) and map to internal `MarkdownStyle` / `PageGeometry` keys at
parse time. Mirrors `docmarq.md.render` field-for-field.

Precedence: `MarkdownStyle()` defaults < frontmatter `lang` preset <
frontmatter `render:` keys < caller's `style=` non-default fields.

Example:
```yaml
---
title: Report
render:
  page: A4
  margin: 25
  landscape: false
  font: Inter
  font_size: 11
  banner: true
  page_number: true
  lang: pl
---
```
"""
from dataclasses import dataclass, fields
import warnings
from ..constants import PageSize, A4, A3, A5, LETTER, LEGAL
from .markdown_style import MarkdownStyle
from .presets import lang_style

#----------------------------------------------------------------------------- Page presets

# Frontmatter `page:` resolves to one of these by case-insensitive name.
# Arbitrary `[w, h]` dims are intentionally NOT accepted in frontmatter -
# they belong in `md_to_pdf(width=, height=)` caller code where they're more
# discoverable and don't clutter document metadata.
PAGE_PRESETS: dict[str, PageSize] = {
  "A4": A4, "A3": A3, "A5": A5, "LETTER": LETTER, "LEGAL": LEGAL,
}

#---------------------------------------------------------------------------- RenderConfig

@dataclass
class RenderConfig:
  """Parsed `render:` block. `None` means "not set" - frontmatter level
  shouldn't override a default with another default."""
  page: PageSize|None = None
  margin: float|tuple|list|None = None
  landscape: bool|None = None
  font_body: str|None = None
  font_head: str|None = None
  font_mono: str|None = None
  font_size: float|None = None
  line_height: float|None = None
  img_max_h: float|None = None
  banner: bool|None = None
  banner_min: bool|None = None
  page_number: bool|None = None
  lang: str|None = None
  mermaid_theme: str|None = None
  syntax_theme: str|None = None

_KNOWN_KEYS = {f.name for f in fields(RenderConfig())}

#---------------------------------------------------------------------------- Parser

def parse_render_block(fm:dict|None) -> RenderConfig:
  """Parse a frontmatter dict's `render:` sub-block into `RenderConfig`.

  Unknown keys, malformed values, and non-positive numerics each warn
  once and the key is dropped. Parsing never raises. Missing `render:`
  block returns an empty `RenderConfig` (all `None`)."""
  out = RenderConfig()
  if not fm or not isinstance(fm, dict):
    return out
  block = fm.get("render")
  if block is None:
    return out
  if not isinstance(block, dict):
    warnings.warn(
      f"frontmatter `render:` must be a mapping, got {type(block).__name__}",
      RuntimeWarning, stacklevel=2,
    )
    return out
  for key, val in block.items():
    if key not in _KNOWN_KEYS:
      warnings.warn(
        f"unknown frontmatter render key {key!r}, ignored",
        RuntimeWarning, stacklevel=2,
      )
      continue
    if key == "page":
      out.page = _parse_page(val)
    elif key == "margin":
      out.margin = _parse_margin_val(val)
    elif key == "landscape":
      out.landscape = _parse_bool(val, "landscape")
    elif key == "font_body":
      out.font_body = _parse_str(val, "font_body")
    elif key == "font_head":
      out.font_head = _parse_str(val, "font_head")
    elif key == "font_mono":
      out.font_mono = _parse_str(val, "font_mono")
    elif key == "font_size":
      out.font_size = _parse_positive_float(val, "font_size")
    elif key == "line_height":
      out.line_height = _parse_positive_float(val, "line_height")
    elif key == "img_max_h":
      out.img_max_h = _parse_positive_float(val, "img_max_h")
    elif key == "banner":
      out.banner = _parse_bool(val, "banner")
    elif key == "banner_min":
      out.banner_min = _parse_bool(val, "banner_min")
    elif key == "page_number":
      out.page_number = _parse_bool(val, "page_number")
    elif key == "lang":
      out.lang = _parse_str(val, "lang")
    elif key == "mermaid_theme":
      out.mermaid_theme = _parse_str(val, "mermaid_theme")
    elif key == "syntax_theme":
      out.syntax_theme = _parse_str(val, "syntax_theme")
  return out

#---------------------------------------------------------------------------- Value parsers

def _parse_page(val) -> PageSize|None:
  """Resolve `page:` to a `PageSize`. Only string presets accepted."""
  if not isinstance(val, str):
    warnings.warn(
      f"render.page must be a preset name string (A4/A5/A3/LETTER/LEGAL), "
      f"got {type(val).__name__}; for custom dimensions pass `width=` and "
      f"`height=` to the `md_to_pdf` call",
      RuntimeWarning, stacklevel=3,
    )
    return None
  key = val.strip().upper()
  if key not in PAGE_PRESETS:
    warnings.warn(
      f"render.page={val!r} unknown; supported: {sorted(PAGE_PRESETS)}",
      RuntimeWarning, stacklevel=3,
    )
    return None
  return PAGE_PRESETS[key]

def _parse_margin_val(val):
  """Margin: scalar or list of 2-4 positive numbers. Returns the value
  passthrough so caller can hand it to `parse_margin()`."""
  if isinstance(val, (int, float)):
    if val < 0:
      warnings.warn(f"render.margin={val} must be >= 0, ignored",
        RuntimeWarning, stacklevel=3)
      return None
    return val
  if isinstance(val, (list, tuple)):
    if not (1 <= len(val) <= 4):
      warnings.warn(
        f"render.margin must have 1-4 elements, got {len(val)}: {val}",
        RuntimeWarning, stacklevel=3,
      )
      return None
    if not all(isinstance(x, (int, float)) and x >= 0 for x in val):
      warnings.warn(f"render.margin elements must be non-negative numbers: {val}",
        RuntimeWarning, stacklevel=3)
      return None
    return list(val)
  warnings.warn(
    f"render.margin must be a number or list, got {type(val).__name__}",
    RuntimeWarning, stacklevel=3,
  )
  return None

def _parse_bool(val, key:str) -> bool|None:
  if isinstance(val, bool):
    return val
  warnings.warn(
    f"render.{key} must be true/false, got {val!r}",
    RuntimeWarning, stacklevel=3,
  )
  return None

def _parse_positive_float(val, key:str, allow_zero:bool=False) -> float|None:
  if not isinstance(val, (int, float)) or isinstance(val, bool):
    warnings.warn(
      f"render.{key} must be a number, got {val!r}",
      RuntimeWarning, stacklevel=3,
    )
    return None
  fv = float(val)
  if fv < 0 or (fv == 0 and not allow_zero):
    warnings.warn(
      f"render.{key}={fv} must be > 0",
      RuntimeWarning, stacklevel=3,
    )
    return None
  return fv

def _parse_str(val, key:str) -> str|None:
  if not isinstance(val, str) or not val.strip():
    warnings.warn(
      f"render.{key} must be a non-empty string, got {val!r}",
      RuntimeWarning, stacklevel=3,
    )
    return None
  return val.strip()

#---------------------------------------------------------------------- Style application

def build_style(
  fm: dict|None,
  caller_style: MarkdownStyle|None,
  render: RenderConfig,
) -> MarkdownStyle:
  """Build the effective `MarkdownStyle` by layering defaults < lang
  preset < frontmatter `render:` fields < caller's `style=` non-default
  fields.

  Caller's field is considered "non-default" when it differs from the
  fresh `MarkdownStyle()` default - that's how we tell apart "user passed
  this on purpose" from "user passed `MarkdownStyle()` with no overrides".
  """
  if render.lang:
    base = lang_style(render.lang)
  else:
    base = MarkdownStyle()
  # Apply frontmatter render-block overrides
  if render.font_body:
    base.body_family = render.font_body
  if render.font_head or render.font_body:
    base.head_family = render.font_head or render.font_body
  if render.font_mono:
    base.mono_family = render.font_mono
  if render.font_size is not None:
    base.body_size = render.font_size
  if render.line_height is not None:
    base.line_height = render.line_height
  if render.img_max_h is not None:
    base.image_max_h = render.img_max_h
  if render.mermaid_theme is not None:
    base.mermaid_theme = render.mermaid_theme
  if render.syntax_theme is not None:
    base.syntax_theme = render.syntax_theme
  if render.banner is not None:
    base.banner_render = render.banner
  if render.banner_min is not None:
    base.mini_banner_render = render.banner_min
  if render.page_number is not None:
    # `True` keeps the current (possibly lang-derived) label; `False`
    # disables page numbers entirely.
    if render.page_number is False:
      base.page_number_label = None
  # Caller's explicit fields win on top
  if caller_style is not None:
    default = MarkdownStyle()
    for f in fields(caller_style):
      cv = getattr(caller_style, f.name)
      dv = getattr(default, f.name)
      if cv != dv:
        setattr(base, f.name, cv)
  return base

#---------------------------------------------------------------- Top-level deprecation

def warn_top_level_landscape(fm:dict|None) -> None:
  """Hard break: `landscape:` at frontmatter top-level used to flip the
  page; it must now live under `render:`. Warn loudly when detected so
  users see the migration path; the value is NOT honored."""
  if not fm or not isinstance(fm, dict):
    return
  if "landscape" in fm:
    warnings.warn(
      "top-level frontmatter `landscape:` is no longer honored - move it "
      "under `render:` block (`render.landscape: true`). Ignoring.",
      RuntimeWarning, stacklevel=3,
    )
