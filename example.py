"""
Render a markdown file to PDF via `pdfmarq`, then compress with Ghostscript.

Usage:
  python example.py <input.md>

Showcases:
  - language preset
  - custom TTF fonts loaded from `./fonts/`
  - `link_root` for cross-document references in the rendered PDF
  - `base_dir` so relative image paths in the markdown resolve correctly
  - YAML frontmatter → page-1 banner + chrome (`render:` block)
  - Ghostscript post-process for a smaller, distribution-ready PDF
"""
import sys
from pdfmarq.md import md_to_pdf, lang_style
from xaeian import PATH, FILE, Print, Color as c
from xaeian.media.pdf import pdf_compress

p = Print()

LANG = "en" # en | pl | de | fr | es | it | cs | sk
LINK_ROOT = "https://github.com/{owner}/docs/blob/main"
FONTS = dict(body_family="IBMPlexSans", mono_family="IBMPlexMono", head_family="Sora")
COMPRESS = "/printer" # /screen | /ebook | /printer | /prepress | None

#----------------------------------------------------------------------------------- Renderer

def render(in_path:str) -> str:
  """Convert markdown at `in_path` to a sibling `.pdf`. Returns output path."""
  in_path = PATH.resolve(in_path, read=False)
  if not PATH.is_file(in_path):
    p.err(f"input not found | {c.RED}{in_path}{c.END}")
    sys.exit(1)
  here = PATH.dirname(PATH.resolve(__file__))
  out_path = PATH.with_suffix(in_path, ".pdf")
  md_to_pdf(
    FILE.load(in_path), out_path,
    style=lang_style(LANG, link_root=LINK_ROOT, **FONTS),
    font_dir=f"{here}/fonts",
    base_dir=PATH.dirname(in_path),
  )
  return out_path

#-------------------------------------------------------------------------------------- Entry

def main():
  if len(sys.argv) != 2:
    p.err(f"usage: {c.SKY}python example.py <input.md>{c.END}")
    sys.exit(1)
  out = render(sys.argv[1])
  s0 = FILE.size(out)
  p.ok(f"rendered | {c.SKY}{out}{c.END} | {c.GREEN}{s0/1024:.1f} kB{c.END}")
  if COMPRESS:
    try:
      pdf_compress(out, settings=COMPRESS, inplace=True)
      s1 = FILE.size(out)
      p.ok(
        f"compressed {COMPRESS} | "
        f"{c.GREEN}{s1/1024:.1f} kB{c.END} "
        f"({c.YELLOW}{s1/s0*100:.0f}%{c.END})"
      )
    except RuntimeError as e:
      p.wrn(f"compress skipped | {e}")

if __name__ == "__main__":
  main()
