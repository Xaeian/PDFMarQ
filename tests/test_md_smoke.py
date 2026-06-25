# tests/test_md_smoke.py

"""Markdown rendering smoke: feed small samples through `md_to_pdf`, verify valid PDF."""

import pytest
from conftest import assert_valid_pdf
from pdfmarq.md import md_to_pdf, MarkdownStyle

#---------------------------------------------------------------------------------- Markdown

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
  ("empty_string", ""),                    # edge: empty input must not blow up
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
  style = MarkdownStyle(body_size=10, head_gap_top=8, table_zebra=False)
  md_to_pdf("# H\n\nbody", str(path), style=style)
  assert_valid_pdf(path)

def md_footnote_label_renders_heading(tmp_path):
  # when `footnote_label` is set, the footnote section gets an H2 heading
  # above it instead of the HR separator
  path = tmp_path / "fn_label.pdf"
  src = "Body[^1].\n\n[^1]: footnote text."
  style = MarkdownStyle(footnote_label="References")
  md_to_pdf(src, str(path), style=style)
  assert_valid_pdf(path)

def md_landscape_from_frontmatter_flips_page(tmp_path):
  # `render.landscape: true` flips the page when caller doesn't pass landscape=
  path = tmp_path / "fm_landscape.pdf"
  src = "---\nrender:\n  landscape: true\n---\n\n# Wide content"
  pdf = md_to_pdf(src, str(path))
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
  # regression: two renderers used to clobber the global mathtext.fontset so
  # whichever was constructed last won; now each holds its own MathFontConfig
  src = "$x^2 + 1$"
  md_to_pdf(src, str(tmp_path / "stix.pdf"), style=MarkdownStyle(math_fontset="stix"))
  md_to_pdf(src, str(tmp_path / "cm.pdf"),   style=MarkdownStyle(math_fontset="cm"))
  md_to_pdf(src, str(tmp_path / "stix2.pdf"), style=MarkdownStyle(math_fontset="stix"))
  for name in ("stix.pdf", "cm.pdf", "stix2.pdf"):
    assert_valid_pdf(tmp_path / name)
