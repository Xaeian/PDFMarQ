# pdfmarq/_warn.py

"""
Warnings of the library, pointing at the user's line however deep the library called.
A missing optional package warns once per process.

>>> from ._warn import warn_missing
>>> warn_missing("matplotlib", "matplotlib", "math formulas")
RuntimeWarning: math formulas disabled, install with: pip install matplotlib
"""
import sys, warnings

_seen: set = set()

def warn_missing(key:str, package:str, feature:str) -> None:
  """
  Warn once per process that `feature` is disabled because `package` is absent.
  `key` is the dedup handle, typically the import name.
  `package` is the pip name.
  """
  if key in _seen: return
  _seen.add(key)
  warnings.warn(f"{feature} disabled, install with: pip install {package}", RuntimeWarning,
    stacklevel=caller_level())

def caller_level() -> int:
  """
  `stacklevel` of the first frame outside `pdfmarq`, seen from the function that warns,
  so the warning points at the user's line however deep the library called.
  """
  frame, level = sys._getframe(2), 2
  while frame is not None and frame.f_globals.get("__name__", "").split(".")[0] == "pdfmarq":
    frame, level = frame.f_back, level + 1
  return level

def reset_warnings() -> None:
  """Clear the seen-warnings registry. Used in tests."""
  _seen.clear()
