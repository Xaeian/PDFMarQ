# pdfmarq/md/markdown_style.py

"""GitHub-flavored markdown visual style."""
from dataclasses import dataclass, field

#-------------------------------------------------------------------------- Callout palette default

def _default_callout_colors() -> dict:
  """GitHub-style callout colors per type (border, text/icon).
  Each entry: lowercase type → `(border_rgb, text_rgb)` in 0..1 range.
  """
  return {
    "note": ((0.035, 0.41, 0.855), (0.035, 0.41, 0.855)),  # blue
    "tip": ((0.12, 0.53, 0.24), (0.12, 0.53, 0.24)),  # green
    "important": ((0.51, 0.31, 0.87), (0.51, 0.31, 0.87)),  # purple
    "warning": ((0.60, 0.40, 0.0), (0.60, 0.40, 0.0)),  # amber
    "caution": ((0.81, 0.13, 0.18), (0.81, 0.13, 0.18)),  # red
  }

#----------------------------------------------------------------------------------- Status palette

def _default_status_colors() -> dict:
  """Default badge colors for document status.
  Each entry maps lowercase status name to (bg_rgb, text_rgb) in 0..1 range.
  """
  return {
    "draft": ((0.85, 0.87, 0.92), (0.30, 0.34, 0.45)),  # cool blue-grey
    "review": ((1.00, 0.95, 0.78), (0.62, 0.40, 0.05)),  # amber
    "approved": ((0.86, 0.96, 0.87), (0.10, 0.45, 0.18)),  # green
    "deprecated": ((1.00, 0.88, 0.85), (0.74, 0.20, 0.15)),  # red
    "archived": ((0.92, 0.87, 0.96), (0.45, 0.25, 0.55)),  # violet
  }

#------------------------------------------------------------------------------ Sign labels default

def _default_sign_labels() -> dict:
  """Standard signing scenarios: name → one label per line."""
  return {
    "signature": ["Signature"],
    "approval": ["Prepared by", "Approved by"],
    "contract": ["Client", "Contractor"],
  }

#------------------------------------------------------------------------------------ MarkdownStyle

@dataclass
class MarkdownStyle:
  """Visual style for markdown rendering, matching GitHub light theme.

  Default fonts use **Vera Sans** (Bitstream Vera) bundled with reportlab.
  Vera covers most of Latin Extended-A but is missing some Polish glyphs
  (ą, ę, ń, ś, ź, ż). For full Polish coverage register a TTF via
  `pdf.fonts.register()` and set `font_body` to that family.
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

  # Font sizes (pt).
  body_size: float = 11
  h1_size: float = 20
  h2_size: float = 16
  h3_size: float = 13
  h4_size: float = 11
  h5_size: float = 11
  h6_size: float = 11
  mono_size: float = 9.5
  code_block_size: float = 9
  # Table cell font size in pt. `None` (default) auto-derives one step
  # below body on the typographic ladder (11→10, 12→11, 14→12, ...) via
  # `smaller_size`. Set explicitly to override - mirrors how
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
  quote_text: tuple = (0.40, 0.44, 0.50)
  hr_color: tuple = (0.82, 0.84, 0.87)
  table_header_bg: tuple = (0.96, 0.97, 0.98)
  table_border: tuple = (0.82, 0.84, 0.87)
  table_zebra_bg: tuple = (0.985, 0.99, 0.995) # very subtle - lighter than header_bg
  # `==text==` highlight background. Accepts either an RGB tuple or a
  # named highlight color matching Word: `yellow` / `green` / `cyan` /
  # `magenta` / `blue` / `red` / `grey`. Default `"yellow"` matches
  mark_bg: tuple|str = "yellow"

  # Spacing (mm) - tightened for GitHub feel
  line_height: float = 1.4  # ratio of font size
  para_gap: float = 3  # mm between paragraphs
  head_gap_top: float = 3  # mm above headings
  head_gap_bot: float = 1.5  # mm below headings
  list_indent: float = 6  # mm per list level
  list_gap: float = 0.5  # mm between items (tight)
  bullet_radius: float = 0.7  # mm - solid disc for bullets
  code_block_pad: float = 3  # mm inside code blocks
  code_block_gap: float = 3  # mm after code blocks
  code_block_radius: float = 2  # mm corner radius (GitHub: 6pt ≈ 2.1mm)
  syntax_theme: str = "default"  # pygments style name for highlighting
  # Image sizing rules - see `md_images.py` for the full algorithm
  image_max_h: float = 120  # mm - cap image height (block + table cells)
  image_dpi: int = 96  # fallback DPI for rasters without metadata
  inline_image_max_h: float = 5.5  # mm - cap inline mid-paragraph icons (~2ex @ 11pt)
  cell_image_max_w: float = 60  # mm - absolute cap on col_max
  cell_image_scale: float = 0.5  # render image cells at this fraction of natural
  cell_image_balance_bias: float = 0.7  # target image_h = text_h × bias (<1 = smaller image)
  svg_block_fill_width: bool = True  # SVG block images fill page width
  quote_pad: float = 5  # mm left indent
  quote_border_w: float = 1  # mm thickness of left bar
  hr_thick: float = 0.3  # pt line width
  underline_thick: float = 0.3  # pt
  table_pad: float = 1.5  # mm extra vertical padding inside cells
  table_h_pad: float = 2  # mm horizontal cell padding
  table_border_thick: float = 0.3 # pt - table line thickness
  table_header_thick: float = 0.5 # pt - thicker line under header row

  # Mermaid diagrams (```mermaid fenced blocks). Rendered via local `mmdc`
  # CLI (Node.js) when available, falling back to mermaid.ink HTTP service.
  # Set `mermaid_enable=False` to skip rendering and emit the source as a
  # plain code block.
  mermaid_enable: bool = True
  mermaid_theme: str = "default"
  mermaid_background: str = "transparent"
  mermaid_scale: float = 3
  mermaid_cli: str = "mmdc"

  # Math formulas (matplotlib mathtext → SVG → vector in PDF).
  # `math_fontset` accepts either a matplotlib preset (`"stix"`, `"stixsans"`,
  # `"cm"`, `"dejavusans"`, `"dejavuserif"`) or a font family name following
  # the standard `fonts/<Family>/<Family>-<Mode>.ttf` convention. When a
  # family name is given, the loader registers Regular/Italic/Bold from
  # that folder. Default is `"stixsans"` - sans-serif with real italic and
  # full unicode math symbols, bundled with matplotlib (no setup).
  math_fontset: str = "stixsans"
  math_block_gap: float = 3  # mm above/below block equations
  math_numbering: bool = True  # auto (1), (2), (3) for block math

  # Layout flags
  h1_underline: bool = True
  h2_underline: bool = True
  table_zebra: bool = True

  # YAML frontmatter (`---\n...\n---`) is rendered as a header layout when
  # present. Set `banner=False` to parse but skip rendering.
  banner: bool = True
  # Drop a leading `# title` that duplicates the frontmatter title (only
  # when the banner was rendered, to avoid showing the title twice).
  skip_dup_title: bool = True
  # Compact header on pages 2+ (code | title | page N/M). Disable for
  # single-page-style documents.
  banner_compact: bool = True
  # strftime syntax. ISO `%Y-%m-%d` (default), PL `%d.%m.%Y`, long `%d %B %Y`.
  date_format: str = "%Y-%m-%d"
  # Page number prefix; `None` disables footer entirely. Localize freely.
  page_number_label: str|None = "Page"
  # `Page X / Y` vs just `Page X`.
  page_number_total: bool = True

  # Frontmatter header layout (mm)
  banner_pad_top: float = 0  # mm above header block (start near top)
  banner_pad_bot: float = 3  # mm below header block before body
  banner_logo_max_h: float = 50  # mm - cap on logo height (page 1, big left column)
  banner_logo_max_w: float = 60  # mm - cap on logo width; overrides height if aspect wide
  banner_title_size: float = 20 # pt - main title
  banner_id_size: float = 9  # pt - document id
  banner_version_size: float = 9  # pt - version
  banner_meta_size: float = 9  # pt - author/date/entity text
  banner_rule: float = 0.3  # pt - matches markdown h1/h2 underlines
  # Compact banner on continuation pages
  banner_compact_logo_max_h: float = 12  # mm - cap on compact-banner logo height (2 lines tall)
  banner_compact_logo_max_w: float = 24  # mm - cap on compact-banner logo width
  banner_compact_size: float = 10  # pt - text size in compact-banner
  banner_compact_top: float = 12  # mm - distance from page top
  banner_compact_gap: float = 8  # mm - gap between compact-banner line and content
  # Signing lines at the very end, independent of `banner`. `True` or a
  # `sign_labels` scenario draws its labels; a list draws custom ones verbatim.
  sign: bool|str|list = False
  sign_labels: dict = field(default_factory=_default_sign_labels)
  sign_gap: float = 25  # mm - blank space above the line, for the handwriting
  sign_w: float = 70  # mm - width of one line
  sign_size: float = 9  # pt - label
  # Status badge colors (background, text). Keys must be lowercase.
  banner_status_colors: dict = field(default_factory=_default_status_colors)
  # Frontmatter labels, shown as `"{label}: {value}"`. Override for localization.
  banner_label_author: str = "Author"
  banner_label_created: str = "Created"
  banner_label_updated: str = "Updated"
  # GitHub callout titles (`> [!NOTE]`, `> [!TIP]`, ...). Override for
  # localization or custom wording. Color + icon stay constant per type.
  callout_label_note: str = "Note"
  callout_label_tip: str = "Tip"
  callout_label_important: str = "Important"
  callout_label_warning: str = "Warning"
  callout_label_caution: str = "Caution"
  # Callout palette (border + text colors per type). Lowercase type → tuple
  # `(border_rgb, text_rgb)` in 0..1 range.
  callout_colors: dict = field(default_factory=_default_callout_colors)

  # `None` emits a thin HR above footnotes; the smaller font signals reference
  # matter. Set to a string (e.g. `"References"`) to add an H2 heading above.
  footnote_label: str|None = None

  # Local-link handling. `[x](file.md)` has no schema and no `#` prefix.
  # Without `link_root`, the link renders styled (blue underline) but is
  # not clickable - a PDF cannot follow a relative filesystem path.
  # With `link_root`, hrefs resolve to:
  #   absolute `/x/y` → `{link_root}/x/y`
  #   relative `file.md` → `{link_root}/{link_base}/file.md`
  link_root: str|None = None
  link_base: str = ""
  # h1 defaults to extra top spacing, not a hard page break.
  h1_page_break: bool = False

  def sign_lines(self) -> list[str]:
    """Labels to draw: a scenario from `sign_labels`, or a list verbatim."""
    if not self.sign: return []
    if isinstance(self.sign, (list, tuple)): return [str(x) for x in self.sign]
    key = "signature" if self.sign is True else str(self.sign).lower()
    return list(self.sign_labels.get(key, [str(self.sign)]))
