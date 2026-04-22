# pdfmarq/md/mermaid.py

"""
Mermaid diagram rendering with hybrid backends.

Mermaid is a JavaScript-only library - no native Python implementation
exists. We try multiple rendering backends in priority order and use the
first one that succeeds:

  1. **mermaid-cli (mmdc)** - local subprocess, best quality, requires
     Node.js + `npm install -g @mermaid-js/mermaid-cli`. Fully offline.
  2. **mermaid.ink** - public HTTP service, no local deps but needs internet.
     Free, no API key. Used as fallback when mmdc unavailable.
  3. **None** - both failed. Caller falls back to plain code block.

Rendered output is cached to `~/.cache/pdfmarq/mermaid/{hash}.png` so the
same diagram isn't re-rendered on every PDF build.

Usage:
  >>> from pdfmarq.mermaid import render_mermaid
  >>> path, w_pt, h_pt = render_mermaid("flowchart LR\\nA-->B")
  >>> # path: PNG file path, dimensions in points
"""

__extras__ = ("mermaid", [])

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

#---------------------------------------------------------------------------------------- Cache

_CACHE_DIR = Path.home() / ".cache" / "pdfmarq" / "mermaid"
_RENDER_CACHE: dict = {}  # in-memory cache for current process

def _ensure_cache():
  _CACHE_DIR.mkdir(parents=True, exist_ok=True)
  return _CACHE_DIR

def _hash(code: str) -> str:
  return hashlib.sha1(code.encode("utf-8")).hexdigest()[:16]

#------------------------------------------------------------------------- Backend: mermaid-cli

def _try_mmdc(code: str, out_path: Path) -> bool:
  """Render via local mermaid-cli binary. Returns True on success."""
  mmdc = shutil.which("mmdc")
  if not mmdc:
    return False
  try:
    in_path = out_path.with_suffix(".mmd")
    in_path.write_text(code, encoding="utf-8")
    cmd = [mmdc, "-i", str(in_path), "-o", str(out_path),
           "-b", "transparent", "-s", "3"]
    # Optional puppeteer config (e.g. custom Chrome path in sandboxed envs)
    pp_config = os.environ.get("XAEIAN_MMDC_PUPPETEER_CONFIG")
    if pp_config and Path(pp_config).exists():
      cmd += ["-p", pp_config]
    result = subprocess.run(cmd, capture_output=True, timeout=60)
    in_path.unlink(missing_ok=True)
    return result.returncode == 0 and out_path.exists()
  except Exception:
    return False

#------------------------------------------------------------------------- Backend: mermaid.ink

def _try_mermaid_ink(code: str, out_path: Path) -> bool:
  """Render via mermaid.ink HTTP service. Returns True on success."""
  try:
    import urllib.request
    import base64
    import zlib
    # mermaid.ink expects pako-deflate-base64-url-safe encoded code
    # Format: pako:base64(zlib.deflate(json))
    import json
    payload = json.dumps({"code": code, "mermaid": {"theme": "default"}})
    deflated = zlib.compress(payload.encode("utf-8"), 9)
    encoded = base64.urlsafe_b64encode(deflated).decode("ascii").rstrip("=")
    url = f"https://mermaid.ink/img/pako:{encoded}?type=png&bgColor=!FFFFFF00"
    req = urllib.request.Request(url, headers={"User-Agent": "pdfmarq"})
    with urllib.request.urlopen(req, timeout=15) as resp:
      data = resp.read()
    if data and len(data) > 100:
      out_path.write_bytes(data)
      return True
  except Exception:
    pass
  return False

#----------------------------------------------------------------------------------- Public API

def render_mermaid(code: str) -> tuple[str, float, float]|None:
  """Render a mermaid diagram to a PNG file.

  Tries backends in order: mmdc → mermaid.ink. Returns (path, width_pt,
  height_pt) on success or None if all backends failed.

  Results are cached on disk by SHA-1 hash of the code, so identical
  diagrams across builds reuse the same file.
  """
  code = code.strip()
  if not code:
    return None
  key = _hash(code)
  if key in _RENDER_CACHE:
    return _RENDER_CACHE[key]
  cache_dir = _ensure_cache()
  out_path = cache_dir / f"{key}.png"
  if not out_path.exists():
    success = _try_mmdc(code, out_path) or _try_mermaid_ink(code, out_path)
    if not success:
      _RENDER_CACHE[key] = None
      return None
  # Read PNG dimensions for sizing
  try:
    from PIL import Image
    with Image.open(out_path) as im:
      px_w, px_h = im.size
    # Mermaid renders at 96 DPI by default; mmdc -s 3 gives 3x oversampling.
    # Convert px → pt assuming 96 DPI base, with oversampling factored out.
    # Heuristic: if image > 1500 px wide, assume oversampled at 3x.
    dpi = 96 * (3 if px_w > 1500 else 1)
    w_pt = px_w * 72 / dpi
    h_pt = px_h * 72 / dpi
  except Exception:
    _RENDER_CACHE[key] = None
    return None
  result = (str(out_path), w_pt, h_pt)
  _RENDER_CACHE[key] = result
  return result
