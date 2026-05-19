"""Shared test fixtures and helpers.

PDF smoke tests just confirm that:
  - a file is produced at the requested path
  - it begins with `%PDF-` (valid header)
  - it is non-empty (at least one xref + EOF)

For deeper verification (page count, content extraction) we'd need pypdf
or pdfminer - kept out for now to keep the test suite zero-extra-deps.
"""
from pathlib import Path
import sys

# Make `pdfmarq` importable when running tests from inside the package dir.
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
  sys.path.insert(0, str(_ROOT))

#----------------------------------------------------------------------------------- Assertions

def assert_valid_pdf(path:str|Path, min_size:int=200):
  """Validate that `path` points to a real-looking PDF file."""
  p = Path(path)
  assert p.exists(), f"PDF not created: {p}"
  size = p.stat().st_size
  assert size >= min_size, f"PDF suspiciously small ({size} bytes): {p}"
  with p.open("rb") as f:
    head = f.read(8)
  assert head.startswith(b"%PDF-"), f"Not a PDF (header={head!r}): {p}"
