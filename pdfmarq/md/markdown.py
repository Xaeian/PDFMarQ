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
from ..fonts import FontManager
from ..floats import Floats
from ..layout import lowest_fit
from .markdown_style import MarkdownStyle, TABLE_RULES
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
from ..warn import caller_level, warn_missing
from ..inline import hyphenator
from . import md_html

_OFF_PAGE_SIDE_MM = 10 # margin of an off-page sheet, which heights do not depend on
_OFF_PAGE_TALL_MM = 5000 # an off-page sheet taller than any part it measures
_START_LINES = 3 # with room for fewer lines of text, columns start on the next page
_HOLE_LINES = 7 # a wide figure set in place under its text leaves no taller hole over it
_MOVED_MM = 0.5 # text an `on_new_page` moved down further than this misses the measure
_BELOW_TOP_MM = 1 # where a block is measured: under the top of a frame, never at it

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
    self._check_style()
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
    self._in_group = False # inside a group directive, where blocks skip their own pre-break
    self._queue = Floats(pdf, self._block_height, self._draw_float) # blocks waiting, in order
    self._measured: dict = {} # what columns measured of their blocks, shared with probes
    self._held = False # whether blocks still waited as the bibliography of a flow began
    self._ended = (0, False) # the page a flow's blocks ended on, and whether some waited there
    self._page_seen = 0 # the last page whose header room a run of columns checked
    self._squeezed = False # whether a table drawn so far breaks words, its columns too narrow
    self._eq_counter = 0
    self._after_math = False # the block set last was a formula, a sentence maybe going on under it
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
    self.pdf.kerning(self.style.kerning)
    self._publish_style_fonts()

  def _publish_style_fonts(self):
    """
    Load the style's families up front, so SVG text can reach all three.

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
    self._render_top(tokens, 0)

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
    fonts:FontManager|None = None,
  ) -> "MarkdownRenderer":
    """
    The engine on an off-page sheet whose content area is `width` × `height` mm,
    taller than any part it measures without `height`.
    What it draws there takes the room it takes on the page, so a layout measures with it.
    `fonts` hands over the faces a page registered, those from files of any folder included.
    """
    pdf = PDF(io.BytesIO(), width=width + 2 * _OFF_PAGE_SIDE_MM,
      height=height or _OFF_PAGE_TALL_MM, margin=(0, _OFF_PAGE_SIDE_MM), font_dir=font_dir,
      pictures=False)
    if fonts is not None: pdf.fonts.adopt(fonts)
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

  def render_tokens(self, tokens:list[Token], style:MarkdownStyle|None=None, below:float=0):
    """
    Draw `tokens`, the whole parsed document or any slice of it, into the current frame.

    `style` sets this part in a look of its own, its fonts set up as the renderer's own were.
    The document's state is kept: heading slugs and equation numbers run on across parts.
    A look with `columns > 1` sets the part in columns,
    and `below` mm stay free under their last page for what follows the part, as signing lines.
    Each call opens and balances columns of its own,
    so a package drawing block by block opens them itself, with `pdf.columns()`.
    """
    if style is None: return self._render_top(tokens, below)
    own, self.style = self.style, style
    try:
      self._check_style()
      self._ensure_default_font()
      self._publish_style_fonts()
      self._render_top(tokens, below)
    finally:
      self.style = own

  def _check_style(self):
    """Fail on a value of `style` the engine cannot set, before anything is drawn."""
    s = self.style
    if s.hyphenate: hyphenator(s.hyphenate) # an unknown language fails here
    if s.table_rules not in TABLE_RULES:
      raise ValueError(f"table_rules must be one of {', '.join(TABLE_RULES)}, "
        f"got {s.table_rules!r}")
    if not isinstance(s.columns, int) or s.columns < 1:
      raise ValueError(f"columns must be a whole number from 1 up, got {s.columns!r}")
    if not isinstance(s.bind_single_letters, str):
      raise TypeError(f"bind_single_letters names the letters that bind, as `aiouwz`, "
        f"got {s.bind_single_letters!r}")

  @staticmethod
  def _collect_heading_slugs(tokens:list[Token]) -> set:
    """
    Pre-scan tokens to collect all heading slugs. Used to filter internal links:
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

  def _render_tokens(self, tokens:list[Token], floats:bool=False):
    """
    Block-level dispatcher.
    With `floats`, as a run of columns sets its own blocks, a figure may wait for a frame's top.
    """
    notes = _notes_span(tokens) if floats else None
    i = 0
    while i < len(tokens):
      t = tokens[i]
      ttype = t.type
      after_math, self._after_math = self._after_math, False
      if notes and i == notes[0]: self._notes_begin(tokens[notes[0]:notes[1]])
      if floats:
        end = self._float_end(tokens, i)
        if end and self._defer(tokens[i:end]):
          i = end
          continue
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
        self._render_paragraph(tokens[i+1], after_math)
        i = close_i + 1
      elif ttype == "fence" or ttype == "code_block":
        # info string: first word = lang, remainder = optional DSL (mermaid).
        info_parts = (t.info or "").strip().split(maxsplit=1)
        lang = info_parts[0] if info_parts else ""
        info_rest = info_parts[1] if len(info_parts) > 1 else ""
        if lang == "math":
          self._render_math_block(t.content)
          self._after_math = True
        else:
          self._render_code_block(t.content, lang, info_rest)
        i += 1
      elif ttype == "math_block":
        self._render_math_block(t.content)
        self._after_math = True
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
          self.pdf.page_break()
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

  def _float_end(self, tokens:list[Token], i:int) -> int|None:
    """
    End of the block at `i` when it may float, as a journal floats its figures:
    a picture alone, a table, a group opened `wide`, or a group that sets a figure (`_figure`).
    A group of text stays where it is written, since text reads in its order.
    """
    t = tokens[i]
    if t.type == "table_open": return self._find_close(tokens, i, "table_open", "table_close") + 1
    picture = i + 1 < len(tokens) and self._is_image_only_inline(tokens[i+1])
    if t.type == "paragraph_open" and picture:
      return self._find_close(tokens, i, "paragraph_open", "paragraph_close") + 1
    if t.type == "html_block" and md_html.is_group_open_directive(t.content or ""):
      close = _group_close(tokens, i) # one left unclosed warns where it is drawn
      end = len(tokens) if close is None else close + 1
      if "wide" in md_html.group_options(t.content) or _figure(tokens[i+1:end]): return end
    return None

  #--------------------------------------------------------------------------------- Shared helpers

  @staticmethod
  def _is_image_only_inline(inline:Token) -> bool:
    """
    True when an inline token's only meaningful child is a single image
    (softbreaks/hardbreaks ignored).
    Used to detect the setext-heading-with-image misparse
    and the paragraph-with-image block-image promotion.
    """
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
        if depth == 0: return j
    return len(tokens) - 1

  def _reset_stroke(self):
    """
    Reset canvas stroke and fill to black.
    Prevents color leaks from link underlines and coloured rects bleeding into later elements.
    """
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
    """
    Join `src` with `base_dir` when relative.
    Absolute paths and URLs pass through unchanged.
    """
    if not src or src.startswith(("http://", "https://", "data:")): return src
    if os.path.isabs(src): return src
    return os.path.normpath(os.path.join(self.base_dir, src))

  #------------------------------------------------------------------------------------- Directives

  def _find_group_close(self, tokens:list[Token], start:int) -> int:
    """
    Return index of the matching `<!-- /group -->` for the open at `start`.
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

  def _group_height(self, tokens:list[Token], y:float|None=None) -> float:
    """
    Height (mm) `tokens` take from the cursor, or from `y` mm down the frame,
    drawn off the page in a frame as wide as this one.
    A long table or listing counts in full, as it will draw.
    """
    y = self.pdf.y if y is None else y
    probe = self._probe(self.pdf.content_width - self._indent_mm)
    probe._in_group = True # inner blocks skip their own pre-break, as on the page
    probe.pdf.cursor(0, y)
    probe._render_tokens(tokens)
    return probe.pdf.y - y

  def _render_group(self, tokens:list[Token]):
    """
    Render a group, moved on whole when it misses the rest of this frame but fits a fresh one,
    past a short column to the next page if need be.
    `_in_group` makes the blocks inside skip their own pre-break.
    """
    if not tokens: return
    total_h = self._group_height(tokens)
    if total_h <= self.pdf.fresh_height: self.pdf.keep(total_h)
    was_in_group = self._in_group
    self._in_group = True
    try:
      self._render_tokens(tokens)
    finally:
      self._in_group = was_in_group

  @property
  def _keeps_whole(self) -> bool:
    """Whether a paragraph or list that misses the rest of a frame moves on whole."""
    s = self.style
    return s.columns < 2 if s.keep_together is None else s.keep_together

  #---------------------------------------------------------------------------------------- Columns

  def _render_top(self, tokens:list[Token], below:float):
    """`tokens` as the look sets them: in columns when it asks for more than one."""
    if self.style.columns > 1: self._render_columns(tokens, below)
    else: self._render_tokens(tokens)

  def _render_columns(self, tokens:list[Token], below:float):
    """
    The text before the first `##` across the page, the rest in runs of columns.
    A run ends at a page break, and at a block across the page, set under it,
    unless the block waits for the top of a page instead, and the next one goes on:
    a wide figure waits only when it misses the page where it is written, as `_in_place` tells.
    A `#` that starts on a new page ends the run before it too, and begins the next.
    Blocks still waiting where a run's text ends come right after it, before what ends it,
    and its bibliography may part from it for them, as `_notes_apart` tells,
    a narrow one last in line, whole and alone, then opening the bibliography's columns.
    `below` mm stay free under the last run for what follows it.
    """
    if self.pdf.in_columns:
      raise ValueError("columns cannot open in columns or an inset: give this part `columns=1`")
    self._measured = {} # its tokens live while it runs, so their ids name its blocks
    first = first_section(tokens)
    self._render_tokens(tokens[:first])
    def cut(block:list[Token]) -> bool:
      return _breaks(block) or (self._spans(block) and not self._floats_wide(block))
    parts = _chapters(tokens[first:]) if self.style.h1_page_break else [tokens[first:]]
    pending = [pair for part in parts for pair in _runs(part, cut)]
    while pending:
      run, wide = pending.pop(0)
      place = self._in_place(run) # asked as the run begins, where the page stands then
      if place:
        start, end = place
        pending.insert(0, (run[end:], wide))
        run, wide = run[:start], run[start:end]
      under = self._block_height(wide) if wide and not _breaks(wide) else 0
      room = below if not pending else under
      parts = self._notes_apart(run, room) if _sets_anything(run) else [(run, None)]
      lead = [] # a narrow block still waiting where the text ended, set first in the next part
      for n, (part, balanced) in enumerate(parts):
        closes = n == len(parts) - 1 # what ends the run follows its last part
        part = lead + part # a part they open was not measured with them: `balanced` is None
        if _sets_anything(part): self._render_run(part, room if closes else 0, balanced)
        else: self._render_tokens(part) # comments alone open no columns
        lead = self._render_waiting(room if closes else 0, notes=not closes)
      self._render_tokens(wide)

  def _notes_apart(self, run:list[Token], below:float) -> list[tuple]:
    """
    `(blocks, balanced)` of each part of `run`, `balanced` its caps and pages where measured.
    One part, as a journal sets it: a block still waiting as the bibliography begins
    takes the top of a frame among its entries, or stands right before them where they end first.
    The text and its bibliography part only where that block fits under the text where it ends,
    or would otherwise be left after the bibliography.
    """
    notes = (_notes_span(run) or (0, 0))[0]
    if not (self.style.floats and notes and _sets_anything(run[:notes])): return [(run, None)]
    s, pdf = self.style, self.pdf
    line = s.line_mm(s.body_size)
    pdf.keep(_START_LINES * line) # where the run starts, as `_render_run` moves it
    whole = self._balance(run, below, line)
    probe = self._flowed(run, pdf.content_height, pdf.y, whole[0])
    if not probe._held: return [(run, whole)]
    _, left = probe._ended # still waiting as its last entry is set: no frame opened for it
    if left or self._settles(run[:notes]): return [(run[:notes], None), (run[notes:], None)]
    return [(run, whole)]

  def _in_place(self, run:list[Token]) -> tuple[int, int]|None:
    """
    `(start, end)` of a wide figure of `run` that fits across the page where it is written,
    under the text before it, balanced: it ends the run there, as without floats,
    instead of waiting for the top of a page while the figures after it wait behind it.
    Only the first wide figure is asked: those after it wait behind it once it waits.
    """
    if not self.style.floats: return None
    blocks = top_blocks(run)
    for k, (start, end) in enumerate(blocks):
      block = run[start:end]
      if not (self._spans(block) and self._floats_wide(block)): continue
      if k and run[blocks[k - 1][0]].type == "heading_open": return None # keeps its text
      text = run[:start]
      if _sets_anything(text): # where the run starts, as `_render_run` moves it
        self.pdf.keep(_START_LINES * self.style.line_mm(self.style.body_size))
      return (start, end) if self._settles(text, block) else None
    return None

  def _settles(self, text:list[Token], then:list[Token]|None=None) -> bool:
    """
    Whether the blocks still waiting where `text` ends, as a run of its own,
    fit under it on its last page, as `_render_waiting` sets them, and `then` across under them.
    `then` asks its columns there to end evenly too: a figure of one column among them
    leaves no hole over it taller than `_HOLE_LINES` lines.
    """
    s, pdf = self.style, self.pdf
    line = s.line_mm(s.body_size)
    under = self._block_height(then) if then else 0
    if not _sets_anything(text): return under <= pdf.content_height - pdf.y # nothing waits
    caps, _ = self._balance(text, under, line)
    probe = self._flowed(text, pdf.content_height, pdf.y, caps)
    page, _ = probe._ended # where the text ends, before those whose turn it is follow it
    ends = probe.pdf.column_ends + [0] * (s.columns - len(probe.pdf.column_ends))
    if then and max(ends) - min(ends) > _HOLE_LINES * line: return False
    probe.pdf.columns(1)
    with warnings.catch_warnings(): # the page warns of what it draws itself
      warnings.simplefilter("ignore")
      probe._render_waiting(0)
      if then: probe._render_tokens(then)
    return probe.pdf.page_num == page

  def _render_waiting(self, below:float, notes:bool=False) -> list[Token]:
    """
    The blocks still waiting where a run's text ends, set after it as they would stand
    without floats, in order: a wide one across the page, the narrow ones in columns of their own.
    `below` mm stay free under the last of them.
    With `notes` the bibliography follows: a narrow one last in line is handed back instead,
    to open its columns with its entries beside it, when it stands whole and alone there.
    A table, which parts by its rows, and two blocks or more leave no column of their own blank.
    """
    waiting = self._queue.take()
    while waiting:
      block, wide = waiting.pop(0)
      if wide:
        self._render_tokens(block)
        continue
      whole = block[0].type != "table_open" and not (waiting and not waiting[0][1])
      while waiting and not waiting[0][1]: block = block + waiting.pop(0)[0]
      if notes and whole and not waiting: return block
      self._render_run(block, 0 if waiting else below)
    return []

  def _render_run(self, run:list[Token], below:float, balanced:tuple|None=None):
    """
    One run of columns from the cursor, measured off the page first, its last page balanced,
    by `balanced` caps and pages where they were measured already.
    """
    s, pdf = self.style, self.pdf
    line = s.line_mm(s.body_size)
    pdf.keep(_START_LINES * line)
    caps, pages = balanced or self._balance(run, below, line)
    first = pdf.page_num
    pdf.columns(s.columns, gap=s.column_gap, height=caps)
    self._flow_run(run)
    pdf.columns(1)
    drawn = pdf.page_num - first + 1
    # Fewer pages than measured come from a frame, which holds one page and warns of it itself
    if caps is not None and drawn > pages:
      warnings.warn(f"columns measured on {pages} pages took {drawn}: "
        "room a header takes on new pages belongs in `pdf.headroom`, which measuring knows",
        RuntimeWarning, stacklevel=caller_level())

  def _balance(self, run:list[Token], below:float, line:float) -> tuple[float|list|None, int]:
    """
    Caps for `pdf.columns()` balancing the last page of `run` from the cursor,
    and the pages it takes then, `(None, 0)` when no cap holds it.
    `below` mm stay free under that page when they can, and otherwise it is balanced without them.

    One flow without caps gives the pages and what the last one holds,
    then its height goes up line by line from an even share of that.
    """
    pdf = self.pdf
    start, page = pdf.y, pdf.content_height
    pages, _, filled, top = self._column_flow(run, page, start, None)
    def caps(height:float) -> float|list:
      return height if pages == 1 else [None] * (pages - 1) + [height]
    tried = {} # a height drawn once serves both rooms under the columns
    def fits(height:float) -> bool:
      if height not in tried:
        done, end, _, begins = self._column_flow(run, page, start, caps(height))
        tried[height] = done == pages and end - begins <= height
      return tried[height]
    share = max(filled / self.style.columns, line)
    for under in dict.fromkeys((below, 0)):
      limit = page - top - under
      if limit < line: continue
      height = lowest_fit(fits, min(share, limit), limit, line)
      if height is not None: return caps(height), pages
    return None, 0

  def _column_flow(
    self, run:list[Token], page:float, start:float, caps:float|list|None,
  ) -> tuple[int, float, float, float]:
    """
    How `run` flows off the page in columns capped by `caps`, from `start` on pages `page` mm tall:
    the pages it takes, where its last page ends, the gap after its last block included,
    how much that page holds, as one column of it would, and where its columns begin,
    under `headroom` and the wide groups at its top.
    """
    pdf = self._flowed(run, page, start, caps).pdf
    filled = pdf.column_index * pdf.content_height + pdf.y
    top = pdf.margin_top # the sheet has no top margin: this is where the columns begin
    pdf.columns(1)
    return pdf.page_num, pdf.y, filled, top

  def _flowed(
    self, run:list[Token], page:float, start:float, caps:float|list|None,
  ) -> "MarkdownRenderer":
    """The engine off the page, `run` flowed in its columns capped by `caps` from `start`."""
    s = self.style
    probe = self._probe(self.pdf.content_width, page)
    probe.pdf.cursor(0, start)
    probe.pdf.columns(s.columns, gap=s.column_gap, height=caps)
    probe._flow_run(run)
    return probe

  #----------------------------------------------------------------------------------------- Floats

  def _flow_run(self, run:list[Token]):
    """
    `run` into the open columns, drawn or measured alike.
    Blocks waiting for the top of a frame go there as it opens,
    and at the end the narrow ones whose turn it is follow the text,
    the rest left for `_render_waiting`, so a measure counts the run alone.
    """
    with self.pdf.frames(enter=self._frame_opened):
      self._render_tokens(run, floats=self.style.floats)
      # Noted before those whose turn it is follow the text, maybe on a page of their own
      self._ended = self.pdf.page_num, bool(self._queue.narrow or self._queue.wide)
      self._queue.flush()

  def _notes_begin(self, notes:list[Token]):
    """
    The bibliography, `notes`, begins: whether blocks still wait is noted for `_notes_apart`,
    and where it ends before a frame that could take the first narrow one opens,
    the narrow ones whose turn it is stand before it instead of after its last entry.
    Such a frame is the next column, or the next page when the columns of this one miss it.
    """
    queue, pdf = self._queue, self.pdf
    self._held = bool(queue.narrow or queue.wide)
    if not queue.narrow: return
    room = pdf.content_height - pdf.y # the rest of this column
    if self._block_height(queue.narrow[0][1]) > pdf.content_height:
      room += (self.style.columns - 1 - pdf.column_index) * pdf.content_height
    if self._block_height(notes) <= room: queue.flush()

  def _frame_opened(self, pdf:PDF):
    """
    A new column or page of a run of columns: the room above its text checked,
    then the blocks waiting for its top, as the queue places them.
    """
    if pdf.column_index == 0 and pdf.page_num != self._page_seen:
      self._page_seen = pdf.page_num
      moved = pdf.page_top - pdf.headroom
      if moved > _MOVED_MM:
        raise ValueError(f"on_new_page moved the text of page {pdf.page_num} {moved:.1f}mm down "
          "while columns flow, which measuring them cannot see: give that room to `pdf.headroom`")
    self._queue.opened(pdf)

  def _defer(self, block:list[Token]) -> bool:
    """
    Whether `block`, a figure `_float_end` found, waits for the top of a frame:
    one across the page always, for the next page, and the rest behind those already waiting,
    or when they miss the rest of this column but fit a fresh one.
    """
    if self._spans(block):
      self._queue.defer_wide(block)
      return True
    return self._queue.defer(block)

  def _spans(self, block:list[Token]) -> bool:
    """
    Whether `block` goes across the page between runs of columns:
    a group opened `wide`, and with `floats` as a journal sets it,
    a table, alone or in a group, whose words a column cannot hold.
    """
    head = block[0]
    group = head.type == "html_block" and md_html.is_group_open_directive(head.content or "")
    if group and "wide" in md_html.group_options(head.content): return True
    if not self.style.floats or (not group and head.type != "table_open"): return False
    if not any(t.type == "table_open" for t in block): return False
    key = ("spans", id(head), len(block))
    if key not in self._measured:
      s, pdf = self.style, self.pdf
      column = (pdf.content_width if pdf.in_columns
        else (pdf.content_width - s.column_gap * (s.columns - 1)) / s.columns)
      probe = self._probe(column)
      with warnings.catch_warnings(): # the page warns of a table still too narrow there
        warnings.simplefilter("ignore")
        probe._render_tokens(block)
      self._measured[key] = probe._squeezed
    return self._measured[key]

  def _floats_wide(self, block:list[Token]) -> bool:
    """
    Whether `block`, set across the page, waits for the top of one:
    floating, a figure a page holds, since the queue sets it while a page opens.
    """
    return (self.style.floats and self._float_end(block, 0) is not None
      and self._block_height(block) <= self.pdf.fresh_height)

  def _block_height(self, block:list[Token]) -> float:
    """
    Height (mm) `block` takes as a top-level block in a frame this wide, drawn off the page once.
    It is measured under the top of a frame, where a heading takes the gap above it,
    so the height holds wherever the block is set.
    """
    head = block[0]
    key = ("height", id(head), len(block), round(self.pdf.content_width, 2))
    if key in self._measured: return self._measured[key]
    group = head.type == "html_block" and md_html.is_group_open_directive(head.content or "")
    inside = _group_inside(block) if group else block
    indent, self._indent_mm = self._indent_mm, 0 # a frame may open inside a list
    try:
      self._measured[key] = self._group_height(inside, _BELOW_TOP_MM)
    finally:
      self._indent_mm = indent
    return self._measured[key]

  def _draw_float(self, block:list[Token]):
    """`block` at the cursor, as a top-level block of the document, whatever it interrupted."""
    state = self._indent_mm, self._list_depth, self._in_group
    self._indent_mm, self._list_depth, self._in_group = 0, 0, False
    try:
      self.pdf.cursor(0, self.pdf.y)
      self._render_tokens(block)
    finally:
      self._indent_mm, self._list_depth, self._in_group = state

  def _probe(self, width:float, height:float|None=None) -> "MarkdownRenderer":
    """
    The engine off the page in a frame `width` × `height` mm, as `off_page` makes it,
    in this page's faces, knowing this document's headings and formula numbers,
    its first page starting as this one did and later ones under the same `headroom`.
    """
    probe = self.off_page(width, self.style, self.base_dir, str(self.pdf.fonts.font_dir), height,
      fonts=self.pdf.fonts)
    probe.pdf.headroom = self.pdf.headroom
    probe.pdf.page_top = self.pdf.page_top
    probe._known_slugs, probe._anchors = self._known_slugs, self._anchors
    probe._eq_counter, probe._after_math = self._eq_counter, self._after_math
    probe._measured = self._measured
    return probe

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
      # Matched by type and depth: the footnote plugin opens each note at level 0 too
      close_type = t.type.replace("_open", "_close")
      end = MarkdownRenderer._find_close(tokens, i, t.type, close_type) + 1
    else:
      end = i + 1
    blocks.append((i, end))
    i = end
  return blocks

def first_section(tokens:list[Token]) -> int:
  """
  Start of the first top-level `##`, `0` without one:
  where columns begin, and where a contract's preamble ends.
  """
  return next((start for start, _ in top_blocks(tokens)
    if tokens[start].type == "heading_open" and tokens[start].tag == "h2"), 0)

def closing_breaks(tokens:list[Token]) -> int:
  """
  Start of the page breaks that end `tokens`, the comments among them, `len(tokens)` without:
  a file that ends there leaves them out, as a break with nothing after it opens an empty page.
  """
  def closing(t:Token) -> bool:
    content = (t.content or "").strip()
    group = md_html.is_group_open_directive(content) or md_html.is_group_close_directive(content)
    return t.type == "html_block" and content.startswith("<!--") and not group
  end = len(tokens)
  while end and closing(tokens[end - 1]): end -= 1
  return end

def _runs(tokens:list[Token], spans) -> list[tuple[list[Token], list[Token]]]:
  """`(run, wide)` pairs: the blocks set in columns, then the block after them that `spans`."""
  runs, start = [], 0
  for begin, end in top_blocks(tokens):
    if spans(tokens[begin:end]):
      runs.append((tokens[start:begin], tokens[begin:end]))
      start = end
  runs.append((tokens[start:], []))
  return runs

def _chapters(tokens:list[Token]) -> list[list[Token]]:
  """`tokens` cut before every top-level `#` but the first block: a chapter each, on a new page."""
  parts, start = [], 0
  for begin, _ in top_blocks(tokens):
    if begin > start and tokens[begin].type == "heading_open" and tokens[begin].tag == "h1":
      parts.append(tokens[start:begin])
      start = begin
  return parts + [tokens[start:]]

def _notes_span(tokens:list[Token]) -> tuple[int, int]|None:
  """
  `(start, end)` of the bibliography among `tokens`, `None` without one:
  its entries, and the heading right above them where the document titles them itself.
  """
  blocks = top_blocks(tokens)
  for k, (begin, end) in enumerate(blocks):
    if tokens[begin].type != "footnote_block_open": continue
    titled = k > 0 and tokens[blocks[k - 1][0]].type == "heading_open"
    return (blocks[k - 1][0] if titled else begin), end
  return None

def _breaks(block:list[Token]) -> bool:
  """Whether `block` is a page break directive."""
  head = block[0]
  return head.type == "html_block" and md_html.is_pagebreak_directive(head.content or "")

def _sets_anything(run:list[Token]) -> bool:
  """Whether `run` holds more than comments, which draw nothing."""
  def silent(t:Token) -> bool:
    content = t.content or ""
    return (t.type == "html_block" and not md_html.is_hr_block(content)
      and not md_html.is_pagebreak_directive(content))
  return not all(silent(t) for t in run)

def _figure(group:list[Token]) -> bool:
  """
  Whether the blocks of a group set a figure: a picture, a table or a listing with its caption,
  and no heading, which belongs to the text under it.
  """
  shown = any(t.type in ("table_open", "fence", "code_block")
    or (t.type == "inline" and MarkdownRenderer._is_image_only_inline(t)) for t in group)
  return shown and not any(t.type == "heading_open" for t in group)

def _group_inside(group:list[Token]) -> list[Token]:
  """The blocks of a `<!-- group -->` through its `<!-- /group -->`, one left unclosed included."""
  closed = len(group) > 1 and md_html.is_group_close_directive(group[-1].content or "")
  return group[1:-1] if closed else group[1:]
