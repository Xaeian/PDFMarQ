# `pdfmarq.md`

Markdown-to-PDF renderer with YAML frontmatter headers. Requires `pip install pdfmarq[md]`.

## `md_to_pdf`

```py
from pdfmarq.md import md_to_pdf
md_to_pdf(open("doc.md").read(), "doc.pdf", font_dir="./fonts")
# Force landscape orientation (overrides `landscape: true` in YAML)
md_to_pdf(md_text, "out.pdf", landscape=True)
```

## Frontmatter

YAML block at the top becomes a styled document header on page 1 plus a mini-header on continuation pages.

```yaml
---
id: TXR-1991-007
title: Roundhouse kick deployment protocol
version: 1.3.2
status: approved
entity: Texas Ranger Division
address: 1 Lone Star Boulevard, Dallas TX 75201
logo: ./ranger-badge.svg
author: Walker, Texas Ranger
created: 1993-04-21
updated: 2026-03-15
sign: true
landscape: false
---

# Document body starts here
```

| Field       | Effect                                                                               |
| ----------- | ------------------------------------------------------------------------------------ |
| `id`        | Document code in code-style box (e.g. `MD-001`)                                      |
| `title`     | Main title, centered, large                                                          |
| `info`      | Metadata only, not rendered                                                          |
| `version`   | Version in code-style box (no `v` prefix added)                                      |
| `status`    | Badge: `draft` / `review` / `approved` / `deprecated` / `archived`                   |
| `entity`    | Organization (left of header, bold)                                                  |
| `address`   | Address (right of header, muted)                                                     |
| `logo`      | Path to `.svg`/`.png`/`.jpg`, aspect-aware _(tall logos take less horizontal space)_ |
| `author`    | Author name, shown as `{fm_label_author}: ...`                                       |
| `created`   | ISO date, formatted via `style.date_format`                                          |
| `updated`   | Same                                                                                 |
| `sign`      | `true` adds a dashed signature line + label at the end                               |
| `landscape` | `true` flips page to landscape orientation                                           |

Aliases: `code` → `id`, `company` → `entity` _(legacy)_.

If the first body block is `# X` and `X` matches `title` exactly, the h1 is dropped to avoid showing the title twice. Disable with `skip_duplicate_title=False`.

## Internal links

Markdown anchor links work out of the box:

```md
See the [Notify characteristic](#bluetooth-low-energy) section.

## Bluetooth Low Energy
...
```

Each heading auto-registers a GitHub-style slug _(lowercase, spaces → hyphens, unicode preserved)_. Links to non-existent slugs render as plain text rather than crashing the build. Footnote refs `[^1]` jump to their definitions the same way.

## Style

```py
from pdfmarq.md import MarkdownStyle
style = MarkdownStyle(
  body_family="IBMPlexSans",
  mono_family="IBMPlexMono",
  heading_family="Sora",
  page_number_label="Strona",  # "Strona 1/5" footer; None to disable
  page_number_total=True,      # False → "Strona 1" without total
  date_format="%d.%m.%Y",      # strftime pattern
  page_break_on_h1=False,      # True for chaptered documents
  mini_header_on_continuation=True,
  render_frontmatter=True,
  skip_duplicate_title=True,   # drop `# X` if it matches frontmatter title
  mermaid_max_height=120,      # mm - cap tall diagrams (default 120)
)
md_to_pdf(md_text, "out.pdf", style=style)
```

### Frontmatter labels (i18n)

All labels in the document header are style fields - defaults are English.

```py
# Polish
MarkdownStyle(
  page_number_label="Strona",
  fm_label_author="Autor",
  fm_label_created="Utworzono",
  fm_label_updated="Zaktualizowano",
  fm_label_signature="Podpis",
)
# German
MarkdownStyle(
  page_number_label="Seite",
  fm_label_author="Autor",
  fm_label_created="Erstellt",
  fm_label_updated="Aktualisiert",
  fm_label_signature="Unterschrift",
)
```

### Logo sizing

```py
MarkdownStyle(
  fm_logo_max_height=50,       # mm - big logo on page 1 (default 50)
  fm_logo_max_width=60,        # mm - caps wide logos (default 60)
  fm_mini_logo_max_height=12,  # mm - mini-header logo (default 12)
  fm_mini_logo_max_width=24,   # mm - caps wide mini logos (default 24)
)
```

Width cap kicks in for wide logos _(wordmarks, horizontal lockups)_. Height is reduced proportionally so aspect ratio is preserved.

### Heading sizes

```py
MarkdownStyle(h1_size=18, h2_size=14, h3_size=12, h4_size=11, h5_size=10, h6_size=10)
```

### Table zebra

```py
MarkdownStyle(table_zebra=True, table_zebra_bg=(0.985, 0.99, 0.995))
```

### Status badge palette

```py
MarkdownStyle(fm_status_colors={
  "draft":      ((0.93, 0.93, 0.95), (0.40, 0.44, 0.50)),
  "review":     ((1.00, 0.95, 0.78), (0.62, 0.40, 0.05)),
  "approved":   ((0.86, 0.96, 0.87), (0.10, 0.45, 0.18)),
  "deprecated": ((0.97, 0.85, 0.84), (0.65, 0.15, 0.10)),
  "archived":   ((0.86, 0.89, 0.93), (0.30, 0.36, 0.45)),
})
```

Custom keys are allowed: `status: zatwierdzony` works if `"zatwierdzony"` is in the palette.

## Features

````md
# Headings h1 through h6

**bold** *italic* ***bold italic*** ~~strike~~ `inline code`

- Unordered lists
  - Nested
1. Ordered lists

| GFM | tables |
| --- | -----: |
| A   |  right |

```py
# Fenced code with syntax highlighting (Pygments)
def hello(): pass
```

Math inline: $E = mc^2$  Block: $$\int_0^1 x\,dx$$

```mermaid
flowchart LR
  A --> B
```

> Blockquote with left border

> [!NOTE]
> GitHub-style callouts: NOTE / TIP / IMPORTANT / WARNING / CAUTION

Footnotes[^1] and emoji :rocket: :sparkles:
[^1]: Definition at end of doc.
````

Paragraphs and tables pre-measure their height and break to a new page when they don't fit - no orphaned first lines across page breaks.

## Mixing with core API

```py
from pdfmarq import PDF
from pdfmarq.md import MarkdownRenderer, MarkdownStyle
pdf = PDF("out.pdf", font_dir="./fonts")
# Hand-crafted cover page
pdf.font("Helvetica", 36, "Bold").cursor(0, 80).text("Title", 170, align="C")
pdf.new_page()
# Markdown body
renderer = MarkdownRenderer(pdf, MarkdownStyle(render_frontmatter=False))
renderer.render(open("body.md").read())
# Custom signature
pdf.enter(20).cursor(110, pdf.y).line(70, 0, 0.5, dash=(2, 2))
pdf.save()
```

## Optional deps for features

Installed by `pip install pdfmarq[md]`:
- `Pygments` - syntax highlighting in code blocks
- `matplotlib` - math formulas (`$x^2$`, `$$...$$`)
- `emoji`, `mdit-py-emoji` - `:shortcode:` emoji
- `mermaid-cli` via npm for ` ```mermaid ` blocks: `npm install -g @mermaid-js/mermaid-cli` _(System tool, **not on PyPI**)_. Falls back to `mermaid.ink` HTTP service when `mmdc` is absent but network is available.

If any dep is missing, the feature silently degrades _(code renders without highlight, math renders as literal text, mermaid block renders as text fallback)_.