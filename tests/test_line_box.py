# tests/test_line_box.py

"""
Line box: the letters of a line sit in its middle, from the top of its capitals
to the bottom of its descenders, whatever room a font keeps above its capitals.
Blocks drawn around lines keep their letters in the middle too.
"""

import io
import pytest
from conftest import needs_pymupdf, pdf_ink, pdf_strokes, pdf_words, render_md
from pdfmarq import PDF, MM_TO_PT, RichSegment, RichText, TableStyle, render_rich
from pdfmarq.inline import measure_rich, wrap_line_heights
from pdfmarq.md import MarkdownStyle

SIZE = 40 # pt, so a pixel of ink is a small share of a letter
TOP_PT = 20 * MM_TO_PT # page margin, where a line drawn at the top starts
PAGE_H = 842 # A4 height in pt, the reach of a clip down the whole page

#------------------------------------------------------------------------------------------ Helpers

@pytest.fixture
def tall_font(tmp_path) -> str:
  """
  Font directory holding `Tall-Regular.ttf`, which keeps room above its capitals as Barlow does:
  an ascender of 1000 units over capitals 700 tall and descenders 200 deep, each glyph a box.
  `Capless-Regular.ttf` is the same font recording a cap height of 0, as some fonts do.
  """
  pytest.importorskip("fontTools")
  from fontTools.fontBuilder import FontBuilder
  from fontTools.pens.ttGlyphPen import TTGlyphPen
  def box(bottom:int, top:int):
    pen = TTGlyphPen(None)
    if top > bottom:
      pen.moveTo((50, bottom))
      for point in ((50, top), (550, top), (550, bottom)): pen.lineTo(point)
      pen.closePath()
    return pen.glyph()
  def save(family:str, cap:int):
    glyphs = {".notdef": box(0, 0), "H": box(0, 700), "p": box(-200, 500)}
    build = FontBuilder(1000, isTTF=True)
    build.setupGlyphOrder(list(glyphs))
    build.setupCharacterMap({ord("H"): "H", ord("p"): "p"})
    build.setupGlyf(glyphs)
    build.setupHorizontalMetrics({name: (600, 50) for name in glyphs})
    build.setupHorizontalHeader(ascent=1000, descent=-200)
    build.setupNameTable({"familyName": family, "styleName": "Regular",
      "psName": f"{family}-Regular"})
    build.setupOS2(sTypoAscender=1000, sTypoDescender=-200, sCapHeight=cap, sxHeight=500,
      usWinAscent=1000, usWinDescent=200)
    build.setupPost()
    build.save(str(tmp_path / f"{family}-Regular.ttf"))
  save("Tall", 700)
  save("Capless", 0)
  return str(tmp_path)

#--------------------------------------------------------------------------------------------- Line

@needs_pymupdf
@pytest.mark.parametrize("family", ["Helvetica", "Tall"])
def letters_sit_in_the_middle_of_their_line(tmp_path, tall_font, family):
  # Tall keeps 300 units above its capitals for accents, which must not push its letters down
  path = str(tmp_path / "line.pdf")
  pdf = PDF(path, font_dir=tall_font)
  text = RichText([RichSegment("Hp", family=family, size=SIZE)], 100, line_gap=1.4)
  height = render_rich(pdf, text, 0, 0)
  pdf.save()
  line = (TOP_PT, TOP_PT + height * MM_TO_PT)
  assert sum(pdf_ink(path, (0, 0, 595, PAGE_H))) / 2 == pytest.approx(sum(line) / 2, abs=0.5)

@needs_pymupdf
@pytest.mark.parametrize("family", ["Helvetica", "Tall"])
def text_box_holds_its_lines_in_the_middle(tmp_path, tall_font, family):
  # `text` centres three lines in a box as each line centres its letters
  path = str(tmp_path / "box.pdf")
  with PDF(path, font_dir=tall_font) as pdf:
    pdf.font(family, 20).text("Hp\nHp\nHp", width=100, height=50)
  box = (TOP_PT, TOP_PT + 50 * MM_TO_PT)
  assert sum(pdf_ink(path, (0, 0, 595, PAGE_H))) / 2 == pytest.approx(sum(box) / 2, abs=0.5)

def zero_cap_height_falls_back_to_the_ascender(tall_font):
  # a cap height of 0 would set the letters up off their line
  metrics = PDF(io.BytesIO(), font_dir=tall_font).metrics
  assert metrics.letter_span("Capless", "Regular", 1000) == pytest.approx((1000, 200))
  assert metrics.letter_span("Tall", "Regular", 1000) == pytest.approx((700, 200))

def empty_line_is_as_tall_as_its_text():
  # two hard breaks in a row leave a line with no words, still a line of the text around it
  pdf = PDF(io.BytesIO())
  lines = [RichSegment(text, size=20) for text in ("one", "\n", "\n", "three")]
  assert wrap_line_heights(pdf, RichText(lines, 100)) == pytest.approx([20 * 1.45 / MM_TO_PT] * 3)
  empty = RichText([RichSegment("", size=20)], 100)
  assert measure_rich(pdf, empty) == pytest.approx(20 * 1.45 / MM_TO_PT)

#------------------------------------------------------------------------------------------- Blocks

@needs_pymupdf
@pytest.mark.parametrize("md", [
  "```\nHx\nHx\n```\n", # no descenders: the ink ends on the baseline
  "> Hp\n",
  "> [!NOTE]\n> Hp\n", # the title is the first line
], ids=["code", "quote", "callout"])
def block_keeps_its_letters_in_the_middle(tmp_path, md):
  # As much room above the capitals as below the descenders, between borders or beside a bar,
  # and in a frame of code as below the last baseline, which the eye measures there
  path = str(tmp_path / "block.pdf")
  render_md(path, md)
  words = pdf_words(path)
  top, bottom = pdf_ink(path, (min(w[0] for w in words), 0, max(w[2] for w in words), PAGE_H))
  frame = min((d["rect"] for d in pdf_strokes(path)[0] if d["rect"].height > 2
    and d["rect"].y0 <= top and d["rect"].y1 >= bottom), key=lambda rect: rect.height)
  # Courier, the mono face where DejaVu is missing, records no cap height and is never embedded:
  # its capitals sit up to a point low, in whatever face the viewer draws it
  assert top - frame.y0 == pytest.approx(frame.y1 - bottom, abs=1.2)

@needs_pymupdf
def a_long_line_of_code_runs_on_two_characters_in(tmp_path):
  # So it reads as one line of code wrapped, not as two lines
  path = str(tmp_path / "code.pdf")
  render_md(path, "```\n" + "word" * 50 + "\n```\n")
  first, second = sorted(pdf_words(path), key=lambda w: w[1])[:2]
  style = MarkdownStyle()
  two = 2 * PDF(io.BytesIO()).metrics.text_width("x", style.font_mono, style.mono_mode,
    style.code_block_size)
  assert second[0] - first[0] == pytest.approx(two, abs=0.5)

@needs_pymupdf
def a_code_block_keeps_its_gap_above_where_paragraphs_keep_none(tmp_path):
  # Its frame would touch the descenders of the line above it, with its gap only under it
  path = str(tmp_path / "code.pdf")
  style = MarkdownStyle(para_gap=0)
  render_md(path, "Text above the code.\n\n```\nHx\n```\n", style)
  text = max(w[3] for w in pdf_words(path) if w[4] == "code.")
  frame = min(d["rect"].y0 for d in pdf_strokes(path)[0] if d["rect"].height > 2)
  assert frame - text >= style.code_block_gap * MM_TO_PT

@needs_pymupdf
def table_text_sits_between_its_pads(tmp_path):
  # the table is as tall as before, only its letters move: half the difference of the pads
  def draw(name:str, top:float, bot:float) -> tuple[float, float]:
    path = str(tmp_path / f"{name}.pdf")
    with PDF(path) as pdf:
      pdf.table([["Hp"]], style=TableStyle(cell_pad_top=top, cell_pad_bot=bot))
      end = pdf.y
    return pdf_ink(path, (0, 0, 595, PAGE_H))[0], end
  level, level_end = draw("level", 0.5, 0.5)
  pushed, pushed_end = draw("pushed", 1.0, 0.0)
  assert pushed_end == pytest.approx(level_end)
  assert pushed - level == pytest.approx(0.5 * MM_TO_PT, abs=0.3)

@needs_pymupdf
@pytest.mark.parametrize("markdown", [False, True], ids=["table", "markdown"])
def table_cell_centres_its_capitals(tmp_path, markdown):
  # capitals and digits sit level in a cell: descenders would hang into the bottom pad
  path = str(tmp_path / "cell.pdf")
  if markdown:
    render_md(path, "| H |\n|---|\n")
  else:
    with PDF(path) as pdf:
      pdf.table([], header=["H"])
  top, bottom = pdf_ink(path, (0, 0, 595, PAGE_H))
  cell = min((d["rect"] for d in pdf_strokes(path)[0] if d["rect"].height > 2
    and d["rect"].y0 <= top and d["rect"].y1 >= bottom), key=lambda rect: rect.height)
  assert top - cell.y0 == pytest.approx(cell.y1 - bottom, abs=0.5)

@needs_pymupdf
def bullet_sits_mid_lowercase(tmp_path):
  path = str(tmp_path / "list.pdf")
  render_md(path, "- xxx\n")
  word = pdf_words(path)[0]
  disc = next(d["rect"] for d in pdf_strokes(path)[0] if d["fill"])
  letters = pdf_ink(path, (word[0], 0, word[2], PAGE_H))
  assert (disc.y0 + disc.y1) / 2 == pytest.approx(sum(letters) / 2, abs=0.5)

@needs_pymupdf
def equation_number_sits_mid_formula(tmp_path):
  pytest.importorskip("matplotlib")
  path = str(tmp_path / "math.pdf")
  render_md(path, "$$E = mc^2$$\n", MarkdownStyle(math_engine="mathtext"))
  number = next(w for w in pdf_words(path) if w[4] == "(1)")
  formula = pdf_ink(path, (0, 0, number[0] - 10, PAGE_H))
  label = pdf_ink(path, (number[0], 0, number[2], PAGE_H))
  assert sum(label) / 2 == pytest.approx(sum(formula) / 2, abs=1.5) # the drawing pads its ink
