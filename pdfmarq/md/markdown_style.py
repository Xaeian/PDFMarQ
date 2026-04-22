# pdfmarq/md/markdown_style.py

"""GitHub-flavored markdown visual style."""
from dataclasses import dataclass, field

#------------------------------------------------------------------------------- Status palette

def _default_status_colors() -> dict:
  """Default badge colors for document status.
  Each entry maps lowercase status name to (bg_rgb, text_rgb) in 0..1 range.
  """
  return {
    "draft":      ((0.85, 0.87, 0.92), (0.30, 0.34, 0.45)),  # cool blue-grey
    "review":     ((1.00, 0.95, 0.78), (0.62, 0.40, 0.05)),  # amber
    "approved":   ((0.86, 0.96, 0.87), (0.10, 0.45, 0.18)),  # green
    "deprecated": ((1.00, 0.88, 0.85), (0.74, 0.20, 0.15)),  # red
    "archived":   ((0.92, 0.87, 0.96), (0.45, 0.25, 0.55)),  # violet
  }

#-------------------------------------------------------------------------------- MarkdownStyle

@dataclass
class MarkdownStyle:
  """Visual style for markdown rendering, matching GitHub light theme.

  Default fonts use **Vera Sans** (Bitstream Vera) bundled with reportlab.
  Vera has complete Latin-Extended coverage including Polish `ąęłńóśźż`,
  unlike core-14 Helvetica which lacks them entirely. To use a different
  font register a TTF via `pdf.fonts.register()` and set `body_family` etc.
  """

  # Font families - Vera Sans has Polish glyphs out of the box
  body_family: str = "Vera"
  heading_family: str = "Vera"
  mono_family: str = "Courier" # keeping Courier for mono; can be overridden

  # Modes (Vera has dedicated Italic / BoldItalic TTFs)
  body_mode: str = "Regular"
  bold_mode: str = "Bold"
  italic_mode: str = "Italic"
  bold_italic_mode: str = "BoldItalic"
  heading_mode: str = "Bold"
  mono_mode: str = "Regular"

  # Font sizes (pt)
  body_size: float = 11
  h1_size: float = 18
  h2_size: float = 14
  h3_size: float = 12
  h4_size: float = 11
  h5_size: float = 10
  h6_size: float = 10
  mono_size: float = 9.5
  code_block_size: float = 9

  # Colors (rgb 0-1) - GitHub light theme
  body_color: tuple = (0.09, 0.11, 0.13) # #1f2328
  heading_color: tuple = (0.09, 0.11, 0.13)
  muted_color: tuple = (0.40, 0.44, 0.50)
  link_color: tuple = (0.03, 0.41, 0.85) # #0969da
  code_color: tuple = (0.09, 0.11, 0.13)
  code_bg: tuple = (0.96, 0.97, 0.98) # same as code_block_bg
  code_block_bg: tuple = (0.96, 0.97, 0.98) # #f6f8fa
  code_block_border: tuple = (0.82, 0.84, 0.87) # #d0d7de GitHub border
  blockquote_border: tuple = (0.82, 0.84, 0.87)
  blockquote_color: tuple = (0.40, 0.44, 0.50)
  hr_color: tuple = (0.82, 0.84, 0.87)
  table_header_bg: tuple = (0.96, 0.97, 0.98)
  table_border: tuple = (0.82, 0.84, 0.87)
  table_zebra_bg: tuple = (0.985, 0.99, 0.995) # very subtle - lighter than header_bg

  # Spacing (mm) - tightened for GitHub feel
  line_height: float = 1.4            # ratio of font size
  paragraph_spacing: float = 3        # mm between paragraphs
  heading_spacing_top: float = 5      # mm above headings
  heading_spacing_bot: float = 1.5    # mm below headings
  list_indent: float = 6              # mm per list level
  list_item_spacing: float = 0.5      # mm between items (tight)
  bullet_radius: float = 0.7          # mm - solid disc for bullets
  code_block_padding: float = 3       # mm inside code blocks
  code_block_spacing: float = 3       # mm after code blocks
  code_block_radius: float = 2        # mm corner radius (GitHub: 6pt ≈ 2.1mm)
  syntax_theme: str = "default"       # pygments style name for highlighting
  mermaid_max_height: float = 120     # mm - cap on mermaid diagram height
  blockquote_padding: float = 5       # mm left indent
  blockquote_border_width: float = 1  # mm thickness of left bar
  hr_thickness: float = 0.3           # pt line width
  underline_thickness: float = 0.3    # pt
  table_cell_vpad: float = 1.5        # mm extra vertical padding inside cells

  # Math formulas (matplotlib mathtext -> SVG -> vector in PDF).
  # `math_fontset` accepts either a matplotlib preset (`"stix"`, `"stixsans"`,
  # `"cm"`, `"dejavusans"`, `"dejavuserif"`) or a font family name following
  # the standard `fonts/<Family>/<Family>-<Mode>.ttf` convention. When a
  # family name is given, the loader registers Regular/Italic/Bold from
  # that folder. Default is `"stixsans"` - sans-serif with real italic and
  # full unicode math symbols, bundled with matplotlib (no setup).
  math_fontset: str = "stixsans"
  math_block_spacing: float = 3            # mm above/below block equations
  math_equation_numbering: bool = True     # auto (1), (2), (3) for block math

  # Layout flags
  h1_underline: bool = True
  h2_underline: bool = True
  table_zebra: bool = True

  # YAML frontmatter -> document header.
  # When the document starts with `---\n...\n---`, the YAML block is parsed
  # and rendered as a header layout instead of body text. Set
  # `render_frontmatter=False` to skip frontmatter without rendering.
  render_frontmatter: bool = True
  # If the first body block is `# X` and `X` exactly matches frontmatter
  # `title`, drop that h1 to avoid showing the title twice. Only active
  # when the frontmatter header was actually rendered.
  skip_duplicate_title: bool = True
  # Mini header on pages 2+ (compact: code | title | page N/M).
  # Disable for single-page-style documents.
  mini_header_on_continuation: bool = True
  # Date format for created/updated fields. Python strftime syntax.
  # ISO `%Y-%m-%d` (default), PL `%d.%m.%Y`, long `%d %B %Y`.
  date_format: str = "%Y-%m-%d"
  # Word for page numbering. Set to None to disable page numbers entirely.
  # Examples: "Page", "Strona", "Seite".
  page_number_label: str|None = "Page"
  # Show total page count: `Page 1/5` instead of just `Page 1`. Default ON.
  page_number_total: bool = True

  # Frontmatter header layout (mm)
  fm_header_pad_top: float = 0    # mm above header block (start near top)
  fm_header_pad_bot: float = 8    # mm below header block before body
  fm_logo_max_height: float = 50  # mm - cap on logo height (page 1, big left column)
  fm_logo_max_width: float = 60   # mm - cap on logo width; overrides height if aspect wide
  fm_title_size: float = 22       # pt - main title
  fm_id_size: float = 9           # pt - document id
  fm_version_size: float = 9      # pt - version
  fm_meta_size: float = 9         # pt - author/date/entity text
  fm_rule_thickness: float = 0.3  # pt - matches markdown h1/h2 underlines
  fm_sign_size: float = 9         # pt - signature label
  fm_sign_line_width: float = 70  # mm - width of signature line
  # Mini header on continuation pages
  fm_mini_logo_max_height: float = 12  # mm - cap on mini-header logo height (2 lines tall)
  fm_mini_logo_max_width: float = 24   # mm - cap on mini-header logo width
  fm_mini_size: float = 10        # pt - text size in mini-header
  fm_mini_top_offset: float = 12  # mm - distance from page top
  fm_mini_gap_to_body: float = 8  # mm - gap between mini-header line and content
  # Status badge colors (background, text). Keys must be lowercase.
  fm_status_colors: dict = field(default_factory=_default_status_colors)
  # Frontmatter labels - shown as `"{label}: {value}"` (author/created/updated)
  # or as-is (signature). Override for localization or custom wording.
  fm_label_author: str = "Author"
  fm_label_created: str = "Created"
  fm_label_updated: str = "Updated"
  fm_label_signature: str = "Signature"

  # Local-link handling. Links like `[x](file.md)` or `[x](folder/doc)` have
  # no schema and no `#` prefix. Without `link_root`, they get the link style
  # (blue underline) but no clickable action - a dead link in a PDF context.
  # When `link_root` is set, they resolve to:
  #   absolute href `/x/y`         -> `{link_root}/x/y`
  #   relative href `file.md`      -> `{link_root}/{link_base}/file.md`
  # `link_base` can also be set per-document via `base:` in YAML frontmatter,
  # which overrides the style value for that document only.
  link_root: str|None = None
  link_base: str = ""
  # Page break behavior. h1 page break is OFF by default - matches original
  # behavior where h1 just gets extra top spacing like other headings.
  page_break_on_h1: bool = False
