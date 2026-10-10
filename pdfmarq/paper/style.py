# pdfmarq/paper/style.py

"""Style of a documentation PDF: the markdown style plus banner, footer and signing lines."""
from dataclasses import dataclass, field
from ..md import MarkdownStyle
from ..parts import sign_labels, default_sign_labels

#----------------------------------------------------------------------------------- Status palette

def _default_status_colors() -> dict:
  """
  Default badge colors for document status.
  Each entry maps lowercase status name to `(bg_rgb, text_rgb)` in 0..1 range.
  """
  return {
    "draft": ((0.85, 0.87, 0.92), (0.30, 0.34, 0.45)), # cool blue-grey
    "review": ((1.00, 0.95, 0.78), (0.62, 0.40, 0.05)), # amber
    "approved": ((0.86, 0.96, 0.87), (0.10, 0.45, 0.18)), # green
    "deprecated": ((1.00, 0.88, 0.85), (0.74, 0.20, 0.15)), # red
    "archived": ((0.92, 0.87, 0.96), (0.45, 0.25, 0.55)), # violet
  }

# Badge colors `(bg, text)` of a status the palette does not name.
UNKNOWN_STATUS = ((0.93, 0.93, 0.95), (0.40, 0.44, 0.50))

#--------------------------------------------------------------------------------------- PaperStyle

@dataclass
class PaperStyle(MarkdownStyle):
  """`MarkdownStyle` plus the frontmatter banner, compact banner, page number and signatures."""
  # Frontmatter is drawn as a header on page 1; `False` reads it and draws no header.
  banner: bool = True
  # Drop a leading `# title` repeating the frontmatter title, when the banner shows it.
  skip_dup_title: bool = True
  # Compact header on pages 2+: logo, id and title left, version and `updated` right.
  banner_compact: bool = True
  # strftime syntax. ISO `%Y-%m-%d` (default), PL `%d.%m.%Y`, long `%d %B %Y`.
  date_format: str = "%Y-%m-%d"
  # Page number prefix; `None` draws no page number.
  page_number_label: str|None = "Page"
  # `Page X/Y` vs just `Page X`.
  page_number_total: bool = True

  # Frontmatter header layout
  banner_pad_top: float = 0 # mm above header block (start near top)
  banner_pad_bot: float = 3 # mm below header block before body
  banner_logo_max_h: float = 50 # mm - cap on logo height (page 1, big left column)
  banner_logo_max_w: float = 60 # mm - cap on logo width; overrides height if aspect wide
  banner_title_size: float = 20 # pt - main title
  banner_id_size: float = 9 # pt - document id
  banner_version_size: float = 9 # pt - version
  banner_meta_size: float = 9 # pt - author/date/entity text
  banner_rule: float = 0.3 # pt - matches markdown h1/h2 underlines
  # Compact banner on continuation pages
  banner_compact_logo_max_h: float = 12 # mm - cap on compact-banner logo height (2 lines tall)
  banner_compact_logo_max_w: float = 24 # mm - cap on compact-banner logo width
  banner_compact_size: float = 10 # pt - text size in compact-banner
  banner_compact_top: float = 12 # mm - distance from page top
  banner_compact_gap: float = 8 # mm - gap between compact-banner line and content
  # Signing lines at the very end, independent of `banner`.
  # `True` or a `sign_labels` scenario draws its labels; a list draws custom ones verbatim.
  sign: bool|str|list = False
  sign_labels: dict = field(default_factory=default_sign_labels)
  sign_gap: float = 25 # mm - blank space above the line, for the handwriting
  sign_w: float = 70 # mm - width of one line
  sign_size: float = 9 # pt - label
  # Status badge colors (background, text). Keys must be lowercase.
  banner_status_colors: dict = field(default_factory=_default_status_colors)
  # Frontmatter labels, shown as `"{label}: {value}"`. Override for localization.
  banner_label_author: str = "Author"
  banner_label_created: str = "Created"
  banner_label_updated: str = "Updated"

  def sign_lines(self) -> list[str]:
    """Labels to draw: a scenario from `sign_labels`, or a list verbatim."""
    return sign_labels(self.sign, self.sign_labels)
