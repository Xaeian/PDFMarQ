# pdfmarq/md/markdown.py

"""
Markdown → PDF content with GitHub-flavored style.

The `MarkdownRenderer` class is composed from mixins, each in its own `md_*.py` module:

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
  >>> from pdfmarq import PDF
  >>> from pdfmarq.md import MarkdownRenderer, MarkdownStyle
  >>> pdf = PDF("notes.pdf")
  >>> MarkdownRenderer(pdf, MarkdownStyle()).render(open("notes.md").read())
  >>> pdf.save()
"""

__extras__ = ("markdown", ["markdown-it-py"])

import io, os, warnings
try:
  from markdown_it import MarkdownIt
  from markdown_it.token import Token
except ImportError:
  raise ImportError("Install with: pip install pdfmarq[md]")

from reportlab.lib.colors import Color
from ..core import PDF
from .markdown_style import MarkdownStyle
from .md_fonts import FontsMixin
from .md_preprocess import PreprocessMixin, normalize_math_delimiters
from .md_inline import InlineMixin
from .md_estimate import EstimateMixin
from .md_blocks import BlocksMixin, flowing_kind
from .md_list import ListMixin
from .md_blockquote import BlockquoteMixin
from .md_table import TableMixin
from .md_footnotes import FootnotesMixin
from .md_frontmatter import split_frontmatter
from .md_plugins import sup_plugin, mark_plugin
from .._warn import caller_level, warn_missing
from ..inline import hyphenator
from . import md_html

_OFF_PAGE_SIDE_MM = 10 # margin of an off-page sheet, which heights do not depend on
_OFF_PAGE_TALL_MM = 5000 # an off-page sheet taller than any part it measures

#--------------------------------------------------------------------------------- MarkdownRenderer

class MarkdownRenderer(
  FontsMixin, PreprocessMixin, InlineMixin, EstimateMixin,
  BlocksMixin, ListMixin, BlockquoteMixin, TableMixin, FootnotesMixin,
):
  """Render a markdown-it token stream into the current frame of a `PDF`."""
  def __init__(
    self, pdf:PDF, style:MarkdownStyle|None = None,
    base_dir:str|None = None,
  ):
    if pdf.unit != "mm":
      raise ValueError(f"the markdown engine draws in mm: make the PDF with unit=\"mm\", "
        f"not {pdf.unit!r}")
    self.pdf = pdf
    self.style = style or MarkdownStyle()
    if self.style.hyphenate: hyphenator(self.style.hyphenate) # an unknown language fails here
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
    self._known_slugs: set = set() # populated by `index()`
    self._slug_uses: dict = {} # slug → times used, for numbering repeats
    self._anchors = "" # prefix of this document's anchor names, set by `index()`
    # Math font config is applied per-render-call (`MathFontConfig.apply()`), not at init,
    # so renderers with different fontsets don't clobber matplotlib's global rcParams mid-render.
    from .math import configure_math_fonts # loads matplotlib, so not on import
    self._math_config = configure_math_fonts(
      fontset=self.style.math_fontset,
      font_dir=str(self.pdf.fonts.font_dir),
    )
    self.pdf.font(self.style.font_body, self.style.body_size, self.style.body_mode)
    self._publish_style_fonts()

  def _publish_style_fonts(self):
    """Load the style's families up front, so SVG text can reach all three.

    Drawing alone registers them lazily.
    That leaves a diagram labelled in the mono family on Helvetica whenever the page holds no code.
    Runs after `_ensure_default_font`, so a family it substituted is the one published.

    A missing TTF is skipped, not raised on - that error belongs at the draw.
    """
    for family in (self.style.font_body, self.style.font_head, self.style.font_mono):
      try:
        self.pdf.fonts.register(family)
      except FileNotFoundError:
        continue

  def _load_plugins(self, md):
    """Load optional markdown-it plugins, warning once per missing one."""
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
      if attr == "dollarmath_plugin" and not self.style.math_enable: continue
      try:
        mod = __import__(module_path, fromlist=[attr])
        md.use(getattr(mod, attr))
      except ImportError:
        warn_missing(key, pkg, feature)
    md.use(sup_plugin).use(mark_plugin) # bundled

  #------------------------------------------------------------------------------------------ Entry
  
  def render(self, md_text:str):
    """Parse, index and draw a whole markdown document into the current frame."""
    tokens = self.parse(md_text)
    self.index(tokens)
    self._render_tokens(tokens)

  def parse(self, md_text:str) -> list[Token]:
    """
    Tokens of `md_text`, ready for `index` and `render_tokens`.

    Frontmatter is dropped, so a whole document can come in as it is.
    Reading it is the document package's business, through `split_frontmatter`.
    """
    _, md_text = split_frontmatter(md_text, warn=False)
    md_text = self._normalize_list_indent(md_text)
    md_text = self._emojize_outside_code(md_text)
    md_text = normalize_math_delimiters(md_text)
    return self._md.parse(md_text)

  @classmethod
  def off_page(
    cls,
    width:float,
    style:MarkdownStyle,
    base_dir:str|None,
    font_dir:str,
    height:float|None = None,
  ) -> "MarkdownRenderer":
    """
    The engine on an off-page sheet whose content area is `width` × `height` mm,
    taller than any part it measures without `height`.
    What it draws there takes the room it takes on the page, so a layout measures with it.
    """
    pdf = PDF(io.BytesIO(), width=width + 2 * _OFF_PAGE_SIDE_MM,
      height=height or _OFF_PAGE_TALL_MM, margin=(0, _OFF_PAGE_SIDE_MM), font_dir=font_dir)
    return cls(pdf, style, base_dir)

  def index(self, tokens:list[Token], prefix:str=""):
    """
    Register the heading slugs of the whole document, numbering repeats from scratch.

    Once per document, before any part of it is drawn:
    a link is live only when its target is a heading here.
    A heading dropped before this call, like a repeated title, leaves links to it as plain text.
    """
    self._known_slugs = self._collect_heading_slugs(tokens)
    self._slug_uses = {}
    self._anchors = prefix

  def render_tokens(self, tokens:list[Token], style:MarkdownStyle|None=None):
    """
    Draw `tokens`, the whole parsed document or any slice of it, into the current frame.

    `style` sets this part in a look of its own, its fonts set up as the renderer's own were.
    The document's state is kept: heading slugs and equation numbers run on across parts.
    """
    if style is None: return self._render_tokens(tokens)
    own, self.style = self.style, style
    try:
      self._ensure_default_font()
      self._publish_style_fonts()
      self._render_tokens(tokens)
    finally:
      self.style = own

  @staticmethod
  def _collect_heading_slugs(tokens:list[Token]) -> set:
    """Pre-scan tokens to collect all heading slugs. Used to filter internal links:
    `[x](#slug)` is rendered as a jump only when `slug` is a real heading,
    otherwise the text is kept but not linkified.
    Prevents reportlab crash on save when a link targets a non-existent anchor.

    Repeats are numbered here exactly as the render pass numbers them,
    so a link to `heading-1` resolves to the second heading of that name.
    """
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
        # `![alt](src)\n---` is a common misparse: markdown-it treats `---` as setext h2,
        # sinking the image into a heading (inline thumbnail cap).
        # Recover: render as block image + HR. markup is `-`/`=` for setext, `#` for ATX.
        if t.markup and t.markup[0] in ("-", "=") and self._is_image_only_inline(inline):
          img = next(c for c in inline.children if c.type == "image")
          img_attrs = img.attrs if isinstance(img.attrs, dict) else dict(img.attrs or [])
          src = img_attrs.get("src", "")
          if src and not src.startswith(("http://", "https://")):
            self._render_block_image(src, img.content or "", attrs=img_attrs)
            if t.markup[0] == "-": self._render_hr()
            i = close_i + 1
            continue
        lookahead_mm = self._estimate_next_block(tokens, close_i + 1)
        self._render_heading(level, inline, lookahead_mm=lookahead_mm,
          next_kind=flowing_kind(tokens, close_i + 1))
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
        content = t.content or ""
        if md_html.is_hr_block(content):
          self._render_hr()
        elif md_html.is_pagebreak_directive(content):
          if self.pdf.y > 0.5: # skip when already at page top
            self.pdf.new_page()
        elif md_html.is_group_open_directive(content):
          end_i = self._find_group_close(tokens, i)
          self._render_group(tokens[i+1:end_i])
          i = end_i + 1
          continue
        elif md_html.is_group_close_directive(content):
          # Stray close without a matching open.
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
    (softbreaks/hardbreaks ignored).
    Used to detect the setext-heading-with-image misparse
    and the paragraph-with-image block-image promotion."""
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

  def _reset_stroke(self):
    """Reset canvas stroke and fill to black.
    Prevents color leaks from link underlines and coloured rects bleeding into later elements."""
    c = self.pdf.c
    c.setStrokeColor(Color(0, 0, 0))
    c.setFillColor(Color(0, 0, 0))
    c.setLineWidth(1)

  def frontmatter_file(self, fm:dict, key:str, warn:bool=True) -> str|None:
    """
    The file frontmatter `key` names, resolved against `base_dir`.
    `None` when the key is unset, or when the file is missing, which warns unless `warn` is off.
    The warning points at the first line outside `pdfmarq`: the one that asked for the document.
    """
    raw = fm.get(key)
    if not raw: return None
    path = self.resolve_path(str(raw))
    if os.path.isfile(path): return path
    if warn:
      warnings.warn(f"frontmatter `{key}: {raw}` not found (base_dir={self.base_dir}); "
        "drawn without it", RuntimeWarning, stacklevel=caller_level())
    return None

  def resolve_path(self, src:str) -> str:
    """Join `src` with `base_dir` when relative.
    Absolute paths and URLs pass through unchanged."""
    if not src or src.startswith(("http://", "https://", "data:")):
      return src
    if os.path.isabs(src):
      return src
    return os.path.normpath(os.path.join(self.base_dir, src))

  #------------------------------------------------------------------------------------- Directives

  def _find_group_close(self, tokens:list[Token], start:int) -> int:
    """Return index of the matching `<!-- /group -->` for the open at `start`.
    Inner groups are silent markers only (no extra keep-together behavior).
    Returns `len(tokens)` for unclosed groups (warns, renders to EOF).
    """
    close = _group_close(tokens, start)
    if close is not None: return close
    warnings.warn(
      "unclosed `<!-- group -->` directive - rendering to end of document",
      RuntimeWarning, stacklevel=2,
    )
    return len(tokens)

  def _group_height(self, tokens:list[Token]) -> float:
    """
    Height (mm) `tokens` take from the cursor, drawn off the page in a frame as wide as this one.
    A long table or listing counts in full, as it will draw.
    """
    probe = self.off_page(self.pdf.content_width - self._indent_mm, self.style, self.base_dir,
      str(self.pdf.fonts.font_dir))
    probe._in_group = True # inner blocks skip their own pre-break, as on the page
    # links and formula numbers as the page has them, so they take the same width
    probe._known_slugs, probe._anchors = self._known_slugs, self._anchors
    probe._eq_counter = self._eq_counter
    probe.pdf.cursor(0, self.pdf.y)
    probe._render_tokens(tokens)
    return probe.pdf.y - self.pdf.y

  def _render_group(self, tokens:list[Token]):
    """
    Render a group, on the next page when it misses the rest of this one but fits a whole page.
    `_in_group` makes the blocks inside skip their own pre-break.
    """
    if not tokens: return
    total_h = self._group_height(tokens)
    remaining = self.pdf.content_height - self.pdf.y
    page_avail = self.pdf.content_height
    if total_h > remaining and total_h <= page_avail and self.pdf.y > 0.5:
      self.pdf.next_frame()
    was_in_group = getattr(self, "_in_group", False)
    self._in_group = True
    try:
      self._render_tokens(tokens)
    finally:
      self._in_group = was_in_group

#------------------------------------------------------------------------------------------- Blocks

def _group_close(tokens:list[Token], start:int) -> int|None:
  """
  Index of the `<!-- /group -->` closing the group opened at `start`, `None` when unclosed.
  Depth-tracked, so nested group directives don't confuse the outer close.
  """
  depth = 1
  for j in range(start + 1, len(tokens)):
    t = tokens[j]
    if t.type != "html_block": continue
    content = t.content or ""
    if md_html.is_group_open_directive(content): depth += 1
    elif md_html.is_group_close_directive(content):
      depth -= 1
      if depth == 0: return j
  return None

def top_blocks(tokens:list[Token]) -> list[tuple[int, int]]:
  """
  `(start, end)` of every top-level block, so `tokens[start:end]` renders it alone.

  A block runs from an opening token to its close, or is a single leaf token.
  A `<!-- group -->` through its `<!-- /group -->` counts as one block.
  """
  blocks = []
  i = 0
  while i < len(tokens):
    t = tokens[i]
    if t.type == "html_block" and md_html.is_group_open_directive(t.content or ""):
      close = _group_close(tokens, i)
      end = len(tokens) if close is None else close + 1
    elif t.nesting == 1:
      # matched by type and depth: the footnote plugin opens each note at level 0 too
      close_type = t.type.replace("_open", "_close")
      end = MarkdownRenderer._find_close(tokens, i, t.type, close_type) + 1
    else:
      end = i + 1
    blocks.append((i, end))
    i = end
  return blocks
