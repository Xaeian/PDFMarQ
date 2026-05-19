"""Markdown directive tests: `<!-- pagebreak -->` and `<!-- group -->`.

Cross-lib coverage: same source through both `pdfmarq.md_to_pdf` and
`docmarq.md_to_docx`. Existing auto-pagebreak machinery (heading lookahead,
`_ensure_space`, `h1_page_break`) stays active - these tests only verify
that the new manual overrides do their job WITHOUT interfering with it.
"""
import warnings
import pytest
from pdfmarq.md import md_to_pdf, MarkdownStyle
from pdfmarq.md.md_html import (
  is_pagebreak_directive, is_group_open_directive, is_group_close_directive,
)
from docmarq.md import md_to_docx
from docmarq.md.tokens import (
  is_pagebreak_directive as docx_is_pb,
  is_group_open_directive as docx_is_go,
  is_group_close_directive as docx_is_gc,
)
from pdfmarq.tests.conftest import assert_valid_pdf
from docmarq.tests.conftest import assert_valid_docx

#--------------------------------------------------------------------- Directive detectors

@pytest.mark.parametrize("content,expected", [
  ("<!-- pagebreak -->\n", True),
  ("<!--pagebreak-->\n", True),
  ("<!-- PageBreak -->\n", True),
  ("<!--    pagebreak    -->\n", True),
  ("<!--    pagebreak   xxx  -->\n", False),
  ("<!-- pagebreaks -->\n", False),
  ("<!-- page break -->\n", False),
])
def test_pagebreak_detector(content, expected):
  # Both libs must recognize directives the same way.
  assert is_pagebreak_directive(content) is expected
  assert docx_is_pb(content) is expected

@pytest.mark.parametrize("content,expected", [
  ("<!-- group -->\n", True),
  ("<!--group-->\n", True),
  ("<!--  group  -->\n", True),
  ("<!-- /group -->\n", False),
  ("<!-- group xxx -->\n", False),
])
def test_group_open_detector(content, expected):
  assert is_group_open_directive(content) is expected
  assert docx_is_go(content) is expected

@pytest.mark.parametrize("content,expected", [
  ("<!-- /group -->\n", True),
  ("<!--/group-->\n", True),
  ("<!--  / group  -->\n", True),
  ("<!-- group -->\n", False),
])
def test_group_close_detector(content, expected):
  assert is_group_close_directive(content) is expected
  assert docx_is_gc(content) is expected

#----------------------------------------------------------------------------- pagebreak

def test_pagebreak_pdf_forces_new_page(tmp_path):
  src = "# A\n\nFirst.\n\n<!-- pagebreak -->\n\n# B\n\nSecond."
  path = tmp_path / "pb.pdf"
  pdf = md_to_pdf(src, str(path))
  assert pdf.page_num == 2
  assert_valid_pdf(path)

def test_pagebreak_docx_produces_valid_doc(tmp_path):
  src = "First.\n\n<!-- pagebreak -->\n\nSecond."
  path = tmp_path / "pb.docx"
  md_to_docx(src, str(path))
  assert_valid_docx(path)

def test_pagebreak_at_top_does_not_double_break(tmp_path):
  # Directive at cursor y≈0 should be a no-op (cursor already at page top).
  # Prevents users from accidentally creating empty first pages.
  src = "<!-- pagebreak -->\n\nContent."
  path = tmp_path / "pb_top.pdf"
  pdf = md_to_pdf(src, str(path))
  assert pdf.page_num == 1

def test_pagebreak_case_insensitive(tmp_path):
  src = "A.\n\n<!-- PageBreak -->\n\nB."
  path = tmp_path / "pb_case.pdf"
  pdf = md_to_pdf(src, str(path))
  assert pdf.page_num == 2

def test_pagebreak_invalid_extra_tokens_drops_silently(tmp_path):
  # `<!-- pagebreak xxx -->` is a plain HTML comment, not the directive.
  src = "A.\n\n<!-- pagebreak xxx -->\n\nB."
  path = tmp_path / "pb_invalid.pdf"
  pdf = md_to_pdf(src, str(path))
  assert pdf.page_num == 1  # no break

#--------------------------------------------------------------------------------- group

def test_group_fitting_content_renders_normally(tmp_path):
  # Small group at top of page: no preemptive break expected.
  src = "<!-- group -->\n\nA.\n\nB.\n\n<!-- /group -->"
  path = tmp_path / "g_fit.pdf"
  pdf = md_to_pdf(src, str(path))
  assert pdf.page_num == 1

def test_group_oversized_renders_without_break(tmp_path):
  # Group larger than a full page: skip the break (would just produce
  # an empty page top then overflow naturally). Existing auto-pagebreak
  # handles the actual splitting inside.
  src = "<!-- group -->\n\n" + "\n\n".join(
    f"Paragraph {i} " + "lorem ipsum " * 30 for i in range(60)
  ) + "\n\n<!-- /group -->"
  path = tmp_path / "g_oversized.pdf"
  pdf = md_to_pdf(src, str(path))
  # Did NOT crash, multiple pages produced via auto-pagebreak.
  assert pdf.page_num >= 2
  assert_valid_pdf(path)

def test_group_docx_sets_keep_with_next(tmp_path):
  # docmarq encodes group as `<w:keepNext/>` on each paragraph except last.
  src = "<!-- group -->\n\nA.\n\nB.\n\n<!-- /group -->\n\nC."
  path = tmp_path / "g.docx"
  md_to_docx(src, str(path))
  from docx import Document
  doc = Document(str(path))
  flags = [p.paragraph_format.keep_with_next for p in doc.paragraphs]
  # First paragraph in group: True; last in group: None/False; outside: None/False.
  assert flags[0] is True, f"first group para should keep_with_next, got {flags}"
  assert not flags[-1], f"trailing para outside group should not, got {flags}"

#------------------------------------------------------------------------- Malformed input

def test_stray_close_emits_warning_pdf(tmp_path):
  src = "A.\n\n<!-- /group -->\n\nB."
  path = tmp_path / "stray.pdf"
  with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter("always")
    md_to_pdf(src, str(path))
  msgs = [str(x.message) for x in w if "stray" in str(x.message).lower()]
  assert msgs, "expected stray-close warning"
  assert_valid_pdf(path)

def test_stray_close_emits_warning_docx(tmp_path):
  src = "A.\n\n<!-- /group -->\n\nB."
  path = tmp_path / "stray.docx"
  with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter("always")
    md_to_docx(src, str(path))
  msgs = [str(x.message) for x in w if "stray" in str(x.message).lower()]
  assert msgs
  assert_valid_docx(path)

def test_unclosed_group_warns_and_renders_to_end(tmp_path):
  # Unclosed group: emit warning, render everything from open to EOF.
  src = "<!-- group -->\n\nA.\n\nB.\n\nC."
  path = tmp_path / "unclosed.pdf"
  with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter("always")
    md_to_pdf(src, str(path))
  msgs = [str(x.message) for x in w if "unclosed" in str(x.message).lower()]
  assert msgs
  assert_valid_pdf(path)

def test_nested_group_collapses(tmp_path):
  # Inner `<!-- group -->` is treated as a silent depth marker, NOT as
  # a separate keep-together region. Outer close matches outer open.
  src = (
    "<!-- group -->\n\nOuter A.\n\n"
    "<!-- group -->\n\nInner.\n\n<!-- /group -->\n\n"
    "Outer B.\n\n<!-- /group -->\n\nAfter."
  )
  path = tmp_path / "nested.pdf"
  pdf = md_to_pdf(src, str(path))
  assert pdf.page_num >= 1
  assert_valid_pdf(path)

#-------------------------------------------------------------- Auto-pagebreak coexistence

def test_auto_pagebreak_still_active_inside_group(tmp_path):
  # Inside a group, the existing auto-pagebreak (heading lookahead etc.)
  # must continue to work - a group can't be SO sticky it suppresses
  # natural overflow handling for oversize content.
  para = "lorem ipsum " * 25
  body = "\n\n".join([para] * 50)
  src = f"<!-- group -->\n\n{body}\n\n<!-- /group -->"
  path = tmp_path / "auto_inside.pdf"
  pdf = md_to_pdf(src, str(path))
  assert pdf.page_num >= 2  # overflow forced multiple pages via auto-break
