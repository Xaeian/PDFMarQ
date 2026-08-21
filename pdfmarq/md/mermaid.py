# pdfmarq/md/mermaid.py

"""Mermaid diagram rendering with hybrid backends.

Backends tried in priority order:
  1. mermaid-cli (mmdc) - local subprocess, best quality, fully offline.
  2. mermaid.ink - public HTTP fallback, needs internet, **sends the diagram
     source to a third party**. Warns once per process; disable entirely with
     `MarkdownStyle(mermaid_remote=False)` / `render_mermaid(remote=False)`.
  3. None - both failed; caller falls back to a plain code block.

Output cached to `~/.cache/marq/mermaid/{hash}.png`, keyed on everything
that affects the pixels (source, theme, background, scale, font, cli), so a
diagram is rendered once per distinct look. Writes go through a temp file
and an atomic rename; a cached PNG that fails to decode is re-rendered.

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
import time
from pathlib import Path

#-------------------------------------------------------------------------------------------- Cache

# `marq`, not `pdfmarq`: docmarq computes the same key for the same diagram
# and both packages read each other's entries. Package-private caches (the
# openmoji checkout) live under `pdfmarq` instead.
_CACHE_DIR = Path.home() / ".cache" / "marq" / "mermaid"

_MISS = object() # "not in cache", distinct from a cached failure (None)
_RENDER_CACHE: dict = {} # key → (path, w_pt, h_pt)
_FAIL_CACHE: dict = {} # key → time.monotonic() of the last failure
# Failures expire so a transient network error costs one diagram for a
# minute, not for the life of the process. Matters for long-running
# servers: connectivity returns, and the diagram has to return with it.
_FAIL_TTL_S = 60.0

def _ensure_cache():
  _CACHE_DIR.mkdir(parents=True, exist_ok=True)
  return _CACHE_DIR

def _cache_key(code:str, theme:str, background:str, scale:float,
    font_family:str="", font_dir:str="", cli:str="") -> str:
  """SHA-1 over every input that affects rendering. Different theme, bg,
  scale, font (family *and* directory - same family name can resolve to a
  different TTF) or cli must produce a different cache file.

  docmarq builds this payload identically so both packages share entries;
  the field order is part of that contract.
  """
  payload = (f"{code}\x00{theme}\x00{background}\x00{scale}\x00"
    f"{font_family}\x00{font_dir}\x00{cli}").encode("utf-8")
  return hashlib.sha1(payload).hexdigest()[:16]

def _cache_get(key:str):
  """Cached result, `None` for a fresh failure, `_MISS` when unknown."""
  hit = _RENDER_CACHE.get(key)
  if hit is not None:
    if Path(hit[0]).exists():
      return hit
    del _RENDER_CACHE[key] # cache file disappeared underneath us
  failed_at = _FAIL_CACHE.get(key)
  if failed_at is not None:
    if time.monotonic() - failed_at < _FAIL_TTL_S:
      return None
    del _FAIL_CACHE[key]
  return _MISS

def _cache_fail(key:str) -> None:
  _FAIL_CACHE[key] = time.monotonic()

def _tmp_path(out_path:Path) -> Path:
  """Unique sibling temp path. Rendering straight into the cache name would
  leave a truncated PNG behind on a crash or a killed subprocess."""
  return out_path.with_name(f"{out_path.stem}.{os.getpid()}.tmp{out_path.suffix}")

def _valid_png(path:Path) -> bool:
  """True when `path` holds a PNG that decodes. A corrupt or half-written
  leftover has to be re-rendered rather than served from cache."""
  if not path.exists() or path.stat().st_size == 0:
    return False
  try:
    from PIL import Image
    with Image.open(path) as im:
      im.verify()
    return True
  except Exception:
    return False

def _scale_sidecar(out_path:Path) -> Path:
  return out_path.with_suffix(".scale")

def _write_scale(out_path:Path, eff_scale:float) -> None:
  """Record the scale the PNG was actually rendered at.

  The pt-per-pixel math needs the effective scale and the mermaid.ink
  backend ignores the requested one, so the number has to survive next to
  the file - a later process reads the cache without knowing the backend.
  """
  try:
    _scale_sidecar(out_path).write_text(str(eff_scale), encoding="utf-8")
  except Exception:
    pass # cosmetic: a missing sidecar falls back to the requested scale

def _read_scale(out_path:Path, default:float) -> float:
  try:
    return float(_scale_sidecar(out_path).read_text(encoding="utf-8").strip())
  except Exception:
    return default

#----------------------------------------------------------------------------------------- Font CSS

def _resolve_font_ttf(font_dir:str, family:str) -> Path|None:
  """Find `<family>-Regular.ttf` under `font_dir` (mirrors `FontManager`)."""
  base = Path(font_dir)
  for sub in (family.lower(), family):
    p = base / sub / f"{family}-Regular.ttf"
    if p.exists(): return p
  p = base / f"{family}-Regular.ttf"
  if p.exists(): return p
  return None

def _mmdc_css_with_font(ttf_path:Path, family:str) -> str:
  """CSS for mmdc: @font-face from local TTF + apply to all SVG text."""
  return (
    f"@font-face {{\n"
    f"  font-family: '{family}';\n"
    f"  src: url('file:///{ttf_path.as_posix()}');\n"
    f"}}\n"
    f"* {{ font-family: '{family}', sans-serif !important; }}\n"
  )

def _puppeteer_config() -> str|None:
  """Path to a puppeteer config for mmdc, from the environment.

  `PDFMARQ_MMDC_PUPPETEER_CONFIG` is the documented name; the `XAEIAN_*`
  spelling is accepted as an alias.
  """
  for name in ("PDFMARQ_MMDC_PUPPETEER_CONFIG", "XAEIAN_MMDC_PUPPETEER_CONFIG"):
    val = os.environ.get(name)
    if val and Path(val).exists():
      return val
  return None

#----------------------------------------------------------------------------- Backend: mermaid-cli

def _try_mmdc(code:str, out_path:Path, *, cli:str, theme:str,
    background:str, scale:float,
    font_family:str|None=None, font_dir:str|None=None) -> bool:
  """Render via local mermaid-cli. Returns `True` on success.
  When `font_family`+`font_dir` are set and a matching TTF is found, a
  temp CSS file with `@font-face` is injected via `--cssFile`."""
  mmdc = shutil.which(cli)
  if not mmdc: return False
  in_path = out_path.with_suffix(".mmd")
  css_path = out_path.with_suffix(".css")
  try:
    in_path.write_text(code, encoding="utf-8")
    cmd = [mmdc, "-i", str(in_path), "-o", str(out_path),
      "-t", theme, "-b", background, "-s", str(scale)]
    pp_config = _puppeteer_config()
    if pp_config:
      cmd += ["-p", pp_config]
    if font_family and font_dir:
      ttf = _resolve_font_ttf(font_dir, font_family)
      if ttf is not None:
        css_path.write_text(_mmdc_css_with_font(ttf, font_family), encoding="utf-8")
        cmd += ["--cssFile", str(css_path)]
    result = subprocess.run(cmd, capture_output=True, timeout=60)
    return result.returncode == 0 and out_path.exists()
  except Exception:
    return False
  finally:
    in_path.unlink(missing_ok=True)
    css_path.unlink(missing_ok=True)

#----------------------------------------------------------------------------- Backend: mermaid.ink

# mermaid.ink renders at a fixed oversampling factor regardless of what the
# caller asked for, so the pt-per-pixel math has to use this number and not
# the requested `scale`.
_INK_SCALE = 3

_INK_WARNED = False

def _warn_remote_once() -> None:
  """Warn once per process before any diagram source leaves the machine."""
  global _INK_WARNED
  if _INK_WARNED:
    return
  _INK_WARNED = True
  import warnings
  warnings.warn(
    "mermaid: local `mmdc` not found, falling back to the mermaid.ink public "
    "HTTP service - the diagram source is sent to a third-party server. "
    "Install mermaid-cli (npm i -g @mermaid-js/mermaid-cli) to render "
    "locally, or pass mermaid_remote=False to keep everything offline.",
    RuntimeWarning, stacklevel=3,
  )

def _try_mermaid_ink(code:str, out_path:Path, *, theme:str,
    background:str) -> bool:
  """Render via mermaid.ink HTTP service. Returns `True` on success.
  Internal `scale` is capped at 3 by the API regardless of mmdc setting."""
  _warn_remote_once()
  try:
    import urllib.request, urllib.parse, base64, zlib, json
    payload = json.dumps({"code": code, "mermaid": {"theme": theme}})
    deflated = zlib.compress(payload.encode("utf-8"), 9)
    encoded = base64.urlsafe_b64encode(deflated).decode("ascii").rstrip("=")
    bg = background.lstrip("#")
    if bg.lower() == "transparent": bg_param = "!FFFFFF00"
    elif all(c in "0123456789abcdefABCDEF" for c in bg):
      bg_param = f"!{bg}"
    else:
      bg_param = bg
    # Named colors are arbitrary user text - quote before splicing into the URL.
    bg_param = urllib.parse.quote(bg_param, safe="!")
    url = (f"https://mermaid.ink/img/pako:{encoded}"
      f"?type=png&width=800&scale={_INK_SCALE}&bgColor={bg_param}")
    req = urllib.request.Request(url, headers={"User-Agent": "pdfmarq"})
    with urllib.request.urlopen(req, timeout=15) as resp:
      data = resp.read()
    if data.startswith(b"\x89PNG"):
      out_path.write_bytes(data)
      return True
  except Exception:
    pass
  return False

#--------------------------------------------------------------------------------------- Public API

def render_mermaid(code:str, *, cli:str="mmdc", theme:str="default",
    background:str="transparent", scale:float=3,
    font_family:str|None=None, font_dir:str|None=None,
    remote:bool=True,
) -> tuple[str, float, float]|None:
  """Render a mermaid diagram to a PNG file.

  Args:
    code: Mermaid source (the content of a ```mermaid fenced block).
    cli: `mermaid-cli` binary name or path. Override if mmdc isn't in PATH.
    theme: Mermaid theme - `default` / `dark` / `forest` / `neutral`.
    background: PNG background - `transparent`, hex (`#RRGGBB`), or named.
    scale: Oversampling factor for the mmdc backend (mermaid.ink caps at 3).
    font_family: Font family name (matches body). Diagram text uses it
      instead of system default. Requires `font_dir` with a matching TTF.
      Ignored by the mermaid.ink HTTP fallback (no custom-font support).
    font_dir: Directory holding `<family>/<family>-Regular.ttf` (mirrors
      `FontManager._resolve_path`). Skipped when family TTF isn't found.
    remote: Allow the mermaid.ink HTTP fallback when `mmdc` is unavailable.
      Set `False` to keep the diagram source on this machine - rendering then
      fails (returns `None`) instead, and the caller emits a code block.

  Returns:
    `(path, width_pt, height_pt)` on success, `None` when no backend
    succeeded. Failures are remembered for a minute, then retried.
  """
  code = code.strip()
  if not code: return None
  key = _cache_key(code, theme, background, scale,
    font_family or "", font_dir or "", cli)
  cached = _cache_get(key)
  if cached is not _MISS:
    return cached
  cache_dir = _ensure_cache()
  out_path = cache_dir / f"{key}.png"
  if _valid_png(out_path):
    eff_scale = _read_scale(out_path, scale)
  else:
    out_path.unlink(missing_ok=True) # drop a corrupt leftover
    tmp = _tmp_path(out_path)
    if _try_mmdc(code, tmp, cli=cli, theme=theme,
        background=background, scale=scale,
        font_family=font_family, font_dir=font_dir):
      eff_scale = scale
    elif remote and _try_mermaid_ink(
        code, tmp, theme=theme, background=background):
      eff_scale = _INK_SCALE
    else:
      tmp.unlink(missing_ok=True)
      _cache_fail(key)
      return None
    try:
      os.replace(tmp, out_path) # atomic: readers never see a partial file
    except Exception:
      tmp.unlink(missing_ok=True)
      _cache_fail(key)
      return None
    _write_scale(out_path, eff_scale)
  try:
    from PIL import Image
    with Image.open(out_path) as im:
      px_w, px_h = im.size
    # Renders at 96 DPI * the scale actually used - which is the backend's
    # fixed factor for mermaid.ink, not the requested one.
    dpi = 96 * eff_scale
    w_pt = px_w * 72 / dpi
    h_pt = px_h * 72 / dpi
  except Exception:
    _cache_fail(key)
    return None
  result = (str(out_path), w_pt, h_pt)
  _RENDER_CACHE[key] = result
  return result
