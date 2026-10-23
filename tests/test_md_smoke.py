# tests/test_md_smoke.py

"""Markdown rendering smoke: feed small samples through `md_to_pdf`, verify valid PDF."""

import warnings
from pathlib import Path
import pytest
from conftest import assert_valid_pdf, needs_fitz, pdf_pages, pdf_text
from pdfmarq import GlyphWarning
from pdfmarq.paper import md_to_pdf, PaperStyle, lang_style
from pdfmarq.constants import A4

#----------------------------------------------------------------------------------------- Markdown

@pytest.mark.parametrize("name, src", [
  ("minimal", "# Title\n\nHello world."),
  ("headings", "# H1\n## H2\n### H3\n#### H4\n##### H5\n###### H6\n\nbody"),
  ("emphasis",
    "Plain text with **bold**, *italic*, ***both***, `inline code`, "
    "~~strike~~ and a [link](https://example.com).\n\nSecond paragraph here."),
  ("lists",
    "- item one\n- item two\n  - nested\n  - nested 2\n- item three\n\n"
    "1. ordered\n2. ordered\n3. ordered\n"),
  ("code_block",
    "Inline `x = 1` and fenced:\n\n```python\ndef foo():\n  return 42\n```\n"),
  ("table",
    "| Col A | Col B | Col C |\n|-------|------:|:-----:|\n"
    "| a     |    1  |   x   |\n| bbbb  |   22  |  yy   |\n"),
  ("blockquote", "> a quote\n> spanning two lines\n\nNext para."),
  ("github_callout",
    "> [!NOTE]\n> Note callout.\n\n> [!WARNING]\n> Be careful.\n"),
  ("hr", "a\n\n---\n\nb"),
  ("frontmatter",
    "---\ntitle: Doc\nauthor: Xaeian\nsubject: smoke\nkeywords: [a, b]\n---\n\n"
    "# Doc\n\nBody."),
  ("empty_string", ""), # edge: empty input must not blow up
  ("inline_math", "Pythagoras: $a^2 + b^2 = c^2$ done.\n\n$$ E = mc^2 $$\n"),
])
def md_constructs_render_valid_pdf(tmp_path, name, src):
  path = tmp_path / f"{name}.pdf"
  md_to_pdf(src, str(path))
  assert_valid_pdf(path)

def md_internal_anchor_link_guards_against_dangling_target(tmp_path):
  # `[x](#slug)` becomes a click target only when `slug` is a real heading,
  # else reportlab crashes at save. `_collect_heading_slugs` pre-scan guards it.
  path = tmp_path / "anchor.pdf"
  src = (
    "# Top heading\n\nJump to [there](#another-heading) or [ghost](#nope).\n\n"
    "## Another heading\n\nTarget."
  )
  md_to_pdf(src, str(path))
  assert_valid_pdf(path)

def md_long_doc_renders_multipage(tmp_path):
  # force multi-page render: exercises NumberedCanvas replay + page chrome
  path = tmp_path / "long.pdf"
  lorem = "Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 6
  src = "# Long\n\n" + "\n\n".join([lorem] * 30)
  md_to_pdf(src, str(path))
  assert_valid_pdf(path)

def md_custom_style_applies(tmp_path):
  path = tmp_path / "styled.pdf"
  style = PaperStyle(body_size=10, head_gap_top=8, table_zebra=False)
  md_to_pdf("# H\n\nbody", str(path), style=style)
  assert_valid_pdf(path)

@needs_fitz
@pytest.mark.parametrize("label, title", [
  (None, None), ("Bibliografia", "Bibliografia"), (True, "Literatura"),
], ids=["rule", "own word", "language word"])
def md_footnote_label_titles_the_bibliography(tmp_path, label, title):
  # a rule by default, or a title: the style's own word, or its language's with `True`,
  # which starts no page of its own: a page break is the author's, put where it is wanted
  path = str(tmp_path / "fn.pdf")
  style = lang_style("pl", footnote_label=label)
  md_to_pdf("Body[^1].\n\n[^1]: footnote text.", path, style=style)
  titles = {"Literatura", "Bibliografia", "References"} & set(pdf_text(path).split())
  assert titles == ({title} if title else set())
  assert pdf_pages(path) == 1

def md_page_landscape_flips_page(tmp_path):
  # orientation comes from `page=`, never from the document
  path = tmp_path / "landscape.pdf"
  pdf = md_to_pdf("# Wide content", str(path), page=A4.landscape())
  assert pdf.page_width > pdf.page_height
  assert_valid_pdf(path)

def md_base_dir_resolves_relative_image(tmp_path):
  # real image one dir over; `base_dir=` finds it without a chdir
  from PIL import Image
  img_dir = tmp_path / "assets"
  img_dir.mkdir()
  Image.new("RGB", (10, 10), (200, 100, 50)).save(img_dir / "x.png")
  src = "# Doc\n\n![alt](assets/x.png)"
  path = tmp_path / "img.pdf"
  md_to_pdf(src, str(path), base_dir=str(tmp_path))
  assert_valid_pdf(path)

def md_two_renderers_keep_independent_fontsets(tmp_path):
  # each renderer keeps its own `MathFontConfig` and applies it just before rendering,
  # so renderers never clobber each other through the global `mathtext.fontset`
  src = "$x^2 + 1$"
  md_to_pdf(src, str(tmp_path / "stix.pdf"), style=PaperStyle(math_fontset="stix"))
  md_to_pdf(src, str(tmp_path / "cm.pdf"), style=PaperStyle(math_fontset="cm"))
  md_to_pdf(src, str(tmp_path / "stix2.pdf"), style=PaperStyle(math_fontset="stix"))
  for name in ("stix.pdf", "cm.pdf", "stix2.pdf"):
    assert_valid_pdf(tmp_path / name)

#--------------------------------------------------------------------------- Math tags & delimiters

def pop_tag_extracts_the_label():
  from pdfmarq.md.math import pop_tag
  assert pop_tag(r"E = I R \tag{X1.1}") == ("E = I R", "(X1.1)")
  assert pop_tag("x^2") == ("x^2", None)

def pop_tag_star_keeps_the_label_bare():
  from pdfmarq.md.math import pop_tag
  assert pop_tag(r"a + b \tag*{7a}") == ("a + b", "7a")

def bracket_block_becomes_dollar_block():
  from pdfmarq.md.md_preprocess import normalize_math_delimiters as norm
  assert norm("\\[\nE = I R\n\\]") == "$$\nE = I R\n$$"

def bracket_block_on_one_line_expands():
  from pdfmarq.md.md_preprocess import normalize_math_delimiters as norm
  assert norm(r"\[ E = I R \]") == "$$\nE = I R\n$$"

def bracket_inline_becomes_dollars():
  from pdfmarq.md.md_preprocess import normalize_math_delimiters as norm
  assert norm(r"wzor \( x^2 \) w zdaniu") == "wzor $x^2$ w zdaniu"

def fenced_code_keeps_its_backslashes():
  from pdfmarq.md.md_preprocess import normalize_math_delimiters as norm
  src = "```\n" + r"\[ nie ruszac \]" + "\n```"
  assert norm(src) == src

def inline_code_keeps_its_backslashes():
  from pdfmarq.md.md_preprocess import normalize_math_delimiters as norm
  src = r"tekst `\( kod \)` dalej"
  assert norm(src) == src

def tagged_block_renders_with_its_own_label(tmp_path):
  # `\tag{...}` must never reach the engine:
  # MathJax draws it as a giant glyph across the page, mathtext falls back to a code block
  pytest.importorskip("fitz", reason="PyMuPDF not installed")
  from conftest import pdf_text
  src = "$$\nE = I R\n" + r"\tag{X1.1}" + "\n$$"
  path = tmp_path / "tag.pdf"
  md_to_pdf(src, str(path))
  assert_valid_pdf(path)
  text = pdf_text(str(path))
  assert "(X1.1)" in text, f"tag label missing from page: {text!r}"
  assert "(1)" not in text, "auto number printed alongside an explicit tag"

def math_with_no_engine_says_so(tmp_path, monkeypatch):
  # no MathJax and no matplotlib: formulas stay as code, and a warning names the package
  import pdfmarq.md.math as math, pdfmarq.md.mathjax as mathjax
  from pdfmarq._warn import reset_warnings
  monkeypatch.setattr(math, "_HAS_MATPLOTLIB", False)
  monkeypatch.setattr(mathjax, "available", lambda: False)
  reset_warnings()
  path = tmp_path / "plain.pdf"
  with pytest.warns(RuntimeWarning, match="pip install matplotlib") as caught:
    md_to_pdf("$$\nE = mc^2\n$$\n\nInline $x^2$ too.\n", str(path))
  assert_valid_pdf(path)
  # the warning points at the line that asked for the document, not into the library
  assert {Path(w.filename).name for w in caught if "matplotlib" in str(w.message)} == {
    Path(__file__).name}

def mermaid_block_reaches_its_renderer(tmp_path):
  # with no mmdc and the network off the diagram stays a code block, which still has to draw
  path = tmp_path / "mermaid.pdf"
  md_to_pdf("```mermaid\nflowchart LR\n  A --> B\n```\n", str(path),
    style=PaperStyle(mermaid_remote=False))
  assert_valid_pdf(path)

def default_fonts_draw_polish(tmp_path):
  # DejaVu comes from the system or from matplotlib.
  # Vera and Courier would draw ą ę ś ź ż ń as boxes.
  pytest.importorskip("matplotlib")
  fitz = pytest.importorskip("fitz")
  path = tmp_path / "pl.pdf"
  with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    md_to_pdf("Letters ą ę ś ź ż ń, `code: ą ę ś`\n\n```\nblock: ź ż ń\n```\n", str(path))
  assert not [w for w in caught if issubclass(w.category, GlyphWarning)]
  page = fitz.open(str(path))[0]
  text = page.get_text()
  assert "Letters ą ę ś ź ż ń" in text and "block: ź ż ń" in text and "\x00" not in text
  assert {font[3].split("+")[-1] for font in page.get_fonts()} >= {"DejaVuSans", "DejaVuSansMono"}

def missing_glyph_warns_once_at_the_calling_line(tmp_path):
  # DejaVu has no kanji: each draws as an empty box, said once however often it comes
  pytest.importorskip("matplotlib")
  from pdfmarq._warn import reset_warnings
  reset_warnings()
  with pytest.warns(GlyphWarning) as caught:
    md_to_pdf("Kanji 漢, and 漢 again.\n", str(tmp_path / "kanji.pdf"))
  glyphs = [w for w in caught if issubclass(w.category, GlyphWarning)]
  assert [str(w.message) for w in glyphs] \
    == ["DejaVuSans-Regular has no glyph for '漢' (U+6F22), drawn as an empty box"]
  assert Path(glyphs[0].filename).name == Path(__file__).name

def fonts_are_read_once_per_process(tmp_path, monkeypatch):
  # a series of documents would otherwise parse every face again for each one
  import pdfmarq.fonts as fonts
  read = []
  real = fonts.TTFont
  monkeypatch.setattr(fonts, "TTFont", lambda name, path: read.append(path) or real(name, path))
  monkeypatch.setattr(fonts, "_TTF", {})
  for i in range(3):
    md_to_pdf("Letters ą ę `code`.\n", str(tmp_path / f"{i}.pdf"))
  assert read and len(read) == len(set(read))
