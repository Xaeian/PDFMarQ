# tests/test_units.py

"""Pure helpers - units, colors, margins, fonts, cursor/page geometry, box_fit. No canvas."""

import pytest
from pdfmarq import PDF
from pdfmarq.utils import to_mm, mm_to_pt, parse_color, color_alpha, color_hex, parse_margin
from pdfmarq.fonts import FontManager, is_builtin, builtin_name
from pdfmarq.inline import RichSegment
from pdfmarq.layout import Cursor, PageGeometry
from pdfmarq.text import TextMetrics
from pdfmarq.constants import Align, Defaults
from pdfmarq.styles import Style, Styles, TableStyle
from pdfmarq.structure import Metadata
from docmarq import DOCX

@pytest.fixture
def metrics():
  return TextMetrics(FontManager("./fonts"))

#-------------------------------------------------------------------------------------------- Units

@pytest.mark.parametrize("value, unit, expected", [
  (10, "mm", 10),
  (1, "cm", 10),
  (1, "in", 25.4),
])
def to_mm_converts_known_units(value, unit, expected):
  assert to_mm(value, unit) == pytest.approx(expected)

def to_mm_converts_points_with_tolerance():
  assert to_mm(72, "pt") == pytest.approx(25.4, rel=1e-3)

def to_mm_rejects_unknown_unit():
  with pytest.raises(ValueError):
    to_mm(1, "furlong")

def mm_to_pt_single_value():
  assert mm_to_pt(10) == pytest.approx(10 * 72 / 25.4)

def mm_to_pt_many_returns_list():
  out = mm_to_pt(10, 20)
  assert isinstance(out, list) and len(out) == 2

#------------------------------------------------------------------------------------------- Colors

@pytest.mark.parametrize("value, expected", [
  ("#FF0000", (1, 0, 0)),
  ("#F00", (1, 0, 0)),     # short hex
  ("00FF00", (0, 1, 0)),   # no hash
])
def parse_color_hex_forms(value, expected):
  assert parse_color(value) == pytest.approx(expected)

@pytest.mark.parametrize("value, expected", [
  ((0.2, 0.4, 0.8), (0.2, 0.4, 0.8)),
  ((0.2, 0.4, 0.8, 0.5), (0.2, 0.4, 0.8)), # alpha dropped from 4-tuple
  (None, (0, 0, 0)),
])
def parse_color_tuple_and_none(value, expected):
  assert parse_color(value) == expected

def parse_color_rejects_bad_hex():
  with pytest.raises(ValueError):
    parse_color("#GGGGGG")

def color_alpha_appends_alpha_channel():
  assert color_alpha("#FF0000", 0.5) == pytest.approx((1, 0, 0, 0.5))

@pytest.mark.parametrize("value, expected", [
  ((1.0, 0.0, 0.0), "FF0000"),
  ((0.5, 0.5, 0.5), "808080"),
  ("#1f2328", "1F2328"),
  ("0969da", "0969DA"),
])
def color_hex_normalizes_to_uppercase(value, expected):
  assert color_hex(value) == expected

#-------------------------------------------------------------------------------------- RichSegment

@pytest.mark.parametrize("kwargs, expected", [
  ({"bold": True}, "Bold"),
  ({"italic": True}, "Italic"),
  ({"bold": True, "italic": True}, "BoldItalic"),
  ({"mode": "Bold"}, "Bold"), # explicit mode wins when no flags set
])
def rich_segment_flags_derive_mode(kwargs, expected):
  assert RichSegment(text="x", **kwargs).mode == expected

def rich_segment_strike_field_exists():
  # regression: was `strikethrough`, renamed for cross-lib parity with docmarq
  assert RichSegment(text="x", strike=True).strike is True

def rich_segment_break_line_field():
  # symmetric with docmarq's `break_line` flag - alternative to "\n" in text
  assert RichSegment(text="x", break_line=True).break_line is True

def rich_segment_superscript_subscript_fields():
  assert RichSegment(text="x", superscript=True).superscript is True
  assert RichSegment(text="x", subscript=True).subscript is True

#----------------------------------------------------------------------------------------- Defaults

def defaults_match_docmarq():
  # cross-lib parity: same numeric defaults so PDF and DOCX land comparable
  from docmarq.constants import Defaults as DD
  assert Defaults.MARGIN == DD.MARGIN == 20
  assert Defaults.FONT_SIZE == DD.FONT_SIZE == 11
  assert Defaults.LINE_HEIGHT == DD.LINE_HEIGHT == 1.15

#-------------------------------------------------------------------------------------- Style flags

@pytest.mark.parametrize("kwargs, expected", [
  ({"bold": True}, "Bold"),
  ({"italic": True}, "Italic"),
  ({"font_mode": "BoldItalic"}, "BoldItalic"), # explicit mode wins over flags
])
def style_flags_derive_font_mode(kwargs, expected):
  assert Style(**kwargs).with_defaults().font_mode == expected

def styles_preset_heading4_exists():
  assert Styles.HEADING4.font_size == 11 and Styles.HEADING4.bold is True

def styles_preset_code_exists():
  assert Styles.CODE.font_family == "Courier" and Styles.CODE.font_size == 10

#----------------------------------------------------------------------------------------- Metadata

def metadata_comments_category_fields():
  m = Metadata(title="T", comments="c", category="cat")
  assert m.comments == "c" and m.category == "cat"

#-------------------------------------------------------------------------------- TableStyle parity

def table_style_shared_fields_match_docmarq():
  # cross-lib: the fields users tweak most must have matching names in both libs
  from docmarq.styles import TableStyle as DT
  from dataclasses import fields
  shared = {
    "header_bg", "header_color", "header_bold",
    "row_bg_even", "row_bg_odd",
    "border_color",
    "cell_pad_top", "cell_pad_bot", "cell_pad_h",
    "header_repeat", "vertical_align", "font_size",
    "table_align", "fill_content_width",
  }
  p_fields = {f.name for f in fields(TableStyle())}
  d_fields = {f.name for f in fields(DT())}
  assert not (shared - p_fields), f"pdfmarq.TableStyle missing: {shared - p_fields}"
  assert not (shared - d_fields), f"docmarq.TableStyle missing: {shared - d_fields}"

def table_style_accepts_hex_colors():
  # both libs accept either (r,g,b) floats or #hex strings for color fields
  s = TableStyle(header_bg="#f6f8fa", border_color="#d0d7de")
  assert s.header_bg == "#f6f8fa"

#------------------------------------------------------------------------------- output_path parity

def output_path_property_pdf():
  import tempfile, os
  with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, "x.pdf")
    assert PDF(p).output_path == p

def output_path_property_docx():
  import tempfile, os
  with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, "x.docx")
    assert DOCX(p).output_path == p

#------------------------------------------------------------------------------------- Version bump

def versions_aligned():
  # both libs co-evolve, version bumps tracked together
  from pdfmarq import __version__ as pv
  from docmarq import __version__ as dv
  assert pv >= "0.3.0"
  assert dv >= "0.2.0"

#------------------------------------------------------------------------------------------- Margin

@pytest.mark.parametrize("value, expected", [
  (10, (10, 10, 10, 10)),          # scalar
  ((10, 20), (10, 20, 10, 20)),    # (v, h)
  ((10, 20, 30), (10, 20, 30, 20)),# (t, h, b)
  ((1, 2, 3, 4), (1, 2, 3, 4)),    # regression: 4-element CSS form used to drop last
  ([1, 2, 3, 4], (1, 2, 3, 4)),    # list accepted
])
def parse_margin_css_forms(value, expected):
  assert parse_margin(value) == expected

def parse_margin_rejects_invalid():
  with pytest.raises(ValueError):
    parse_margin("nope")

#-------------------------------------------------------------------------------------------- Fonts

@pytest.mark.parametrize("family, mode", [
  ("Helvetica", "Regular"),
  ("Helvetica", "Bold"),
  ("Times", "Regular"),
  ("Times", "Bold"), # regression: Times+Bold used to slip through is_builtin
])
def is_builtin_recognizes_builtins(family, mode):
  assert is_builtin(family, mode)

def is_builtin_rejects_unknown_family():
  assert not is_builtin("Barlow", "Regular")

@pytest.mark.parametrize("family, mode, expected", [
  ("Helvetica", "Regular", "Helvetica"),
  ("Helvetica", "Bold", "Helvetica-Bold"),
  ("Helvetica", "Italic", "Helvetica-Oblique"), # Italic alias for Oblique
  ("Courier", "Italic", "Courier-Oblique"),
  ("Times", "Bold", "Times-Bold"),
  # `Times-Roman` reportlab alias must still resolve modal variants
  ("Times-Roman", "Bold", "Times-Bold"),
  ("Times-Roman", "Italic", "Times-Italic"),
  ("Times-Roman", "Regular", "Times-Roman"),
])
def builtin_name_resolves_modal_variant(family, mode, expected):
  assert builtin_name(family, mode) == expected

def is_builtin_times_roman_alias():
  # regression: `Times-Roman` + Bold used to silently produce Regular
  assert is_builtin("Times", "Bold")
  assert is_builtin("Times-Roman", "Bold")

#------------------------------------------------------------------------------------------- Cursor

def cursor_set_resets_x_base():
  c = Cursor()
  c.set(5, 10)
  assert c.x == 5 and c.y == 10 and c.x_base == 5

def cursor_enter_resets_x_and_advances_y():
  c = Cursor()
  c.set(5, 10)
  c.x = 30
  c.enter(8)
  assert c.x == 5 and c.y == 18

@pytest.mark.parametrize("align, start_x, expected_x", [
  (Align.LEFT, 0, 10),
  (Align.RIGHT, 50, 40),
  (Align.CENTER, 25, 25), # CENTER is a no-op (documented quirk)
])
def cursor_advance_x_per_alignment(align, start_x, expected_x):
  c = Cursor(align=align)
  c.x = start_x
  c.advance_x(10)
  assert c.x == expected_x

def cursor_copy_is_independent():
  c = Cursor(x=5, y=10, align=Align.RIGHT)
  d = c.copy()
  d.x = 99
  assert c.x == 5 and d.x == 99

#------------------------------------------------------------------------------------- PageGeometry

def page_content_dims_subtract_margins():
  p = PageGeometry(width=210, height=297, margin_left=20, margin_right=20, margin_top=15, margin_bot=15)
  assert p.content_width == 170 and p.content_height == 267

@pytest.mark.parametrize("align, expected", [
  (Align.LEFT, 20),
  (Align.CENTER, 80),
  (Align.RIGHT, 140),
])
def page_x_for_align(align, expected):
  p = PageGeometry(width=210, height=297, margin_left=20, margin_right=20)
  assert p.x_for_align(50, align) == pytest.approx(expected)

def page_asymmetric_margins():
  # left and right can differ; content width reflects the sum
  p = PageGeometry(width=210, height=297, margin_left=10, margin_right=30)
  assert p.content_width == 170
  assert p.x_for_align(50, Align.LEFT) == 10
  assert p.x_for_align(50, Align.RIGHT) == pytest.approx(130)

#------------------------------------------------------------------------------------------ box_fit

def box_fit_simple_no_wrap(metrics):
  r = metrics.box_fit("Hi", width=200, family="Helvetica", mode="Regular", size=12)
  assert r.text == "Hi" and r.lines == 1 and not r.overflow

def box_fit_wraps_long_text(metrics):
  r = metrics.box_fit(
    "Lorem ipsum dolor sit amet consectetur adipiscing elit",
    width=80, family="Helvetica", mode="Regular", size=12,
  )
  assert r.lines >= 2 and not r.overflow

def box_fit_autoscale_fine_step_no_stack_overflow(metrics):
  # regression: was recursive, could blow the stack at small autoscale steps
  r = metrics.box_fit(
    "A" * 200, width=50, height=10,
    family="Helvetica", mode="Regular", size=12, autoscale=0.1,
  )
  assert r is not None # won't fit even at minimum, but must return (not crash)

def box_fit_autoscale_extreme_step(metrics):
  # autoscale=0.001 would have meant ~12000 recursions in the old impl
  r = metrics.box_fit(
    "word " * 100, width=60,
    family="Helvetica", mode="Regular", size=12, autoscale=0.001,
  )
  assert r.font_size <= 12

def box_fit_overflow_flag_on_unbreakable_word(metrics):
  # single word wider than `width` with no autoscale headroom → overflow True
  r = metrics.box_fit(
    "Pneumonoultramicroscopicsilicovolcanoconiosis",
    width=20, family="Helvetica", mode="Regular", size=12,
  )
  assert r.overflow is True
