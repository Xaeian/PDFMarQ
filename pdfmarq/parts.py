# pdfmarq/parts.py

"""
Document parts drawn with the core API: signing lines and the page number,
with the labels and date format they take in each language.

They need no markdown, so a caller passes its look in as plain values.
Lengths are mm: the `PDF` they draw into must use mm, as the markdown engine does.
"""
from dataclasses import replace
from reportlab.lib.colors import Color
from .constants import Align, MM_TO_PT
from .inline import RichSegment, render_rich, measure_rich

_SIGN_BLOCK_MM = 10 # least room under the handwriting gap: line, label and breathing space
_SIGN_SPACING_MM = 6 # least space between two signing lines
_LABEL_GAP_MM = 1 # between a signing line and its label

#------------------------------------------------------------------------------------------- Labels

def default_sign_labels() -> dict:
  """Signing scenarios in English: name → one label per signing line."""
  return {
    "signature": ["Signature"],
    "approval": ["Prepared by", "Approved by"],
    "contract": ["Client", "Contractor"],
  }

# Page number label, date format and signing scenarios per language, English being the default.
# The presets of the document packages build on them.
LANG_LABELS: dict[str, dict] = {
  "pl": {
    "page_number_label": "Strona",
    "date_format": "%d.%m.%Y",
    "sign_labels": {"signature": ["Podpis"], "approval": ["Opracował", "Zatwierdził"],
      "contract": ["Zleceniodawca", "Zleceniobiorca"]},
  },
  "de": {
    "page_number_label": "Seite",
    "date_format": "%d.%m.%Y",
    "sign_labels": {"signature": ["Unterschrift"], "approval": ["Erstellt", "Genehmigt"],
      "contract": ["Auftraggeber", "Auftragnehmer"]},
  },
  "fr": {
    "page_number_label": "Page",
    "date_format": "%d/%m/%Y",
    "sign_labels": {"signature": ["Signature"], "approval": ["Rédigé par", "Approuvé par"],
      "contract": ["Donneur d'ordre", "Prestataire"]},
  },
  "es": {
    "page_number_label": "Página",
    "date_format": "%d/%m/%Y",
    "sign_labels": {"signature": ["Firma"], "approval": ["Elaborado por", "Aprobado por"],
      "contract": ["Cliente", "Contratista"]},
  },
  "it": {
    "page_number_label": "Pagina",
    "date_format": "%d/%m/%Y",
    "sign_labels": {"signature": ["Firma"], "approval": ["Redatto da", "Approvato da"],
      "contract": ["Committente", "Appaltatore"]},
  },
  "cs": {
    "page_number_label": "Strana",
    "date_format": "%d.%m.%Y",
    "sign_labels": {"signature": ["Podpis"], "approval": ["Vypracoval", "Schválil"],
      "contract": ["Objednatel", "Zhotovitel"]},
  },
  "sk": {
    "page_number_label": "Strana",
    "date_format": "%d.%m.%Y",
    "sign_labels": {"signature": ["Podpis"], "approval": ["Vypracoval", "Schválil"],
      "contract": ["Objednávateľ", "Zhotoviteľ"]},
  },
}

def sign_labels(sign:bool|str|list, scenarios:dict) -> list[str]:
  """
  Labels `sign` asks for: a scenario of `scenarios`, `True` being `signature`, or a list as is.
  A scenario missing from `scenarios` gives one line, labelled with its name, bare for `True`.
  """
  if not sign: return []
  if isinstance(sign, (list, tuple)): return [str(x) for x in sign]
  key = "signature" if sign is True else str(sign).lower()
  return list(scenarios.get(key, [""] if sign is True else [str(sign)]))

#--------------------------------------------------------------------------------------- Signatures

def _line_width(pdf, count:int, width:float) -> float:
  """Width (mm) of each of `count` signing lines across the frame, `width` at most."""
  return min(width, pdf.content_width / count - _SIGN_SPACING_MM)

def _label_height(pdf, labels:list[str], face:RichSegment, line_w:float) -> float:
  """Height (mm) of the tallest label, set in `face` under a line `line_w` mm wide."""
  return max(measure_rich(pdf, [replace(face, text=label)], line_w, 1.0) for label in labels)

def signatures_height(
  pdf, labels:list[str], face:RichSegment, *,
  gap:float, width:float,
) -> float:
  """Height (mm) of the `signatures` block in the current frame: the gap, the lines, the labels."""
  if not labels: return 0.0
  line_w = _line_width(pdf, len(labels), width)
  return gap + max(_SIGN_BLOCK_MM, _LABEL_GAP_MM + _label_height(pdf, labels, face, line_w))

def signatures(
  pdf, labels:list[str], face:RichSegment, *,
  gap:float, width:float, thick:float,
  dash:tuple = (2, 2),
):
  """
  Signing lines at the cursor, under each its label in `face`, centred.

  One line sits at the right margin; several span margin to margin, spread evenly.
  The lines are `thick` pt, in the colour of `face`, dashed `(on, off)` pt by `dash`:
  `(1, 2)` gives the dotted line of a form.
  A block that does not fit the rest of the frame moves on, as `pdf.keep()` decides.
  Leaves the cursor below the labels.
  """
  if not labels: return
  pdf.keep(signatures_height(pdf, labels, face, gap=gap, width=width))
  count = len(labels)
  content_w = pdf.content_width
  line_w = _line_width(pdf, count, width)
  x0 = content_w - line_w if count == 1 else 0
  step = (content_w - line_w) / (count - 1) if count > 1 else 0
  y = pdf.y + gap
  for i, label in enumerate(labels):
    x_left = x0 + i * step
    pdf.cursor(x_left, y)
    pdf.stroke_color(*face.color[:3])
    pdf.line(line_w, 0, thick, dash=dash)
    render_rich(pdf, [replace(face, text=label)], line_w, x_left, y + _LABEL_GAP_MM,
      Align.CENTER, 1.0)
  pdf.cursor(0, y + _LABEL_GAP_MM + _label_height(pdf, labels, face, line_w))

#-------------------------------------------------------------------------------------- Page number

def page_number(pdf, label:str, n:int, total:int, face:RichSegment, *, show_total:bool):
  """`Label N/M`, or `Label N` without `show_total`, in `face`, centred in the bottom margin."""
  text = (f"{label} {n}/{total}" if show_total else f"{label} {n}").strip()
  c = pdf.c
  c.setFillColor(Color(*face.color[:3]))
  c.setFont(pdf.fonts.register(face.family, face.mode), face.size)
  c.drawCentredString(pdf.page_width / 2 * MM_TO_PT, pdf._page.margin_bot / 2 * MM_TO_PT, text)
