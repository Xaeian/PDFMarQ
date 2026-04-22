# `pdfmarq`

Fluent PDF generation. Built on reportlab with a cursor-based flow model.

## `PDF` context

```py
from pdfmarq import PDF, A4
with PDF("out.pdf") as pdf:
  pdf.font("Helvetica", 16, "Bold").text("Hello")
# Custom page size + margins
with PDF("out.pdf", width=A4.width, height=A4.height, margin=15) as pdf:
  pdf.margin(20, 25, 15) # lr, top, bot in mm
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
# Read current position
pdf.x, pdf.y           # cursor mm
pdf.content_width, pdf.content_height # page area minus margins
pdf.page_num           # current page number
```

## Text

```py
pdf.text("Simple text") # auto-width (measured)
pdf.text("Long text that wraps", width=60) # word wrap at 60mm
pdf.text("Centered", width=60, height=20, align="C") # centered in box
pdf.text("Right", width=40, align="R", padding=1) # right-aligned with padding
```

When both `width` and `height` are given, font auto-scales down by `0.1pt` steps to fit.

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
# Custom style
from pdfmarq import TableBuilder, TableStyle
style = TableStyle(
  header_bg=(0.3, 0.3, 0.3, 0.8),
  row_bg_even=(0.95, 0.95, 0.95, 0.5),
  border_width=0.5,
  padding=1,
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
pdf.color(0.2, 0.4, 0.8)    # RGB 0-1
pdf.color_hex("#2E75B6")  # hex
pdf.color_grey(0.5, 0.8)    # grey with alpha
pdf.color_black()           # reset
pdf.color_rand()            # random pastel
pdf.stroke_color(0, 0, 0)   # stroke/line color
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
pdf.metadata(title="Report", author="Xaeian")
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
Styles.BOLD      # font_mode="Bold"
Styles.ITALIC    # font_mode="Italic"
Styles.HEADING1  # size=24, Bold
Styles.HEADING2  # size=18, Bold
Styles.SMALL     # size=10
Styles.CAPTION   # size=9, Italic
```

## Compression

```py
pdf.save().compress(quality="ebook") # screen / ebook / printer / prepress
```

Requires ghostscript installed on the system.
