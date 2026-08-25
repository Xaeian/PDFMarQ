# Changes `pdfmarq`

## `0.5.1` Image sizing

- Block images fill the text width down to `image_min_dpi`
- Images alone in a paragraph become a row of figures, wrapping into a grid
- Mermaid diagrams size like any other figure
- `inline_image_max_h` applies, scaled off the surrounding font
- Fix: `max_h` ignored for block SVG

## `0.5.0` Vector math

- MathJax engine: formulas stay vector, with `\underbrace`, `cases`, `substack` and stretchable delimiters
- `math_font` picks the typeface, `math_engine` the backend
- Lines and columns size themselves to the formula they hold
- Fix: outline destinations, formulas holding `<`, leading `---`

## `0.4.2` Naming

- Style fields renamed: `font_body`, `banner`, `banner_compact`, `sign`
- Sign scenarios from `sign_labels`
- Dropped `margin_lr` and attr image sizing

## `0.4.1` Deps cleanup

- `Pygments` naming unified across extras

## `0.4.0` Caller-owned styling

- Breaking: `render:` block dropped, `page=A4` replaces `width` / `height` / `landscape`
- Breaking: `compress()` removed
- Fixes across fonts, heading anchors and mermaid

## `0.3.3` List numbering

- Ordered lists follow the author's numbering
- Fix: two-digit markers `10.` split across lines
- Fix: `^sup^` / `~sub~` baseline
- Fix: nested lists indented 4+ spaces flattened

## `0.3.2` Gutter

- `render:` keys `gutter`, `header`
- Fix: PDF generation without markdown

## `0.3.1` Fonts & mermaid

- Font mode fallback, `heavy_mode` in headings
- Frontmatter `logo:` via `base_dir`
- Mermaid: info-string DSL, `font_body` labels
- Fix: unicode glyphs like **Ω**

## `0.3.0` Directives & image DSL

- Directives `<!-- pagebreak -->`, `<!-- group -->`
- Image title DSL: `max_w max_h w h scale align`
- Frontmatter `render:` block
- Auto-derived table + footnote font sizes

## `0.2.0` HTML, tables & languages

- Basic HTML tags: `<b>`, `<i>`, `<code>`, `<br>`, `<hr>`
- Headerless tables _(single-row card layout)_
- Callout labels, language presets `en` `pl` `de` `fr` `es` `it` `cs` `sk`
- Improved image handling in tables

## `0.1.1` Names

- Shorter variable names and metadata

## `0.1.0` Initial release

Fluent, cursor-based PDF generation. The `[md]` extra renders markdown with banner headers,
syntax highlighting, math, mermaid and footnotes.
