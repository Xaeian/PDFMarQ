"""Unit tests for pure helpers - utils, fonts, layout.

Cheap and fast, no canvas. Catches regressions in the bits the rest of
the library leans on (color parsing, margin parsing, builtin font
detection, cursor math).
"""
import pytest
from pdfmarq.utils import to_mm, mm_to_pt, parse_color, color_alpha, color_hex, parse_margin
from pdfmarq.fonts import FontManager, is_builtin, builtin_name
from pdfmarq.inline import RichSegment
from pdfmarq.layout import Cursor, PageGeometry
from pdfmarq.text import TextMetrics
from pdfmarq.constants import Align

#--------------------------------------------------------------------------------------- Units

def test_to_mm_identity():
  assert to_mm(10, "mm") == 10

def test_to_mm_cm():
  assert to_mm(1, "cm") == pytest.approx(10)

def test_to_mm_in():
  assert to_mm(1, "in") == pytest.approx(25.4)

def test_to_mm_pt():
  assert to_mm(72, "pt") == pytest.approx(25.4, rel=1e-3)

def test_to_mm_bad_unit():
  with pytest.raises(ValueError):
    to_mm(1, "furlong")

def test_mm_to_pt_single():
  assert mm_to_pt(10) == pytest.approx(10 * 72 / 25.4)

def test_mm_to_pt_many():
  out = mm_to_pt(10, 20)
  assert isinstance(out, list) and len(out) == 2

#------------------------------------------------------------------------------------- Colors

def test_parse_color_hex_long():
  r, g, b = parse_color("#FF0000")
  assert (r, g, b) == pytest.approx((1, 0, 0))

def test_parse_color_hex_short():
  r, g, b = parse_color("#F00")
  assert (r, g, b) == pytest.approx((1, 0, 0))

def test_parse_color_hex_no_hash():
  r, g, b = parse_color("00FF00")
  assert (r, g, b) == pytest.approx((0, 1, 0))

def test_parse_color_tuple_3():
  assert parse_color((0.2, 0.4, 0.8)) == (0.2, 0.4, 0.8)

def test_parse_color_tuple_4_drops_alpha():
  # `parse_color` returns 3-tuple - alpha is dropped if present.
  assert parse_color((0.2, 0.4, 0.8, 0.5)) == (0.2, 0.4, 0.8)

def test_parse_color_none():
  assert parse_color(None) == (0, 0, 0)

def test_parse_color_bad_hex_raises():
  with pytest.raises(ValueError):
    parse_color("#GGGGGG")

def test_color_alpha():
  out = color_alpha("#FF0000", 0.5)
  assert out == pytest.approx((1, 0, 0, 0.5))

def test_color_hex_from_floats():
  assert color_hex((1.0, 0.0, 0.0)) == "FF0000"
  assert color_hex((0.5, 0.5, 0.5)) == "808080"

def test_color_hex_from_hex():
  assert color_hex("#1f2328") == "1F2328"
  assert color_hex("0969da") == "0969DA"

#-------------------------------------------------------------------------------- RichSegment

def test_rich_segment_bold_flag_sets_mode():
  seg = RichSegment(text="x", bold=True)
  assert seg.mode == "Bold"

def test_rich_segment_italic_flag_sets_mode():
  seg = RichSegment(text="x", italic=True)
  assert seg.mode == "Italic"

def test_rich_segment_bold_italic_flags_combine():
  seg = RichSegment(text="x", bold=True, italic=True)
  assert seg.mode == "BoldItalic"

def test_rich_segment_explicit_mode_default_flags():
  # No flags set → `mode` argument wins.
  seg = RichSegment(text="x", mode="Bold")
  assert seg.mode == "Bold"

def test_rich_segment_strike_field_exists():
  # Regression: was `strikethrough`, renamed for cross-lib parity with docmarq.
  seg = RichSegment(text="x", strike=True)
  assert seg.strike is True

#-------------------------------------------------------------------------------- Defaults

def test_defaults_match_docmarq():
  # Cross-lib parity: same numeric defaults so a PDF and a DOCX rendered
  # from the same source land on comparable visual properties.
  from pdfmarq.constants import Defaults as PD
  from docmarq.constants import Defaults as DD
  assert PD.MARGIN == DD.MARGIN == 20
  assert PD.FONT_SIZE == DD.FONT_SIZE == 11
  assert PD.LINE_HEIGHT == DD.LINE_HEIGHT == 1.15

#----------------------------------------------------------------------------- Style flags

def test_style_bold_flag_sets_mode_via_with_defaults():
  from pdfmarq.styles import Style
  s = Style(bold=True).with_defaults()
  assert s.font_mode == "Bold"

def test_style_italic_flag_sets_mode():
  from pdfmarq.styles import Style
  s = Style(italic=True).with_defaults()
  assert s.font_mode == "Italic"

def test_style_explicit_mode_wins_over_flags():
  # Explicit `font_mode` overrides the flag derivation - user can force
  # an unusual combination (e.g. mode="Italic" with bold=True for some
  # non-standard register).
  from pdfmarq.styles import Style
  s = Style(font_mode="BoldItalic").with_defaults()
  assert s.font_mode == "BoldItalic"

def test_styles_preset_heading4_exists():
  from pdfmarq.styles import Styles
  h = Styles.HEADING4
  assert h.font_size == 11 and h.bold is True

def test_styles_preset_code_exists():
  from pdfmarq.styles import Styles
  c = Styles.CODE
  assert c.font_family == "Courier" and c.font_size == 10

#-------------------------------------------------------------------------------- Metadata

def test_metadata_comments_category_fields():
  from pdfmarq.structure import Metadata
  m = Metadata(title="T", comments="c", category="cat")
  assert m.comments == "c" and m.category == "cat"

#---------------------------------------------------------------------------- TableStyle parity

def test_table_style_shared_fields_match_docmarq():
  # Cross-lib: the fields users tweak most often must have matching names
  # in both libs so the same config dict works for either pipeline.
  from pdfmarq.styles import TableStyle as PT
  from docmarq.styles import TableStyle as DT
  shared = {
    "header_bg", "header_color", "header_bold",
    "row_bg_even", "row_bg_odd",
    "border_color",
    "cell_pad_top", "cell_pad_bot", "cell_pad_h",
    "header_repeat", "vertical_align", "font_size",
    "table_align", "fill_content_width",
  }
  from dataclasses import fields
  p_fields = {f.name for f in fields(PT())}
  d_fields = {f.name for f in fields(DT())}
  missing_p = shared - p_fields
  missing_d = shared - d_fields
  assert not missing_p, f"pdfmarq.TableStyle missing: {missing_p}"
  assert not missing_d, f"docmarq.TableStyle missing: {missing_d}"

def test_table_style_accepts_hex_colors():
  # Both libs accept either `(r,g,b)` floats or `#hex` strings for color fields.
  from pdfmarq.styles import TableStyle
  s = TableStyle(header_bg="#f6f8fa", border_color="#d0d7de")
  assert s.header_bg == "#f6f8fa"

#-------------------------------------------------------------------- RichSegment extra flags

def test_rich_segment_break_line_field():
  # Symmetric with docmarq's `break_line` flag - alternative to "\n" in text.
  seg = RichSegment(text="x", break_line=True)
  assert seg.break_line is True

def test_rich_segment_superscript_subscript():
  seg = RichSegment(text="x", superscript=True)
  assert seg.superscript is True
  seg2 = RichSegment(text="x", subscript=True)
  assert seg2.subscript is True

#------------------------------------------------------------------- output_path parity

def test_output_path_property_pdf():
  from pdfmarq import PDF
  import tempfile, os
  with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, "x.pdf")
    pdf = PDF(p)
    assert pdf.output_path == p

def test_output_path_property_docx():
  from docmarq import DOCX
  import tempfile, os
  with tempfile.TemporaryDirectory() as d:
    p = os.path.join(d, "x.docx")
    doc = DOCX(p)
    assert doc.output_path == p

#------------------------------------------------------------------- Version bump check

def test_versions_aligned():
  # Both libs co-evolve, version bumps tracked together.
  from pdfmarq import __version__ as pv
  from docmarq import __version__ as dv
  # Just confirm strings parseable and bumped past initial.
  assert pv >= "0.3.0"
  assert dv >= "0.2.0"

#------------------------------------------------------------------------------------- Margin

def test_parse_margin_scalar():
  # CSS-style: (top, right, bot, left)
  assert parse_margin(10) == (10, 10, 10, 10)

def test_parse_margin_2tuple():
  # `(v, h)` - vertical and horizontal
  assert parse_margin((10, 20)) == (10, 20, 10, 20)

def test_parse_margin_3tuple():
  # `(t, h, b)` - top, horizontal, bottom
  assert parse_margin((10, 20, 30)) == (10, 20, 30, 20)

def test_parse_margin_4tuple():
  # Regression: 4-element CSS form used to silently drop the last value.
  assert parse_margin((1, 2, 3, 4)) == (1, 2, 3, 4)

def test_parse_margin_list_accepted():
  assert parse_margin([1, 2, 3, 4]) == (1, 2, 3, 4)

def test_parse_margin_invalid():
  with pytest.raises(ValueError):
    parse_margin("nope")

#-------------------------------------------------------------------------------------- Fonts

def test_is_builtin_helvetica():
  assert is_builtin("Helvetica", "Regular")
  assert is_builtin("Helvetica", "Bold")

def test_is_builtin_times_regular():
  assert is_builtin("Times", "Regular")

def test_is_builtin_times_bold():
  # Catches the bug review.md flagged: family="Times-Roman" + mode="Bold"
  # used to slip through `is_builtin` then resolve to plain "Times-Roman".
  assert is_builtin("Times", "Bold")
  assert builtin_name("Times", "Bold") == "Times-Bold"

def test_is_builtin_times_roman_alias():
  # Users passing the reportlab name `Times-Roman` must still get the
  # right modal variant - was silently producing Regular before.
  assert is_builtin("Times-Roman", "Bold")
  assert builtin_name("Times-Roman", "Bold") == "Times-Bold"
  assert builtin_name("Times-Roman", "Italic") == "Times-Italic"
  assert builtin_name("Times-Roman", "Regular") == "Times-Roman"

def test_is_builtin_italic_alias():
  # `Italic` is an accepted alias for `Oblique` in the Helvetica/Courier
  # families (which reportlab names with `Oblique`). Lets users write
  # `Italic` everywhere regardless of family.
  assert builtin_name("Helvetica", "Italic") == "Helvetica-Oblique"
  assert builtin_name("Courier", "Italic") == "Courier-Oblique"

def test_is_builtin_not_known():
  assert not is_builtin("Barlow", "Regular")

def test_builtin_name_regular():
  assert builtin_name("Helvetica", "Regular") == "Helvetica"

def test_builtin_name_bold():
  assert builtin_name("Helvetica", "Bold") == "Helvetica-Bold"

#-------------------------------------------------------------------------------------- Cursor

def test_cursor_set_resets_x_base():
  c = Cursor()
  c.set(5, 10)
  assert c.x == 5 and c.y == 10 and c.x_base == 5

def test_cursor_enter_resets_x():
  c = Cursor()
  c.set(5, 10)
  c.x = 30
  c.enter(8)
  assert c.x == 5
  assert c.y == 18

def test_cursor_advance_x_left():
  c = Cursor(align=Align.LEFT)
  c.advance_x(10)
  assert c.x == 10

def test_cursor_advance_x_right():
  c = Cursor(align=Align.RIGHT)
  c.x = 50
  c.advance_x(10)
  assert c.x == 40

def test_cursor_advance_x_center_unchanged():
  # Currently CENTER is a no-op - confirm the behavior is consistent so
  # callers can rely on it (this is documented in review.md as a quirk).
  c = Cursor(align=Align.CENTER)
  c.x = 25
  c.advance_x(10)
  assert c.x == 25

def test_cursor_copy_independent():
  c = Cursor(x=5, y=10, align=Align.RIGHT)
  d = c.copy()
  d.x = 99
  assert c.x == 5
  assert d.x == 99

#-------------------------------------------------------------------------------- PageGeometry

def test_page_content_dims():
  p = PageGeometry(width=210, height=297, margin_left=20, margin_right=20, margin_top=15, margin_bot=15)
  assert p.content_width == 170
  assert p.content_height == 267

def test_page_x_for_align_left():
  p = PageGeometry(width=210, height=297, margin_left=20, margin_right=20)
  assert p.x_for_align(50, Align.LEFT) == 20

def test_page_x_for_align_center():
  p = PageGeometry(width=210, height=297, margin_left=20, margin_right=20)
  assert p.x_for_align(50, Align.CENTER) == pytest.approx(80)

def test_page_x_for_align_right():
  p = PageGeometry(width=210, height=297, margin_left=20, margin_right=20)
  assert p.x_for_align(50, Align.RIGHT) == pytest.approx(140)

def test_page_asymmetric_margins():
  # Left and right can differ; content width should reflect the sum.
  p = PageGeometry(width=210, height=297, margin_left=10, margin_right=30)
  assert p.content_width == 170
  assert p.x_for_align(50, Align.LEFT) == 10
  assert p.x_for_align(50, Align.RIGHT) == pytest.approx(130)

def test_page_margin_lr_compat_property():
  # `margin_lr` is a back-compat alias: read returns left, write sets both.
  p = PageGeometry(width=210, height=297, margin_left=20, margin_right=20)
  assert p.margin_lr == 20
  p.margin_lr = 25
  assert p.margin_left == 25 and p.margin_right == 25

#------------------------------------------------------------------------------------ box_fit

def _metrics():
  return TextMetrics(FontManager("./fonts"))

def test_box_fit_simple_no_wrap():
  m = _metrics()
  r = m.box_fit("Hi", width=200, family="Helvetica", mode="Regular", size=12)
  assert r.text == "Hi" and r.lines == 1 and not r.overflow

def test_box_fit_wrap():
  m = _metrics()
  r = m.box_fit(
    "Lorem ipsum dolor sit amet consectetur adipiscing elit",
    width=80, family="Helvetica", mode="Regular", size=12,
  )
  assert r.lines >= 2 and not r.overflow

def test_box_fit_autoscale_fine_step_no_stack_overflow():
  # Regression: was recursive, could blow the stack at small autoscale steps.
  # `box_fit("loooong", 50pt-wide, autoscale=0.1)` used to recurse ~120 times.
  m = _metrics()
  r = m.box_fit(
    "A" * 200, width=50, height=10,
    family="Helvetica", mode="Regular", size=12, autoscale=0.1,
  )
  # The text won't fit even at minimum, but the call must return (not crash).
  assert r is not None

def test_box_fit_autoscale_extreme_step():
  # `autoscale=0.001` would have meant ~12000 recursions in the old impl;
  # iterative version handles it fine, just confirm no crash + sane result.
  m = _metrics()
  r = m.box_fit(
    "word " * 100, width=60,
    family="Helvetica", mode="Regular", size=12, autoscale=0.001,
  )
  assert r.font_size <= 12

def test_box_fit_overflow_flag():
  # Single unbreakable word wider than `width` and no autoscale headroom:
  # `overflow` must be True so callers know they hit the wall.
  m = _metrics()
  r = m.box_fit(
    "Pneumonoultramicroscopicsilicovolcanoconiosis",
    width=20, family="Helvetica", mode="Regular", size=12,
  )
  assert r.overflow is True
