# tests/test_columns.py

"""Column regions: frames, flow between them, parallel placement and page chrome around them."""

import pytest
from pdfmarq import PDF, MM_TO_PT
from pdfmarq.md import MarkdownRenderer, MarkdownStyle
from conftest import needs_fitz, pdf_page_words, pdf_links

LONG = "\n\n".join(
  f"Paragraph {i} " + "with words that keep the column busy for a while. " * 6 for i in range(30))

# A4 with 20mm margins and a 10mm gap: two 80mm columns
LEFT_COL = (20, 100)
RIGHT_COL = (110, 190)

#------------------------------------------------------------------------------------------ Helpers

@pytest.fixture
def pdf(tmp_path):
  return PDF(str(tmp_path / "columns.pdf"))

@pytest.fixture
def in_mm():
  """Whether a word box `x0..x1` in pt lies inside a horizontal span given in mm."""
  def check(span:tuple, x0:float, x1:float, slack:float=0.5) -> bool:
    return span[0] * MM_TO_PT - slack <= x0 and x1 <= span[1] * MM_TO_PT + slack
  return check

#------------------------------------------------------------------------------------------- Frames

def frame_is_a_narrower_page(pdf):
  pdf.columns(2, gap=10)
  assert pdf.content_width == pytest.approx(80)
  assert pdf.margin_left == pytest.approx(20)
  pdf.column(1)
  assert pdf.content_width == pytest.approx(80)
  assert pdf.margin_left == pytest.approx(110)

def region_starts_at_current_height(pdf):
  pdf.cursor(0, 40)
  pdf.columns(2, gap=10)
  assert pdf.y == 0
  assert pdf.content_height == pytest.approx(pdf._page_full.content_height - 40)

def closing_lands_below_lowest_column(pdf):
  pdf.cursor(0, 30).columns(2, gap=10)
  pdf.cursor(0, 50)
  pdf.column(1).cursor(0, 20)
  pdf.columns(1)
  assert pdf.y == pytest.approx(80)
  assert pdf.content_width == pytest.approx(170)

def closing_lands_below_text_left_without_enter(tmp_path):
  plain = PDF(str(tmp_path / "plain.pdf"))
  plain.text("Last words").enter()
  pdf = PDF(str(tmp_path / "columns.pdf"))
  pdf.columns(2, gap=10)
  pdf.text("Last words")
  pdf.columns(1)
  assert pdf.y > 0
  assert pdf.y == pytest.approx(plain.y)

def columns_without_width_are_refused(pdf):
  with pytest.raises(ValueError, match="wide"):
    pdf.inset(left=200)
  with pytest.raises(ValueError, match="wide"):
    pdf.columns(30, gap=8)
  assert pdf.content_width == pytest.approx(170)

def margin_keeps_the_gutter(tmp_path):
  pdf = PDF(str(tmp_path / "gutter.pdf"), margin=20, gutter=8)
  pdf.margin(15)
  assert pdf.margin_left == pytest.approx(23)
  assert pdf.margin_right == pytest.approx(15)

def column_keeps_height(pdf):
  pdf.columns(2, gap=10, flow=False)
  pdf.cursor(0, 12)
  pdf.column(1)
  assert pdf.y == pytest.approx(12)

def height_caps_the_column(pdf):
  pdf.columns(2, gap=10, height=50)
  assert pdf.content_height == pytest.approx(50)

def center_is_the_column_axis(pdf):
  pdf.columns(2, gap=10)
  pdf.column(1)
  pdf.cursor(0, 0, align="C")
  x, _ = pdf._page.cursor_to_canvas(pdf._cursor, 20)
  assert x == pytest.approx(150 - 10)

def center_is_the_page_axis_without_columns(pdf):
  pdf.cursor(0, 0, align="C")
  x, _ = pdf._page.cursor_to_canvas(pdf._cursor, 20)
  assert x == pytest.approx(95)

#--------------------------------------------------------------------------------------------- Flow

def next_frame_moves_to_next_column_then_page(pdf):
  pdf.columns(2, gap=10)
  pdf.next_frame()
  assert (pdf.column_index, pdf.page_num) == (1, 1)
  pdf.next_frame()
  assert (pdf.column_index, pdf.page_num) == (0, 2)

def next_frame_without_columns_is_new_page(pdf):
  pdf.next_frame()
  assert pdf.page_num == 2

def parallel_next_frame_does_nothing(pdf):
  pdf.columns(2, gap=10, flow=False)
  pdf.cursor(0, 30).next_frame()
  assert (pdf.column_index, pdf.page_num, pdf.y) == (0, 1, 30)

def new_page_drops_the_height_cap(pdf):
  pdf.columns(2, gap=10, height=50)
  pdf.new_page()
  assert pdf.content_height == pytest.approx(pdf._page_full.content_height)

def height_list_caps_page_by_page(pdf):
  full = pdf._page_full.content_height
  pdf.columns(2, gap=10, height=[None, 50])
  heights = [pdf.content_height]
  for _ in range(2):
    pdf.new_page()
    heights.append(pdf.content_height)
  assert heights == pytest.approx([full, 50, full]) # past the list, pages are uncapped

def region_restarts_below_new_page_header(pdf):
  pdf.on_new_page(lambda p, n: p.enter(15))
  pdf.columns(2, gap=10)
  pdf.new_page()
  assert pdf._columns.top == pytest.approx(15)
  assert pdf.y == 0

@needs_fitz
def markdown_flows_through_both_columns(tmp_path, in_mm):
  path = str(tmp_path / "flow.pdf")
  pdf = PDF(path)
  pdf.columns(2, gap=10)
  MarkdownRenderer(pdf, MarkdownStyle()).render(LONG)
  pdf.columns(1)
  pdf.save()
  pages = pdf_page_words(path)
  assert len(pages) >= 2
  body_bottom = (297 - 20) * MM_TO_PT
  first = [w for w in pages[0] if w[1] < body_bottom]
  assert all(in_mm(LEFT_COL, w[0], w[2]) or in_mm(RIGHT_COL, w[0], w[2]) for w in first)
  assert any(in_mm(RIGHT_COL, w[0], w[2]) for w in first)

#-------------------------------------------------------------------------------------------- Inset

def inset_narrows_the_frame(pdf):
  pdf.cursor(0, 30).inset(left=10, right=25)
  assert pdf.content_width == pytest.approx(135)
  assert pdf.margin_left == pytest.approx(30)
  assert pdf.y == 0

def inset_closes_below_what_was_drawn(pdf):
  pdf.cursor(0, 30).inset(right=40)
  pdf.cursor(0, 12)
  pdf.inset()
  assert pdf.content_width == pytest.approx(170)
  assert pdf.y == pytest.approx(42)

def inset_carries_over_a_page_break(pdf):
  pdf.inset(left=15)
  pdf.next_frame()
  assert pdf.page_num == 2
  assert pdf.content_width == pytest.approx(155)
  assert pdf.y == 0

@needs_fitz
def text_wraps_inside_the_inset(tmp_path, in_mm):
  path = str(tmp_path / "inset.pdf")
  pdf = PDF(path)
  pdf.inset(left=30, right=50)
  MarkdownRenderer(pdf, MarkdownStyle()).render(LONG[:600])
  pdf.inset()
  pdf.save()
  words = pdf_page_words(path)[0]
  assert words and all(in_mm((50, 140), w[0], w[2]) for w in words)

#-------------------------------------------------------------------------------------- Page chrome

def chrome_sees_the_whole_page(tmp_path):
  pdf = PDF(str(tmp_path / "chrome.pdf"))
  seen = []
  pdf.on_page(lambda p, n: seen.append(("page", p.content_width)))
  pdf.on_final_page(lambda p, n, total: seen.append(("final", p.content_width)))
  pdf.columns(2, gap=10)
  pdf.new_page()
  pdf.save()
  assert {kind for kind, _ in seen} == {"page", "final"}
  assert all(width == pytest.approx(170) for _, width in seen)

def page_changes_refused_inside_columns(pdf):
  pdf.columns(2)
  with pytest.raises(ValueError):
    pdf.margin(10)
  with pytest.raises(ValueError):
    pdf.page(100, 100)

def column_outside_region_refused(pdf):
  with pytest.raises(ValueError):
    pdf.column(0)
  pdf.columns(2)
  with pytest.raises(ValueError):
    pdf.column(2)

#-------------------------------------------------------------------------------------------- Links

@needs_fitz
def link_rect_starts_at_the_margins(tmp_path):
  path = str(tmp_path / "link.pdf")
  pdf = PDF(path)
  pdf.cursor(5, 10).link("https://example.com", 30, 6)
  pdf.text("Example") # a page with nothing drawn on it is never written
  pdf.save()
  rect = pdf_links(path)[0]["from"]
  assert rect.x0 == pytest.approx(25 * MM_TO_PT, abs=0.1)
  assert rect.y0 == pytest.approx(30 * MM_TO_PT, abs=0.1)
  assert rect.width == pytest.approx(30 * MM_TO_PT, abs=0.1)
