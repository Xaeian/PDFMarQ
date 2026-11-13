# `pdfmarq.paper`

Documentation PDFs: markdown content with a frontmatter banner around it.
Requires `pip install pdfmarq[md]`.
The content is drawn by [`pdfmarq.md`](../md/readme.md).

## `md_to_pdf`

```py
from pdfmarq.paper import md_to_pdf
md_to_pdf(open("doc.md").read(), "doc.pdf", font_dir="./fonts")
# Landscape, and relative images resolved against a directory
from pdfmarq.constants import A4
md_to_pdf(md_text, "out.pdf", page=A4.landscape(), base_dir="./assets")
```

`style` must be a `PaperStyle`, built directly or with `lang_style()`.

## `md_into`

```py
from pdfmarq import PDF
from pdfmarq.paper import md_into, lang_style
pdf = PDF("report.pdf", font_dir="./fonts")
pdf.font("Helvetica", 36, "Bold").cursor(0, 80).text("Cover", 170, align="C") # pages of its own
pdf.new_page()
md_into(pdf, open("doc.md").read(), style=lang_style("pl", banner=False))
pdf.save()
```

`md_into` writes a paper document into a `PDF` that already holds pages, as a cover, and the caller saves it.
It sets the metadata, banner, compact banner, page number, content and signing lines as `md_to_pdf` does.
The compact banner starts on the page after the one `md_into` starts on, and the page number counts every page, the cover's too.
One call per `PDF`: each adds page furniture of its own.

## Banner (YAML frontmatter)

YAML block at top becomes a styled banner on page 1 plus a compact banner on continuation pages.

```yaml
---
id: TXR-1991-007
title: Roundhouse kick deployment protocol
version: 1.3.2
author: Walker, Texas Ranger
status: approved
entity: Texas Ranger Division
address: 1 Lone Star Boulevard, Dallas TX 75201
created: 1993-04-21
updated: 2026-03-15
logo: ./ranger-badge.svg
---

# Document body starts here
```

- `id`: document code in code-style box (e.g. `MD-001`)
- `title`: main title, centered, large
- `version`: version in code-style box (no `v` prefix added)
- `author`: names shown as `{banner_label_author}: ...` and written to the metadata.
  `banner_label_authors` labels more than one person.
  A string or a list item names people between commas, an ORCID or an e-mail after a name belonging to it: `Anna Nowak, 0000-0002-1825-0097, a.nowak@example.com`.
  Each is known by its shape, so a label as `ORCID:` or a stray letter beside it goes, and a comma left out between a name and its detail loses no one.
  A list may also hold mappings with `name` and the details a package uses, as `orcid`, `email` or `aff`.
- `status`: badge: `draft` / `review` / `approved` / `deprecated` / `archived`
- `entity`: organization (left of banner, bold)
- `address`: address (right of banner, muted)
- `created`: ISO date, formatted via `style.date_format`
- `updated`: same as `created`
- `logo`: path to `.svg`/`.png`/`.jpg`, aspect-aware _(tall logos take less horizontal space)_
- `subject`: written to PDF metadata `/Subject`, not rendered
- `keywords`: written to PDF metadata `/Keywords`, string or YAML list

PDF metadata _(`/Title`, `/Author`, `/Subject`, `/Keywords`)_ is auto-filled from matching YAML keys.
Pass `metadata={...}` to `md_to_pdf()` to override per-key.

If first body block is `# X` and `X` matches `title` exactly, h1 is dropped to avoid showing the title twice.
Only applies when banner actually printed that title, so `banner=False` never costs you the heading.
Disable with `skip_dup_title=False`.

## Presentation

Frontmatter carries content only; everything visual comes from the caller.
`style=` is used verbatim, so any value can be set, a `PaperStyle()` default included.

```python
from pdfmarq.paper import md_to_pdf, lang_style
from pdfmarq.constants import A4, page_size

style = lang_style("pl", # banner/footer labels
  font_body="IBMPlexSans", font_head="Sora", font_mono="IBMPlexMono",
  body_size=11, line_height=1.4, image_max_h=120,
  banner=True, banner_compact=True, sign="approval",
  mermaid_theme="default", syntax_theme="default",
)
md_to_pdf(md, "out.pdf", style=style,
  page=A4, margin=25, gutter=0, two_sided=False, base_dir=".", font_dir="./fonts")
```

`gutter` widens the left margin for binding, and `two_sided=True` prints on both sides of the sheet: even pages mirror the margins, the gutter at the bound edge.

`sign` takes `True` for one line, a `sign_labels` scenario or a list of custom labels.
Scenarios: `signature`, `approval` and `contract`, localized by the language preset.
Several lines sit side by side, sharing the content width.

`columns=2` sets the text in two columns, its last page balanced with the signing lines under it.
`floats` is on in `PaperStyle`: pictures, tables and groups setting them wait for the top of the next column instead of leaving gaps, while groups of text stay where written.
`<!-- group wide -->`, or a table no column holds, waits for the top of the next page, above its columns, or goes under the columns where they end first.
Text before the first `##` spans the page.
The compact banner's room on later pages is `pdf.headroom`, so the columns measure their pages as they draw them.

`page` is a `PageSize` in mm: `A4`, `A4.landscape()`, `page_size("a3")` for a preset name (`A4`/`A3`/`A5`/`LETTER`/`LEGAL`, raises on anything else), or `PageSize(200, 250)` for a custom sheet.

Everything after `output_path` is keyword-only, so argument order cannot silently diverge from `docmarq.paper.md_to_docx`.

## Style

Beyond fields shown above:

```py
PaperStyle(
  page_number_label="Strona",  # "Strona 1/5" footer; None to disable
  page_number_total=True,      # False → "Strona 1" without total
  date_format="%d.%m.%Y",      # strftime pattern
  skip_dup_title=True,         # drop `# X` if it matches frontmatter title
  footnote_label=True,         # the bibliography titled in the style's language; None for a rule
)
```

The engine's fields (fonts, sizes, `h1_page_break`, `justify`, `keep_together`) are there too, since `PaperStyle` extends `MarkdownStyle`.

A paper titles its bibliography unasked: the footnotes collected at the end go under a level-2 heading in the style's language, `Literatura` in `pl`, `References` in `en`.
A document that ends with a heading of its own has titled them already, as `### Literatura` at the very end, and gets no second title.
`footnote_label="Bibliografia"` titles them with its own word, `footnote_label=None` draws the engine's thin rule instead.

### Banner labels (i18n)

Labels in banner, footer, and callouts are style fields.
Defaults are English.
Use `lang_style("pl"|"de"|...)` to apply a built-in preset, or override fields manually.

Built-in presets cover `en` _(defaults)_, `pl`, `de`, `fr`, `es`, `it`, `cs`, `sk`, `pt`.
Each configures `page_number_label`, `date_format`, banner labels _(author / authors / created / updated)_, signing scenarios _(`sign_labels`)_, and the engine's callout labels.
`pl`, `cs` and `sk` also set `bind_single_letters`.

```py
PaperStyle(
  page_number_label="Page",
  banner_label_author="Author",
  callout_label_warning="Heads up",
)
```

### Logo sizing

```py
PaperStyle(
  banner_logo_max_h=50,         # mm - big logo on page 1
  banner_logo_max_w=60,         # mm - caps wide logos
  banner_compact_logo_max_h=12, # mm - compact banner logo
  banner_compact_logo_max_w=24, # mm - caps wide logos
)
```

Width cap kicks in for wide logos _(wordmarks, horizontal lockups)_.
Height is reduced proportionally so aspect ratio is preserved.

### Status badge palette

The default palette, `(background, text)` per status:

```py
PaperStyle(banner_status_colors={
  "draft": ((0.85, 0.87, 0.92), (0.30, 0.34, 0.45)),
  "review": ((1.00, 0.95, 0.78), (0.62, 0.40, 0.05)),
  "approved": ((0.86, 0.96, 0.87), (0.10, 0.45, 0.18)),
  "deprecated": ((1.00, 0.88, 0.85), (0.74, 0.20, 0.15)),
  "archived": ((0.92, 0.87, 0.96), (0.45, 0.25, 0.55)),
})
```

Custom keys are allowed: `status: zatwierdzony` works if `"zatwierdzony"` is in the palette.
