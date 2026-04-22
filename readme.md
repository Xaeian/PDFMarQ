# PDFMarQ

PDF generation with a fluent API. Core is lean _(reportlab + Pillow + svglib)_. Optional `[md]` extra adds full markdown-to-PDF rendering with frontmatter headers, math, mermaid, syntax highlighting and more.

## Philosophy

PDFMarQ wraps reportlab's stateful canvas into a fluent, cursor-based API. You describe document flow, not coordinates. Markdown rendering lives in a separate subpackage so the core stays installable without heavyweight dependencies.

- **Fluent over imperative**: `pdf.font("Helvetica", 12).text("Hi").enter().text("World")` vs `canvas.setFont() → canvas.drawString() → manual Y tracking`
- **Cursor flows naturally**: top-left origin, `y` grows down, `enter()` is a newline
- **One way per feature**: `pdf.table()`, `pdf.image()`, `pdf.svg()`, `pdf.link()`, no overloaded call signatures
- **Markdown is optional**: core → 3 deps, `[md]` adds the stack
- **Frontmatter as contract**: YAML block at top of markdown becomes a styled header with logo, status badge, version, dates, signature slot
- **Lean output**: no headless Chrome, no web stack, no React SSR. Pure Python + native PDF primitives. Files stay small, rendering stays fast, fonts are embedded properly, and the output opens clean in every PDF reader

Trade-offs:
- Cursor mutation is a state machine. Great for linear documents, awkward for complex grid layouts. For those, drop into raw reportlab via `pdf._canvas`.
- Markdown rendering estimates heights analytically to decide page breaks. Good enough for 95% of content. Edge cases with math + wide tables may push onto the next page more aggressively than necessary.
- Installing Python + a stack of deps is a barrier for non-technical users. If you're building a tool end-users will actually touch, put PDFMarQ behind a backend service _(FastAPI endpoint, CLI wrapper, desktop app)_ rather than asking them to `pip install` anything.

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
from pdfmarq.md import md_to_pdf, MarkdownStyle
# Markdown to PDF
style = MarkdownStyle(
  body_family="IBMPlexSans",
  heading_family="Sora",
  page_number_label="Page", # "Page 1/5" in footer
)
md_to_pdf(open("doc.md").read(), "doc.pdf", style=style, font_dir="./fonts")
```

## Markdown features

- GitHub-flavored markdown _(tables, fenced code, lists, strikethrough)_
- YAML frontmatter with styled document header _(logo, status badge, version, sign block, landscape flag)_
- Mini-header on continuation pages with aspect-aware logo _(width + height caps)_
- Page numbering `Page N/M` via deferred canvas rendering _(configurable)_
- Configurable frontmatter labels for localization _(`fm_label_author`, `fm_label_created`, …)_
- Skip-duplicate-title: drops `# X` when it matches frontmatter `title`
- Auto-slugged headings with clickable `[text](#anchor)` internal links _(unicode-aware, broken targets degrade to plain text)_
- Local-path links configurable via `link_root` + `link_base` _(or per-doc YAML `base:`)_
- Syntax highlighting _(Pygments)_
- Math formulas inline `$x^2$` and block `$$...$$` _(matplotlib)_
- Mermaid diagrams via `mermaid-cli` _(local)_ or `mermaid.ink` _(network fallback)_, capped at a configurable max height
- Footnotes, emoji shortcodes `:rocket:`, nested lists, blockquotes, GitHub callouts _(`> [!NOTE]`, `> [!WARNING]`, …)_
- Zebra-striped tables _(subtle, readability without noise)_
- Smart page breaks for paragraphs, tables, lists, and blockquotes _(pre-measured, no orphans)_

## Modules

| Module       | Description                                        | Docs                                         |
| ------------ | -------------------------------------------------- | -------------------------------------------- |
| `pdfmarq`    | Core PDF API _(fluent cursor-based drawing)_       | [pdfmarq/readme.md](pdfmarq/readme.md)       |
| `pdfmarq.md` | Markdown-to-PDF renderer _(optional `[md]` extra)_ | [pdfmarq/md/readme.md](pdfmarq/md/readme.md) |