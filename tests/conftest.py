# tests/conftest.py

"""Collect only functions defined in the test module, since `python_functions = ["*"]`.
Carries the shared PDF validator too."""

import importlib.util, inspect
from pathlib import Path
import pytest

def pytest_pycollect_makeitem(collector, name, obj):
  if inspect.isclass(obj):
    return None # a test class is pytest's own business
  if not inspect.isfunction(obj) or obj.__module__ != collector.obj.__name__:
    return [] # imported helpers, marks and constants are not tests

#------------------------------------------------------------------------------------- Twin package

# `docmarq` renders the same markdown to DOCX, but it ships on its own.
# A wheel under test has no twin beside it, so the parity tests stand down
# rather than compare against whatever version PyPI happens to hold.
def _twin_installed() -> bool:
  """A bare `docmarq` can resolve as an empty namespace package,
  so ask for the subpackage the tests actually reach for."""
  try:
    import docmarq.paper
  except ImportError:
    return False
  return True

needs_twin = pytest.mark.skipif(not _twin_installed(), reason="docmarq not installed")

#--------------------------------------------------------------------------------------- PDF reader

# Reading a PDF back takes PyMuPDF, which the wheel under test does not pull in.
needs_fitz = pytest.mark.skipif(importlib.util.find_spec("fitz") is None,
  reason="PyMuPDF not installed")

#--------------------------------------------------------------------------------------- Assertions

def assert_valid_pdf(path:str|Path, min_size:int=200):
  """Validate that `path` points to a real-looking PDF file."""
  p = Path(path)
  assert p.exists(), f"PDF not created: {p}"
  size = p.stat().st_size
  assert size >= min_size, f"PDF suspiciously small ({size} bytes): {p}"
  with p.open("rb") as f:
    head = f.read(8)
  assert head.startswith(b"%PDF-"), f"Not a PDF (header={head!r}): {p}"

def assert_valid_docx(path:str|Path, min_size:int=2000):
  """Validate that `path` points to a real-looking DOCX file (ZIP magic `PK\\x03\\x04`).

  Local copy so cross-lib tests don't depend on `docmarq.tests.*`.
  """
  p = Path(path)
  assert p.exists(), f"DOCX not created: {p}"
  size = p.stat().st_size
  assert size >= min_size, f"DOCX suspiciously small ({size} bytes): {p}"
  with p.open("rb") as f:
    head = f.read(4)
  assert head == b"PK\x03\x04", f"Not a DOCX/ZIP (header={head!r}): {p}"

#-------------------------------------------------------------------------------- Optional backends

def has_mathjax() -> bool:
  """Node plus the MathJax packages, which the vector math engine needs."""
  try:
    from pdfmarq.md.mathjax import available
  except ImportError:
    return False
  return available()

#---------------------------------------------------------------------------------------- Rendering

def render_md(path:str, md:str, style=None):
  """Render markdown to `path` and return the finished `PDF`."""
  from pdfmarq import PDF
  from pdfmarq.md import MarkdownRenderer, MarkdownStyle
  pdf = PDF(path)
  MarkdownRenderer(pdf, style or MarkdownStyle()).render(md)
  pdf.save()
  return pdf

def tight_mm(text:str, font:str, size:float) -> float:
  """
  Width (mm) `text` fills on one line only with its spaces tightened.
  It asks 80% of the tightening justified text allows,
  so the line takes its last word justified and wraps it ragged,
  whatever rounding the widths carry.
  """
  from reportlab.pdfbase.pdfmetrics import stringWidth
  from pdfmarq import MM_TO_PT
  from pdfmarq.inline import _JUSTIFY_SHRINK
  squeeze = text.count(" ") * stringWidth(" ", font, size) * (1 - _JUSTIFY_SHRINK) * 0.8
  return (stringWidth(text, font, size) - squeeze) / MM_TO_PT

#----------------------------------------------------------------------------------------- Fixtures

@pytest.fixture
def word():
  """First word box with exactly this text, `None` when absent."""
  return lambda words, text: next((w for w in words if w[4] == text), None)

@pytest.fixture
def logo(tmp_path):
  """A logo twice as tall as wide, saved as `logo.png` in `tmp_path`."""
  from PIL import Image
  Image.new("RGB", (100, 200), (30, 30, 30)).save(tmp_path / "logo.png")
  return "logo.png"

@pytest.fixture
def small_caps_font(tmp_path) -> str:
  """
  Font directory holding `TestSC-Regular.ttf`: capitals `A` and `B`, letters `a` and `b`
  and a small capital for `a` only, each glyph a box as wide as its advance in units.
  """
  pytest.importorskip("fontTools")
  from fontTools.feaLib.builder import addOpenTypeFeaturesFromString
  from fontTools.fontBuilder import FontBuilder
  from fontTools.pens.ttGlyphPen import TTGlyphPen
  widths = {".notdef": 500, "space": 250, "A": 700, "B": 650, "a": 500, "b": 520, "a.sc": 600}
  def box(width:int):
    pen = TTGlyphPen(None)
    if width:
      pen.moveTo((0, 0))
      for point in ((0, 500), (width, 500), (width, 0)): pen.lineTo(point)
      pen.closePath()
    return pen.glyph()
  build = FontBuilder(1000, isTTF=True)
  build.setupGlyphOrder(list(widths))
  build.setupCharacterMap({32: "space", **{ord(c): c for c in "ABab"}})
  build.setupGlyf({name: box(0 if name == "space" else width) for name, width in widths.items()})
  build.setupHorizontalMetrics({name: (width, 0) for name, width in widths.items()})
  build.setupHorizontalHeader(ascent=800, descent=-200)
  build.setupNameTable({"familyName": "TestSC", "styleName": "Regular",
    "psName": "TestSC-Regular"})
  build.setupOS2(sTypoAscender=800, usWinAscent=800, usWinDescent=200)
  build.setupPost()
  addOpenTypeFeaturesFromString(build.font, "feature smcp { sub a by a.sc; } smcp;")
  build.save(str(tmp_path / "TestSC-Regular.ttf"))
  return str(tmp_path)

#--------------------------------------------------------------------------------------- Inspection

def pdf_text(path:str) -> str:
  """All extractable text of a PDF, pages concatenated."""
  import fitz
  doc = fitz.open(path)
  try:
    return "".join(page.get_text() for page in doc)
  finally:
    doc.close()

def pdf_pages(path:str) -> int:
  import fitz
  doc = fitz.open(path)
  try:
    return doc.page_count
  finally:
    doc.close()

def pdf_words(path:str) -> list:
  """Word boxes `(x0, y0, x1, y1, word, ...)` of every page, in pt."""
  return [w for page in pdf_page_words(path) for w in page]

def pdf_page_words(path:str) -> list[list]:
  """Word boxes `(x0, y0, x1, y1, word, ...)` per page, in pt."""
  import fitz
  doc = fitz.open(path)
  try:
    return [page.get_text("words") for page in doc]
  finally:
    doc.close()

def pdf_spans(path:str) -> list[list[tuple]]:
  """Text spans `(text, font, size, bbox)` per page: what each run of text is set in."""
  import fitz
  doc = fitz.open(path)
  try:
    return [[(s["text"], s["font"], s["size"], s["bbox"])
      for b in page.get_text("dict")["blocks"] for l in b.get("lines", []) for s in l["spans"]]
      for page in doc]
  finally:
    doc.close()

def pdf_faces(path:str, page:int=0) -> dict[str, tuple[str, float]]:
  """Word → `(font, size)` on one page: words are drawn one by one, each a span of its own."""
  return {text: (font, size) for text, font, size, _ in pdf_spans(path)[page]}

def pdf_chars(path:str) -> list[tuple[str, float, float]]:
  """Glyphs `(char, x, y)` of every page, `x, y` being the origin of each in pt."""
  import fitz
  doc = fitz.open(path)
  try:
    return [(c["c"], *c["origin"]) for page in doc for b in page.get_text("rawdict")["blocks"]
      for line in b.get("lines", []) for s in line["spans"] for c in s["chars"]]
  finally:
    doc.close()

def pdf_links(path:str) -> list[dict]:
  """Link annotations of every page, as PyMuPDF reads them."""
  import fitz
  doc = fitz.open(path)
  try:
    return [link for page in doc for link in page.get_links()]
  finally:
    doc.close()

def pdf_images(path:str) -> list[list[tuple]]:
  """Image boxes `(x0, y0, x1, y1)` per page, in pt."""
  import fitz
  doc = fitz.open(path)
  try:
    return [[tuple(info["bbox"]) for info in page.get_image_info()] for page in doc]
  finally:
    doc.close()

def pdf_strokes(path:str) -> list[list[dict]]:
  """Vector paths per page, as PyMuPDF reads them: `rect`, `width`, `dashes` and more."""
  import fitz
  doc = fitz.open(path)
  try:
    return [page.get_drawings() for page in doc]
  finally:
    doc.close()

def pdf_glyphs_past(path:str, right_pt:float) -> list[str]:
  """Glyphs whose box ends right of `right_pt`: text spilling over a margin or border."""
  import fitz
  right_pt += 0.3 # rounding slack: a glyph set flush to the edge still passes
  out = []
  doc = fitz.open(path)
  try:
    for page in doc:
      for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
          for span in line["spans"]:
            out += [c["c"] for c in span["chars"] if c["bbox"][2] > right_pt]
  finally:
    doc.close()
  return out

def pdf_offpage_words(path:str) -> list:
  """Words drawn outside the page box - in the file, invisible in a viewer."""
  import fitz
  out = []
  doc = fitz.open(path)
  try:
    for pno, page in enumerate(doc):
      box = page.rect
      for x0, y0, x1, y1, word, *_ in page.get_text("words"):
        if y1 < -1 or y0 > box.height + 1 or x1 < -1 or x0 > box.width + 1:
          out.append((pno + 1, word))
  finally:
    doc.close()
  return out
