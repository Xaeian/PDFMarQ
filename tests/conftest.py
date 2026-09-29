# tests/conftest.py

"""Collect only functions defined in the test module, since `python_functions = ["*"]`.
Carries the shared PDF validator too."""

import inspect
from pathlib import Path
import pytest

def pytest_pycollect_makeitem(collector, name, obj):
  if inspect.isclass(obj):
    return None # a test class is pytest's own business
  if not inspect.isfunction(obj) or obj.__module__ != collector.obj.__name__:
    return [] # imported helpers, marks and constants are not tests

#------------------------------------------------------------------------------------- Twin package

# `docmarq` renders the same markdown to DOCX, but it ships on its own. A wheel under
# test has no twin beside it, so the parity tests stand down rather than compare against
# whatever version PyPI happens to hold.
def _twin_installed() -> bool:
  """A bare `docmarq` can resolve as an empty namespace package, so ask for the
  subpackage the tests actually reach for."""
  try:
    import docmarq.md
  except ImportError:
    return False
  return True

needs_twin = pytest.mark.skipif(not _twin_installed(), reason="docmarq not installed")

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
  import fitz
  doc = fitz.open(path)
  try:
    return [w for page in doc for w in page.get_text("words")]
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
