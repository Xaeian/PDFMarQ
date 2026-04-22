# pdfmarq/_warn.py

"""
Deduplicated warning printer for missing optional dependencies.

When a feature degrades because an optional package is absent, call
`warn_missing(key, package, feature)` once. Repeated calls with the same
key are suppressed so renders do not spam the console.

Example:
  >>> from ._warn import warn_missing
  >>> warn_missing("matplotlib", "matplotlib", "math formulas")
  pdfmarq: math formulas disabled, install with: pip install matplotlib
"""
import sys

_seen: set = set()

def warn_missing(key:str, package:str, feature:str) -> None:
  """Print a one-time warning about a missing optional package.
  Args:
    key: Deduplication key (typically the import name).
    package: pip-installable name (may differ from import name).
    feature: Short human description of what was disabled.
  """
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
