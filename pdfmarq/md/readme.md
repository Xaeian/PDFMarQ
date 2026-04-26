# `pdfmarq.md`

Markdown-to-PDF renderer with YAML frontmatter. Requires `pip install pdfmarq[md]`.

## `md_to_pdf`

```py
from pdfmarq.md import md_to_pdf
md_to_pdf(open("doc.md").read(), "doc.pdf", font_dir="./fonts")
# Force landscape orientation (overrides `landscape: true` in YAML)
md_to_pdf(md_text, "out.pdf", landscape=True)
```

## Banner (YAML frontmatter)

YAML block at the top becomes a styled banner on page 1 plus a compact mini-banner on continuation pages.

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
sign: true
landscape: false
logo: ./ranger-badge.svg
---

# Document body starts here
```

| Field       | Effect                                                                               |
| ----------- | ------------------------------------------------------------------------------------ |
| `id`        | Document code in code-style box (e.g. `MD-001`)                                      |
| `title`     | Main title, centered, large                                                          |
| `version`   | Version in code-style box (no `v` prefix added)                                      |
| `author`    | Author name, shown as `{banner_label_author}: ...`                                   |
| `status`    | Badge: `draft` / `review` / `approved` / `deprecated` / `archived`                   |
| `entity`    | Organization (left of banner, bold)                                                  |
| `address`   | Address (right of banner, muted)                                                     |
| `created`   | ISO date, formatted via `style.date_format`                                          |
| `updated`   | Same                                                                                 |
| `sign`      | `true` adds a dashed signature line + label at the end                               |
| `landscape` | `true` flips page to landscape orientation                                           |
| `logo`      | Path to `.svg`/`.png`/`.jpg`, aspect-aware _(tall logos take less horizontal space)_ |
| `subject`   | Written to PDF metadata `/Subject`, not rendered                                     |
| `keywords`  | Written to PDF metadata `/Keywords`, string or YAML list                             |

Aliases: `code` → `id`, `company` → `entity` _(legacy)_.

PDF metadata _(`/Title`, `/Author`, `/Subject`, `/Keywords`)_ is auto-filled from matching YAML keys. Pass `metadata={...}` to `md_to_pdf()` to override per-key.

If the first body block is `# X` and `X` matches `title` exactly, the h1 is dropped to avoid showing the title twice. Disable with `skip_dup_title=False`.

## Internal links

Markdown anchor links work out of the box:

```md
See the [Notify characteristic](#bluetooth-low-energy) section.

## Bluetooth Low Energy
...
```

Each heading auto-registers a GitHub-style slug _(lowercase, spaces → hyphens, unicode preserved)_. Links to non-existent slugs render as plain text rather than crashing the build. Footnote refs `[^1]` jump to their definitions the same way.

## Local links

Paths without a schema _(`[x](file.md)`, `[x](folder/doc)`, `[x](/absolute/path)`)_ get the link style _(blue + underline)_ but no clickable action by default - a PDF can't follow a filesystem link. Set `link_root` to make them real URLs:

```py
MarkdownStyle(
  link_root="https://docs.company.com",  # root to prepend
  link_base="projects/foo",              # subfolder this doc sits in
)
```

Resolution:
- `[x](file.md)` → `https://docs.company.com/projects/foo/file.md`
- `[x](/abs/path)` → `https://docs.company.com/abs/path` _(absolute ignores base)_

## Style

```py
from pdfmarq.md import MarkdownStyle
style = MarkdownStyle(
  body_family="IBMPlexSans",
  mono_family="IBMPlexMono",
  head_family="Sora",
  page_number_label="Strona",  # "Strona 1/5" footer; None to disable
  page_number_total=True,      # False → "Strona 1" without total
  date_format="%d.%m.%Y",      # strftime pattern
  h1_page_break=False,         # True for chaptered documents
  mini_banner_render=True,     # mini-banner on pages 2+
  banner_render=True,          # page 1 full banner
  skip_dup_title=True,         # drop `# X` if it matches frontmatter title
  image_max_h=120,             # mm - cap tall images and diagrams (default 120)
)
md_to_pdf(md_text, "out.pdf", style=style)
```

### Banner labels (i18n)

Labels in the banner, footer, and callouts are style fields — defaults are English. Use `lang_style("pl"|"de"|...)` to apply a built-in preset, or override fields manually.

```py
from pdfmarq.md import lang_style, md_to_pdf
style = lang_style("pl", body_family="IBMPlexSans")
md_to_pdf(md_text, "out.pdf", style=style)
```

Built-in presets ship in `pdfmarq/md/presets.py` and currently cover `en` _(defaults)_, `pl`, `de`, `fr`, `es`, `it`, `cs`, `sk`. Each preset configures `page_number_label`, `date_format`, banner labels _(author / created / updated / signature)_, and callout labels _(note / tip / important / warning / caution)_. Extend by adding entries to `LANG_PRESETS`.

For ad-hoc overrides without a preset, set fields directly:

```py
MarkdownStyle(
  page_number_label="Page",
  banner_label_author="Author",
  callout_label_warning="Heads up",
)
```

### Logo sizing

```py
MarkdownStyle(
  banner_logo_max_h=50,       # mm - big logo on page 1 (default 50)
  banner_logo_max_w=60,       # mm - caps wide logos (default 60)
  mini_banner_logo_max_h=12,  # mm - mini-banner logo (default 12)
  mini_banner_logo_max_w=24,  # mm - caps wide mini logos (default 24)
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
MarkdownStyle(banner_status_colors={
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

## HTML support

A small whitelist of raw HTML tags is recognized inside markdown. Everything else _(`<table>`, `<div>`, `<span>`, `<style>`, attributes)_ is dropped silently.

| Tag                  | Effect                                            |
| -------------------- | ------------------------------------------------- |
| `<b>`, `<strong>`    | Bold                                              |
| `<i>`, `<em>`        | Italic                                            |
| `<code>`             | Inline code _(mono family, code colors)_          |
| `<br>`               | Hard line break                                   |
| `<hr>`               | Horizontal rule _(block-level)_                   |

Tag set lives in `pdfmarq/md/md_html.py` if you need to extend it.

### Headerless tables

Markdown tables require a header row per spec, but a single-row "card" layout is a common pattern. A table with header but no body is rendered as headerless — useful for label/value blocks and contact cards:

```md
| ![](logo.svg) | Pocket Diagnostics Poland sp. z o.o<br>80-890 Gdańsk<br>Jana Heweliusza 11/811 |
| --- | --- |
```

### Setext-heading-with-image recovery

```md
![diagram](schema.svg)
---
```

CommonMark parses this as a setext h2 with the image as heading text — a common footgun that would render the image at heading-inline size _(thumbnail)_. `pdfmarq` detects the image-only setext case and renders it as a block image followed by an `<hr>`, matching the user's actual intent.

## Mixing with core API

```py
from pdfmarq import PDF
from pdfmarq.md import MarkdownRenderer, MarkdownStyle
pdf = PDF("out.pdf", font_dir="./fonts")
# Hand-crafted cover page
pdf.font("Helvetica", 36, "Bold").cursor(0, 80).text("Title", 170, align="C")
pdf.new_page()
# Markdown body (no banner - we already have a custom cover)
renderer = MarkdownRenderer(pdf, MarkdownStyle(banner_render=False))
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
