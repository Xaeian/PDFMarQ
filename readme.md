# PDFMarQ

PDF generation with a fluent API.
Core is lean _(reportlab + Pillow + svglib)_.
Optional `[md]` extra adds full markdown-to-PDF rendering: documentation with banner headers, letters and contracts in one or two columns, math, mermaid, syntax highlighting and more.

## Philosophy

PDFMarQ wraps reportlab's stateful canvas into a fluent, cursor-based API.
You describe document flow, not coordinates.
Markdown rendering lives in a separate subpackage so core stays installable without heavyweight dependencies.

- **Fluent over imperative**: `pdf.font("Helvetica", 12).text("Hi").enter().text("World")`
  vs `canvas.setFont() → canvas.drawString() → manual Y tracking`
- **Cursor flows naturally**: top-left origin, `y` grows down, `enter()` is a newline
- **One way per feature**: `pdf.table()`, `pdf.image()`, `pdf.svg()`, `pdf.link()`, no overloaded call signatures
- **Markdown is optional**: core → 3 deps, `[md]` adds the stack
- **Engine and documents apart**: `pdfmarq.md` draws markdown content, a document package lays out the page around it
- **Banner as contract**: in `pdfmarq.paper` YAML frontmatter becomes a styled banner with logo, status badge, version, dates
- **Letters and contracts**: `pdfmarq.legal` sets a letter header from frontmatter and signing lines from the style, in one or two columns, or with language versions side by side
- **Lean output**: no headless Chrome, no web stack, no React SSR.
  Pure Python + native PDF primitives.
  Files stay small, rendering stays fast, fonts are embedded properly, and output opens clean in every PDF reader

Trade-offs:
- Cursor mutation is a state machine.
  Great for linear documents, awkward for complex grid layouts.
  For those, drop into the raw reportlab canvas via `pdf.c`.
- Markdown rendering estimates heights analytically to decide page breaks.
  Good enough for 95% of content.
  Edge cases with math + wide tables may push onto the next page more aggressively than necessary.
- Installing Python + a stack of deps is a barrier for non-technical users.
  If you're building a tool end-users will actually touch, put PDFMarQ behind a backend service
  _(FastAPI endpoint, CLI wrapper, desktop app)_ rather than asking them to `pip install` anything.

## Install

```sh
pip install pdfmarq      # core: reportlab, Pillow, svglib
pip install pdfmarq[md]  # + markdown rendering stack
```

## Examples

```py
from pdfmarq import PDF
# Fluent core API
with PDF("report.pdf") as pdf:
  pdf.font("Helvetica", 20, "Bold").text("Quarterly Report")
  pdf.enter().font(size=12, mode="Regular")
  pdf.text("Revenue up 23% year-over-year.")
  pdf.table(
    [["Q1", "120k"], ["Q2", "148k"], ["Q3", "172k"]],
    header=["Quarter", "Revenue"],
    sizes=[1, 2], aligns=["C", "R"],
  )
  pdf.image("chart.png", 180, 80)
  pdf.link("https://xaeian.com", 40, 5)
```

```py
from pdfmarq.paper import md_to_pdf, PaperStyle
# Markdown documentation to PDF
style = PaperStyle(
  font_body="IBMPlexSans",
  font_head="Sora",
  page_number_label="Page", # "Page 1/5" in footer
)
md_to_pdf(open("doc.md").read(), "doc.pdf", style=style, font_dir="./fonts")
```

```py
from pdfmarq.legal import md_to_pdf, md_parallel_to_pdf, lang_style
# A contract in two balanced columns, signed by both parties
md_to_pdf(open("contract.md").read(), "contract.pdf",
  style=lang_style("pl", columns=2, sign="contract"), font_dir="./fonts")
# Language versions side by side, each from its own file
md_parallel_to_pdf([pl_text, en_text], "contract-pl-en.pdf",
  styles=[lang_style("pl"), lang_style("en")], font_dir="./fonts")
```

See [`example.py`](https://github.com/Xaeian/PDFMarQ/blob/main/example.py) for an end-to-end CLI script.
It covers a language preset, custom TTF fonts from `./fonts/`, `link_root` for cross-document references,
`base_dir` for relative images, and optional Ghostscript post-compression.

## Markdown features

- GitHub-flavored markdown _(tables, fenced code, lists, strikethrough)_
- YAML frontmatter rendered as a styled banner _(logo, status badge, version, dates)_ by `pdfmarq.paper`
- Letters, statements and contracts by `pdfmarq.legal`: letter header from frontmatter, justified text that flows, two balanced columns, language versions side by side _(see [`legal/guide`](https://github.com/Xaeian/PDFMarQ/blob/main/pdfmarq/legal/guide.md))_
- Columns in the core API: `pdf.columns(2)`, and everything markdown draws flows through them
- Page geometry, fonts, banner toggles and locale come from caller's `style=`, never from the document _(see [`md/guide`](https://github.com/Xaeian/PDFMarQ/blob/main/pdfmarq/md/guide.md))_
- Mini-banner on continuation pages with aspect-aware logo _(width + height caps)_
- Page numbering `Page N/M` via deferred canvas rendering _(configurable)_
- Built-in language presets _(en|pl|de|fr|es|it|cs|sk)_ via `lang_style()`: covers banner, callouts, date format, page numbers
- Skip-duplicate-title: drops `# X` when it matches frontmatter `title`
- Auto-slugged headings with clickable `[text](#anchor)` internal links _(unicode-aware, broken targets degrade to plain text)_
- Local-path links configurable via `link_root` + `link_base`
- Syntax highlighting _(Pygments)_
- Math formulas inline `$x^2$` and block `$$...$$`, drawn as vectors _(MathJax, matplotlib fallback)_
- Images sized from their own resolution, capped by `image_max_h`, centred
- Images alone in a paragraph become a row of figures, wrapping into a grid beyond text width
- Mermaid diagrams via `mermaid-cli` _(local)_ or `mermaid.ink` _(network fallback)_, capped at a configurable max height
- Footnotes, emoji shortcodes `:rocket:`, nested lists, blockquotes, GitHub callouts _(`> [!NOTE]`, `> [!WARNING]`, …)_
- Zebra-striped tables _(subtle, readability without noise)_
- Smart page breaks for paragraphs, tables, lists, and blockquotes _(pre-measured, no orphans)_
- Basic inline HTML pass-through _(`<b>`, `<i>`, `<code>`, `<br>`, `<hr>`)_

## Modules

- [`pdfmarq`](https://github.com/Xaeian/PDFMarQ/blob/main/pdfmarq/readme.md): core PDF API _(fluent cursor-based drawing, columns)_
- [`pdfmarq.md`](https://github.com/Xaeian/PDFMarQ/blob/main/pdfmarq/md/readme.md): markdown engine _(optional `[md]` extra)_
- [`pdfmarq.paper`](https://github.com/Xaeian/PDFMarQ/blob/main/pdfmarq/paper/readme.md): documentation with a frontmatter banner
- [`pdfmarq.legal`](https://github.com/Xaeian/PDFMarQ/blob/main/pdfmarq/legal/readme.md): letters, statements, contracts, parallel versions

## See also

Need `.docx` instead of PDF?
Check [**DocMarQ**](https://github.com/Xaeian/docmarq), sibling library with the same API shape and `.docx` output.
Syntax highlighting is PDF-only, and math there covers a wider slice of LaTeX _(DocMarQ emits native Word equations for the common subset)_.
Everything else _(banner, callouts, mermaid, lang presets, letters and contracts)_ works the same in both.