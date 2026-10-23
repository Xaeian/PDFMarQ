# pdfmarq/legal/render.py

"""
Letters, statements and contracts: the page around the markdown content.

`md_to_pdf` lays out one document, `md_parallel_to_pdf` versions of one document side by side.
"""
from dataclasses import dataclass, replace
from markdown_it.token import Token
from ..core import PDF
from ..constants import PageSize, A4
from ..inline import RichSegment
from ..parts import signatures, signatures_height, page_number
from ..md import (MarkdownRenderer, split_frontmatter, pdf_metadata, top_blocks,
  is_pagebreak_directive, is_group_open_directive)
from .style import LegalStyle
from .header import Side, draw_header, draw_attachments, attachments_height, lines_of
from .measure import Probe, Region, balanced_height, balanced_pages

# With fewer body lines than this left on the page, the columns start on the next one.
_MIN_REGION_LINES = 3
_DOTTED = (1, 2) # signing lines, as on a form: dash on and off (pt)

#--------------------------------------------------------------------------------------------- Page

def md_to_pdf(
  md_text:str,
  output_path:str,
  *,
  style:LegalStyle|None = None,
  page:PageSize = A4,
  margin:float|tuple = 20,
  gutter:float = 0,
  base_dir:str|None = None,
  font_dir:str|None = None,
  metadata:dict|None = None,
) -> PDF:
  """
  Letter, statement or contract: markdown content with a letter header and a signed end.

  The text before the first `##` is the preamble, the rest the clauses.
  The arguments match `pdfmarq.paper.md_to_pdf`.
  """
  style = _checked(style or LegalStyle())
  fm, _ = split_frontmatter(md_text)
  pdf = _new_pdf(output_path, page, margin, gutter, font_dir, fm, metadata)
  renderer = MarkdownRenderer(pdf, style, base_dir)
  _footer(pdf, style)
  side = draw_header(pdf, style, fm, renderer.frontmatter_file(fm, "logo"))
  tokens = renderer.parse(md_text)
  renderer.index(tokens)
  labels = style.sign_lines()
  items = lines_of(fm.get("attachments"))
  first = _clauses(tokens)
  _preamble(pdf, renderer, style, tokens[:first], side)
  if style.columns > 1:
    probe = Probe(pdf, style, tokens, base_dir)
    _columns(pdf, renderer, probe, style, tokens[first:], _tail_height(pdf, style, labels, items))
  else:
    renderer.render_tokens(tokens[first:])
  _tail(pdf, style, labels, items)
  pdf.save()
  return pdf

def _checked(style) -> LegalStyle:
  """`style` when it is a usable `LegalStyle`. A wrong one fails here, before anything is drawn."""
  if not isinstance(style, LegalStyle):
    raise TypeError("style must be a LegalStyle, build one with pdfmarq.legal.lang_style()")
  if style.logo_align not in ("L", "C", "R"):
    raise ValueError(f"logo_align must be L, C or R, got {style.logo_align!r}")
  if style.to_align not in ("L", "R"):
    raise ValueError(f"to_align must be L or R, got {style.to_align!r}")
  if not isinstance(style.columns, int) or style.columns < 1:
    raise ValueError(f"columns must be a whole number from 1 up, got {style.columns!r}")
  return style

def _new_pdf(
  output_path:str, page:PageSize, margin:float|tuple, gutter:float,
  font_dir:str|None, fm:dict, metadata:dict|None,
) -> PDF:
  """The output `PDF`, its metadata from frontmatter, which `metadata=` overrides per key."""
  pdf = PDF(output_path, width=page.width, height=page.height,
    margin=margin, gutter=gutter, font_dir=font_dir or "./fonts")
  meta = pdf_metadata(fm, metadata)
  if meta: pdf.metadata(**meta)
  return pdf

def _footer(pdf:PDF, style:LegalStyle):
  """Page number on every page of a document longer than one."""
  if not style.page_number_label: return
  face = RichSegment("", family=style.page_font, mode=style.body_mode,
    size=style.header_size, color=style.muted_color)
  def footer(p:PDF, n:int, total:int):
    if total > 1:
      page_number(p, style.page_number_label, n, total, face, show_total=style.page_number_total)
  pdf.on_final_page(footer)

#----------------------------------------------------------------------------------------- Preamble

def _clauses(tokens:list[Token]) -> int:
  """Start of the first top-level `##`, where the clauses begin. Without one it is `0`."""
  return next((start for start, _ in top_blocks(tokens)
    if tokens[start].type == "heading_open" and tokens[start].tag == "h2"), 0)

def _preamble(
  pdf:PDF, renderer:MarkdownRenderer, style:LegalStyle, tokens:list[Token], side:Side|None,
):
  """
  The preamble in the header face and its own size and spacing,
  beside a side logo while it is next to it.
  The clauses start `preamble_gap` below the preamble and the logo.
  """
  if not tokens and side is None: return
  page = pdf.page_num
  look = replace(style, font_body=style.page_font,
    body_size=style.preamble_size or style.body_size,
    para_gap=style.para_gap if style.preamble_para_gap is None else style.preamble_para_gap)
  done = _beside(pdf, renderer, look, tokens, side) if side else 0
  renderer.render_tokens(tokens[done:], look)
  y = pdf.y
  if side and pdf.page_num == page: y = max(y, side.bottom)
  pdf.cursor(0, y + style.preamble_gap)

def _beside(
  pdf:PDF, renderer:MarkdownRenderer, look:LegalStyle, tokens:list[Token], side:Side,
) -> int:
  """
  Draw the blocks that start next to the logo, in the width it leaves them.
  Returns the index of the first token left to draw.

  The frame beside the logo starts at its top,
  so the text below the title is spaced as on a page that goes on.
  """
  page = pdf.page_num
  below = pdf.y
  pdf.cursor(0, side.top)
  if side.align == "L": pdf.inset(left=side.width)
  else: pdf.inset(right=side.width)
  pdf.cursor(0, below - side.top)
  done = 0
  for start, end in top_blocks(tokens):
    if pdf.page_num != page or side.top + pdf.y >= side.bottom: break
    renderer.render_tokens(tokens[start:end], look)
    done = end
  pdf.inset()
  return done

#------------------------------------------------------------------------------------------ Columns

def _columns(
  pdf:PDF, renderer:MarkdownRenderer, probe:Probe,
  style:LegalStyle, clauses:list[Token], tail_h:float,
):
  """
  The clauses in columns from the cursor, the preamble already above them.

  A text that fits the page with the end of the document below it gets balanced columns.
  A longer one flows, its last page balanced when the end of the document still fits below it.
  """
  line = style.line_mm(style.body_size)
  if pdf.content_height - pdf.y < _MIN_REGION_LINES * line and pdf.y > 0.5:
    pdf.new_page()
  region = Region(clauses, pdf.content_width, style.columns, style.column_gap)
  page = pdf.content_height
  height = balanced_height(probe, region, page - pdf.y - tail_h, line)
  if height is None:
    height = balanced_pages(probe, region, pdf.y, page, page - tail_h, line)
  pdf.columns(region.count, gap=region.gap, height=height)
  renderer.render_tokens(clauses)
  pdf.columns(1)

#---------------------------------------------------------------------------------------------- End

def _sign_face(style:LegalStyle) -> RichSegment:
  """Signing line labels: italics in the header face, in the text colour."""
  return RichSegment("", family=style.page_font, mode=style.italic_mode,
    size=style.sign_size, color=style.body_color)

def _signing_height(pdf:PDF, style:LegalStyle, labels:list[str]) -> float:
  """Height (mm) of the signing lines `style` draws for `labels`, none for no labels."""
  return signatures_height(pdf, labels, _sign_face(style), gap=style.sign_gap, width=style.sign_w)

def _signatures(pdf:PDF, style:LegalStyle, labels:list[str]):
  """Dotted signing lines in the text colour, labels in the header face."""
  signatures(pdf, labels, _sign_face(style),
    gap=style.sign_gap, width=style.sign_w, thick=style.hr_thick, dash=_DOTTED)

def _make_room(pdf:PDF, height:float, bottom:bool):
  """
  Room for the end of a document, kept on one page:
  a new page when the rest of this one is too short, otherwise, with `bottom`, its bottom margin.
  """
  if height > pdf.content_height - pdf.y and pdf.y > 0.5: pdf.new_page()
  elif bottom: pdf.cursor(0, pdf.content_height - height)

def _tail_height(pdf:PDF, style:LegalStyle, labels:list[str], items:list[str]) -> float:
  """Height (mm) of the signing lines and attachments that end the document."""
  return _signing_height(pdf, style, labels) + attachments_height(pdf, style, items)

def _tail(pdf:PDF, style:LegalStyle, labels:list[str], items:list[str]):
  """
  Signing lines, then the attachments, always together on one page.
  With `sign_bottom` they sit at the bottom margin when the current page has room for them.
  """
  if not labels and not items: return
  _make_room(pdf, _tail_height(pdf, style, labels, items), style.sign_bottom)
  _signatures(pdf, style, labels)
  draw_attachments(pdf, style, items)

#----------------------------------------------------------------------------------------- Parallel

def md_parallel_to_pdf(
  md_texts:list[str],
  output_path:str,
  *,
  styles:list[LegalStyle],
  page:PageSize = A4,
  margin:float|tuple = 20,
  gutter:float = 0,
  base_dir:str|None = None,
  font_dir:str|None = None,
  metadata:dict|None = None,
) -> PDF:
  """
  Versions of one document side by side, one column each, usually one per language.

  Each version is an ordinary legal document drawn with its own style,
  so its own labels and date format.
  Which language a version is in is the caller's knowledge, not this one's.
  Top-level blocks pair up in order and every row starts level in all columns.
  Signing lines and the page number come from `styles[0]`,
  the PDF metadata from the first version's frontmatter, which `metadata=` overrides per key.
  """
  if len(md_texts) < 2:
    raise ValueError(f"a parallel document needs two versions or more, got {len(md_texts)}")
  if len(styles) != len(md_texts):
    raise ValueError(f"{len(md_texts)} versions need as many styles, got {len(styles)}")
  styles = [_checked(s) for s in styles]
  for i, style in enumerate(styles, 1):
    if style.h1_page_break:
      raise ValueError(f"style {i}: h1_page_break would break a page in the middle of a row")
  fronts = [split_frontmatter(text)[0] for text in md_texts]
  pdf = _new_pdf(output_path, page, margin, gutter, font_dir, fronts[0], metadata)
  versions = [_version(pdf, style, text, fm, base_dir, i)
    for i, (style, text, fm) in enumerate(zip(styles, md_texts, fronts))]
  rows = _pair([v.tokens for v in versions])
  _footer(pdf, styles[0])
  count, gap = len(versions), styles[0].column_gap
  pdf.columns(count, gap=gap, flow=False)
  def header(i:int):
    v = versions[i]
    draw_header(pdf, v.style, v.front, v.logo, beside=False)
  _level(pdf, count, header)
  _rows(pdf, versions, rows)
  items = [lines_of(fm.get("attachments")) for fm in fronts]
  listing = max(attachments_height(pdf, s, i) for s, i in zip(styles, items)) # in a column
  pdf.columns(1)
  _parallel_tail(pdf, styles, items, listing)
  pdf.save()
  return pdf

@dataclass
class _Version:
  """One version of a parallel document: its look, its facts, its text and what draws it."""
  style: LegalStyle
  front: dict
  logo: str|None
  renderer: MarkdownRenderer
  tokens: list[Token]
  probe: Probe

def _version(
  pdf:PDF, style:LegalStyle, md_text:str, fm:dict,
  base_dir:str|None, i:int,
) -> _Version:
  """
  Version `i` parsed and indexed, its anchors named apart from the other versions' anchors,
  so a link in one version jumps to a heading of its own.
  """
  renderer = MarkdownRenderer(pdf, style, base_dir)
  tokens = renderer.parse(md_text)
  renderer.index(tokens, prefix=f"v{i + 1}-" if i else "")
  logo = renderer.frontmatter_file(fm, "logo")
  return _Version(style, fm, logo, renderer, tokens, Probe(pdf, style, tokens, base_dir))

def _level(pdf:PDF, count:int, draw):
  """Call `draw(i)` in each column `i` from the same height, then leave the cursor below all."""
  y = pdf.y
  bottom = y
  for i in range(count):
    pdf.column(i)
    pdf.cursor(0, y)
    draw(i)
    bottom = max(bottom, pdf.y)
  pdf.column(0)
  pdf.cursor(0, bottom)

def _kind(tokens:list[Token], start:int) -> str:
  """What a top-level block is, for matching versions: its opening token, a directive by name."""
  t = tokens[start]
  if t.type == "html_block":
    if is_pagebreak_directive(t.content or ""): return "pagebreak"
    if is_group_open_directive(t.content or ""): return "group"
  return f"{t.type} {t.tag}".strip()

def _preview(tokens:list[Token], span:tuple[int, int]|None) -> str:
  """Start of the text of the block at `span`, for an error message."""
  if span is None: return ""
  start, end = span
  text = next((t.content for t in tokens[start:end] if t.type == "inline"), "")
  text = " ".join(text.split())
  return f" {text[:40] + '...' if len(text) > 40 else text!r}" if text else ""

def _pair(versions:list[list[Token]]) -> list[list[tuple[int, int]]]:
  """
  Rows of block spans, one span per version, after checking the versions line up.
  Differing block counts or kinds raise, naming the first block where they part ways,
  and so does a page break inside a block, which would break a page mid-row.
  """
  blocks = [top_blocks(tokens) for tokens in versions]
  for k in range(max(len(b) for b in blocks)):
    spans = [b[k] if k < len(b) else None for b in blocks]
    kinds = [_kind(t, s[0]) if s else "nothing" for t, s in zip(versions, spans)]
    if len(set(kinds)) > 1:
      parts = "; ".join(f"version {i}: {kind}{_preview(t, s)}"
        for i, (kind, t, s) in enumerate(zip(kinds, versions, spans), 1))
      raise ValueError(f"versions part ways at block {k + 1}: {parts}")
  for tokens, spans in zip(versions, blocks):
    for start, end in spans:
      if any(t.type == "html_block" and is_pagebreak_directive(t.content or "")
          for t in tokens[start + 1:end]):
        raise ValueError("a <!-- pagebreak --> inside a block would break a page mid-row")
  return [list(row) for row in zip(*blocks)]

def _rows(pdf:PDF, versions:list[_Version], rows:list[list[tuple[int, int]]]):
  """
  Draw the rows level across the columns, breaking pages between rows only.

  Each row is measured where it will be drawn.
  One that misses the rest of the page goes to the next;
  a heading row keeps the row after it company.
  A row taller than a whole column cannot be placed and raises.
  """
  width = pdf.content_width
  k = 0
  while k < len(rows):
    row = rows[k]
    kind = _kind(versions[0].tokens, row[0][0])
    if kind == "pagebreak":
      if pdf.y > 0.5: pdf.new_page()
      k += 1
      continue
    y = pdf.y
    height = _row_height(versions, row, width, y)
    need = height
    if kind.startswith("heading_open") and k + 1 < len(rows) \
        and _kind(versions[0].tokens, rows[k + 1][0][0]) != "pagebreak":
      need += _row_height(versions, rows[k + 1], width, y + height)
    room = pdf.content_height - y
    if need > room:
      if y > 0.5:
        pdf.new_page()
        continue
      if height > room:
        raise ValueError(f"block {k + 1} is taller than a whole column; split it up")
    _level(pdf, len(versions),
      lambda i: versions[i].renderer.render_tokens(versions[i].tokens[slice(*row[i])]))
    k += 1

def _row_height(
  versions:list[_Version], row:list[tuple[int, int]],
  width:float, y:float,
) -> float:
  """Height (mm) of the tallest version of `row`, each measured from `y`."""
  return max(v.probe.height(v.tokens[slice(*span)], width, y) for v, span in zip(versions, row))

def _parallel_tail(pdf:PDF, styles:list[LegalStyle], items:list[list[str]], listing:float):
  """
  Signing lines across the page from `styles[0]`, then each version's attachments in its column,
  `listing` mm tall at most, kept together on one page and moved down with `sign_bottom`.
  """
  first = styles[0]
  labels = first.sign_lines()
  if not labels and not any(items): return
  _make_room(pdf, _signing_height(pdf, first, labels) + listing, first.sign_bottom)
  _signatures(pdf, first, labels)
  if any(items):
    pdf.columns(len(styles), gap=first.column_gap, flow=False)
    _level(pdf, len(styles), lambda i: draw_attachments(pdf, styles[i], items[i]))
    pdf.columns(1)
