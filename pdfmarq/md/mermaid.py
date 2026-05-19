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

Rendered output is cached to `~/.cache/marq/mermaid/{hash}.png` (shared
with `docmarq`) so the same diagram isn't re-rendered on every build,
even when alternating between PDF and DOCX outputs.

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

# Shared between pdfmarq and docmarq - identical diagrams render once
# regardless of which output format triggers the build first.
_CACHE_DIR = Path.home() / ".cache" / "marq" / "mermaid"
_RENDER_CACHE: dict = {}  # in-memory cache for current process

def _ensure_cache():
  _CACHE_DIR.mkdir(parents=True, exist_ok=True)
  return _CACHE_DIR

def _cache_key(code:str, theme:str, background:str, scale:float) -> str:
  """SHA-1 over inputs that affect rendering. Different theme/bg/scale
  must produce different cache files."""
  payload = f"{code}\x00{theme}\x00{background}\x00{scale}".encode("utf-8")
  return hashlib.sha1(payload).hexdigest()[:16]

#------------------------------------------------------------------------- Backend: mermaid-cli

def _try_mmdc(code:str, out_path:Path, *, cli:str, theme:str,
    background:str, scale:float) -> bool:
  """Render via local mermaid-cli. Returns `True` on success."""
  mmdc = shutil.which(cli)
  if not mmdc: return False
  try:
    in_path = out_path.with_suffix(".mmd")
    in_path.write_text(code, encoding="utf-8")
    cmd = [mmdc, "-i", str(in_path), "-o", str(out_path),
      "-t", theme, "-b", background, "-s", str(scale)]
    pp_config = os.environ.get("XAEIAN_MMDC_PUPPETEER_CONFIG")
    if pp_config and Path(pp_config).exists():
      cmd += ["-p", pp_config]
    result = subprocess.run(cmd, capture_output=True, timeout=60)
    in_path.unlink(missing_ok=True)
    return result.returncode == 0 and out_path.exists()
  except Exception:
    return False

#------------------------------------------------------------------------- Backend: mermaid.ink

def _try_mermaid_ink(code:str, out_path:Path, *, theme:str,
    background:str) -> bool:
  """Render via mermaid.ink HTTP service. Returns `True` on success.
  Internal `scale` is capped at 3 by the API regardless of mmdc setting."""
  ink_scale = 3
  try:
    import urllib.request, base64, zlib, json
    payload = json.dumps({"code": code, "mermaid": {"theme": theme}})
    deflated = zlib.compress(payload.encode("utf-8"), 9)
    encoded = base64.urlsafe_b64encode(deflated).decode("ascii").rstrip("=")
    bg = background.lstrip("#")
    if bg.lower() == "transparent": bg_param = "!FFFFFF00"
    elif all(c in "0123456789abcdefABCDEF" for c in bg):
      bg_param = f"!{bg}"
    else:
      bg_param = bg
    url = (f"https://mermaid.ink/img/pako:{encoded}"
      f"?type=png&width=800&scale={ink_scale}&bgColor={bg_param}")
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

def render_mermaid(code:str, *, cli:str="mmdc", theme:str="default",
    background:str="transparent", scale:float=4) -> tuple[str, float, float]|None:
  """Render a mermaid diagram to a PNG file.

  Args:
    code: Mermaid source (the content of a ```mermaid fenced block).
    cli: `mermaid-cli` binary name or path. Override if mmdc isn't in PATH.
    theme: Mermaid theme - `default` / `dark` / `forest` / `neutral`.
    background: PNG background - `transparent`, hex (`#RRGGBB`), or named.
    scale: Oversampling factor for the mmdc backend (mermaid.ink caps at 3
      internally regardless).

  Returns:
    `(path, width_pt, height_pt)` on success, `None` when both backends fail.
    Results are cached on disk keyed by code + theme + background + scale.
  """
  code = code.strip()
  if not code: return None
  key = _cache_key(code, theme, background, scale)
  if key in _RENDER_CACHE:
    return _RENDER_CACHE[key]
  cache_dir = _ensure_cache()
  out_path = cache_dir / f"{key}.png"
  if not out_path.exists():
    ok = _try_mmdc(code, out_path, cli=cli, theme=theme,
      background=background, scale=scale) or _try_mermaid_ink(
      code, out_path, theme=theme, background=background)
    if not ok:
      _RENDER_CACHE[key] = None
      return None
  try:
    from PIL import Image
    with Image.open(out_path) as im:
      px_w, px_h = im.size
    # Convert px → pt at 96 DPI * oversampling scale. Loaded from cache:
    # scale is the configured value (cache key includes it, so pixel size
    # matches that scale).
    dpi = 96 * scale
    w_pt = px_w * 72 / dpi
    h_pt = px_h * 72 / dpi
  except Exception:
    _RENDER_CACHE[key] = None
    return None
  result = (str(out_path), w_pt, h_pt)
  _RENDER_CACHE[key] = result
  return result