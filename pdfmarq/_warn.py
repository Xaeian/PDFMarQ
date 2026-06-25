# pdfmarq/_warn.py

"""One-time warning printer for missing optional dependencies.
Repeated calls with the same key are suppressed to avoid console spam.

>>> from ._warn import warn_missing
>>> warn_missing("matplotlib", "matplotlib", "math formulas")
pdfmarq: math formulas disabled, install with: pip install matplotlib
"""
import sys

_seen: set = set()

def warn_missing(key:str, package:str, feature:str) -> None:
  """Emit a one-time warning that `feature` is disabled because `package` is absent.
  `key` is the dedup handle (typically the import name); `package` is the pip name."""
  if key in _seen:
    return
  _seen.add(key)
  print(
    f"pdfmarq: {feature} disabled, install with: pip install {package}",
    file=sys.stderr,
  )

def reset_warnings() -> None:
  """Clear the seen-warnings registry. Used in tests."""
  _seen.clear()
