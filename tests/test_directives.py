# tests/test_directives.py

"""Markdown directives `<!-- pagebreak -->` / `<!-- group -->`: detectors + render, cross-lib."""

import warnings
import pytest
from conftest import assert_valid_pdf, assert_valid_docx
from pdfmarq.md import md_to_pdf
from pdfmarq.md.md_html import (
  is_pagebreak_directive, is_group_open_directive, is_group_close_directive,
)
from docmarq.md import md_to_docx
from docmarq.md.tokens import (
  is_pagebreak_directive as docx_is_pb,
  is_group_open_directive as docx_is_go,
  is_group_close_directive as docx_is_gc,
)

#------------------------------------------------------------------------------ Directive detectors

@pytest.mark.parametrize("content, expected", [
  ("<!-- pagebreak -->\n", True),
  ("<!--pagebreak-->\n", True),
  ("<!-- PageBreak -->\n", True),
  ("<!--    pagebreak    -->\n", True),
  ("<!--    pagebreak   xxx  -->\n", False),
  ("<!-- pagebreaks -->\n", False),
  ("<!-- page break -->\n", False),
])
def pagebreak_detector_matches_both_libs(content, expected):
  assert is_pagebreak_directive(content) is expected
  assert docx_is_pb(content) is expected

@pytest.mark.parametrize("content, expected", [
  ("<!-- group -->\n", True),
  ("<!--group-->\n", True),
  ("<!--  group  -->\n", True),
  ("<!-- /group -->\n", False),
  ("<!-- group xxx -->\n", False),
])
def group_open_detector_matches_both_libs(content, expected):
  assert is_group_open_directive(content) is expected
  assert docx_is_go(content) is expected

@pytest.mark.parametrize("content, expected", [
  ("<!-- /group -->\n", True),
  ("<!--/group-->\n", True),
  ("<!--  / group  -->\n", True),
  ("<!-- group -->\n", False),
])
def group_close_detector_matches_both_libs(content, expected):
  assert is_group_close_directive(content) is expected
  assert docx_is_gc(content) is expected

#---------------------------------------------------------------------------------------- pagebreak

def pagebreak_pdf_forces_new_page(tmp_path):
  src = "# A\n\nFirst.\n\n<!-- pagebreak -->\n\n# B\n\nSecond."
  path = tmp_path / "pb.pdf"
  pdf = md_to_pdf(src, str(path))
  assert pdf.page_num == 2
  assert_valid_pdf(path)

def pagebreak_docx_produces_valid_doc(tmp_path):
  src = "First.\n\n<!-- pagebreak -->\n\nSecond."
  path = tmp_path / "pb.docx"
  md_to_docx(src, str(path))
  assert_valid_docx(path)

def pagebreak_at_top_does_not_double_break(tmp_path):
  # directive at cursor y≈0 is a no-op (already at page top); avoids empty first page
  src = "<!-- pagebreak -->\n\nContent."
  path = tmp_path / "pb_top.pdf"
  pdf = md_to_pdf(src, str(path))
  assert pdf.page_num == 1

def pagebreak_case_insensitive(tmp_path):
  src = "A.\n\n<!-- PageBreak -->\n\nB."
  pdf = md_to_pdf(src, str(tmp_path / "pb_case.pdf"))
  assert pdf.page_num == 2

def pagebreak_invalid_extra_tokens_drops_silently(tmp_path):
  # `<!-- pagebreak xxx -->` is a plain HTML comment, not the directive
  src = "A.\n\n<!-- pagebreak xxx -->\n\nB."
  pdf = md_to_pdf(src, str(tmp_path / "pb_invalid.pdf"))
  assert pdf.page_num == 1 # no break

#-------------------------------------------------------------------------------------------- group

def group_fitting_content_renders_normally(tmp_path):
  # small group at top of page: no preemptive break expected
  src = "<!-- group -->\n\nA.\n\nB.\n\n<!-- /group -->"
  pdf = md_to_pdf(src, str(tmp_path / "g_fit.pdf"))
  assert pdf.page_num == 1

def group_oversized_renders_without_break(tmp_path):
  # group larger than a full page: skip the break, auto-pagebreak splits inside
  src = "<!-- group -->\n\n" + "\n\n".join(
    f"Paragraph {i} " + "lorem ipsum " * 30 for i in range(60)
  ) + "\n\n<!-- /group -->"
  path = tmp_path / "g_oversized.pdf"
  pdf = md_to_pdf(src, str(path))
  assert pdf.page_num >= 2
  assert_valid_pdf(path)

def group_docx_sets_keep_with_next(tmp_path):
  # docmarq encodes group as `<w:keepNext/>` on each paragraph except last
  src = "<!-- group -->\n\nA.\n\nB.\n\n<!-- /group -->\n\nC."
  path = tmp_path / "g.docx"
  md_to_docx(src, str(path))
  from docx import Document
  doc = Document(str(path))
  flags = [p.paragraph_format.keep_with_next for p in doc.paragraphs]
  assert flags[0] is True, f"first group para should keep_with_next, got {flags}"
  assert not flags[-1], f"trailing para outside group should not, got {flags}"

#---------------------------------------------------------------------------------- Malformed input

def stray_close_emits_warning_pdf(tmp_path):
  src = "A.\n\n<!-- /group -->\n\nB."
  path = tmp_path / "stray.pdf"
  with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter("always")
    md_to_pdf(src, str(path))
  msgs = [str(x.message) for x in w if "stray" in str(x.message).lower()]
  assert msgs, "expected stray-close warning"
  assert_valid_pdf(path)

def stray_close_emits_warning_docx(tmp_path):
  src = "A.\n\n<!-- /group -->\n\nB."
  path = tmp_path / "stray.docx"
  with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter("always")
    md_to_docx(src, str(path))
  msgs = [str(x.message) for x in w if "stray" in str(x.message).lower()]
  assert msgs
  assert_valid_docx(path)

def unclosed_group_warns_and_renders_to_end(tmp_path):
  # unclosed group: emit warning, render everything from open to EOF
  src = "<!-- group -->\n\nA.\n\nB.\n\nC."
  path = tmp_path / "unclosed.pdf"
  with warnings.catch_warnings(record=True) as w:
    warnings.simplefilter("always")
    md_to_pdf(src, str(path))
  msgs = [str(x.message) for x in w if "unclosed" in str(x.message).lower()]
  assert msgs
  assert_valid_pdf(path)

def nested_group_collapses(tmp_path):
  # inner `<!-- group -->` is a silent depth marker; outer close matches outer open
  src = (
    "<!-- group -->\n\nOuter A.\n\n"
    "<!-- group -->\n\nInner.\n\n<!-- /group -->\n\n"
    "Outer B.\n\n<!-- /group -->\n\nAfter."
  )
  path = tmp_path / "nested.pdf"
  pdf = md_to_pdf(src, str(path))
  assert pdf.page_num >= 1
  assert_valid_pdf(path)

#----------------------------------------------------------------------- Auto-pagebreak coexistence

def auto_pagebreak_still_active_inside_group(tmp_path):
  # inside a group, auto-pagebreak (heading lookahead etc.) must keep working
  para = "lorem ipsum " * 25
  body = "\n\n".join([para] * 50)
  src = f"<!-- group -->\n\n{body}\n\n<!-- /group -->"
  pdf = md_to_pdf(src, str(tmp_path / "auto_inside.pdf"))
  assert pdf.page_num >= 2 # overflow forced multiple pages via auto-break
