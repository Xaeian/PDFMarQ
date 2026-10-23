# pdfmarq/_warn.py

"""
Warnings of the library, pointing at the user's line however deep the library called.
A missing optional package or a missing glyph warns once per process.

>>> from ._warn import warn_missing
>>> warn_missing("matplotlib", "matplotlib", "math formulas")
RuntimeWarning: math formulas disabled, install with: pip install matplotlib
"""
import sys, warnings

_seen: set = set()
_LIBRARY = ("pdfmarq", "contextlib") # modules whose frames a warning looks past

def warn_once(key, message:str, category:type[Warning]=RuntimeWarning) -> None:
  """Warn `message` the first time `key` comes, later ones staying quiet."""
  if key in _seen: return
  _seen.add(key)
  warnings.warn(message, category, stacklevel=caller_level())

def warn_missing(key:str, package:str, feature:str) -> None:
  """
  Warn once per process that `feature` is disabled because `package` is absent.
  `key` is the dedup handle, typically the import name.
  `package` is the pip name.
  """
  warn_once(key, f"{feature} disabled, install with: pip install {package}")

def caller_level() -> int:
  """
  `stacklevel` of the first frame outside `pdfmarq`, seen from the function that warns,
  so the warning points at the user's line however deep the library called.
  `contextlib` counts as the library: a `with` block it closes warns at the user's `with`.
  """
  frame, level = sys._getframe(2), 2
  while frame is not None and frame.f_globals.get("__name__", "").split(".")[0] in _LIBRARY:
    frame, level = frame.f_back, level + 1
  return level

def reset_warnings() -> None:
  """Clear the seen-warnings registry. Used in tests."""
  _seen.clear()
