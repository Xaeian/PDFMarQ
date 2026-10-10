# pdfmarq/md/markdown_style.py

"""GitHub-flavored markdown visual style."""
from dataclasses import dataclass, field

#-------------------------------------------------------------------------- Callout palette default

def _default_callout_colors() -> dict:
  """GitHub-style callout colors per type (border, text/icon).
  Each entry: lowercase type → `(border_rgb, text_rgb)` in 0..1 range.
  """
  return {
    "note": ((0.035, 0.41, 0.855), (0.035, 0.41, 0.855)), # blue
    "tip": ((0.12, 0.53, 0.24), (0.12, 0.53, 0.24)), # green
    "important": ((0.51, 0.31, 0.87), (0.51, 0.31, 0.87)), # purple
    "warning": ((0.60, 0.40, 0.0), (0.60, 0.40, 0.0)), # amber
    "caution": ((0.81, 0.13, 0.18), (0.81, 0.13, 0.18)), # red
  }

#------------------------------------------------------------------------------------ MarkdownStyle

@dataclass
class MarkdownStyle:
  """Visual style for markdown rendering, matching GitHub light theme.

  The renderer swaps default families for DejaVu Sans and DejaVu Sans Mono,
  found in the system or in matplotlib, which the `[md]` extra installs.
  DejaVu covers Polish and the rest of Latin Extended-A.
  Without either, `Vera` stays: Bitstream Vera bundled with reportlab, which has no ą ę ś ź ż ń.
  """
  # Font families
  font_body: str = "Vera"
  font_head: str = "Vera"
  font_mono: str = "Courier" # PDF core 14, no TTF needed

  # Modes (Vera has dedicated Italic / BoldItalic TTFs)
  body_mode: str = "Regular"
  bold_mode: str = "Bold"
  italic_mode: str = "Italic"
  bold_italic_mode: str = "BoldItalic"
  head_mode: str = "Bold"
  mono_mode: str = "Regular"
  heavy_mode: str = "Black" # `**bold**` inside bold base escalates to this

  # Font sizes (pt). A heading size of `None` follows `body_size`.
  body_size: float = 11
  h1_size: float|None = 20
  h2_size: float|None = 16
  h3_size: float|None = 13
  h4_size: float|None = 11
  h5_size: float|None = 11
  h6_size: float|None = 11
  mono_size: float = 9.5
  code_block_size: float = 9
  # Table cell font size in pt.
  # `None` derives it one step below the body on the typographic ladder, via `smaller_size`:
  # 11→10, 12→11, 14→12, ...
  table_size: float|None = None

  # Colors (rgb 0-1) - GitHub light theme
  body_color: tuple = (0.09, 0.11, 0.13) # #1f2328
  head_color: tuple = (0.09, 0.11, 0.13)
  muted_color: tuple = (0.40, 0.44, 0.50)
  link_color: tuple = (0.03, 0.41, 0.85) # #0969da
  code_inline_color: tuple = (0.09, 0.11, 0.13)
  code_inline_bg: tuple = (0.96, 0.97, 0.98) # same as code_block_bg
  code_block_bg: tuple = (0.96, 0.97, 0.98) # #f6f8fa
  code_block_border: tuple = (0.82, 0.84, 0.87) # #d0d7de GitHub border
  quote_border: tuple = (0.82, 0.84, 0.87)
  hr_color: tuple = (0.82, 0.84, 0.87)
  table_header_bg: tuple = (0.96, 0.97, 0.98)
  table_border: tuple = (0.82, 0.84, 0.87)
  table_zebra_bg: tuple = (0.985, 0.99, 0.995) # very subtle - lighter than header_bg
  # `==text==` highlight background.
  # Accepts either an RGB tuple or a named highlight color matching Word:
  # `yellow` / `green` / `cyan` / `magenta` / `blue` / `red` / `grey`.
  mark_bg: tuple|str = "yellow"

  # Spacing (mm) - tightened for GitHub feel
  line_height: float = 1.4 # ratio of font size
  para_gap: float = 3 # mm between paragraphs
  head_gap_top: float = 3 # mm above headings
  head_gap_bot: float = 1.5 # mm below headings
  list_indent: float = 6 # mm per list level
  list_gap: float = 0.5 # mm between items (tight)
  bullet_radius: float = 0.7 # mm - solid disc for bullets
  code_block_pad: float = 3  # mm inside code blocks
  code_block_gap: float = 3  # mm after code blocks
  code_block_radius: float = 2 # mm corner radius (GitHub: 6pt ≈ 2.1mm)
  syntax_theme: str = "default" # pygments style name for highlighting
  # Image sizing rules - see `size_block`, `size_inline` and `size_cell` for the full algorithm
  image_max_h: float = 120 # mm - cap image height (block + table cells)
  image_dpi: int = 96 # fallback DPI for rasters without metadata
  image_min_dpi: int = 150 # block raster fills page width down to this; 0 = always
  inline_image_max_h: float = 5.5 # mm - cap inline icons, at `body_size`
  cell_image_max_w: float = 60 # mm - absolute cap on col_max
  cell_image_scale: float = 0.5 # render image cells at this fraction of natural
  cell_image_balance_bias: float = 0.7 # target image_h = text_h × bias (<1 = smaller image)
  svg_block_fill_width: bool = True # SVG block images fill page width
  quote_pad: float = 5 # mm left indent
  quote_border_w: float = 1 # mm thickness of left bar
  hr_thick: float = 0.3 # pt line width
  underline_thick: float = 0.3 # pt
  table_pad: float = 1.5  # mm extra vertical padding inside cells
  table_h_pad: float = 2  # mm horizontal cell padding
  table_border_thick: float = 0.3 # pt - table line thickness
  table_header_thick: float = 0.5 # pt - thicker line under header row

  # Mermaid diagrams (```mermaid fenced blocks).
  # Rendered via local `mmdc` CLI (Node.js) when available,
  # falling back to mermaid.ink HTTP service.
  # Set `mermaid_enable=False` to skip rendering and emit the source as a plain code block.
  mermaid_enable: bool = True
  mermaid_theme: str = "default"
  mermaid_background: str = "transparent"
  mermaid_scale: float = 3
  mermaid_cli: str = "mmdc"
  # Allow the mermaid.ink HTTP fallback when `mmdc` is not installed.
  # It uploads the diagram source to a public third-party service and warns once per process.
  # Set `False` to keep rendering strictly local (diagrams then fall back to a plain code block).
  mermaid_remote: bool = True

  # `False` leaves `$...$` as plain text.
  math_enable: bool = True
  # Math formulas (matplotlib mathtext → SVG → vector in PDF).
  # `math_fontset` accepts either a matplotlib preset or a font family name.
  # Presets: `"stix"`, `"stixsans"`, `"cm"`, `"dejavusans"`, `"dejavuserif"`.
  # A family name follows the standard `fonts/<Family>/<Family>-<Mode>.ttf` convention:
  # the loader registers Regular/Italic/Bold from that folder.
  # Default is `"stixsans"` - sans-serif with real italic and full unicode math symbols,
  # bundled with matplotlib (no setup).
  math_fontset: str = "stixsans"
  # Which renderer draws the formulas.
  # `auto` prefers MathJax (all of LaTeX math, New Computer Modern glyphs)
  # when Node and its packages are installed.
  # Otherwise it falls back to matplotlib mathtext, which needs no Node but understands a subset.
  # `mathtext` pins the fallback, `mathjax` refuses it.
  # `math_fontset` applies to mathtext only - MathJax brings its own font.
  math_engine: str = "auto"
  # Typeface MathJax sets formulas in, from the font packages it ships.
  # Serif: `newcm` _(New Computer Modern, the modern LaTeX look)_,
  # `stix2`, `modern`, `termes`, `pagella`. Sans: `dejavu`.
  # Each needs its own npm package installed: `@mathjax/mathjax-<font>-font`.
  # Ignored by the mathtext engine, which reads `math_fontset` instead.
  math_font: str = "newcm"
  math_block_gap: float = 3.5  # mm below a block equation; above, the previous block's gap counts
  math_numbering: bool = True  # auto (1), (2), (3) for block math

  # Layout flags
  h1_underline: bool = True
  h2_underline: bool = True
  table_zebra: bool = True
  # Paragraphs set flush to both edges, spaces tightening to take one more word where they can.
  # The last line and a line a hard break ends stay left.
  justify: bool = False
  # Language whose hyphenation patterns split words at the end of a paragraph line, as `pl`.
  # `None` keeps words whole. Needs `pyphen`.
  hyphenate: str|None = None
  # `True` moves a paragraph or list that does not fit here to the next frame, whole.
  # `False` lets text flow, so columns end evenly:
  # a paragraph splits with at least two lines on each side, a list goes item by item,
  # and a heading reserves room only for itself and three lines of the text after it.
  keep_together: bool = True

  # GitHub callout titles (`> [!NOTE]`, `> [!TIP]`, ...).
  # Override for localization or custom wording. Color + icon stay constant per type.
  callout_label_note: str = "Note"
  callout_label_tip: str = "Tip"
  callout_label_important: str = "Important"
  callout_label_warning: str = "Warning"
  callout_label_caution: str = "Caution"
  # Callout palette (border + text colors per type).
  # Lowercase type → tuple `(border_rgb, text_rgb)` in 0..1 range.
  callout_colors: dict = field(default_factory=_default_callout_colors)

  # `None` emits a thin HR above footnotes; the smaller font signals reference matter.
  # Set to a string (e.g. `"References"`) to add an H2 heading above.
  footnote_label: str|None = None

  # Local-link handling. `[x](file.md)` has no scheme and no `#` prefix.
  # Without `link_root`, the link renders styled (blue underline) but is not clickable:
  # a PDF cannot follow a relative filesystem path.
  # With `link_root`, hrefs resolve to:
  #   absolute `/x/y` → `{link_root}/x/y`
  #   relative `file.md` → `{link_root}/{link_base}/file.md`
  link_root: str|None = None
  link_base: str = ""
  # h1 defaults to extra top spacing, not a hard page break.
  h1_page_break: bool = False
