# tests/test_columns.py

"""
Column regions and fixed frames:
flow between them, parallel placement and page chrome around them.
"""

import io, math, warnings
from pathlib import Path
import pytest
from pdfmarq import PDF, MM_TO_PT, Floats, lowest_fit
from pdfmarq.md import MarkdownRenderer, MarkdownStyle
from conftest import needs_pymupdf, pdf_page_words, pdf_links, pdf_strokes

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

def two_sided_mirrors_even_pages(tmp_path):
  pdf = PDF(str(tmp_path / "two.pdf"), margin=25, gutter=10, two_sided=True)
  sides = [(pdf.margin_left, pdf.margin_right)]
  for _ in range(2):
    pdf.new_page()
    sides.append((pdf.margin_left, pdf.margin_right))
  assert sides == [(35, 25), (25, 35), (35, 25)]
  assert pdf.content_width == 150
  pdf.new_page()
  pdf.margin(20)
  assert (pdf.margin_left, pdf.margin_right) == (20, 30)

def two_sided_columns_and_final_pages_take_their_page(tmp_path):
  pdf = PDF(str(tmp_path / "two.pdf"), margin=25, gutter=10, two_sided=True)
  feet = {}
  pdf.on_final_page(lambda p, n, total: feet.setdefault(n, p.margin_left))
  pdf.columns(2, gap=10)
  pdf.new_page()
  assert pdf.margin_left == 25 # column 1 of an even page starts at its outer margin
  pdf.save()
  assert feet == {1: 35, 2: 25}

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

@needs_pymupdf
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

@needs_pymupdf
def text_wraps_inside_the_inset(tmp_path, in_mm):
  path = str(tmp_path / "inset.pdf")
  pdf = PDF(path)
  pdf.inset(left=30, right=50)
  MarkdownRenderer(pdf, MarkdownStyle()).render(LONG[:600])
  pdf.inset()
  pdf.save()
  words = pdf_page_words(path)[0]
  assert words and all(in_mm((50, 140), w[0], w[2]) for w in words)

#-------------------------------------------------------------------------------------- Fixed frame

def frame_is_a_page_of_its_own(pdf):
  with pdf.frame(10, 30, 120, 40):
    assert (pdf.content_width, pdf.content_height) == pytest.approx((120, 40))
    assert (pdf.margin_left, pdf.margin_top, pdf.x, pdf.y) == pytest.approx((30, 50, 0, 0))
    pdf.columns(2, gap=10)
    assert pdf.content_width == pytest.approx(55) # columns divide the frame
  assert pdf.content_width == pytest.approx(170)

def cursor_comes_back_after_a_frame(pdf):
  pdf.cursor(5, 7, "R")
  with pdf.frame(10, 30, 120, 40):
    pdf.text("inside").enter()
  assert (pdf.x, pdf.y, pdf._cursor.align) == (5, 7, "R")

@needs_pymupdf
def markdown_fills_a_frame(tmp_path, in_mm):
  path = str(tmp_path / "frame.pdf")
  with PDF(path) as pdf, pdf.frame(10, 30, 120, 60):
    MarkdownRenderer(pdf, MarkdownStyle()).render("# Title\n\n" + "Words fill the box. " * 20)
  words = pdf_page_words(path)[0]
  assert all(in_mm((30, 150), w[0], w[2]) for w in words)
  assert min(w[1] for w in words) >= 50 * MM_TO_PT # from the top of the frame

@pytest.mark.parametrize("md", [
  "Long text. " * 80,
  "One\n\n<!-- pagebreak -->\n\nTwo\n",
  "Text\n\n# Title on a page of its own\n",
], ids=["too long", "page break", "heading page"])
def content_past_a_frame_warns(pdf, md):
  # A frame holds one page: what asks for more room, a page break too, runs on in it and warns
  with pytest.warns(RuntimeWarning, match="more room"):
    with pdf.frame(10, 30, 60, 20):
      MarkdownRenderer(pdf, MarkdownStyle(h1_page_break=True)).render(md)
  assert pdf.page_num == 1

def frame_refuses_nesting(pdf):
  with pdf.frame(10, 30, 60, 20):
    with pytest.raises(ValueError), pdf.frame(0, 0, 10, 10): pass
  pdf.columns(2)
  with pytest.raises(ValueError), pdf.frame(0, 0, 10, 10): pass

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

@needs_pymupdf
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

def caps_set_column_by_column(pdf):
  full = pdf._page_full.content_height
  pdf.columns(2, gap=10, height=[(50, None), 80])
  assert pdf.content_height == pytest.approx(50)
  pdf.next_frame()
  assert pdf.content_height == pytest.approx(full)
  pdf.next_frame()
  assert pdf.content_height == pytest.approx(80)

def column_ends_tell_how_far_each_column_of_the_page_reached(pdf):
  assert pdf.column_ends == []
  pdf.columns(2)
  pdf.cursor(0, 50)
  pdf.next_frame()
  pdf.cursor(0, 20)
  assert pdf.column_ends == pytest.approx([50, 20])
  pdf.next_frame() # a new page starts them over
  assert pdf.column_ends == pytest.approx([0])

def a_tuple_caps_page_by_page_as_a_list_does(pdf):
  pdf.columns(2, gap=10, height=(50, 80))
  assert pdf.content_height == pytest.approx(50)
  pdf.next_frame()
  assert pdf.content_height == pytest.approx(50)
  pdf.next_frame()
  assert pdf.content_height == pytest.approx(80)

def caps_refuse_a_count_off_the_columns(pdf):
  with pytest.raises(ValueError, match="3 column caps for 2 columns"):
    pdf.columns(2, height=[(10, 20, 30)])
  with pytest.raises(ValueError, match="1 column caps for 2 columns"):
    pdf.columns(2, height=[[10]])

def wrong_caps_leave_the_open_region_as_it_was(pdf):
  pdf.columns(2, gap=10)
  width = pdf.content_width
  with pytest.raises(ValueError):
    pdf.columns(3, height=[(10, 20)])
  assert pdf.content_width == pytest.approx(width) # still a column of the region

def at_top_holds_until_the_cursor_moves_down(pdf):
  assert pdf.at_top
  pdf.cursor(0, 1)
  assert not pdf.at_top
  pdf.next_frame()
  assert pdf.at_top

#----------------------------------------------------------------------------------------- Page top

@pytest.fixture
def header(pdf) -> PDF:
  """`pdf` on page 2, whose text starts 8mm down under a header `on_new_page` set."""
  pdf.on_new_page(lambda p, n: p.cursor(0, 8))
  pdf.new_page()
  return pdf

def page_break_on_an_empty_page_adds_none(pdf):
  pdf.page_break()
  assert pdf.page_num == 1

def page_break_under_a_header_adds_no_page(header):
  header.page_break()
  assert header.page_num == 2

def page_break_where_columns_open_low_starts_a_page(pdf):
  pdf.cursor(0, 150)
  pdf.columns(2)
  assert pdf.at_top # the top of its column, not of the page
  pdf.page_break()
  assert pdf.page_num == 2

def page_break_at_the_top_of_the_right_column_starts_a_page(pdf):
  pdf.columns(2)
  pdf.column(1)
  pdf.page_break()
  assert pdf.page_num == 2

def pagebreak_directive_after_columns_opened_low_starts_a_page(pdf):
  pdf.cursor(0, 150)
  pdf.columns(2)
  MarkdownRenderer(pdf, MarkdownStyle()).render("<!-- pagebreak -->\n\nAfter the break.\n")
  assert pdf.page_num == 2

def keep_moves_on_from_a_column_opened_low(pdf):
  pdf.cursor(0, 150)
  pdf.columns(2)
  pdf.keep(150) # taller than both columns left on this page, not than those of the next
  assert (pdf.page_num, pdf.column_index, pdf.y) == (2, 0, 0)

def keep_leaves_what_no_frame_holds_at_the_top_of_one(header):
  header.keep(400)
  assert (header.page_num, header.y) == (2, 8) # moving on would only leave this page blank
  header.columns(2)
  header.column(1)
  header.keep(400)
  assert (header.page_num, header.column_index) == (2, 1)

def keep_ends_where_no_frame_follows(pdf):
  # in `frame()` and in parallel columns `next_frame()` stays put
  import threading, warnings
  def run():
    with warnings.catch_warnings():
      warnings.simplefilter("ignore", RuntimeWarning) # the frame runs over
      with pdf.frame(0, 0, 80, 40):
        pdf.cursor(0, 30)
        pdf.keep(100)
    pdf.columns(2, flow=False)
    pdf.cursor(0, 200)
    pdf.keep(100)
  worker = threading.Thread(target=run, daemon=True)
  worker.start()
  worker.join(5)
  assert not worker.is_alive()

#---------------------------------------------------------------------------------------- Balancing

@pytest.fixture
def counted():
  """`fits` holding from `answer` on, and the heights it was asked about."""
  def make(answer:float):
    asked = []
    def fits(height:float) -> bool:
      asked.append(height)
      return height >= answer
    return fits, asked
  return make

def lowest_fit_takes_the_share_when_it_fits(counted):
  fits, asked = counted(30)
  assert lowest_fit(fits, 40, 200, 4) == 40
  assert asked == [40]

def lowest_fit_finds_the_first_step_that_fits(counted):
  for answer in (41, 47, 90, 199, 200):
    fits, asked = counted(answer)
    steps = math.ceil((answer - 40) / 4)
    assert lowest_fit(fits, 40, 200, 4) == min(40 + steps * 4, 200)
    assert len(asked) == steps + 1 # one by one from the share

def lowest_fit_climbs_little_for_an_answer_close_above_the_share(counted):
  fits, asked = counted(43)
  assert lowest_fit(fits, 40, 200, 4) == 44
  assert asked == [40, 44] # the share, then one step up

def lowest_fit_gives_none_when_the_top_misses(counted):
  fits, asked = counted(300)
  assert lowest_fit(fits, 40, 200, 4) is None
  assert asked[-1] == 200 and len(asked) == 41

def lowest_fit_takes_a_height_that_fits_below_one_that_misses():
  # A block that does not split overruns a cap a little higher, so halving would skip this one
  fits = lambda height: height == 102 or height >= 110
  assert lowest_fit(fits, 100, 200, 1) == 102

def lowest_fit_finds_columns_balanced_below_a_top_they_miss():
  # One column all but full misses its cap by the gap after the last block
  fits = lambda height: 139 <= height < 214 or height >= 216
  assert lowest_fit(fits, 134, 215, 5) == 139

def pictures_off_keep_their_room_and_draw_nothing(tmp_path):
  from PIL import Image
  png = tmp_path / "red.png"
  Image.new("RGB", (40, 20), "red").save(png)
  room, drawn = {}, {}
  for pictures in (True, False):
    data = io.BytesIO()
    pdf = PDF(data, pictures=pictures)
    pdf.image(str(png), 40, 20).enter()
    room[pictures] = pdf.y
    pdf.save()
    drawn[pictures] = b"/Image" in data.getvalue()
  assert room[True] == room[False] == pytest.approx(20)
  assert drawn[True] and not drawn[False]

#------------------------------------------------------------------------------- Columns of a style

LEAD = ("# Title\n\nLeadmark paragraph across the whole page, "
  "long enough to run past the middle.\n\n")
@pytest.fixture
def sections():
  """`count` sections of text, `mark` opening each paragraph."""
  def make(mark:str, count:int=4) -> str:
    text = "words that fill a narrow column for a while. " * 7
    return "\n\n".join(f"## Section {i}\n\n{mark} " + text
      for i in range(count))
  return make

@pytest.fixture
def engine(pdf):
  """Render `md` into `pdf` in two columns 10mm apart, return the words of each page."""
  def run(md:str, **style) -> list:
    look = dict(columns=2, column_gap=10, keep_together=False) | style
    MarkdownRenderer(pdf, MarkdownStyle(**look)).render(md)
    pdf.save()
    return pdf_page_words(pdf.output_path)
  return run

@needs_pymupdf
def columns_of_a_style_leave_the_lead_across_the_page(engine, in_mm, sections):
  words = engine(LEAD + sections("Bodymark"))[0]
  body = [w for w in words if w[4] == "Bodymark"]
  assert any(in_mm(LEFT_COL, w[0], w[2]) for w in body)
  assert any(in_mm(RIGHT_COL, w[0], w[2]) for w in body)
  lead = [w for w in words if w[3] < min(w[1] for w in body)]
  assert max(w[2] for w in lead) > RIGHT_COL[0] * MM_TO_PT # the lead runs past the gap

@needs_pymupdf
def a_wide_group_spans_the_page_between_balanced_runs(engine, in_mm, sections):
  wide = ("<!-- group wide -->\n\nWidemark " + "words across the whole page " * 8
    + "\n\n<!-- /group -->")
  words = engine(sections("Abovemark", 3) + "\n\n" + wide + "\n\n" + sections("Belowmark", 3))[0]
  mark = next(w for w in words if w[4] == "Widemark")
  assert max(w[2] for w in words if abs(w[1] - mark[1]) < 1) > RIGHT_COL[0] * MM_TO_PT
  above = [w for w in words if w[4] == "Abovemark"]
  below = [w for w in words if w[4] == "Belowmark"]
  assert all(w[3] <= mark[1] for w in above) and all(w[1] >= mark[3] for w in below)
  for marks in (above, below):
    assert any(in_mm(LEFT_COL, w[0], w[2]) for w in marks)
    assert any(in_mm(RIGHT_COL, w[0], w[2]) for w in marks)

def a_page_break_after_a_wide_group_starts_a_page(pdf, sections):
  md = (sections("Text", 2) + "\n\n<!-- group wide -->\n\nWide.\n\n<!-- /group -->\n\n"
    "<!-- pagebreak -->\n\n## After\n\nText.\n\n")
  MarkdownRenderer(pdf, MarkdownStyle(columns=2)).render(md)
  assert pdf.page_num == 2

def columns_of_a_style_refuse_to_open_in_columns(pdf):
  pdf.columns(2)
  with pytest.raises(ValueError, match="columns cannot open in columns"):
    MarkdownRenderer(pdf, MarkdownStyle(columns=2)).render("Text.\n\n")

def columns_of_a_style_must_be_a_whole_number(pdf):
  with pytest.raises(ValueError, match="columns must be a whole number"):
    MarkdownRenderer(pdf, MarkdownStyle(columns=0))

def columns_of_a_style_fill_a_slide_frame(pdf):
  # a frame holds one page and `next_frame()` stays in it, so this must end
  import threading
  def run():
    with pdf.frame(0, 0, 170, 60):
      points = "## Points\n\n" + "- a point in words\n" * 10
      MarkdownRenderer(pdf, MarkdownStyle(columns=2)).render(points)
  worker = threading.Thread(target=run, daemon=True)
  worker.start()
  worker.join(10)
  assert not worker.is_alive() and pdf.page_num == 1

def columns_warn_when_they_take_more_pages_than_measured(pdf, monkeypatch):
  # Measured on one page under a 40mm cap, the text runs on to the next
  monkeypatch.setattr(MarkdownRenderer, "_balance", lambda self, run, below, line: (40, 1))
  with pytest.warns(RuntimeWarning, match="measured on 1 pages took"):
    MarkdownRenderer(pdf, MarkdownStyle(columns=2)).render("## Section\n\n" + LONG)

def a_table_squeezed_in_a_column_points_to_a_wide_group(pdf):
  table = "| Name | Kind | Owner | Repository | Status |\n|---|---|---|---|---|\n" \
    + "| Markdown | engine | someone | md2paper | maintained |\n"
  pdf.columns(3)
  with pytest.warns(RuntimeWarning, match="group wide"):
    MarkdownRenderer(pdf, MarkdownStyle()).render(table)

def a_table_holding_its_words_warns_of_nothing(pdf):
  import warnings
  with warnings.catch_warnings():
    warnings.simplefilter("error", RuntimeWarning)
    MarkdownRenderer(pdf, MarkdownStyle()).render("| A | B |\n|---|---|\n| one | two |\n")

def a_new_page_starts_its_text_under_the_headroom(pdf):
  pdf.headroom = 8
  pdf.new_page()
  assert pdf.y == pytest.approx(8)
  pdf.page_break() # nothing set under the headroom yet
  assert pdf.page_num == 2

def balancing_a_run_takes_few_probes(pdf, monkeypatch):
  # One flow without caps, then line by line from the even share, which most often fits
  flows, runs = [], []
  flow, run = MarkdownRenderer._column_flow, MarkdownRenderer._render_run
  def counted(self, *args, **kwargs):
    flows.append(args)
    return flow(self, *args, **kwargs)
  def per_run(self, *args, **kwargs):
    before = len(flows)
    run(self, *args, **kwargs)
    runs.append(len(flows) - before)
  monkeypatch.setattr(MarkdownRenderer, "_column_flow", counted)
  monkeypatch.setattr(MarkdownRenderer, "_render_run", per_run)
  text = "Words that fill the columns of several pages. " * 30
  sections = "\n\n".join(f"## Section {i}\n\n" + text for i in range(10))
  broken = sections + "\n\n<!-- pagebreak -->\n\n## After\n\n" + text
  for md in (sections, broken): # over pages, and over a page break, which ends a run
    MarkdownRenderer(pdf, MarkdownStyle(columns=2)).render(md)
  assert runs and max(runs) <= 4

@needs_pymupdf
def the_page_before_a_page_break_is_balanced(pdf):
  text = "Words that fill the columns of a page for a while. " * 12
  sections = "\n\n".join(f"## Section {i}\n\n" + text for i in range(2))
  md = sections + "\n\n<!-- pagebreak -->\n\n## After\n\n" + text
  MarkdownRenderer(pdf, MarkdownStyle(columns=2)).render(md)
  pdf.save()
  words = [w for w in pdf_page_words(pdf.output_path)[0] if w[4] in ("Words", "Section")]
  left = max(w[3] for w in words if w[2] < 105 * MM_TO_PT)
  right = max((w[3] for w in words if w[0] > 105 * MM_TO_PT), default=0)
  assert abs(left - right) <= 2 * 11 * 1.5 # both columns hold text, ending level

#------------------------------------------------------------------------------ Columns as the page

def columns_at_the_top_of_a_page_measure_its_page_break_as_drawn(pdf):
  import warnings
  pdf.headroom = 8
  pdf.new_page() # the text of page 2 begins 8mm down, and nothing is set there yet
  with warnings.catch_warnings():
    warnings.simplefilter("error", RuntimeWarning)
    md = "<!-- pagebreak -->\n\nText with no section, so the break opens the columns.\n"
    MarkdownRenderer(pdf, MarkdownStyle(columns=2)).render(md)
  assert pdf.page_num == 2 # an empty page breaks no further, in the measure too

def comments_alone_open_no_columns(pdf):
  pdf.cursor(0, pdf.content_height - 5) # room for less than a line
  MarkdownRenderer(pdf, MarkdownStyle(columns=2)).render("<!-- a note -->\n")
  assert pdf.page_num == 1

def columns_take_a_face_registered_from_a_file(tmp_path):
  import shutil, reportlab
  face = tmp_path / "Own.ttf"
  shutil.copy(Path(reportlab.__file__).parent / "fonts" / "Vera.ttf", face)
  pdf = PDF(str(tmp_path / "x.pdf"), font_dir=str(tmp_path / "none"))
  for mode in ("Regular", "Bold", "Italic", "BoldItalic"):
    pdf.fonts.register_file("Own", mode, str(face))
  style = MarkdownStyle(columns=2, font_body="Own", font_head="Own")
  MarkdownRenderer(pdf, style).render("## Head\n\n" + "Text in a face of its own. " * 80 + "\n")

@needs_pymupdf
def blocks_too_tall_for_a_short_column_move_on_whole(pdf):
  paragraphs = "\n\n".join(["Groupmark " + "words " * 60] * 3)
  group = "<!-- group -->\n\n" + paragraphs + "\n\n<!-- /group -->\n\n"
  code = "```\n" + "".join(f"codemark line {i}\n" for i in range(30)) + "```\n"
  pdf.cursor(0, 150)
  pdf.columns(2) # two columns of 107mm, where a fresh one has 257mm
  MarkdownRenderer(pdf, MarkdownStyle()).render(group + code)
  pdf.columns(1)
  pdf.save()
  first = [w[4] for w in pdf_page_words(pdf.output_path)[0]]
  assert "Groupmark" not in first and "codemark" not in first

def a_header_made_room_for_by_on_new_page_is_refused_in_columns(pdf):
  pdf.on_new_page(lambda p, n: p.enter(30))
  words = "Words that fill the columns. " * 40
  text = "\n\n".join(f"## Section {i}\n\n" + words for i in range(12))
  with pytest.raises(ValueError, match="headroom"): # at once, not after a wrong measure
    MarkdownRenderer(pdf, MarkdownStyle(columns=2)).render(text)

#-------------------------------------------------------------------------------------- Frame hooks

def frames_tell_a_block_where_frames_end_and_begin(pdf):
  calls = []
  pdf.columns(2)
  with pdf.frames(enter=lambda p: calls.append(("enter", p.page_num, p.column_index)),
      leave=lambda p: calls.append(("leave", p.page_num, p.column_index))):
    pdf.next_frame() # to the second column
    pdf.next_frame() # to the next page
  pdf.next_frame() # outside the block: nobody hears it
  assert calls == [("leave", 1, 0), ("enter", 1, 1), ("leave", 1, 1), ("enter", 2, 0)]

def frames_nest_inside_out_on_leaving_and_outside_in_on_entering(pdf):
  calls = []
  def note(word:str):
    return lambda p: calls.append(word)
  with pdf.frames(enter=note("outer in"), leave=note("outer out")):
    with pdf.frames(enter=note("inner in"), leave=note("inner out")):
      pdf.new_page()
  assert calls == ["inner out", "outer out", "outer in", "inner in"]

def frames_stay_quiet_where_nothing_moves_on(pdf):
  calls = []
  with pdf.frames(enter=calls.append, leave=calls.append):
    pdf.columns(2, flow=False)
    pdf.next_frame() # parallel columns stay put
    pdf.columns(1)
  assert calls == []

def a_quote_over_pages_has_its_bar_on_each(pdf, monkeypatch):
  bars = []
  bar = MarkdownRenderer._quote_bar
  def recorded(self, x, top, bottom, width, color):
    bars.append((self.pdf.page_num, top, bottom))
    return bar(self, x, top, bottom, width, color)
  monkeypatch.setattr(MarkdownRenderer, "_quote_bar", recorded)
  pdf.cursor(0, 200)
  quote = "\n>\n".join(["> Quotemark " + "words of a long quote " * 30] * 8) # taller than a page
  MarkdownRenderer(pdf, MarkdownStyle(keep_together=False)).render(quote + "\n")
  assert [page for page, _, _ in bars] == list(range(1, pdf.page_num + 1)) and pdf.page_num > 1
  assert all(bottom - top > 10 for _, top, bottom in bars) # bars, no 4mm trace

@needs_pymupdf
def the_bibliography_title_keeps_with_its_first_entry(pdf):
  entry = "A source cited at a length that wraps over several lines of the column. " * 12
  md = "Text with a note.[^1]\n\n[^1]: " + entry + "\n"
  pdf.cursor(0, pdf.content_height - 45) # room for the title and three lines, not the entry
  MarkdownRenderer(pdf, MarkdownStyle(footnote_label="Bibliography")).render(md)
  pdf.save()
  pages = pdf_page_words(pdf.output_path)
  title = next(n for n, words in enumerate(pages) if any(w[4] == "Bibliography" for w in words))
  first = next(n for n, words in enumerate(pages) if any(w[4] == "[1]" for w in words))
  assert title == first

@needs_pymupdf
def the_rule_over_the_bibliography_keeps_with_its_first_entry(pdf):
  entry = "A source cited at a length that wraps over several lines of the column. " * 12
  md = "Text with a note.[^1]\n\n[^1]: " + entry + "\n"
  pdf.cursor(0, pdf.content_height - 30) # room for the rule and three lines, not the entry
  MarkdownRenderer(pdf, MarkdownStyle()).render(md)
  pdf.save()
  rules = [n for n, paths in enumerate(pdf_strokes(pdf.output_path)) for path in paths
    if path["rect"].height < 2 and path["rect"].width > 100]
  pages = pdf_page_words(pdf.output_path)
  first = next(n for n, words in enumerate(pages) if any(w[4] == "[1]" for w in words))
  assert rules == [first]

#------------------------------------------------------------------------------------------- Floats

@pytest.fixture
def floated(pdf, monkeypatch):
  """Render `md` in floating columns, return where each float was drawn: `(page, column, y)`."""
  def run(md:str, **style) -> list:
    spots = []
    draw = MarkdownRenderer._draw_float
    def recorded(self, block):
      if self.pdf is pdf: spots.append((pdf.page_num, pdf.column_index, round(pdf.y, 1)))
      return draw(self, block)
    monkeypatch.setattr(MarkdownRenderer, "_draw_float", recorded)
    look = dict(columns=2, floats=True) | style
    MarkdownRenderer(pdf, MarkdownStyle(**look)).render(md)
    return spots
  return run

TEXT = "Words that fill the columns for a while. " * 8
ROWS = "| A | B |\n|---|---|\n" + "| cell | value |\n" * 14
KEPT = "<!-- group -->\n\nKeptmark title\n\n" + ROWS + "\n<!-- /group -->" # a figure

def a_block_missing_the_column_waits_for_the_next_one(floated):
  spots = floated("\n\n".join([TEXT] * 5 + [KEPT] + [TEXT] * 3) + "\n")
  assert spots == [(1, 1, 0)] # at the top of the right column, the text filling the left

@needs_pymupdf
def text_fills_the_column_a_waiting_block_left(pdf, floated):
  floated("\n\n".join([TEXT] * 5 + [KEPT, "Aftermark " + TEXT] + [TEXT] * 2) + "\n")
  pdf.save()
  words = pdf_page_words(pdf.output_path)[0]
  after = next(w for w in words if w[4] == "Aftermark")
  kept = next(w for w in words if w[4] == "Keptmark")
  assert after[2] < 105 * MM_TO_PT < kept[0] # the text after it stays left, the block goes right

def waiting_blocks_keep_their_order(floated):
  second = KEPT.replace("Keptmark", "Secondmark")
  spots = floated("\n\n".join([TEXT] * 5 + [KEPT, second] + [TEXT] * 6) + "\n")
  assert len(spots) == 2 and spots[0] < spots[1]

def blocks_stand_where_they_are_without_floats(floated):
  assert floated("\n\n".join([TEXT] * 5 + [KEPT] + [TEXT] * 3) + "\n", floats=False) == []

TALL = "<!-- group wide -->\n\nWidemark " + "words across the page " * 100 + "\n\n<!-- /group -->"

def a_wide_group_missing_its_page_waits_for_the_top_of_the_next(floated):
  # The text before it, balanced, leaves less room than the group takes
  spots = floated("\n\n".join([TEXT] * 9 + [TALL] + [TEXT] * 20) + "\n")
  assert spots[0][0] == 2 and spots[0][2] == 0 # across the top of page 2, before its columns

@needs_pymupdf
def a_wide_group_that_fits_where_it_is_written_stands_there(pdf, floated):
  wide = "<!-- group wide -->\n\nWidemark " + "words across the page " * 10 + "\n\n<!-- /group -->"
  assert floated("\n\n".join([TEXT] * 3 + [wide] + [TEXT] * 20) + "\n") == []
  pdf.save()
  words = pdf_page_words(pdf.output_path)[0]
  mark = next(w for w in words if w[4] == "Widemark")
  assert any(w[1] < mark[1] for w in words if w[4] == "Words") # under the text before it
  assert any(w[1] > mark[3] for w in words if w[4] == "Words") # and the text after it under it

@needs_pymupdf
def a_wide_group_over_a_hole_in_its_columns_waits_for_the_next_page(pdf):
  # A figure of one column takes the top of a column beside a few lines of text:
  # set where written, the group would stand under it, the other column blank above it
  lines = [f"Line {k} of plain text here." for k in range(60)]
  mid = [f"Mid {k} of plain text here." for k in range(3)]
  wide = "<!-- group wide -->\n\nWidemark " + "words across the page " * 10 + "\n\n<!-- /group -->"
  after = [f"After {k} of plain text here." for k in range(70)]
  md = "\n\n".join(["## Start"] + lines + [KEPT] + mid + [wide] + after) + "\n"
  MarkdownRenderer(pdf, MarkdownStyle(columns=2, floats=True)).render(md)
  pdf.save()
  pages = pdf_page_words(pdf.output_path)
  def at(mark:str) -> tuple:
    return next((n, w) for n, words in enumerate(pages) for w in words if w[4] == mark)
  (figure, _), (page, group) = at("Keptmark"), at("Widemark")
  assert page == figure + 1 and group[1] < 25 * MM_TO_PT # across the top of the next page

def a_block_after_a_waiting_wide_group_waits_behind_it(floated):
  # It would fit where it stands, yet the wide group before it waits for the next page
  small = "<!-- group -->\n\nSmallmark title\n\n| A |\n|---|\n| b |\n\n<!-- /group -->"
  spots = floated("\n\n".join([TEXT] * 9 + [TALL, small] + [TEXT] * 20) + "\n")
  assert [page for page, _, _ in spots] == [2, 2] # the wide group first, then the small one

def a_table_a_column_cannot_hold_spans_the_page(pdf):
  table = ("| Name | Kind | Owner | Repository | Status |\n|---|---|---|---|---|\n"
    "| Markdown | engine | someone | md2paper | maintained |\n")
  with warnings.catch_warnings():
    warnings.simplefilter("error", RuntimeWarning) # no word breaks: the table has the page
    style = MarkdownStyle(columns=2, floats=True) # set as a journal sets a wide table
    MarkdownRenderer(pdf, style).render("## Data\n\n" + TEXT + "\n\n" + table)

@needs_pymupdf
def a_table_moves_past_short_columns_to_room_for_its_head(pdf):
  row = "| Tablemark | " + "words that wrap in a narrow cell " * 3 + " | more |\n"
  table = "| Head | Text | End |\n|---|---|---|\n" + row * 4
  pdf.cursor(0, 235)
  pdf.columns(2) # two columns of 22mm, too short for the head and two rows
  MarkdownRenderer(pdf, MarkdownStyle()).render(table)
  pdf.columns(1)
  pdf.save()
  pages = pdf_page_words(pdf.output_path)
  bottom = (297 - 20) * MM_TO_PT
  assert not any(w[3] > bottom + 1 for words in pages for w in words) # nothing past the margin
  assert not any(w[4] == "Head" for w in pages[0]) # the head went on with its rows

@needs_pymupdf
def a_bibliography_entry_taller_than_a_page_flows_on(pdf):
  entry = "A source cited at a length no page can hold in one piece. " * 110
  MarkdownRenderer(pdf, MarkdownStyle()).render(f"Text.[^1]\n\n[^1]: {entry}\n")
  pdf.save()
  pages = pdf_page_words(pdf.output_path)
  bottom = (297 - 20) * MM_TO_PT
  assert len(pages) > 1 and not any(w[3] > bottom + 1 for words in pages for w in words)

SQUEEZED = "| Name | Kind | Owner | Repository | Status |\n|---|---|---|---|---|\n"

@pytest.fixture
def titled():
  """A group setting a figure: a title and a narrow table of `rows` rows."""
  def make(mark:str, rows:int) -> str:
    table = "| A | B |\n|---|---|\n" + "| cell | value |\n" * rows
    return f"<!-- group -->\n\n{mark} title\n\n{table}\n<!-- /group -->"
  return make

@pytest.fixture
def wide_table():
  """A table a column cannot hold, so floating columns set it across the page."""
  def make(mark:str, rows:int=3) -> str:
    return SQUEEZED + f"| {mark} | engine | someone | md2paper | maintained |\n" * rows
  return make

@pytest.fixture
def marks():
  """`(page, word)` of every word of a PDF ending in `mark`, in reading order."""
  def read(path:str) -> list[tuple]:
    return [(n, w[4]) for n, words in enumerate(pdf_page_words(path), 1) for w in words
      if w[4].endswith("mark")]
  return read

@pytest.fixture
def render(pdf):
  """Render markdown in floating columns and save the PDF."""
  def run(md:str, **style):
    with warnings.catch_warnings():
      warnings.simplefilter("ignore")
      MarkdownRenderer(pdf, MarkdownStyle(**(dict(columns=2, floats=True) | style))).render(md)
      pdf.save()
  return run

@needs_pymupdf
def a_group_of_text_stays_where_it_is_written(pdf, render, marks):
  section = "## Keptmark\n\n" + "Words of the kept section. " * 60
  kept = "<!-- group -->\n\n" + section + "\n\n<!-- /group -->"
  render("\n\n".join([TEXT] * 5 + [kept, "Aftermark " + TEXT * 4]) + "\n")
  words = [word for _, word in marks(pdf.output_path)]
  assert words == ["Keptmark", "Aftermark"] # the heading before the text that follows it

@needs_pymupdf
def a_table_in_a_definition_stays_in_it(pdf, render, marks, titled):
  table = "| A | B |\n|---|---|\n" + "| Cellmark | value |\n" * 6
  inner = ("Termmark\n: Opens.\n\n  " + table.replace("\n", "\n  ")
    + "\n\n  Closemark the definition.")
  render("\n\n".join([TEXT] * 7 + [titled("Figmark", 14), inner, "Aftermark " + TEXT]) + "\n")
  words = [word for _, word in marks(pdf.output_path) if word != "Figmark"]
  assert words[0] == "Termmark" and words[-2:] == ["Closemark", "Aftermark"]
  assert words[1:-2] == ["Cellmark"] * 6 # between the term and the end of its definition

@needs_pymupdf
def narrow_blocks_at_the_end_follow_the_wide_ones_before_them(
  pdf, render, marks, titled, wide_table,
):
  md = "\n\n".join(["## Start", TEXT, TEXT, wide_table("Onemark"), wide_table("Twomark"), TEXT,
    titled("Threemark", 4), "Endmark " + TEXT]) + "\n"
  render(md)
  words = list(dict.fromkeys(word for _, word in marks(pdf.output_path) if word != "Endmark"))
  assert words == ["Onemark", "Twomark", "Threemark"]

@needs_pymupdf
def a_table_behind_a_waiting_figure_does_not_wait_for_the_end(pdf, render, marks, titled):
  long = "| A | B |\n|---|---|\n" + "| Longmark | value |\n" * 60 # taller than a column
  figure = titled("Figmark", 24) # misses a column begun, fits a fresh one
  md = "\n\n".join(["## Start"] + [TEXT] * 7 + [figure, long] + [TEXT] * 60
    + ["Endmark " + TEXT]) + "\n"
  render(md)
  found = marks(pdf.output_path)
  first = next(page for page, word in found if word == "Longmark")
  last = next(page for page, word in found if word == "Endmark")
  assert first <= 2 and last > first + 2 # right after the figure, pages before the text ends

@needs_pymupdf
def a_wide_table_taller_than_a_page_keeps_every_row(pdf, render):
  rows = "".join(f"| Row{k}mark | engine | someone | md2paper | maintained |\n" for k in range(75))
  md = "\n\n".join(["## Start", TEXT, TEXT, SQUEEZED + rows] + ["Bodymark " + TEXT] * 30) + "\n"
  render(md)
  pages = pdf_page_words(pdf.output_path)
  drawn = [w[4] for words in pages for w in words if w[4].startswith("Row")]
  assert sorted(drawn) == sorted(f"Row{k}mark" for k in range(75)) # each row once
  for words in pages: # no body text among the rows of the table, none past the right edge
    rows_y = [w[1] for w in words if w[4].startswith("Row")]
    if not rows_y: continue
    assert not any(min(rows_y) < w[1] < max(rows_y) for w in words if w[4] == "Bodymark")
    assert all(w[2] < 200 * MM_TO_PT for w in words)

@needs_pymupdf
def wide_blocks_still_waiting_are_measured_with_the_next_run(pdf, tmp_path):
  from PIL import Image
  Image.new("RGB", (800, 1000), (40, 140, 90)).save(tmp_path / "tall.png")
  body = "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor. " * 5
  one, two = (f"<!-- group wide -->\n\n{mark}.\n\n![](tall.png)\n\n<!-- /group -->"
    for mark in ("One", "Two")) # too tall to share the top of one page
  md = "\n\n".join(["## Start", body, body, body, one, two, body, "<!-- pagebreak -->", "## Next"]
    + [body] * 30) + "\n"
  with warnings.catch_warnings():
    warnings.simplefilter("error", RuntimeWarning) # no "measured on N pages took M"
    MarkdownRenderer(pdf, MarkdownStyle(columns=2, floats=True), str(tmp_path)).render(md)
  pdf.save()
  words = pdf_page_words(pdf.output_path)[-1]
  middle = 105 * MM_TO_PT
  left = max(w[3] for w in words if w[2] < middle)
  right = max(w[3] for w in words if w[0] > middle)
  assert abs(left - right) < 20 * MM_TO_PT # the last page is balanced

@needs_pymupdf
def a_headed_group_with_a_wide_table_goes_across_where_it_is_written(pdf, marks, wide_table):
  section = "<!-- group -->\n\n## Headmark\n\n" + wide_table("Rowmark") + "\n<!-- /group -->"
  md = "\n\n".join(["## Start", TEXT, TEXT, section, "Aftermark " + TEXT]) + "\n"
  with warnings.catch_warnings():
    warnings.simplefilter("error", RuntimeWarning) # across the page, no word breaks in its cells
    MarkdownRenderer(pdf, MarkdownStyle(columns=2, floats=True)).render(md)
  pdf.save()
  words = [word for _, word in marks(pdf.output_path)]
  assert words == ["Headmark"] + ["Rowmark"] * 3 + ["Aftermark"]

def a_page_cannot_turn_while_it_opens(pdf):
  def top(page:PDF, n:int):
    page.cursor(0, page.y + 200)
    page.keep(100) # more than the rest of the page holds
  pdf.on_page_top(top)
  pdf.new_page()
  assert pdf.page_num == 2 and pdf.y == pytest.approx(200)

def a_block_the_queue_sets_cannot_turn_the_page_it_opens(pdf):
  sizes, drawn = {"first": 150, "second": 60}, []
  def draw(name:str):
    drawn.append(name)
    if name == "second": pdf.keep(120) # as a heading keeps three lines its group does not have
    pdf.cursor(0, pdf.y + sizes[name])
  floats = Floats(pdf, sizes.get, draw)
  pdf.columns(2)
  floats.defer_wide("first")
  floats.defer_wide("second")
  with pdf.frames(enter=floats.opened):
    pdf.next_frame()
    pdf.next_frame() # page 2 opens with both across its top
  assert drawn == ["first", "second"] and pdf.page_num == 2
  assert pdf.content_height == pytest.approx(257 - 210) # the columns begin under the two

def a_height_kept_for_a_block_counts_the_gap_above_its_heading(pdf):
  engine = MarkdownRenderer(pdf, MarkdownStyle(columns=2, floats=True))
  tokens = engine.parse("<!-- group wide -->\n\n### Head\n\nBody.\n\n<!-- /group -->\n")
  at_top = engine._block_height(tokens) # first measured with the cursor at the top of the page
  engine._measured = {}
  pdf.cursor(0, 50)
  assert engine._block_height(tokens) == pytest.approx(at_top) # as under another block

@needs_pymupdf
def blocks_left_waiting_stand_after_their_run_before_a_page_break(
  pdf, render, marks, wide_table, titled,
):
  # A wide table waits for the next page top and a figure behind it with it, as the run ends
  md = "\n\n".join(["## Start"] + [TEXT] * 3 + [wide_table("Widemark"), titled("Figmark", 4),
    "Endmark " + TEXT, "<!-- pagebreak -->", "## Nextmark", TEXT]) + "\n"
  render(md)
  page = {word: n for n, word in marks(pdf.output_path)}
  assert (page["Widemark"], page["Figmark"], page["Nextmark"]) == (1, 1, 2) # no page of their own

@needs_pymupdf
def a_chapter_on_a_new_page_leaves_the_page_before_it_balanced(pdf, render):
  render("## Start\n\n" + "\n\n".join([TEXT] * 3) + "\n\n# Chapter\n\n" + TEXT + "\n",
    h1_page_break=True)
  words = pdf_page_words(pdf.output_path)[0]
  middle = pdf.page_width * MM_TO_PT / 2
  assert pdf.page_num == 2 and any(w[0] > middle for w in words) # text in the right column too

@needs_pymupdf
def blocks_left_waiting_stand_before_a_chapter_on_a_new_page(
  pdf, render, marks, wide_table, titled,
):
  md = "\n\n".join(["## Start"] + [TEXT] * 3 + [wide_table("Widemark"), titled("Figmark", 4),
    "Endmark " + TEXT, "# Nextmark", TEXT]) + "\n"
  render(md, h1_page_break=True)
  page = {word: n for n, word in marks(pdf.output_path)}
  assert (page["Widemark"], page["Figmark"], page["Nextmark"]) == (1, 1, 2)

NOTES = "\n".join(f"[^{k}]: Author, **Title {k}**, Journal, 2024, Ref{k}mark" for k in range(4))
CITES = "Citesmark " + " ".join(f"[^{k}]" for k in range(4))

@needs_pymupdf
def a_block_still_waiting_stands_before_the_bibliography(pdf, render, marks, wide_table):
  # The wide table waits for the top of a page the text never turns to before its references
  md = "\n\n".join(["## Start"] + [TEXT] * 3 + [wide_table("Widemark"), CITES, NOTES]) + "\n"
  render(md)
  words = [word for _, word in marks(pdf.output_path)]
  assert words.index("Widemark") < words.index("Ref0mark")

@needs_pymupdf
def a_figure_waiting_for_a_column_stands_before_the_bibliography(pdf, render, marks, titled):
  # The figure misses the rest of its column as the citing paragraph and the references follow
  md = "\n\n".join(["## Start"] + [TEXT] * 3 + [titled("Figmark", 14), CITES, NOTES]) + "\n"
  render(md)
  words = [word for _, word in marks(pdf.output_path)]
  assert words.index("Figmark") < words.index("Ref0mark")

@needs_pymupdf
def a_long_bibliography_fills_the_column_a_waiting_figure_missed(pdf, render, marks, titled):
  # The figure misses the rest of its column, and the references run on for pages
  notes = "\n".join(f"[^{k}]: Author, **Title of the work {k}**, Journal of Things, vol. {k}, "
    f"2024, pp. 1-9, Ref{k:02d}mark" for k in range(60))
  cites = "Citesmark " + " ".join(f"[^{k}]" for k in range(60))
  md = "\n\n".join(["## Start"] + [TEXT] * 6 + [titled("Figmark", 26), cites, notes]) + "\n"
  render(md)
  page = {word: n for n, word in reversed(marks(pdf.output_path))} # where each first stands
  assert page["Ref00mark"] == page["Citesmark"] == 1 # no column left blank for the figure
  assert page["Figmark"] == 2 # at the top of the next page, among the entries

@needs_pymupdf
def a_figure_behind_a_wide_block_is_not_left_after_the_bibliography(
  pdf, render, marks, titled, wide_table,
):
  # The wide table takes the top of the page the references run on to,
  # and the figure behind it misses the room under it
  notes = "\n".join(f"[^{k}]: Author, **Title {k}**, Journal, 2024, Ref{k}mark" for k in range(6))
  cites = "Citesmark " + " ".join(f"[^{k}]" for k in range(6))
  md = "\n\n".join(["## Start"] + [TEXT] * 10
    + [wide_table("Widemark", 20), titled("Figmark", 20), cites, notes]) + "\n"
  render(md)
  words = [word for _, word in marks(pdf.output_path)]
  assert words.index("Figmark") < words.index("Ref5mark") # no page of its own after the last entry

@pytest.fixture
def beside():
  """Words in the other column beside the figure `Figmark` titles, on its page."""
  def read(path:str) -> list[str]:
    page = next(words for words in pdf_page_words(path) if any(w[4] == "Figmark" for w in words))
    head = next(w for w in page if w[4] == "Figmark")
    middle = 105 * MM_TO_PT
    left = head[0] < middle
    bottom = max(w[3] for w in page if (w[0] < middle) == left and w[4] == "value")
    return [w[4] for w in page if (w[0] < middle) != left and w[3] > head[1] and w[1] < bottom]
  return read

@pytest.fixture
def cited():
  """A paragraph citing `count` entries, and the entries, `Ref0mark` on."""
  def make(count:int) -> list[str]:
    notes = "\n".join(f"[^{k}]: Author, **Title {k}**, Journal, 2024, Ref{k}mark"
      for k in range(count))
    return ["Citesmark " + " ".join(f"[^{k}]" for k in range(count)), notes]
  return make

@needs_pymupdf
def a_figure_before_a_short_bibliography_has_its_entries_beside_it(
  pdf, render, marks, titled, cited, beside,
):
  # The figure misses the rest of the column the text ends in, which the three entries would fill
  render("\n\n".join(["## Start"] + [TEXT] * 7 + [titled("Figmark", 20)] + cited(3)) + "\n")
  words = [word for _, word in marks(pdf.output_path)]
  assert words.index("Figmark") < words.index("Ref2mark")
  assert "Ref0mark" in beside(pdf.output_path) # no column left blank beside it

@needs_pymupdf
def a_figure_behind_a_wide_block_opens_the_bibliography_columns(
  pdf, render, titled, wide_table, cited, beside,
):
  # The bibliography parts from the text for the wide table, the figure behind it first in its run
  md = "\n\n".join(["## Start"] + [TEXT] * 8
    + [wide_table("Widemark", 20), titled("Figmark", 20)] + cited(6)) + "\n"
  render(md)
  assert any(word.startswith("Ref") for word in beside(pdf.output_path))

@needs_pymupdf
def a_table_waiting_last_parts_by_its_rows_in_columns_of_its_own(pdf, render, wide_table):
  # Set before the entries it would stand in one column: in three columns that took a page more
  table = "| A | B |\n|---|---|\n" + "| Rowmark | value |\n" * 8
  md = "\n\n".join(["## Start"] + [TEXT] * 7
    + [wide_table("Widemark", 20), table, CITES, NOTES]) + "\n"
  render(md)
  words = pdf_page_words(pdf.output_path)[-1]
  foot = max(w[3] for w in words if w[4] == "Rowmark")
  assert next(w[1] for w in words if w[4] == "Ref0mark") > foot # the entries under both its parts

@needs_pymupdf
def a_figure_waiting_as_a_titled_bibliography_begins_stands_before_its_title(
  pdf, render, marks, titled, cited,
):
  # The document titles its bibliography itself, with a heading right above the entries
  cites, notes = cited(3)
  render("\n\n".join(["## Start"] + [TEXT] * 8
    + [titled("Figmark", 20), cites, "## Referencesmark", notes]) + "\n")
  words = [word for _, word in marks(pdf.output_path)]
  assert words.index("Figmark") < words.index("Referencesmark") < words.index("Ref0mark")

def the_bibliography_stays_in_the_run_of_its_text_when_nothing_waits(pdf, monkeypatch):
  md = "\n\n".join(["## Start"] + [TEXT] * 3 + [CITES, NOTES]) + "\n"
  runs = []
  run = MarkdownRenderer._render_run
  def recorded(self, tokens, below, *balanced):
    if self.pdf is pdf: runs.append(len(tokens))
    return run(self, tokens, below, *balanced)
  monkeypatch.setattr(MarkdownRenderer, "_render_run", recorded)
  MarkdownRenderer(pdf, MarkdownStyle(columns=2, floats=True)).render(md)
  assert len(runs) == 1 # one run of columns, balanced with its references

def columns_overflowing_a_frame_warn_once(pdf):
  text = "Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 6
  md = "## Start\n\n" + "\n\n".join([text] * 14) + "\n"
  with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    with pdf.frame(0, 20, pdf.content_width, 140): # a slide's body holds one page
      MarkdownRenderer(pdf, MarkdownStyle(columns=2)).render(md)
  messages = [str(w.message) for w in caught]
  assert len(messages) == 1 and "frame holds" in messages[0] # no measure blamed on `headroom`

#------------------------------------------------------------------------------------- Floats queue

@pytest.fixture
def queue(pdf):
  """A queue whose blocks are names taking the room `sizes` gives them, and the names drawn."""
  sizes, drawn = {}, []
  def draw(name:str):
    drawn.append((name, pdf.page_num, pdf.column_index))
    left = sizes[name]
    while left > pdf.content_height - pdf.y + 0.01: # runs on over frames, as a long table does
      left -= pdf.content_height - pdf.y
      pdf.next_frame()
    pdf.cursor(0, pdf.y + left)
  return Floats(pdf, sizes.get, draw), sizes, drawn

def a_block_that_fits_here_waits_for_nothing(pdf, queue):
  floats, sizes, _ = queue
  sizes["figure"] = 50
  assert not floats.defer("figure")

def a_block_missing_the_frame_takes_the_top_of_the_next(pdf, queue):
  floats, sizes, drawn = queue
  sizes["figure"] = 120
  pdf.columns(2)
  pdf.cursor(0, 200)
  assert floats.defer("figure")
  with pdf.frames(enter=floats.opened):
    pdf.next_frame()
  assert drawn == [("figure", 1, 1)] and pdf.y == pytest.approx(120)

def no_block_comes_out_before_one_waiting_ahead_of_it(pdf, queue):
  floats, sizes, drawn = queue
  sizes.update(first=120, wide=60, second=40)
  pdf.columns(2)
  pdf.cursor(0, 200)
  with pdf.frames(enter=floats.opened):
    assert floats.defer("first")
    floats.defer_wide("wide")
    assert floats.defer("second") # it would fit, yet it came after the two waiting
    pdf.next_frame() # the right column takes `first`, `second` waits for `wide`
    pdf.next_frame() # page 2 opens with `wide` across its top, then `second`
  assert [(name, page) for name, page, _ in drawn] == [("first", 1), ("wide", 2), ("second", 2)]
  assert drawn[0][2] == 1 and drawn[2][2] == 0 # columns of their own, `wide` across the page

def blocks_still_waiting_follow_the_flow_in_order(pdf, queue):
  floats, sizes, drawn = queue
  sizes.update(first=120, second=120)
  pdf.cursor(0, 200)
  floats.defer("first")
  floats.defer("second")
  floats.flush()
  assert [name for name, _, _ in drawn] == ["first", "second"]

def blocks_behind_a_waiting_wide_one_are_handed_back_in_order(pdf, queue):
  floats, sizes, drawn = queue
  sizes.update(first=40, wide=60, narrow=40)
  pdf.columns(2)
  pdf.cursor(0, 230)
  with pdf.frames(enter=floats.opened):
    assert floats.defer("first") # it misses the rest of this column
    floats.defer_wide("wide")
    assert floats.defer("narrow") # it fits here, yet the wide block before it waits
    floats.flush() # the flow ends on this page: `first` follows the text
  assert [name for name, _, _ in drawn] == ["first"]
  assert floats.take() == [("wide", True), ("narrow", False)] and not floats.take()

def a_block_taller_than_any_frame_comes_out_at_its_turn(pdf, queue):
  floats, sizes, drawn = queue
  sizes.update(first=120, tall=400, last=30)
  pdf.columns(2)
  pdf.cursor(0, 200)
  with pdf.frames(enter=floats.opened):
    assert floats.defer("first")
    assert floats.defer("tall") # no frame holds it whole, and it keeps its place in line
    assert floats.defer("last")
    pdf.next_frame() # the right column takes `first`
    pdf.next_frame() # page 2 takes `tall`, which starts at its top and runs on
    assert [name for name, _, _ in drawn] == ["first", "tall"]
  floats.flush()
  assert [name for name, _, _ in drawn] == ["first", "tall", "last"]

def a_column_top_takes_one_block_waiting(pdf, queue):
  floats, sizes, drawn = queue
  sizes.update(first=60, second=60)
  pdf.columns(2)
  pdf.cursor(0, 220)
  with pdf.frames(enter=floats.opened):
    assert floats.defer("first") and floats.defer("second") # both miss the rest of this column
    pdf.next_frame() # the right column takes `first`, the text going on under it
    pdf.next_frame() # page 2 takes `second`
  assert drawn == [("first", 1, 1), ("second", 2, 0)]

def keep_moves_on_from_under_a_wide_block_at_the_top_of_a_page(pdf, queue):
  floats, sizes, _ = queue
  sizes["wide"] = 150
  pdf.columns(2)
  floats.defer_wide("wide")
  with pdf.frames(enter=floats.opened):
    pdf.next_frame()
    pdf.next_frame() # page 2: the wide block, then columns 107mm tall
    assert pdf.page_num == 2 and pdf.content_height == pytest.approx(107)
    pdf.keep(120) # misses these columns, fits a fresh page
  assert pdf.page_num == 3
