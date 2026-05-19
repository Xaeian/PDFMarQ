# Changes `pdfmarq`

## `0.2.0` Directives, DSL & docmarq parity

- Directives `<!-- pagebreak -->`, `<!-- group -->`
- Image title DSL: `max_w max_h w h scale align`
- Frontmatter `render:` block
- API parity with `docmarq`
- Auto-derived table + footnote font sizes

## `0.1.2` HTML, Table IMG & Lang

- Improved image handling in tables
- Basic HTML tags: `<b>`, `<i>`, `<code>`, `<br>`, `<hr>`
- Headerless tables _(single-row card layout)_
- Callout _(Note/Tip/Important/Warning/Caution)_ labels
- Language presets: `en`, `pl`, `de`, `fr`, `es`, `it`, `cs`, `sk`

## `0.1.1` Names

Shortened variable names and metadata

## `0.1.0` Initial release

Python library for generating PDF documents with a fluent, cursor-based API. Optional `[md]` extra adds markdown-to-PDF rendering with YAML frontmatter headers, syntax highlighting, math, mermaid, and footnotes.