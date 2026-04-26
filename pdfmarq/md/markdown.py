# pdfmarq/md/markdown.py

"""
Markdown → PDF rendering with GitHub-flavored style.

The `MarkdownRenderer` class is composed from mixins, each in its own
`md_*.py` module:

  - `md_fonts`      - default font auto-registration
  - `md_preprocess` - source text preprocessors (list indent, emoji shortcodes)
  - `md_inline`     - inline token → `RichSegment` conversion
  - `md_estimate`   - block height estimation for heading lookahead
  - `md_blocks`     - heading, paragraph, code block, hr, math, images
  - `md_list`       - bullet + ordered list rendering
  - `md_blockquote` - blockquote + GitHub callouts
  - `md_table`      - tables with HTML auto-layout column widths
  - `md_footnotes`  - footnote block + definition list

Example:
  >>> from pdfmarq import md_to_pdf, MarkdownStyle
  >>> md_to_pdf(open("README.md").read(), "readme.pdf")
"""

__extras__ = ("markdown", ["markdown-it-py"])

try:
  from markdown_it import MarkdownIt
  from markdown_it.token import Token
except ImportError:
  raise ImportError("Install with: pip install pdfmarq[md]")

from reportlab.lib.colors import Color
from ..core import PDF
from .markdown_style import MarkdownStyle
from .md_fonts import FontsMixin
from .md_preprocess import PreprocessMixin
from .md_inline import InlineMixin
from .md_estimate import EstimateMixin
from .md_blocks import BlocksMixin
from .md_list import ListMixin
from .md_blockquote import BlockquoteMixin
from .md_table import TableMixin
from .md_footnotes import FootnotesMixin
from .md_frontmatter import FrontmatterMixin, peek_frontmatter

#----------------------------------------------------------------------------- MarkdownRenderer

class MarkdownRenderer(
  FontsMixin, PreprocessMixin, InlineMixin, EstimateMixin,
  BlocksMixin, ListMixin, BlockquoteMixin, TableMixin, FootnotesMixin,
  FrontmatterMixin,
):
  """Render a markdown-it token stream onto a `PDF` instance."""

  def __init__(self, pdf:PDF, style:MarkdownStyle|None=None):
    self.pdf = pdf
    self.style = style or MarkdownStyle()
    # Auto-register default sans/mono fonts before the first draw
    self._ensure_default_font()
    md = MarkdownIt("commonmark", {"html": True, "breaks": False})
    md.enable(["table", "strikethrough"])
    self._load_plugins(md)
    self._md = md
    self._indent_mm = 0
    self._list_depth = 0
    self._eq_counter = 0
    self._known_slugs: set = set()  # populated in render() pre-scan
    # Configure matplotlib math fonts. The fontset is either a matplotlib
    # preset (`"stix"`, `"cm"`, etc.) or a font family name resolved against
    # `<font_dir>/<family>/<family>-<Mode>.ttf`.
    try:
      from .math import configure_math_fonts
      configure_math_fonts(
        fontset=self.style.math_fontset,
        font_dir=str(self.pdf._fonts.font_dir),
      )
    except ImportError:
      from .._warn import warn_missing
      warn_missing("matplotlib", "matplotlib", "math formulas")
    self.pdf.font(self.style.body_family, self.style.body_size, self.style.body_mode)

  def _load_plugins(self, md):
    """Load optional markdown-it plugins, warning once for each missing one.
    The features map maps a plugin module path to a (key, package, feature)
    tuple. Plugins are tried in order and missing ones are reported via the
    deduplicated warning system.
    """
    from .._warn import warn_missing
    plugins = [
      ("mdit_py_plugins.dollarmath", "dollarmath_plugin",
        "mdit-dollarmath", "mdit-py-plugins", "math formulas ($...$, $$...$$)"),
      ("mdit_py_plugins.tasklists", "tasklists_plugin",
        "mdit-tasklists", "mdit-py-plugins", "task lists ([ ], [x])"),
      ("mdit_py_plugins.footnote", "footnote_plugin",
        "mdit-footnote", "mdit-py-plugins", "footnotes ([^1])"),
      ("mdit_py_plugins.subscript", "sub_plugin",
        "mdit-subscript", "mdit-py-plugins", "subscript (~text~)"),
      ("mdit_py_plugins.deflist", "deflist_plugin",
        "mdit-deflist", "mdit-py-plugins", "definition lists"),
      ("mdit_py_emoji", "emoji_plugin",
        "mdit-py-emoji", "mdit-py-emoji", "emoji shortcodes (:smile:)"),
    ]
    for module_path, attr, key, pkg, feature in plugins:
      try:
        mod = __import__(module_path, fromlist=[attr])
        md.use(getattr(mod, attr))
      except ImportError:
        warn_missing(key, pkg, feature)
    # Bundled plugins live in the package itself, so they should always import.
    try:
      from .md_plugins import sup_plugin, mark_plugin
      md.use(sup_plugin).use(mark_plugin)
    except ImportError:
      warn_missing("md_plugins", "mdit-py-plugins", "superscript (^x^) and mark (==x==)")

  #-------------------------------------------------------------------------------------- Entry
  
  def render(self, md_text:str):
    """Parse markdown text and render to PDF."""
    self._frontmatter_data = None
    fm_rendered_title = None
    if self.style.banner_render:
      data, md_text = self._extract_frontmatter(md_text)
      if data:
        self._render_frontmatter_header(data)
        fm_rendered_title = data.get("title")
    else:
      _, md_text = self._extract_frontmatter(md_text)
    # Register page chrome callbacks:
    #   on_page       - mini-header on pages 2+ (per-page, no total known)
    #   on_new_page   - cursor offset on pages 2+ for mini-header gap
    #   on_final_page - footer page number (deferred, has total page count)
    self.pdf.on_page(self._render_page_chrome)
    self.pdf.on_new_page(self._offset_body_for_mini_header)
    if self.style.page_number_label:
      self.pdf.on_final_page(self._render_page_number)
    md_text = self._normalize_list_indent(md_text)
    md_text = self._emojize_outside_code(md_text)
    tokens = self._md.parse(md_text)
    self._known_slugs = self._collect_heading_slugs(tokens)
    if self.style.skip_dup_title and fm_rendered_title:
      tokens = self._skip_matching_h1(tokens, str(fm_rendered_title))
    self._render_tokens(tokens)
    if self._frontmatter_data and self._frontmatter_data.get("sign"):
      self._render_signature_block()

  @staticmethod
  def _skip_matching_h1(tokens:list[Token], title:str) -> list[Token]:
    """Drop first 3 tokens if they are `# <title>` matching frontmatter title."""
    if len(tokens) < 3: return tokens
    t0, t1, t2 = tokens[0], tokens[1], tokens[2]
    if (t0.type == "heading_open" and t0.tag == "h1"
        and t1.type == "inline" and t2.type == "heading_close"
        and (t1.content or "").strip() == title.strip()):
      return tokens[3:]
    return tokens

  @staticmethod
  def _collect_heading_slugs(tokens:list[Token]) -> set:
    """Pre-scan tokens to collect all heading slugs. Used to filter internal
    links - `[x](#slug)` is rendered as a jump only when `slug` is a real
    heading, otherwise the text is kept but not linkified. Prevents
    reportlab crash on save when a link targets a non-existent anchor.
    """
    from .md_blocks import BlocksMixin
    slugs: set = set()
    for i in range(len(tokens) - 1):
      if tokens[i].type == "heading_open" and tokens[i+1].type == "inline":
        slug = BlocksMixin._slugify_inline(tokens[i+1])
        if slug: slugs.add(slug)
    return slugs

  def _render_tokens(self, tokens:list[Token]):
    """Block-level dispatcher."""
    i = 0
    while i < len(tokens):
      t = tokens[i]
      ttype = t.type
      if ttype == "heading_open":
        level = int(t.tag[1])
        inline = tokens[i+1]
        # Setext heading whose only inline content is an image is virtually
        # always user error: `![alt](src)\n---` was meant as block image + HR,
        # but markdown-it consumed `---` as setext h2 markup, sinking the image
        # into a heading where it'd render at inline cap (thumbnail). Recover
        # the original intent. `markup` is `-`/`=` for setext, `#...` for ATX.
        if t.markup and t.markup[0] in ("-", "=") and self._is_image_only_inline(inline):
          img = next(c for c in inline.children if c.type == "image")
          img_attrs = img.attrs if isinstance(img.attrs, dict) else dict(img.attrs or [])
          src = img_attrs.get("src", "")
          if src and not src.startswith(("http://", "https://")):
            self._render_block_image(src, img.content or "", attrs=img_attrs)
            self._render_hr()
            i += 3
            continue
        lookahead_mm = self._estimate_next_block(tokens, i + 3)
        self._render_heading(level, inline, lookahead_mm=lookahead_mm)
        i += 3
      elif ttype == "paragraph_open":
        self._render_paragraph(tokens[i+1])
        i += 3
      elif ttype == "fence" or ttype == "code_block":
        lang = (t.info or "").strip().split()[0] if t.info else ""
        if lang == "math":
          self._render_math_block(t.content)
        else:
          self._render_code_block(t.content, lang)
        i += 1
      elif ttype == "math_block":
        self._render_math_block(t.content)
        i += 1
      elif ttype == "bullet_list_open":
        i = self._render_list(tokens, i, ordered=False)
      elif ttype == "ordered_list_open":
        i = self._render_list(tokens, i, ordered=True)
      elif ttype == "blockquote_open":
        i = self._render_blockquote(tokens, i)
      elif ttype == "hr":
        self._render_hr()
        i += 1
      elif ttype == "html_block":
        # Whitelist: only standalone <hr> is recognized as a block element.
        # Anything else (raw HTML blocks like <table>, <div>, <script>) is
        # silently dropped — pdfmarq doesn't render arbitrary HTML.
        from . import md_html
        if md_html.is_hr_block(t.content or ""):
          self._render_hr()
        i += 1
      elif ttype == "table_open":
        i = self._render_table(tokens, i)
      elif ttype == "footnote_block_open":
        i = self._render_footnote_block(tokens, i)
      elif ttype == "dl_open":
        i = self._render_deflist(tokens, i)
      else:
        i += 1

  #----------------------------------------------------------------------------- Shared helpers
  
  @staticmethod
  def _is_image_only_inline(inline:Token) -> bool:
    """True when an inline token's only meaningful child is a single image
    (softbreaks/hardbreaks ignored). Used to detect the setext-heading-with-
    image misparse and the paragraph-with-image block-image promotion."""
    children = inline.children or []
    non_trivial = [c for c in children if c.type not in ("softbreak", "hardbreak")]
    return len(non_trivial) == 1 and non_trivial[0].type == "image"
  
  @staticmethod
  def _find_close(tokens:list[Token], start:int, open_type:str, close_type:str) -> int:
    """Return index of the matching close token for a balanced open token."""
    depth = 0
    for j in range(start, len(tokens)):
      tt = tokens[j].type
      if tt == open_type: depth += 1
      elif tt == close_type:
        depth -= 1
        if depth == 0:
          return j
    return len(tokens) - 1

  def _ensure_space(self, needed_mm:float):
    """Trigger new page if remaining space too small."""
    if needed_mm > (self.pdf.content_height - self.pdf.y):
      self.pdf.new_page()

  def _reset_stroke(self):
    """Reset canvas stroke and fill to black. Prevents color leaks from link
    underlines and coloured rects bleeding into later elements."""
    c = self.pdf._canvas
    c.setStrokeColor(Color(0, 0, 0))
    c.setFillColor(Color(0, 0, 0))
    c.setLineWidth(1)

#------------------------------------------------------------------------------------ md_to_pdf

def md_to_pdf(
  md_text: str,
  output_path: str,
  style: MarkdownStyle|None = None,
  width: float = 210,
  height: float = 297,
  margin: float|tuple = 20,
  font_dir: str = "./fonts",
  metadata: dict|None = None,
  landscape: bool|None = None,
) -> PDF:
  """Convert markdown text to PDF file.

  YAML frontmatter fields auto-fill PDF metadata:
    `title`    -> PDF /Title
    `author`   -> PDF /Author
    `subject`  -> PDF /Subject
    `keywords` -> PDF /Keywords (string, or list joined with ", ")
  Explicit `metadata={...}` arg overrides YAML values per-key.

  Args:
    landscape: Flip page to landscape (swap width/height). When `None`
      (default), reads `landscape: true` from YAML frontmatter. Explicit
      `True`/`False` overrides the frontmatter value.
  """
  fm = peek_frontmatter(md_text)
  if landscape is None:
    if fm is not None and fm.get("landscape") is not None:
      landscape = bool(fm["landscape"])
  if landscape:
    width, height = height, width
  pdf = PDF(
    output_path, width=width, height=height,
    margin=margin, font_dir=font_dir,
  )
  # Auto-fill PDF metadata from YAML. Explicit `metadata=` kwarg wins per-key.
  meta = _metadata_from_frontmatter(fm) if fm else {}
  if metadata:
    meta.update(metadata)
  if meta:
    pdf.metadata(**meta)
  renderer = MarkdownRenderer(pdf, style)
  renderer.render(md_text)
  pdf.save()
  return pdf

def _metadata_from_frontmatter(fm:dict) -> dict:
  """Map YAML keys to `PDF.metadata()` kwargs. Keys absent in `fm` are skipped."""
  out: dict = {}
  for yaml_key, meta_key in (("title", "title"), ("author", "author"), ("subject", "subject")):
    val = fm.get(yaml_key)
    if val is not None:
      out[meta_key] = str(val)
  kw = fm.get("keywords")
  if kw is not None:
    if isinstance(kw, (list, tuple)):
      out["keywords"] = ", ".join(str(k) for k in kw)
    else:
      out["keywords"] = str(kw)
  return out
