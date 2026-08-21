// pdfmarq/md/tex2svg.mjs
//
// TeX -> SVG through MathJax 4, one formula per line of stdin.
//
// Batched because node startup dominates a single render: the caller sends
// every formula it needs at once and reads the answers back in order.
//
// usage: node tex2svg.mjs <node_modules-root> [font]
//   font  : MathJax font component, e.g. `mathjax-newcm` (the default)
//   stdin : one JSON object per line, {"tex": "...", "display": true}
//   stdout: one JSON object per line, {"svg": "..."} or {"error": "..."}
import { pathToFileURL } from "node:url";
import { createInterface } from "node:readline";

const root = process.argv[2].split("\\").join("/").replace(/\/+$/, "");
const font = process.argv[3] || "mathjax-newcm";

// MathJax asks for its own components by absolute path and for the font
// package by bare specifier; both have to become file:// URLs under `root`.
const resolve = (name) => {
  if (/^\w+:\/\//.test(name)) return name;
  const path = /^([a-zA-Z]:|\/)/.test(name) ? name : root + "/" + name;
  return pathToFileURL(path).href;
};

const mod = await import(resolve(root + "/mathjax/node-main.mjs"));
const init = mod.init || (mod.default && mod.default.init);

const MathJax = await init({
  loader: {
    load: ["input/tex", "output/svg"],
    require: (name) => import(resolve(name)),
  },
  // Inline paths rather than a glyph cache: no ids that could collide when
  // several formulas end up in one document.
  //
  // Line breaking off: MathJax 4 would split an inline formula into several
  // `<svg>` chunks joined by `<mjx-break>`, and pdfmarq lays out its own
  // lines - it needs one drawing per formula, whole.
  svg: { fontCache: "none", font: font, linebreaks: { inline: false } },
});

const out = [];
for await (const line of createInterface({ input: process.stdin })) {
  const text = line.trim();
  if (!text) continue;
  try {
    const job = JSON.parse(text);
    const node = await MathJax.tex2svgPromise(job.tex, { display: !!job.display });
    // The whole container ships: it also holds an assistive-MathML sibling,
    // and picking the SVG out by child order gets a nested viewport for some
    // formulas. `svgflat` selects the right element with a parser.
    //
    // XML, not HTML: MathJax records the source TeX in `data-latex`, and HTML
    // rules leave a `<` there raw - `x < 0` alone is enough to make the
    // fragment unparsable. Only `serializeXML` escapes it.
    out.push(JSON.stringify({ svg: MathJax.startup.adaptor.serializeXML(node) }));
  } catch (err) {
    out.push(JSON.stringify({ error: String(err) }));
  }
}
process.stdout.write(out.join("\n") + "\n");
