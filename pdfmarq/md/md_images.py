# pdfmarq/md/md_images.py

"""
Image metadata + sizing rules.

Distilled from how GitHub, VSCode, MkDocs, Pandoc, LaTeX and Typst handle
images in markdown-rendered documents:

- Natural size at metadata-DPI _(fallback 96)_, never upscale automatically.
- **Block raster**: fit page width, capped by `image_max_h`. Pandoc rule.
- **Block SVG**: fill page width. Vector scales for free; small embedded SVG
  schematics typically want page width regardless of intrinsic dims. Browser
  also does this for SVGs without intrinsic dims (replaced-element fallback).
- **Inline (mid-paragraph)**: cap at `inline_image_max_h` (LaTeX `2ex` idiom).
- **Table cell**: render at natural size capped by column width and
  `image_max_h`. The column-min contribution is separately capped by
  `cell_image_max_w` so a giant image cannot blow up the table layout. CSS
  auto-layout would otherwise treat the image's intrinsic pixel width as a
  hard floor on column width - that's the source of the "huge icon in cell"
  bug. Dimensionless SVGs in cells render at inline cap (icon size).

Author overrides: `width=` and `height=` from token attrs are honored. Units:
`px` _(default for bare numbers)_, `pt`, `mm`, `cm`, `in`, `inch`, `%`. The
percentage resolves against the available width in the rendering context
_(page or cell)_.
"""

import os
from dataclasses import dataclass
from ..constants import MM_TO_PT

#-------------------------------------------------------------------------------- ImageInfo

@dataclass
class ImageInfo:
  """Resolved metadata + author hints for one image."""
  src: str
  is_svg: bool
  nat_w_mm: float  # natural width in mm at metadata-DPI (or 96 fallback)
  nat_h_mm: float  # natural height in mm
  dimensionless: bool = False  # True only when SVG has no width/height/viewBox
  explicit_w_mm: float|None = None # author-specified width (DSL `w=` or `scale=`)
  explicit_h_mm: float|None = None # author-specified height (DSL `h=` or `scale=`)
  dsl_max_w_mm: float|None = None  # DSL `max_w=` soft cap
  dsl_max_h_mm: float|None = None  # DSL `max_h=` soft cap
  align: str|None = None  # DSL `align=L/C/R` block-level horizontal alignment
  alt: str = ""

#--------------------------------------------------------------------------- Loaders

def load_image_info(
  src: str,
  attrs: dict|None = None,
  alt: str = "",
  default_dpi: int = 96,
) -> ImageInfo|None:
  """Read image metadata + parse author overrides. Returns `None` if the
  file cannot be opened.

  Author overrides come from two channels:
    - `attrs['title']`: the markdown image title `![alt](src "DSL")` parsed
      as space-separated `key=value` pairs (`w h max_w max_h scale align`).
    - `attrs['width']`/`attrs['height']`: plugin-set attrs (markdown-it-attrs
      style) honored for back-compat. DSL wins when both present.
  """
  if not src or not os.path.exists(src):
    return None
  is_svg = src.lower().endswith(".svg")
  if is_svg:
    dims = _load_svg_dims(src)
  else:
    dims = _load_raster_dims(src, default_dpi)
  if dims is None:
    return None
  nat_w_mm, nat_h_mm, dimensionless = dims
  # Legacy plugin attrs first - DSL from title overrides if both are set.
  ew, eh = _parse_attrs_dims(attrs, nat_w_mm, nat_h_mm)
  dsl_max_w = dsl_max_h = None
  align = None
  if attrs:
    title = (attrs.get("title") if isinstance(attrs, dict)
      else dict(attrs).get("title"))
    dsl = parse_image_dsl(title)
    if dsl.is_dsl:
      # scale wins absolutely; w/h override flow; max_* apply as soft caps.
      if dsl.scale is not None:
        ew = nat_w_mm * dsl.scale
        eh = nat_h_mm * dsl.scale
      else:
        if dsl.exact_w_mm is not None: ew = dsl.exact_w_mm
        if dsl.exact_h_mm is not None: eh = dsl.exact_h_mm
      dsl_max_w = dsl.max_w_mm
      dsl_max_h = dsl.max_h_mm
      align = dsl.align
  return ImageInfo(
    src=src, is_svg=is_svg,
    nat_w_mm=nat_w_mm, nat_h_mm=nat_h_mm,
    dimensionless=dimensionless,
    explicit_w_mm=ew, explicit_h_mm=eh,
    dsl_max_w_mm=dsl_max_w, dsl_max_h_mm=dsl_max_h,
    align=align, alt=alt,
  )

def _load_svg_dims(src:str) -> tuple[float, float, bool]|None:
  """Returns `(w_mm, h_mm, dimensionless)`. `dimensionless=True` when the
  SVG declares neither intrinsic dims nor viewBox - render context decides
  the size."""
  try:
    from svglib.svglib import svg2rlg
    d = svg2rlg(src)
    if d is None:
      return None
    w, h = float(d.width or 0), float(d.height or 0)
    if w <= 0 or h <= 0:
      return 1.0, 1.0, True  # dimensionless - aspect derived from context
    return w / MM_TO_PT, h / MM_TO_PT, False
  except Exception:
    return None

def _load_raster_dims(src:str, default_dpi:int) -> tuple[float, float, bool]|None:
  """Returns `(w_mm, h_mm, False)`. DPI is read from PIL `info["dpi"]`
  _(present in PNG/JPEG metadata as pHYs/JFIF resolution)_, fallback to
  `default_dpi`."""
  try:
    from PIL import Image as PILImage
    with PILImage.open(src) as im:
      px_w, px_h = im.size
      meta = im.info.get("dpi")
    real_dpi = meta[0] if isinstance(meta, tuple) and meta[0] else default_dpi
    return px_w * 25.4 / real_dpi, px_h * 25.4 / real_dpi, False
  except Exception:
    return None

#-------------------------------------------------------------------------------- Title DSL

@dataclass
class ImageDSL:
  """Parsed `![alt](src "key=value ...")` title DSL.

  When `is_dsl=False` the title was either empty or contained no `=` token -
  treat it as opaque description and do not apply any overrides. Mixed
  titles (some `key=value`, some plain) parse the DSL bits and warn on
  the rest.
  """
  exact_w_mm: float|None = None
  exact_h_mm: float|None = None
  max_w_mm: float|None = None
  max_h_mm: float|None = None
  scale: float|None = None
  align: str|None = None
  is_dsl: bool = False

_DSL_NUMERIC_KEYS = {"w", "h", "max_w", "max_h", "scale"}
_DSL_ALIGN_VALUES = {"L", "C", "R"}

def parse_image_dsl(title:str|None) -> ImageDSL:
  """Parse `key=value` space-separated DSL from an image title slot.

  Supported keys (case-insensitive):
    `w`, `h`         exact dimension in mm
    `max_w`, `max_h` soft cap in mm (image only shrinks, never upscales)
    `scale`          float multiplier on natural size (absolute priority -
                     suppresses w/h/max_* when present)
    `align`          `L` / `C` / `R` block-level horizontal alignment

  When the title contains no `=` token at all, returns `is_dsl=False` so
  the title is silently ignored (legacy "caption" titles keep working).
  Unknown keys, malformed values, and non-positive numerics are warned
  and individually ignored - parsing never raises.
  """
  out = ImageDSL()
  if not title or not title.strip():
    return out
  tokens = title.split()
  if not any("=" in t for t in tokens):
    return out  # opaque description, no DSL parsing
  out.is_dsl = True
  import warnings
  for tok in tokens:
    if "=" not in tok:
      warnings.warn(
        f"image title token {tok!r} is not `key=value`, ignored",
        RuntimeWarning, stacklevel=2,
      )
      continue
    key, _, val = tok.partition("=")
    key = key.strip().lower()
    val = val.strip()
    if key == "align":
      v = val.upper()
      if v in _DSL_ALIGN_VALUES:
        out.align = v
      else:
        warnings.warn(
          f"image title align={val!r} must be L/C/R, ignored",
          RuntimeWarning, stacklevel=2,
        )
      continue
    if key not in _DSL_NUMERIC_KEYS:
      warnings.warn(
        f"unknown image title key {key!r}, ignored",
        RuntimeWarning, stacklevel=2,
      )
      continue
    try:
      fv = float(val)
    except ValueError:
      warnings.warn(
        f"image title {key}={val!r} not a number, ignored",
        RuntimeWarning, stacklevel=2,
      )
      continue
    if fv <= 0:
      warnings.warn(
        f"image title {key}={fv} must be > 0, ignored",
        RuntimeWarning, stacklevel=2,
      )
      continue
    if key == "w": out.exact_w_mm = fv
    elif key == "h": out.exact_h_mm = fv
    elif key == "max_w": out.max_w_mm = fv
    elif key == "max_h": out.max_h_mm = fv
    elif key == "scale": out.scale = fv
  return out

#--------------------------------------------------------------------- Attribute parsing

def _parse_attrs_dims(attrs, nat_w_mm:float, nat_h_mm:float):
  """Extract `width`/`height` from token attrs (dict, list-of-pairs, or
  None). Returns `(w_mm or None, h_mm or None)`."""
  if not attrs:
    return None, None
  d = dict(attrs) if not isinstance(attrs, dict) else attrs
  return _parse_dim(d.get("width"), nat_w_mm), _parse_dim(d.get("height"), nat_h_mm)

_UNITS = {
  "mm": 1.0, "cm": 10.0, "in": 25.4, "inch": 25.4,
  "pt": 25.4 / 72, "px": 25.4 / 96,
}

def _parse_dim(val, ref_mm:float) -> float|None:
  """Parse `'200'`, `'200px'`, `'5cm'`, `'50%'` etc. into mm. Bare numbers
  are interpreted as pixels _(matches HTML `<img width=200>` semantics)_.
  Percentages resolve against `ref_mm`. Returns `None` on parse failure."""
  if val is None:
    return None
  s = str(val).strip().lower()
  if not s:
    return None
  if s.endswith("%"):
    try: return ref_mm * float(s[:-1]) / 100
    except ValueError: return None
  for unit, factor in _UNITS.items():
    if s.endswith(unit):
      try: return float(s[:-len(unit)].strip()) * factor
      except ValueError: return None
  try: return float(s) * _UNITS["px"]
  except ValueError: return None

#---------------------------------------------------------------------- Sizing rules

def size_block(
  info: ImageInfo,
  page_w_mm: float,
  max_h_mm: float,
  svg_fill_width: bool = True,
) -> tuple[float, float]:
  """Size a paragraph-level (block) image.

  - Author override (`w`/`h`/`scale`) wins; final size still clamped to
    `(page_w_mm, max_h_mm)` so explicit dimensions can't run off-page.
  - **Raster**: natural size capped at page width and `max_h_mm`. Never upscales.
  - **SVG with `svg_fill_width=True`** _(default)_: fills page width, height
    derived from aspect ratio. **No `max_h_mm` cap** - SVGs are vector,
    scale-free, and treating them like rasters here defeats the point. Set
    `svg_fill_width=False` to apply raster rules to SVGs as well.
  - DSL `max_w`/`max_h` apply as additional soft caps on top of the page
    constraints (effective cap = `min(style_cap, dsl_cap)`).
  """
  # DSL soft caps narrow the effective constraints. `min` works because
  # both are upper bounds; user explicitly asks for a smaller cap.
  if info.dsl_max_w_mm is not None:
    page_w_mm = min(page_w_mm, info.dsl_max_w_mm)
  if info.dsl_max_h_mm is not None:
    max_h_mm = min(max_h_mm, info.dsl_max_h_mm) if max_h_mm > 0 else info.dsl_max_h_mm
  if info.explicit_w_mm or info.explicit_h_mm:
    return _explicit(info, page_w_mm, max_h_mm)
  if info.is_svg:
    if info.dimensionless or svg_fill_width:
      ar = info.nat_h_mm / info.nat_w_mm if info.nat_w_mm > 0 else 1.0
      return page_w_mm, page_w_mm * ar
  return _clamp_no_upscale(info.nat_w_mm, info.nat_h_mm, page_w_mm, max_h_mm)

def size_inline(
  info: ImageInfo,
  inline_cap_mm: float,
) -> tuple[float, float]:
  """Size an inline mid-paragraph image. Always height-capped at
  `inline_cap_mm` (LaTeX `height=2ex` idiom). Width scales proportionally.
  DSL `max_w`/`max_h` further narrow the cap; `align` is ignored for
  inline (text-anchored)."""
  cap_w = inline_cap_mm * 6
  cap_h = inline_cap_mm * 2
  if info.dsl_max_w_mm is not None: cap_w = min(cap_w, info.dsl_max_w_mm)
  if info.dsl_max_h_mm is not None: cap_h = min(cap_h, info.dsl_max_h_mm)
  if info.explicit_w_mm or info.explicit_h_mm:
    return _explicit(info, cap_w, cap_h)
  effective_cap_h = inline_cap_mm
  if info.dsl_max_h_mm is not None:
    effective_cap_h = min(effective_cap_h, info.dsl_max_h_mm)
  nw, nh = info.nat_w_mm, info.nat_h_mm
  if nh <= 0:
    return effective_cap_h, effective_cap_h
  if nh > effective_cap_h:
    return nw * (effective_cap_h / nh), effective_cap_h
  return nw, nh

def cell_intrinsic_w_mm(
  info: ImageInfo,
  inline_cap_mm: float,
  cell_image_max_w_mm: float,
  cell_image_scale: float = 0.5,
) -> tuple[float, float]:
  """Width range an image cell contributes to HTML auto-layout.

  Returns `(col_min, col_max)`:

  - **col_max**: `min(natural × cell_image_scale, cell_image_max_w_mm)`.
    Half-natural is a heuristic that works across both common table styles:
    icon-grids (small natural like 50mm symbols → render ~25mm) and
    procedure tables (large natural like 100mm photos → render ~50mm). The
    image-to-text visual ratio ends up roughly 1:2-1:3 in both cases,
    matching how GitHub renders tables with `td img { max-width: 100% }`
    after auto-layout pressures the column.
  - **col_min**: `max(inline_cap, 60% × col_max)` - image cells participate
    in overflow shrink without collapsing to icon scale.

  Explicit author width wins, clamped to absolute cap only.
  Dimensionless SVG = inline cap (icon).
  """
  if info.explicit_w_mm:
    v = min(info.explicit_w_mm, cell_image_max_w_mm)
    return v, v
  if info.is_svg and info.dimensionless:
    return inline_cap_mm, inline_cap_mm
  col_max = min(info.nat_w_mm * cell_image_scale, cell_image_max_w_mm)
  col_min = max(inline_cap_mm, col_max * 0.6)
  return col_min, col_max

def size_cell(
  info: ImageInfo,
  cell_w_mm: float,
  max_h_mm: float,
  inline_cap_mm: float,
  cell_image_max_w_mm: float = 60,
  cell_image_scale: float = 0.5,
) -> tuple[float, float]:
  """Size an image inside a table cell.

  Render at `min(natural × cell_image_scale, cell_image_max_w_mm, cell_w_mm,
  max_h_mm)`. Never upscales (unlike block SVG) - a cell-filling SVG looks
  broken inside a multi-column table. The scale + abs cap mirror the
  intrinsic-width logic so that when a mixed col gets stretched wider by
  long text, the image doesn't grow to fill - it stays at its preferred
  scaled size. Dimensionless SVGs render at inline cap (icon)."""
  if info.explicit_w_mm or info.explicit_h_mm:
    return _explicit(info, cell_w_mm, max_h_mm)
  if info.is_svg and info.dimensionless:
    return inline_cap_mm, inline_cap_mm
  preferred_w = min(info.nat_w_mm * cell_image_scale, cell_image_max_w_mm)
  preferred_w = min(preferred_w, cell_w_mm)
  if preferred_w >= info.nat_w_mm:
    return _clamp_no_upscale(info.nat_w_mm, info.nat_h_mm, cell_w_mm, max_h_mm)
  s_factor = preferred_w / info.nat_w_mm
  w = preferred_w
  h = info.nat_h_mm * s_factor
  if max_h_mm > 0 and h > max_h_mm:
    s2 = max_h_mm / h
    w *= s2
    h = max_h_mm
  return w, h

#--------------------------------------------------------------------------- Helpers

def _clamp_no_upscale(
  nw:float, nh:float, max_w:float, max_h:float,
) -> tuple[float, float]:
  """Scale uniformly DOWN to fit `(max_w, max_h)`. Returns natural size when
  it already fits."""
  if nw <= 0 or nh <= 0:
    return nw, nh
  sw = max_w / nw if max_w > 0 and nw > max_w else 1.0
  sh = max_h / nh if max_h > 0 and nh > max_h else 1.0
  s = min(sw, sh)
  return nw * s, nh * s

def _clamp(w:float, h:float, max_w:float, max_h:float) -> tuple[float, float]:
  """Scale uniformly to fit `(max_w, max_h)`. May upscale or downscale."""
  if w <= 0 or h <= 0 or (max_w <= 0 and max_h <= 0):
    return w, h
  sw = max_w / w if max_w > 0 else float("inf")
  sh = max_h / h if max_h > 0 else float("inf")
  s = min(sw, sh)
  return w * s, h * s

def _explicit(
  info: ImageInfo, max_w: float, max_h: float,
) -> tuple[float, float]:
  """Resolve explicit width/height; missing dimension comes from natural
  aspect ratio. Final size still clamped to `(max_w, max_h)`."""
  ew, eh = info.explicit_w_mm, info.explicit_h_mm
  nw, nh = info.nat_w_mm, info.nat_h_mm
  if ew and eh:
    w, h = ew, eh
  elif ew:
    w = ew
    h = nh * (ew / nw) if nw > 0 else ew
  else:
    h = eh
    w = nw * (eh / nh) if nh > 0 else eh
  return _clamp_no_upscale(w, h, max_w, max_h)
