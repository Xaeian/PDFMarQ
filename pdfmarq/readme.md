# `pdfmarq`

Fluent PDF generation.
Built on reportlab with a cursor-based flow model.
Sibling library: [`docmarq`](https://github.com/Xaeian/DocMarQ) - same API shape for DOCX.

## `PDF` context

```py
from pdfmarq import PDF, A4
with PDF("out.pdf") as pdf:
  pdf.font("Helvetica", 16, "Bold").text("Hello")
# Custom page size + margins (CSS-style: scalar / (v,h) / (t,h,b) / (t,r,b,l))
with PDF("out.pdf", width=A4.width, height=A4.height, margin=20) as pdf:
  pdf.margin(20, 25, 15) # lr, top, bot in mm
# Binding margin, added to the left one (PDF has no native gutter)
PDF("out.pdf", margin=20, gutter=8)
# Units (default mm)
PDF("out.pdf", unit="pt") # or "cm", "in", "px"
```

## Fonts

```py
# Built-in (no registration)
pdf.font("Helvetica", 12, "Bold")
pdf.font("Times", 11, "Italic")
pdf.font("Courier", 10)
# Custom TTF from font_dir (convention: fonts/Family/Family-Mode.ttf)
pdf = PDF("out.pdf", font_dir="./fonts")
pdf.add_font("Barlow").add_font("Barlow", "Bold")
pdf.add_font("Barlow", "Italic")
pdf.font("Barlow", 14, "Bold").text("Custom font")
# A face from any folder, under a family name of your choice
pdf.fonts.register_file("DejaVuSans", "Bold", "assets/DejaVuSans-Bold.ttf")
# Partial updates - only change what you need
pdf.font("Helvetica", 16, "Bold").text("Title")
pdf.font(size=11, mode="Regular").text("Body")
```

## Cursor and flow

```py
# Origin = top-left, y grows down. All units in mm by default.
pdf.cursor(0, 0, "L")  # top-left, left-anchored
pdf.cursor(0, 0, "R")  # top-right, right-anchored
pdf.cursor(0, 0, "C")  # top-center
pdf.text("Hi")         # advances x by text width
pdf.enter()            # newline: reset x, advance y by line height
pdf.enter(10)          # newline with explicit 10mm gap
pdf.move(5, 3)         # relative shift dx=5, dy=3
pdf.new_page()         # page break, cursor reset
pdf.next_frame()       # next column, or a new page after the last one
# Read current position
pdf.x, pdf.y           # cursor mm
pdf.content_width, pdf.content_height # frame area: the page minus margins, or the open column
pdf.margin_left        # and margin_right, margin_top, margin_bot: the frame's, mm
pdf.column_index       # column the cursor is in, from 0
pdf.page_num           # current page number
pdf.output_path        # destination file path
```

## Columns

A column is a narrower page: content width, margins, `y` and centring all refer to it, so anything that draws relative to the margins lands inside the column.

```py
pdf.columns(2, gap=8)            # two columns from the current height
pdf.next_frame()                 # move on: column 2, then a new page
pdf.columns(2, gap=8, height=90) # columns capped at 90mm on this page, for balancing
pdf.columns(2, height=[None, 90]) # capped page by page: here the second page only
pdf.columns(1)                   # close: full width again, below the lowest column
# Parallel columns: the caller places content and breaks pages itself
pdf.columns(2, gap=8, flow=False)
pdf.column(1)                    # the second column (index from 0), same height
# One narrower frame, for text set beside a logo or a photo
pdf.inset(right=30)              # 30mm given way on the right, from the current height
pdf.inset()                      # close: full width again, below what was drawn
# Keep a block together
pdf.keep(40)                     # 40mm of room here, or on to the next frame
```

`new_page()` always starts a new page; an open region carries on there from its first column.
Header and footer callbacks always see the whole page.

## Text

```py
pdf.text("Simple text") # auto-width (measured)
pdf.text("Long text that wraps", width=60) # word wrap at 60mm
pdf.text("Centered", width=60, height=20, align="C") # centered in box
pdf.text("Right", width=40, align="R", padding=1) # right-aligned with padding
```

When both `width` and `height` are given, font auto-scales down by `0.1pt` steps to fit.

Mixed-style text goes through `render_rich`, which also justifies:

```py
from pdfmarq import RichSegment, render_rich, Align
segs = [RichSegment("Plain, "), RichSegment("bold", bold=True), RichSegment(" and more.")]
render_rich(pdf, segs, 80, 0, pdf.y, Align.JUSTIFY) # width, x, y in mm
```

A justified line resizes its spaces to meet the edge.
It may tighten them to three quarters of their width to take one more word, as page layout programs do.
Measure justified text with the same `align`: `pdfmarq.inline.wrap_line_heights(..., align=Align.JUSTIFY)`.
The last line and a line a hard break ends stay left.
`RichSegment(char_space=1)` spaces letters out by 1pt each, as capitals want.
`RichSegment(hyphenate="pl")` lets a word split at a line end, at a hyphenation point of the Polish patterns from `pyphen`, which the `[md]` extra installs.
Code, links, numbers and words in capitals stay whole.

## Signing lines and page number

`pdfmarq.parts` draws the pieces both document packages share, from plain values, the face of their text as a `RichSegment`:

```py
from pdfmarq import RichSegment
from pdfmarq.parts import signatures, page_number
label = RichSegment("", family="Helvetica", mode="Oblique", size=9, color=(0.4, 0.4, 0.4))
signatures(pdf, ["Client", "Contractor"], label, gap=20, width=70, thick=0.3)
number = RichSegment("", family="Helvetica", size=9, color=(0.4, 0.4, 0.4))
pdf.on_final_page(lambda p, n, total: page_number(p, "Page", n, total, number, show_total=True))
```

Their labels and the date format in each language are in `pdfmarq.parts.LANG_LABELS`, which the presets of both packages build on.

## Tables

```py
# Simple table
pdf.font("Helvetica", 11)
pdf.table(
  [["1", "Widget", "25.00"], ["2", "Gadget", "50.00"]],
  header=["#", "Name", "Price"],
  sizes=[1, 5, 2], # relative column widths
  aligns=["C", "L", "R"],
)
# Custom style (shape matches docmarq.TableStyle for cross-lib parity)
from pdfmarq import TableBuilder, TableStyle
style = TableStyle(
  header_bg="#f6f8fa",
  header_color="#1f2328",
  header_bold=True,
  row_bg_odd=(0.985, 0.99, 0.995),
  border_color="#d0d7de",
  border_size=0.5,
  cell_pad_h=2.5,
  cell_pad_top=1.6,
  cell_pad_bot=0.6,
  font_size=10,
)
builder = TableBuilder(pdf._metrics, style)
builder.header(["A", "B"]).rows([["a1", "b1"]]).columns([3, 2], ["L", "R"])
data = builder.build(180, "Helvetica", "Regular", 11)
```

## Shapes

```py
pdf.rect(40, 20) # filled rectangle at cursor
pdf.rect(60, 30, thickness=1, fill=False) # stroked only
pdf.round_rect(50, 20, radius=3)
pdf.circle(10, thickness=0.5)
pdf.line(100, 0, 0.5) # horizontal 100mm, 0.5pt thick
pdf.line(0, 50, 1) # vertical 50mm
pdf.line(80, 0, 1, dash=(3, 2)) # dashed
pdf.path([(0, 0), (10, 5), (20, 0)], close=True) # polygon
```

## Colors

```py
pdf.color(0.2, 0.4, 0.8)   # RGB 0-1
pdf.color_hex("#2E75B6")   # hex
pdf.color_grey(0.5, 0.8)   # grey with alpha
pdf.color_black()          # reset
pdf.color_rand()           # random pastel
pdf.stroke_color(0, 0, 0)  # stroke/line color
# Conversion helpers (symmetric with docmarq)
from pdfmarq import parse_color, color_hex
parse_color("#1f2328")     # → (0.121, 0.137, 0.156) floats 0-1
color_hex((0.03, 0.41, 0.85))  # → "0869D9" (uppercase, no '#')
```

## Images and SVG

```py
pdf.image("photo.png", 60, 40)  # PNG/JPG at width=60mm height=40mm
pdf.svg("icon.svg", 15, 15)     # SVG via svglib (aspect preserved)
```

## Pages and callbacks

```py
pdf.new_page()  # manual page break
# Per-page callback (runs before showPage, for headers/footers)
def header(pdf, page_num):
  pdf.cursor(0, -10, "R")
  pdf.font("Helvetica", 9).text(f"Page {page_num}", align="R")
pdf.on_page(header)
# After page reset (runs after cursor = 0,0)
pdf.on_new_page(lambda p, n: p.enter(8))  # leave 8mm for top header
# Deferred final-page callback (runs at save() time with total page count)
# Use for "Page 1/5" style footers that need the final total.
def footer(pdf, page_num, total):
  pdf.cursor(0, -5, "C")
  pdf.font("Helvetica", 9).text(f"{page_num} / {total}", align="C")
pdf.on_final_page(footer)
```

## Metadata, bookmarks, links

```py
pdf.metadata(title="Report", author="Xaeian", subject="Q4", keywords="report,q4")
pdf.bookmark("Chapter 1", level=0)
pdf.bookmark("Section 1.1", level=1)
pdf.link("https://github.com/Xaeian/PDFMarQ", width=40, height=5)
```

Bookmarks are resolved to their actual page at save time, so outline entries point to the correct page even when content reflows across pages.

## Page sizes

```py
from pdfmarq import A4, A3, A5, LETTER, LEGAL
PDF("out.pdf", width=LETTER.width, height=LETTER.height)
landscape = A4.landscape() # swapped dimensions
PDF("out.pdf", width=landscape.width, height=landscape.height)
```

## Style presets

```py
from pdfmarq import Styles
Styles.BOLD      # bold=True
Styles.ITALIC    # italic=True
Styles.HEADING1  # font_size=20, bold
Styles.HEADING2  # font_size=16, bold
Styles.HEADING3  # font_size=13, bold
Styles.HEADING4  # font_size=11, bold
Styles.SMALL     # font_size=9
Styles.CAPTION   # font_size=9, italic, muted grey
Styles.CODE      # font_family="Courier", font_size=10
```

## Markdown

Markdown needs the `[md]` extra.
The engine draws content, a document package lays out the page:

- [`pdfmarq.md`](md/readme.md): the engine, markdown into the current frame
- [`pdfmarq.paper`](paper/readme.md): documentation with a frontmatter banner
- [`pdfmarq.legal`](legal/readme.md): letters, statements, contracts, parallel versions
- [`pdfmarq.merge`](merge/readme.md): a markdown template filled with one record, or one per record of a table

```py
from pdfmarq import A4
from pdfmarq.paper import md_to_pdf, lang_style

md_to_pdf(open("doc.md").read(), "doc.pdf")
# With localization preset
style = lang_style("pl", body_size=11, footnote_label="Bibliografia")
md_to_pdf(text, "doc.pdf", style=style)
# Relative image paths resolved against base_dir
md_to_pdf(text, "doc.pdf", base_dir="./assets")
# Landscape, or any preset, via `page=`
md_to_pdf(text, "doc.pdf", page=A4.landscape())
```

Supported markdown: headings, paragraphs, lists, tables, code blocks (with syntax highlighting via Pygments), blockquotes, GitHub callouts (`> [!NOTE]`), footnotes, math (`$x^2$` via MathJax, matplotlib mathtext as fallback), mermaid diagrams (via local `mmdc` or the mermaid.ink fallback), images.

Blocks taller than a page split across pages, headings and footnotes get position-anchored PDF destinations, and repeated heading text gets numbered slugs the GitHub way.

## Compression

Not this library's job.
Use [`xaeian.media.pdf.pdf_compress`](https://github.com/Xaeian/Python) on the saved file.
