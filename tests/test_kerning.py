# tests/test_kerning.py

"""
Kerning: TrueType letter pairs kerned when asked, measured as they are drawn,
and text copied out of the PDF as it went in, no glyph substituted.
"""

import io, os, warnings
from importlib.util import find_spec
import pytest
import reportlab
from conftest import needs_fitz, pdf_chars, pdf_text, pdf_words, render_md
from pdfmarq import PDF, MM_TO_PT, RichSegment, render_rich
from pdfmarq.inline import measure_extent
from pdfmarq.md import MarkdownStyle

needs_harfbuzz = pytest.mark.skipif(find_spec("uharfbuzz") is None, reason="needs uharfbuzz")
VERA = os.path.join(os.path.dirname(reportlab.__file__), "fonts", "Vera.ttf") # kerns `AV`

#------------------------------------------------------------------------------------------ Helpers

@pytest.fixture
def vera_pdf(tmp_path):
  """A `PDF` whose `Vera` family is reportlab's own Bitstream Vera."""
  def make(name:str="kern.pdf") -> PDF:
    pdf = PDF(str(tmp_path / name))
    pdf.fonts.register_file("Vera", "Regular", VERA)
    return pdf
  return make

#-------------------------------------------------------------------------------------------- Kerns

@needs_harfbuzz
def kerning_tightens_pairs_where_measured(vera_pdf):
  pdf = vera_pdf()
  avatar = [RichSegment("AVATAR", family="Vera", size=40)]
  plain = measure_extent(pdf, avatar)[1]
  kerned = measure_extent(pdf.kerning(), avatar)[1]
  assert plain - kerned == pytest.approx(11.33 / MM_TO_PT, abs=0.05) # `AV`, `VA`, `AT` and `TA`

@needs_harfbuzz
@needs_fitz
def kerned_text_is_drawn_as_measured(vera_pdf, tmp_path):
  def span(kern:bool) -> float:
    """Distance (pt) between the first and the last glyph of `AVATAR`, as drawn."""
    pdf = vera_pdf(f"span{kern}.pdf").kerning(kern)
    render_rich(pdf, [RichSegment("AVATAR", family="Vera", size=40)], 150, 0, 0)
    pdf.save()
    chars = pdf_chars(str(tmp_path / f"span{kern}.pdf"))
    return chars[-1][1] - chars[0][1]
  assert span(False) - span(True) == pytest.approx(11.33, abs=0.1)

@needs_harfbuzz
@needs_fitz
def kerned_text_copies_out_unchanged(vera_pdf, tmp_path):
  # ligatures stay off: `ffi` would otherwise copy out as the one letter `ﬃ`
  text = "office affluent AVATAR Type"
  pdf = vera_pdf().kerning()
  render_rich(pdf, [RichSegment(text, family="Vera", size=20)], 170, 0, 0)
  pdf.font("Vera", 20).cursor(0, 30).text(text)
  pdf.save()
  assert pdf_text(str(tmp_path / "kern.pdf")).split("\n")[:2] == [text, text]

@needs_harfbuzz
@needs_fitz
def markdown_style_kerns_its_text(tmp_path):
  def width(kerning:bool) -> float:
    path = str(tmp_path / f"md{kerning}.pdf")
    render_md(path, "AVATAR\n", MarkdownStyle(font_body="Vera", kerning=kerning))
    word = pdf_words(path)[0]
    return word[2] - word[0]
  assert width(False) - width(True) > 2

def core_faces_keep_their_widths():
  # Helvetica has no kerning to apply: the switch leaves it as it was
  pdf = PDF(io.BytesIO())
  plain = measure_extent(pdf, [RichSegment("AVATAR", size=40)])[1]
  with warnings.catch_warnings():
    warnings.simplefilter("ignore") # uharfbuzz may be missing here
    kerned = measure_extent(pdf.kerning(), [RichSegment("AVATAR", size=40)])[1]
  assert kerned == pytest.approx(plain)

def kerning_without_harfbuzz_warns(monkeypatch):
  from pdfmarq._warn import reset_warnings
  reset_warnings()
  monkeypatch.setattr("pdfmarq.core.find_spec", lambda name: None)
  with pytest.warns(RuntimeWarning, match="pip install uharfbuzz"):
    PDF(io.BytesIO()).kerning()
