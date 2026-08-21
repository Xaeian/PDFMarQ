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
  >>> from pdfmarq.md import md_to_pdf, MarkdownStyle
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
from ..constants import PageSize, A4
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

#--------------------------------------------------------------------------------- MarkdownRenderer

class MarkdownRenderer(
  FontsMixin, PreprocessMixin, InlineMixin, EstimateMixin,
  BlocksMixin, ListMixin, BlockquoteMixin, TableMixin, FootnotesMixin,
  FrontmatterMixin,
):
  """Render a markdown-it token stream onto a `PDF` instance."""

  def __init__(self, pdf:PDF, style:MarkdownStyle|None=None,
      base_dir:str|None=None):
    import os
    self.pdf = pdf
    self.style = style or MarkdownStyle()
    # Root for resolving relative image paths.
    self.base_dir = base_dir or os.getcwd()
    # Auto-register default fonts before the first draw.
    self._ensure_default_font()
    md = MarkdownIt("commonmark", {"html": True, "breaks": False})
    md.enable(["table", "strikethrough"])
    self._load_plugins(md)
    self._md = md
    self._indent_mm = 0
    self._list_depth = 0
    self._eq_counter = 0
    self._known_slugs: set = set()  # populated by render() pre-scan
    self._slug_uses: dict = {} # slug -> times used, for numbering repeats
    self._chrome_registered = False  # page callbacks are registered once
    # Math font config is applied per-render-call (MathFontConfig.apply()), not
    # at init, so multiple renderers with different fontsets don't clobber
    # matplotlib's global rcParams mid-render.
    self._math_config = None
    try:
      from .math import configure_math_fonts
      self._math_config = configure_math_fonts(
        fontset=self.style.math_fontset,
        font_dir=str(self.pdf._fonts.font_dir),
      )
    except ImportError:
      from .._warn import warn_missing
      warn_missing("matplotlib", "matplotlib", "math formulas")
    self.pdf.font(self.style.font_body, self.style.body_size, self.style.body_mode)

  def _load_plugins(self, md):
    """Load optional markdown-it plugins, warning once per missing one."""
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
    # Bundled plugins are always present; ImportError here indicates a broken install.
    try:
      from .md_plugins import sup_plugin, mark_plugin
      md.use(sup_plugin).use(mark_plugin)
    except ImportError:
      warn_missing("md_plugins", "mdit-py-plugins", "superscript (^x^) and mark (==x==)")

  #------------------------------------------------------------------------------------------ Entry
  
  def render(self, md_text:str):
    """Parse markdown text and render to PDF."""
    # The compact banner and the signature block read frontmatter too, so it is
    # captured regardless of `banner`.
    data, md_text = self._extract_frontmatter(md_text)
    self._frontmatter_data = data or None
    fm_rendered_title = None
    if self.style.banner and data:
      self._render_frontmatter_header(data)
      fm_rendered_title = data.get("title")
    # Page chrome: compact-banner fires per-page (no total known yet);
    # footer page number deferred via on_final_page (total count available then).
    # Registered once per renderer - a second render() onto the same PDF
    # would otherwise stack a second set and draw every footer twice.
    if not self._chrome_registered:
      self._chrome_registered = True
      self.pdf.on_page(self._render_page_chrome)
      self.pdf.on_new_page(self._offset_body_for_compact_banner)
      if self.style.page_number_label:
        self.pdf.on_final_page(self._render_page_number)
    md_text = self._normalize_list_indent(md_text)
    md_text = self._emojize_outside_code(md_text)
    tokens = self._md.parse(md_text)
    if self.style.skip_dup_title and fm_rendered_title:
      tokens = _skip_matching_h1(tokens, str(fm_rendered_title))
    # Slugs are collected after the drop, so a link to the removed title is an
    # unknown anchor like any other.
    self._known_slugs = self._collect_heading_slugs(tokens)
    self._slug_uses = {}
    self._render_tokens(tokens)
    if self.style.sign:
      self._render_signature_block()

  @staticmethod
  def _collect_heading_slugs(tokens:list[Token]) -> set:
    """Pre-scan tokens to collect all heading slugs. Used to filter internal
    links - `[x](#slug)` is rendered as a jump only when `slug` is a real
    heading, otherwise the text is kept but not linkified. Prevents
    reportlab crash on save when a link targets a non-existent anchor.

    Repeats are numbered here exactly as the render pass numbers them, so a
    link to `heading-1` resolves to the second heading of that name.
    """
    from .md_blocks import BlocksMixin
    slugs: set = set()
    seen: dict = {}
    for i in range(len(tokens) - 1):
      if tokens[i].type == "heading_open" and tokens[i+1].type == "inline":
        slug = BlocksMixin._slugify_inline(tokens[i+1])
        if slug: slugs.add(BlocksMixin.dedupe_slug(slug, seen))
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
        close_i = self._find_close(tokens, i, "heading_open", "heading_close")
        # `![alt](src)\n---` is a common misparse: markdown-it treats `---`
        # as setext h2, sinking the image into a heading (inline thumbnail cap).
        # Recover: render as block image + HR. markup is `-`/`=` for setext, `#` for ATX.
        if t.markup and t.markup[0] in ("-", "=") and self._is_image_only_inline(inline):
          img = next(c for c in inline.children if c.type == "image")
          img_attrs = img.attrs if isinstance(img.attrs, dict) else dict(img.attrs or [])
          src = img_attrs.get("src", "")
          if src and not src.startswith(("http://", "https://")):
            self._render_block_image(src, img.content or "", attrs=img_attrs)
            self._render_hr()
            i = close_i + 1
            continue
        lookahead_mm = self._estimate_next_block(tokens, close_i + 1)
        self._render_heading(level, inline, lookahead_mm=lookahead_mm)
        i = close_i + 1
      elif ttype == "paragraph_open":
        close_i = self._find_close(tokens, i, "paragraph_open", "paragraph_close")
        self._render_paragraph(tokens[i+1])
        i = close_i + 1
      elif ttype == "fence" or ttype == "code_block":
        # info string: first word = lang, remainder = optional DSL (mermaid).
        info_parts = (t.info or "").strip().split(maxsplit=1)
        lang = info_parts[0] if info_parts else ""
        info_rest = info_parts[1] if len(info_parts) > 1 else ""
        if lang == "math": self._render_math_block(t.content)
        else:
          self._render_code_block(t.content, lang, info_rest)
        i += 1
      elif ttype == "math_block":
        self._render_math_block(t.content)
        i += 1
      elif ttype == "bullet_list_open": i = self._render_list(tokens, i, ordered=False)
      elif ttype == "ordered_list_open": i = self._render_list(tokens, i, ordered=True)
      elif ttype == "blockquote_open": i = self._render_blockquote(tokens, i)
      elif ttype == "hr":
        self._render_hr()
        i += 1
      elif ttype == "html_block":
        # Only <hr>, <!-- pagebreak -->, and <!-- group --> directives are handled;
        # all other HTML blocks are silently dropped.
        from . import md_html
        content = t.content or ""
        if md_html.is_hr_block(content):
          self._render_hr()
        elif md_html.is_pagebreak_directive(content):
          if self.pdf.y > 0.5:  # skip when already at page top
            self.pdf.new_page()
        elif md_html.is_group_open_directive(content):
          end_i = self._find_group_close(tokens, i)
          self._render_group(tokens[i+1:end_i])
          i = end_i + 1
          continue
        elif md_html.is_group_close_directive(content):
          # Stray close without a matching open.
          import warnings
          warnings.warn(
            "stray `<!-- /group -->` directive (no matching open)",
            RuntimeWarning, stacklevel=2,
          )
        i += 1
      elif ttype == "table_open": i = self._render_table(tokens, i)
      elif ttype == "footnote_block_open": i = self._render_footnote_block(tokens, i)
      elif ttype == "dl_open": i = self._render_deflist(tokens, i)
      else:
        i += 1

  #--------------------------------------------------------------------------------- Shared helpers
  
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
    """Trigger new page if remaining space too small.

    A block taller than a whole page gets no break when the cursor is
    already at the top: it cannot fit on a fresh page either, so the break
    would only emit a blank page and push the overflow one page further.
    Blocks that can be split (paragraphs, code) break pages themselves.
    """
    if needed_mm <= (self.pdf.content_height - self.pdf.y):
      return
    if needed_mm > self.pdf.content_height and self.pdf.y <= 0.5:
      return
    self.pdf.new_page()

  def _reset_stroke(self):
    """Reset canvas stroke and fill to black. Prevents color leaks from link
    underlines and coloured rects bleeding into later elements."""
    c = self.pdf._canvas
    c.setStrokeColor(Color(0, 0, 0))
    c.setFillColor(Color(0, 0, 0))
    c.setLineWidth(1)

  def _resolve_image_path(self, src:str) -> str:
    """Join `src` with `base_dir` when relative. Absolute paths and URLs
    pass through unchanged."""
    import os
    if not src or src.startswith(("http://", "https://", "data:")):
      return src
    if os.path.isabs(src):
      return src
    return os.path.normpath(os.path.join(self.base_dir, src))

  #------------------------------------------------------------------------------------- Directives

  def _find_group_close(self, tokens:list[Token], start:int) -> int:
    """Return index of the matching `<!-- /group -->` for the open at `start`.
    Depth-tracked so nested group directives don't confuse the outer close.
    Inner groups are silent markers only (no extra keep-together behavior).
    Returns `len(tokens)` for unclosed groups (warns, renders to EOF).
    """
    from . import md_html
    depth = 1
    for j in range(start + 1, len(tokens)):
      t = tokens[j]
      if t.type != "html_block": continue
      content = t.content or ""
      if md_html.is_group_open_directive(content): depth += 1
      elif md_html.is_group_close_directive(content):
        depth -= 1
        if depth == 0: return j
    import warnings
    warnings.warn(
      "unclosed `<!-- group -->` directive - rendering to end of document",
      RuntimeWarning, stacklevel=2,
    )
    return len(tokens)

  def _estimate_group_height(self, tokens:list[Token]) -> float:
    """Sum estimated heights of top-level blocks in a group.
    Approximate (tighter or looser than real layout); sufficient for a
    binary fits-remaining-space decision."""
    s = self.style
    total = 0.0
    paired = {
      "paragraph_open": "paragraph_close",
      "heading_open": "heading_close",
      "bullet_list_open": "bullet_list_close",
      "ordered_list_open": "ordered_list_close",
      "blockquote_open": "blockquote_close",
      "table_open": "table_close",
      "footnote_block_open": "footnote_block_close",
      "dl_open": "dl_close",
    }
    leaf = {"fence", "code_block", "math_block", "hr"}
    i = 0
    while i < len(tokens):
      t = tokens[i]
      ttype = t.type
      if ttype in paired:
        close_i = self._find_close(tokens, i, ttype, paired[ttype])
        total += self._estimate_next_block(tokens, i) + s.para_gap
        i = close_i + 1
      elif ttype in leaf:
        total += self._estimate_next_block(tokens, i) + s.para_gap
        i += 1
      else:
        i += 1
    return total

  def _render_group(self, tokens:list[Token]):
    """Render group content; pre-break if it doesn't fit but a fresh page
    would. Sets `_in_group` so inner blocks skip their own pre-break."""
    if not tokens: return
    total_h = self._estimate_group_height(tokens)
    remaining = self.pdf.content_height - self.pdf.y
    page_avail = self.pdf.content_height
    if total_h > remaining and total_h <= page_avail and self.pdf.y > 0.5:
      self.pdf.new_page()
    was_in_group = getattr(self, "_in_group", False)
    self._in_group = True
    try:
      self._render_tokens(tokens)
    finally:
      self._in_group = was_in_group

#------------------------------------------------------------------------------------------ Helpers

def _skip_matching_h1(tokens:list[Token], title:str) -> list[Token]:
  """Drop first 3 tokens if they are `# <title>` matching the frontmatter title."""
  if len(tokens) < 3: return tokens
  t0, t1, t2 = tokens[0], tokens[1], tokens[2]
  if (t0.type == "heading_open" and t0.tag == "h1"
      and t1.type == "inline" and t2.type == "heading_close"
      and (t1.content or "").strip() == title.strip()):
    return tokens[3:]
  return tokens

#---------------------------------------------------------------------------------------- md_to_pdf

def md_to_pdf(
  md_text: str,
  output_path: str,
  *,
  style: MarkdownStyle|None = None,
  page: PageSize = A4,
  margin: float|tuple = 20,
  gutter: float = 0,
  base_dir: str|None = None,
  font_dir: str|None = None,
  metadata: dict|None = None,
) -> PDF:
  """Convert markdown text to PDF file.

  Presentation comes from the caller, content from the document. `style` is
  used verbatim - no layering, so a caller can set any value, including one
  equal to a `MarkdownStyle()` default.

  Frontmatter is read for content only: `title`/`author`/`subject`/`keywords`
  seed PDF metadata (`metadata=` overrides per key), the rest feeds the banner.

  Keyword-only after `output_path`, so the parameter order cannot silently
  diverge from `md_to_docx`.

  Args:
    page: `PageSize` in mm. `page_size("a3")` resolves a preset name,
      `A4.landscape()` flips it, `PageSize(200, 250)` is a custom sheet.
    margin: mm, scalar or CSS-order 1-4 sequence.
    gutter: binding margin in mm, folded into the left margin (PDF has no
      native gutter).
    base_dir: root for relative image paths. `None` uses cwd.
  """
  fm = peek_frontmatter(md_text)
  eff_style = style or MarkdownStyle()
  if gutter:
    from ..utils import parse_margin
    mt, mr, mb, ml = parse_margin(margin)
    margin = (mt, mr, mb, ml + gutter)
  pdf = PDF(
    output_path, width=page.width, height=page.height,
    margin=margin, font_dir=font_dir or "./fonts",
  )
  # YAML frontmatter seeds PDF metadata; explicit `metadata=` kwarg overrides per-key.
  meta = _metadata_from_frontmatter(fm) if fm else {}
  if metadata:
    meta.update(metadata)
  if meta:
    pdf.metadata(**meta)
  renderer = MarkdownRenderer(pdf, eff_style)
  if base_dir is not None:
    renderer.base_dir = base_dir
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
