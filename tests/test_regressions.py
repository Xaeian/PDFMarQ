# tests/test_regressions.py

"""
Guards for rendering invariants that are cheap to break.

Every check here answers one question: does the document that comes out hold
everything that went in, at the size and place it belongs? Stdlib `unittest`
only. Text-extraction checks need PyMuPDF (`fitz`) and skip without it.

  >>> python -m pytest tests/test_regressions.py
"""

import os, re, tempfile, unittest, warnings

from pdfmarq import PDF, TextMetrics, FontManager, TableBuilder, TableStyle, smaller_size
from pdfmarq.md import MarkdownRenderer, MarkdownStyle
from conftest import (render_md, pdf_text, pdf_pages, pdf_offpage_words,
  has_mathjax)

try:
  import fitz # PyMuPDF
except ImportError:
  fitz = None

MIDDLE_DOT = "·"
PILCROW = "¶"
NEEDS_FITZ = unittest.skipIf(fitz is None, "PyMuPDF not installed")
NEEDS_MATHJAX = unittest.skipUnless(has_mathjax(), "MathJax not installed")

class TempPDFCase(unittest.TestCase):
  """Base case giving each test a private directory to write PDFs into."""
  def setUp(self):
    self._tmp = tempfile.TemporaryDirectory()

  def tearDown(self):
    self._tmp.cleanup()

  def path(self, name:str="out.pdf") -> str:
    return os.path.join(self._tmp.name, name)

#------------------------------------------------------------------------------------ Text fidelity

class TestMiddleDot(TempPDFCase):
  """`·` is ordinary text - Polish typography, unit and list separators. Text
  measurement and table fitting have to hand it back unchanged."""

  def test_box_fit_keeps_middle_dot(self):
    result = TextMetrics(FontManager()).box_fit(f"a {MIDDLE_DOT} b", 300)
    self.assertIn(MIDDLE_DOT, result.text)
    self.assertNotIn(PILCROW, result.text)

  @NEEDS_FITZ
  def test_table_cell_keeps_middle_dot(self):
    p = self.path()
    with PDF(p) as pdf:
      pdf.table([[f"x {MIDDLE_DOT} y"]])
    self.assertIn(MIDDLE_DOT, pdf_text(p))
    self.assertNotIn(PILCROW, pdf_text(p))

#------------------------------------------------------------------------------------------- Saving

class TestIdempotentSave(TempPDFCase):
  """`save()` is the documented way to finish a document and `with` calls it on
  exit, so calling it twice has to be harmless."""

  def test_with_block_plus_explicit_save(self):
    p = self.path()
    with PDF(p) as pdf:
      pdf.text("hello")
      pdf.save()
    self.assertTrue(os.path.exists(p))

  def test_double_save_is_noop(self):
    pdf = PDF(self.path())
    pdf.text("hello")
    pdf.save()
    pdf.save()

#------------------------------------------------------------------------ Blocks across page breaks

class TestBlockSplitting(TempPDFCase):
  """A block longer than the page belongs on several pages. Anything drawn
  below the page bottom sits outside the MediaBox and no reader ever sees it."""

  LINES = 200

  @NEEDS_FITZ
  def test_long_code_block_stays_on_pages(self):
    code = "\n".join(f"line_{i} = compute(value_{i})" for i in range(self.LINES))
    p = self.path()
    render_md(p, "# T\n\n```python\n" + code + "\n```\n")
    body = pdf_text(p)
    self.assertEqual([], pdf_offpage_words(p))
    for i in (0, self.LINES // 2, self.LINES - 1):
      self.assertIn(f"line_{i}", body)

  @NEEDS_FITZ
  def test_long_paragraph_stays_on_pages(self):
    para = " ".join(f"word{i}" for i in range(3000))
    p = self.path()
    render_md(p, "# T\n\n" + para + "\n")
    body = pdf_text(p)
    self.assertEqual([], pdf_offpage_words(p))
    for token in ("word0", "word1500", "word2999"):
      self.assertIn(token, body)

  def test_cursor_never_leaves_the_page(self):
    code = "\n".join(f"line_{i} = x" for i in range(self.LINES))
    pdf = render_md(self.path(), "```\n" + code + "\n```\n")
    self.assertLessEqual(pdf.y, pdf.content_height)

  @NEEDS_FITZ
  def test_block_that_fits_is_left_whole(self):
    """Splitting is for oversized blocks only - a short document stays on one page."""
    p = self.path()
    render_md(p, "# H\n\nShort paragraph.\n\n```py\nx = 1\n```\n")
    self.assertEqual(1, pdf_pages(p))

#---------------------------------------------------------------------------------------- Footnotes

class TestMultiBlockFootnote(TempPDFCase):
  """A footnote definition can hold several blocks. All of them belong in the
  rendered note, and the smaller bibliography style stays inside it."""

  MD = (
    "Body ref[^1] here.\n\n"
    "[^1]: FIRSTBLOCK of the note.\n\n"
    "    SECONDBLOCK continues it.\n\n"
    "    - LISTITEMA\n"
    "    - LISTITEMB\n"
  )

  @NEEDS_FITZ
  def test_all_blocks_rendered(self):
    p = self.path()
    render_md(p, self.MD)
    body = pdf_text(p)
    for token in ("FIRSTBLOCK", "SECONDBLOCK", "LISTITEMA", "LISTITEMB"):
      self.assertIn(token, body)

  @NEEDS_FITZ
  def test_body_style_survives_the_footnote(self):
    style = MarkdownStyle()
    size, color = style.body_size, style.body_color
    render_md(self.path(), self.MD, style)
    self.assertEqual(size, style.body_size)
    self.assertEqual(color, style.body_color)

#-------------------------------------------------------------------------------------- Inline math

class TestInlineMathSize(TempPDFCase):
  """A formula is rasterized at the size it is asked for and cannot be rescaled
  afterwards, so it has to be rendered at the size of its surroundings."""

  def test_math_font_size_follows_context(self):
    import pdfmarq.md.math as math_mod
    sizes = []
    render_math = math_mod.render_math_svg_with_baseline

    def spy(formula, fontsize=11, **kwargs):
      sizes.append(fontsize)
      return render_math(formula, fontsize=fontsize, **kwargs)

    math_mod.render_math_svg_with_baseline = spy
    style = MarkdownStyle()
    try:
      render_md(self.path(), (
        "Body $a^2$ here.\n\n"
        "# Heading $b^2$\n\n"
        "| c | f |\n|---|---|\n| x | $c^2$ |\n"
      ), style)
    finally:
      math_mod.render_math_svg_with_baseline = render_math
    if not sizes:
      self.skipTest("matplotlib not installed - no math rendered")
    cell_size = (style.table_size if style.table_size is not None
      else smaller_size(style.body_size))
    self.assertEqual([style.body_size, style.h1_size, cell_size], sizes)

#-------------------------------------------------------------------------------------- Page chrome

class TestRepeatedRender(TempPDFCase):
  """Header and footer callbacks belong to the renderer, not to a single
  `render_md()` call, so repeated calls draw one set of page chrome."""

  def test_callbacks_registered_once(self):
    pdf = PDF(self.path())
    renderer = MarkdownRenderer(pdf, MarkdownStyle())
    renderer.render("# One\n\nAlpha.\n")
    renderer.render("# Two\n\nBeta.\n")
    pdf.save()
    self.assertEqual(1, len(pdf._page_callbacks))
    self.assertEqual(1, len(pdf._new_page_callbacks))

  @NEEDS_FITZ
  def test_single_footer_per_page(self):
    p = self.path()
    pdf = PDF(p)
    renderer = MarkdownRenderer(pdf, MarkdownStyle())
    renderer.render("# One\n\nAlpha.\n")
    renderer.render("# Two\n\nBeta.\n")
    pdf.save()
    self.assertEqual(1, pdf_text(p).count("Page 1/"))

#-------------------------------------------------------------------------------------- Frontmatter

class TestFrontmatterWarning(TempPDFCase):
  """Frontmatter carries the title and author. A block that cannot be parsed is
  dropped, and dropping it silently loses that metadata without a trace."""

  def renderer(self) -> MarkdownRenderer:
    return MarkdownRenderer(PDF(self.path()), MarkdownStyle())

  def test_leading_rule_keeps_its_content(self):
    """A document may open with a horizontal rule. Only a YAML mapping is
    frontmatter; everything down to the next `---` is ordinary content."""
    renderer = self.renderer()
    data, rest = renderer._extract_frontmatter(
      "---\n# Intro\nBODYTEXT here\n---\n# Section 2\n")
    self.assertIsNone(data)
    for marker in ("Intro", "BODYTEXT", "Section 2"):
      self.assertIn(marker, rest)

  def test_real_frontmatter_is_still_consumed(self):
    renderer = self.renderer()
    data, rest = renderer._extract_frontmatter(
      "---\ntitle: Doc\nauthor: sara\n---\n\nBODYTEXT.\n")
    self.assertEqual("Doc", data["title"])
    self.assertIn("BODYTEXT", rest)
    self.assertNotIn("author: sara", rest)

  def test_broken_yaml_warns(self):
    with warnings.catch_warnings(record=True) as caught:
      warnings.simplefilter("always")
      data, _ = self.renderer()._extract_frontmatter(
        "---\ntitle: Test\n  bad: [unclosed\n---\n\nBody.\n")
    self.assertIsNone(data)
    self.assertTrue(any("frontmatter" in str(w.message) for w in caught))

  def test_valid_yaml_is_quiet(self):
    with warnings.catch_warnings(record=True) as caught:
      warnings.simplefilter("always")
      data, _ = self.renderer()._extract_frontmatter(
        "---\ntitle: Test\nauthor: sara\n---\n\nBody.\n")
    self.assertEqual("Test", data["title"])
    self.assertEqual([], [w for w in caught if "frontmatter" in str(w.message)])

#------------------------------------------------------------------------------------------ Anchors

class TestAnchors(TempPDFCase):
  """A destination names a place in the document. Fitting the whole page
  instead drops the one thing the reader followed the link for."""

  MD = ("## Ustawienia\n\nPierwsza.\n\n## Ustawienia\n\nDruga.\n\n"
    "[pierwsza](#ustawienia) [druga](#ustawienia-1) [brak](#nie-ma-takiego)\n")

  @NEEDS_FITZ
  def test_links_carry_a_position(self):
    p = self.path()
    render_md(p, self.MD)
    doc = fitz.open(p)
    try:
      links = [l for page in doc for l in page.get_links()]
      self.assertEqual(2, len(links), "unknown anchors must not linkify")
      ys = {round(l["to"].y, 1) for l in links}
      self.assertEqual(2, len(ys), f"both links point at the same spot: {ys}")
    finally:
      doc.close()

  def test_repeated_heading_gets_its_own_slug(self):
    pdf = PDF(self.path())
    renderer = MarkdownRenderer(pdf, MarkdownStyle())
    renderer.render(self.MD)
    pdf.save()
    self.assertEqual({"ustawienia", "ustawienia-1"}, renderer._known_slugs)

  @NEEDS_FITZ
  def test_outline_entry_carries_a_position(self):
    p = self.path()
    pdf = PDF(p)
    pdf.text("Rozdzial 1").bookmark("Rozdzial 1")
    pdf.enter(120).text("Rozdzial 2").bookmark("Rozdzial 2")
    pdf.save()
    doc = fitz.open(p)
    try:
      tops = [entry[3]["to"].y for entry in doc.get_toc(simple=False)]
      self.assertEqual(2, len(tops))
      self.assertNotEqual(tops[0], tops[1], "both entries land in one spot")
    finally:
      doc.close()

#------------------------------------------------------------------------------------- Highlighting

class TestMarkdownHighlighting(unittest.TestCase):
  """Inside a fence the language is no longer markdown: `# x` is a comment
  there and `- x` a flag, so neither takes markdown colouring."""

  SRC = "# Heading\n\n```python\n# comment\n- not a list\n```\n\n- real list\n"

  def colors(self):
    from pdfmarq.md.highlight import highlight_code
    lines = highlight_code(
      self.SRC, "markdown", family="Courier", mode="Regular",
      bold_mode="Bold", size=9, default_color=(0, 0, 0), theme=None)
    return [{tuple(round(c, 2) for c in seg.color)
      for seg in line if seg.text.strip()} for line in lines]

  def test_fence_body_is_left_plain(self):
    rows = self.colors()
    plain = {(0.0, 0.0, 0.0)}
    self.assertEqual(plain, rows[3], "comment inside a fence was coloured")
    self.assertEqual(plain, rows[4], "dash inside a fence was coloured")

  def test_markdown_outside_the_fence_still_colours(self):
    rows = self.colors()
    self.assertGreater(len(rows[0]), 1, "heading lost its colour")
    self.assertGreater(len(rows[7]), 1, "list marker lost its colour")

#---------------------------------------------------------------------------------------- Autoscale

class TestAutoscaleFloor(unittest.TestCase):
  """Autoscale keeps shrinking until the text fits, and past a point the
  result is unreadable. The size is what it is; saying so is the fix."""

  def test_unreadable_shrink_warns_and_reports_overflow(self):
    metrics = TextMetrics(FontManager())
    with warnings.catch_warnings(record=True) as caught:
      warnings.simplefilter("always")
      fit = metrics.box_fit(
        "bardzo dlugi tekst ktory nie zmiesci sie w tej malej komorce nijak",
        30, 12, autoscale=0.1)
    self.assertLess(fit.font_size, 5.0)
    self.assertTrue(fit.overflow)
    self.assertTrue(any("readable" in str(w.message) for w in caught))

  def test_normal_fit_stays_quiet(self):
    metrics = TextMetrics(FontManager())
    with warnings.catch_warnings(record=True) as caught:
      warnings.simplefilter("always")
      fit = metrics.box_fit("krotki tekst", 200, 40, autoscale=0.1)
    self.assertFalse(fit.overflow)
    self.assertEqual([], [w for w in caught if "readable" in str(w.message)])

#-------------------------------------------------------------------------------- Math line metrics

class TestMathLineBox(TempPDFCase):
  """A formula taller than its font size still has to fit the line it sits on,
  or it crosses into the next one - in a table, past the row border."""

  TALL = (r"\sum_{k=1}^{n} k", r"\sqrt{\frac{1}{n}\sum_i (x_i-\mu)^2}",
    r"\int_0^\infty e^{-x^2} dx")

  def line_height_for(self, tex:str, size:float) -> tuple[float, float]:
    from pdfmarq.inline import measure_rich, RichSegment
    from pdfmarq.md.math import render_math_svg_with_baseline
    from pdfmarq.constants import MM_TO_PT
    drawing, base = render_math_svg_with_baseline(tex, fontsize=size)
    if drawing is None:
      self.skipTest("matplotlib not installed")
    seg = RichSegment(
      text="", family="Helvetica", mode="Regular", size=size, color=(0, 0, 0),
      math_drawing=drawing, math_width_pt=float(drawing.width),
      math_baseline_from_bottom_pt=float(base))
    pdf = PDF(self.path())
    return float(drawing.height), measure_rich(pdf, [seg], 60, line_gap=1.4) * MM_TO_PT

  def test_tall_formula_gets_a_line_that_holds_it(self):
    for tex in self.TALL:
      drawing_h, line_h = self.line_height_for(tex, 10)
      self.assertGreaterEqual(line_h, drawing_h - 0.01, f"{tex} overflows its line")

  def test_short_formula_leaves_the_line_alone(self):
    _, line_h = self.line_height_for("E = mc^2", 10)
    self.assertAlmostEqual(14.0, line_h, places=6)

#----------------------------------------------------------------------------------- SVG flattening

class TestSvgFlatten(unittest.TestCase):
  """MathJax builds a stretchy brace inside nested `<svg>` viewports and svglib
  does not reproduce that coordinate system, so the geometry is resolved to
  absolute coordinates before svglib sees it."""

  def flat(self, svg:str):
    from pdfmarq.md.svgflat import flatten
    return flatten(svg)

  HEAD = ('<svg xmlns="http://www.w3.org/2000/svg" width="200pt" height="100pt" '
    'viewBox="0 0 200 100">')

  def test_nested_viewport_becomes_absolute(self):
    """A nested viewport places and scales its content; both must survive."""
    svg = (self.HEAD + '<svg width="50" height="20" x="100" y="10" '
      'viewBox="0 0 100 40"><path d="M0 0 L100 0 L100 40 Z"/></svg></svg>')
    out = self.flat(svg)
    self.assertIsNotNone(out)
    self.assertEqual(0, out.count("transform="))
    self.assertEqual(1, out.count("<svg"), "nested viewport still present")
    # x: 100 + 0..100 * (50/100) -> 100..150; y: 10 + 0..40 * (20/40) -> 10..30
    self.assertIn("100 10", out)
    self.assertIn("150 30", out)

  def test_transforms_compose_parent_first(self):
    svg = (self.HEAD + '<g transform="translate(10,0)">'
      '<path d="M0 0 L100 0" transform="scale(0.5,1)"/></g></svg>')
    out = self.flat(svg)
    self.assertIsNotNone(out)
    self.assertIn("M 10 0 L 60 0", out.replace("  ", " "))

  def test_unknown_construct_is_refused(self):
    """A shape outside the supported set returns None, so the caller keeps
    the original rather than getting a silently wrong drawing."""
    svg = self.HEAD + '<circle cx="10" cy="10" r="5"/></svg>'
    self.assertIsNone(self.flat(svg))

  def test_relative_path_command_is_refused(self):
    svg = self.HEAD + '<path d="M0 0 l100 0"/></svg>'
    self.assertIsNone(self.flat(svg))

  def test_substitute_glyph_keeps_its_place(self):
    """A character its font lacks arrives as `text` rather than a path.

    Refusing it would put the whole formula back on svglib, which is how one
    missing symbol turns into a scrambled line.
    """
    svg = (self.HEAD + '<g transform="translate(20,30) scale(2,2)">'
      '<text font-size="10" font-family="serif">x</text></g></svg>')
    out = self.flat(svg)
    self.assertIsNotNone(out)
    self.assertIn('x="20"', out)
    self.assertIn('y="30"', out)
    self.assertIn('font-size="20"', out)

  def test_mirrored_text_is_refused(self):
    """A flipped frame would print the substitute backwards."""
    svg = (self.HEAD + '<g transform="scale(1,-1)">'
      '<text font-size="10">x</text></g></svg>')
    self.assertIsNone(self.flat(svg))

#--------------------------------------------------------------------------------- MathJax fonts

@NEEDS_MATHJAX
class TestMathJaxFonts(unittest.TestCase):
  """Every font the library offers has to carry a formula all the way to a
  drawing. A font package that is not installed is not offered, and one that
  is must survive both MathJax and the flattener.
  """

  # `<` is the interesting character: MathJax repeats the source TeX in a
  # `data-latex` attribute, where a raw `<` is not XML and costs the parse.
  CASES = r"\begin{cases} a & x < 0 \\ b & x \ge 0 \end{cases}"

  def test_offered_fonts_are_installed(self):
    from pdfmarq.md.mathjax import FONTS, DEFAULT_FONT, installed_fonts
    self.assertIn(DEFAULT_FONT, installed_fonts())
    self.assertLessEqual(set(installed_fonts()), set(FONTS))

  def test_every_installed_font_flattens_a_cases_block(self):
    from pdfmarq.md.mathjax import installed_fonts, render_batch
    from pdfmarq.md.svgflat import flatten
    job = (self.CASES, True)
    for font in installed_fonts():
      with self.subTest(font=font):
        svg = render_batch([job], font=font).get(job)
        self.assertIsNotNone(svg, "MathJax rendered nothing")
        self.assertIsNotNone(flatten(svg), "fell back to svglib")

  def test_no_font_leaves_an_empty_box(self):
    """A character the font lacks would reach the page as a system-face
    substitute, which reportlab has no font for either. The formula moves to
    the default typeface instead.
    """
    from pdfmarq.md.mathjax import installed_fonts, render
    for font in installed_fonts():
      with self.subTest(font=font):
        with warnings.catch_warnings():
          warnings.simplefilter("ignore")
          svg = render(r"A \square B", display=True, font=font)
        self.assertIsNotNone(svg)
        self.assertIsNone(re.search(r"<text\b", svg))

  def test_a_missing_font_falls_back_with_a_warning(self):
    from pdfmarq.md.mathjax import DEFAULT_FONT, resolve_font
    with warnings.catch_warnings(record=True) as caught:
      warnings.simplefilter("always")
      self.assertEqual(DEFAULT_FONT, resolve_font("nosuchfont"))
    self.assertEqual(1, len(caught))

#----------------------------------------------------------------------------------- Math preparing

class TestMathPreprocess(unittest.TestCase):
  """mathtext accepts a subset of LaTeX and renders what it cannot parse as the
  source text itself, which is why what reaches it gets normalised first."""

  def prep(self, formula:str) -> str:
    from pdfmarq.md.math import _preprocess_formula
    return _preprocess_formula(formula)

  def test_line_breaks_collapse(self):
    """A `$$` block spans source lines; math mode reads those as spaces."""
    self.assertEqual("x = 1 y = 2", self.prep("x = 1\n  y = 2\n"))

  def test_unsupported_spellings_are_swapped(self):
    self.assertEqual(r"\leq 3", self.prep(r"\le 3"))
    self.assertEqual(r"\geq 3", self.prep(r"\ge 3"))
    self.assertEqual(r"\underline{x}_{y}", self.prep(r"\underbrace{x}_{y}"))
    self.assertEqual(r"\overline{x}^{y}", self.prep(r"\overbrace{x}^{y}"))

  def test_longer_commands_are_left_alone(self):
    """`\\le` must not bite into `\\leq`, `\\left` or `\\leftarrow`."""
    for keep in (r"\leq x", r"\left| x \right|", r"\leftarrow", r"\ell"):
      self.assertEqual(keep, self.prep(keep))

  def test_shapes_that_used_to_come_out_as_source(self):
    from pdfmarq.md.math import render_math_svg
    cases = (
      r"\le 3\mathrm{mA}",
      r"|Z| = \frac{|D_a|}{|D_b|} \cdot R, \qquad" "\n" r"\varphi = \varphi_a - \varphi_b",
      r"V = \underbrace{\frac{V_b}{|Z|} R}_{\text{stale}}" "\n" r"\; \pm \; A",
    )
    for formula in cases:
      drawing = render_math_svg(formula, fontsize=12)
      if drawing is None:
        self.skipTest("matplotlib not installed")
      # Literal source comes out several times wider than the formula it spells.
      self.assertLess(drawing.width, 300, f"looks like literal source: {formula!r}")

#--------------------------------------------------------------------------------- Math block width

class TestMathBlockWidth(TempPDFCase):
  """A block formula is centred in the column. One wider than the column would
  centre to a negative offset and hang off both edges of the page."""

  # No line break, no unsupported command - just longer than the column, which
  # for A4 with default margins is a bit under 482pt.
  WIDE = "$$\n" + " + ".join(r"\frac{V_{%d}}{R_{%d}}" % (i, i) for i in range(22)) + "\n$$\n"

  def ink_outside_page(self, path:str) -> int:
    doc = fitz.open(path)
    try:
      outside = 0
      for page in doc:
        box = page.rect
        for drawing in page.get_drawings():
          r = drawing["rect"]
          if r.x0 < -1 or r.x1 > box.width + 1:
            outside += 1
      return outside
    finally:
      doc.close()

  @NEEDS_FITZ
  def test_overlong_formula_is_scaled_onto_the_page(self):
    p = self.path()
    with warnings.catch_warnings(record=True) as caught:
      warnings.simplefilter("always")
      render_md(p, self.WIDE)
    self.assertEqual(0, self.ink_outside_page(p), "formula ink passes the page edge")
    self.assertTrue(any("scaled to fit" in str(w.message) for w in caught))

  @NEEDS_FITZ
  def test_multiline_block_needs_no_scaling(self):
    """A `$$` block written across source lines is an ordinary formula once the
    breaks collapse, so it fits like any other."""
    p = self.path()
    md = ("$$\n"
      r"V_{\mathrm{TIA}} = \underbrace{\frac{V_{\mathrm{bias}}}{|Z|} R_{\mathrm{TIA}}}"
      r"_{\text{od biasu}}" "\n" r"\; \pm \; \underbrace{\frac{A}{|Z|} R}_{\text{sinus}}"
      "\n$$\n")
    with warnings.catch_warnings(record=True) as caught:
      warnings.simplefilter("always")
      render_md(p, md)
    self.assertEqual(0, self.ink_outside_page(p))
    self.assertEqual([], [w for w in caught if "scaled to fit" in str(w.message)])

  @NEEDS_FITZ
  def test_ordinary_formula_is_not_scaled(self):
    p = self.path()
    with warnings.catch_warnings(record=True) as caught:
      warnings.simplefilter("always")
      render_md(p, "$$\nE = mc^2\n$$\n")
    self.assertEqual([], [w for w in caught if "scaled to fit" in str(w.message)])

#-------------------------------------------------------------------------------------------- Emoji

class TestEmojiSplit(unittest.TestCase):
  """Modifier codepoints have no glyph of their own. They tune the emoji before
  them and must not become a second drawing next to it."""

  def test_skin_tone_modifier_is_skipped(self):
    from pdfmarq.md.openmoji import split_text_by_emoji
    runs = split_text_by_emoji("ok \U0001F44D\U0001F3FE end")
    self.assertEqual(["\U0001F44D"], [frag for frag, is_emoji in runs if is_emoji])

  def test_zwj_and_variation_selectors_are_skipped(self):
    from pdfmarq.md.openmoji import split_text_by_emoji
    self.assertEqual([("ab", False)], split_text_by_emoji("a️‍b"))

#------------------------------------------------------------------------------------------- Tables

class TestTableTotalHeight(unittest.TestCase):
  """`TableData.total_height` is what a caller reserves for the table, so it has
  to match every band `core._draw_table` puts on the page."""

  def test_total_height_includes_header_gap(self):
    style = TableStyle()
    builder = TableBuilder(TextMetrics(FontManager()), style)
    builder.header(["a", "b"]).row(["1", "2"]).row(["3", "4"])
    data = builder.build(available_width=100)
    expected = data.header_height + style.header_gap + sum(data.body_heights)
    self.assertAlmostEqual(expected, data.total_height, places=6)

if __name__ == "__main__":
  unittest.main(verbosity=2)
