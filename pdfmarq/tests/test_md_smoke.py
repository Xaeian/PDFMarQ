"""Markdown rendering smoke tests.

Each test feeds a small markdown sample through `md_to_pdf` and verifies
the resulting PDF is valid. We don't try to verify visual output - just
that the rendering pipeline doesn't crash on the common construct mix.
"""
from pdfmarq.md import md_to_pdf, MarkdownStyle
from pdfmarq.tests.conftest import assert_valid_pdf

#---------------------------------------------------------------------------------- Markdown

def test_md_minimal(tmp_path):
  path = tmp_path / "min.pdf"
  md_to_pdf("# Title\n\nHello world.", str(path))
  assert_valid_pdf(path)

def test_md_headings(tmp_path):
  path = tmp_path / "head.pdf"
  md_to_pdf(
    "# H1\n## H2\n### H3\n#### H4\n##### H5\n###### H6\n\nbody",
    str(path),
  )
  assert_valid_pdf(path)

def test_md_paragraphs_and_emphasis(tmp_path):
  path = tmp_path / "para.pdf"
  src = (
    "Plain text with **bold**, *italic*, ***both***, `inline code`, "
    "~~strike~~ and a [link](https://example.com).\n\n"
    "Second paragraph here."
  )
  md_to_pdf(src, str(path))
  assert_valid_pdf(path)

def test_md_lists(tmp_path):
  path = tmp_path / "lists.pdf"
  src = (
    "- item one\n"
    "- item two\n"
    "  - nested\n"
    "  - nested 2\n"
    "- item three\n\n"
    "1. ordered\n"
    "2. ordered\n"
    "3. ordered\n"
  )
  md_to_pdf(src, str(path))
  assert_valid_pdf(path)

def test_md_code_block(tmp_path):
  path = tmp_path / "code.pdf"
  src = "Inline `x = 1` and fenced:\n\n```python\ndef foo():\n  return 42\n```\n"
  md_to_pdf(src, str(path))
  assert_valid_pdf(path)

def test_md_table(tmp_path):
  path = tmp_path / "tab.pdf"
  src = (
    "| Col A | Col B | Col C |\n"
    "|-------|------:|:-----:|\n"
    "| a     |    1  |   x   |\n"
    "| bbbb  |   22  |  yy   |\n"
  )
  md_to_pdf(src, str(path))
  assert_valid_pdf(path)

def test_md_blockquote(tmp_path):
  path = tmp_path / "bq.pdf"
  src = "> a quote\n> spanning two lines\n\nNext para."
  md_to_pdf(src, str(path))
  assert_valid_pdf(path)

def test_md_github_callout(tmp_path):
  path = tmp_path / "callout.pdf"
  src = (
    "> [!NOTE]\n> Note callout.\n\n"
    "> [!WARNING]\n> Be careful.\n"
  )
  md_to_pdf(src, str(path))
  assert_valid_pdf(path)

def test_md_hr(tmp_path):
  path = tmp_path / "hr.pdf"
  md_to_pdf("a\n\n---\n\nb", str(path))
  assert_valid_pdf(path)

def test_md_frontmatter(tmp_path):
  path = tmp_path / "fm.pdf"
  src = (
    "---\n"
    "title: Doc\n"
    "author: Xaeian\n"
    "subject: smoke\n"
    "keywords: [a, b]\n"
    "---\n\n"
    "# Doc\n\nBody."
  )
  md_to_pdf(src, str(path))
  assert_valid_pdf(path)

def test_md_internal_anchor_link(tmp_path):
  # `[x](#slug)` must only become a click target when `slug` is a real heading,
  # otherwise reportlab crashes at save time. The pre-scan in
  # `_collect_heading_slugs` guards this - test it doesn't regress.
  path = tmp_path / "anchor.pdf"
  src = (
    "# Top heading\n\nJump to [there](#another-heading) or [ghost](#nope).\n\n"
    "## Another heading\n\nTarget."
  )
  md_to_pdf(src, str(path))
  assert_valid_pdf(path)

def test_md_long_doc_multipage(tmp_path):
  # Force multi-page rendering and exercise NumberedCanvas replay + page chrome.
  path = tmp_path / "long.pdf"
  lorem = "Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 6
  src = "# Long\n\n" + "\n\n".join([lorem] * 30)
  md_to_pdf(src, str(path))
  assert_valid_pdf(path)

def test_md_custom_style(tmp_path):
  path = tmp_path / "styled.pdf"
  style = MarkdownStyle(body_size=10, head_gap_top=8, table_zebra=False)
  md_to_pdf("# H\n\nbody", str(path), style=style)
  assert_valid_pdf(path)

def test_md_empty_string(tmp_path):
  # Edge: empty input shouldn't blow up.
  path = tmp_path / "empty.pdf"
  md_to_pdf("", str(path))
  assert_valid_pdf(path)

def test_md_inline_math(tmp_path):
  # Exercises the matplotlib math pipeline + per-renderer config (rcParams
  # are no longer mutated at construction time).
  path = tmp_path / "math.pdf"
  src = "Pythagoras: $a^2 + b^2 = c^2$ done.\n\n$$ E = mc^2 $$\n"
  md_to_pdf(src, str(path))
  assert_valid_pdf(path)

def test_md_footnote_label_renders_heading(tmp_path):
  # When `footnote_label` is set, the footnote section gets an H2 heading
  # above it instead of the HR separator.
  path = tmp_path / "fn_label.pdf"
  src = "Body[^1].\n\n[^1]: footnote text."
  style = MarkdownStyle(footnote_label="References")
  md_to_pdf(src, str(path), style=style)
  assert_valid_pdf(path)

def test_md_landscape_from_frontmatter(tmp_path):
  # `render.landscape: true` flips the page when caller doesn't pass
  # `landscape=`. Top-level `landscape:` is no longer honored (warns).
  path = tmp_path / "fm_landscape.pdf"
  src = "---\nrender:\n  landscape: true\n---\n\n# Wide content"
  pdf = md_to_pdf(src, str(path))
  assert pdf.page_width > pdf.page_height
  assert_valid_pdf(path)

def test_md_base_dir_resolves_relative_image(tmp_path):
  # Create a real image one dir over; `md_to_pdf(base_dir=...)` should find
  # it without a chdir. Mirrors docmarq.md_to_docx.base_dir behavior.
  from PIL import Image
  img_dir = tmp_path / "assets"
  img_dir.mkdir()
  Image.new("RGB", (10, 10), (200, 100, 50)).save(img_dir / "x.png")
  src = "# Doc\n\n![alt](assets/x.png)"
  path = tmp_path / "img.pdf"
  md_to_pdf(src, str(path), base_dir=str(tmp_path))
  assert_valid_pdf(path)

def test_md_two_renderers_different_fontsets(tmp_path):
  # Regression: two renderers used to clobber `mpl.rcParams["mathtext.fontset"]`
  # globally so whichever was constructed last won. Now each holds its own
  # `MathFontConfig` and applies it per-render.
  src = "$x^2 + 1$"
  md_to_pdf(src, str(tmp_path / "stix.pdf"), style=MarkdownStyle(math_fontset="stix"))
  md_to_pdf(src, str(tmp_path / "cm.pdf"),   style=MarkdownStyle(math_fontset="cm"))
  # Render a third with the first fontset - this is the one that used to
  # silently inherit "cm" because of the global `_LAST_FONTSET` cache.
  md_to_pdf(src, str(tmp_path / "stix2.pdf"), style=MarkdownStyle(math_fontset="stix"))
  for name in ("stix.pdf", "cm.pdf", "stix2.pdf"):
    assert_valid_pdf(tmp_path / name)
