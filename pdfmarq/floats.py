# pdfmarq/floats.py

"""
Blocks that wait for the top of a frame, as a journal sets its figures and tables.

A block that misses the rest of a column waits for the top of the next one,
while the text goes on filling this column, and a wide one waits for the top of the next page,
above its columns.
A column's top takes one block waiting, so those waiting spread over the columns that follow.
The blocks keep their order: none comes out while one before it still waits, of either kind.
The caller measures and draws its own blocks, and sets those still waiting where its flow ends,
so the markdown engine and a package drawing parts of its own share one queue.
"""
from typing import Callable

#------------------------------------------------------------------------------------------- Floats

class Floats:
  """
  The blocks of one flow on `pdf` waiting for the top of a frame.
  `height(block)` gives the room a block takes where it would stand,
  and `draw(block)` sets it at the cursor.
  The flow runs inside `pdf.frames(enter=floats.opened)`,
  so the blocks waiting go to the top of each frame as it opens.
  """
  def __init__(self, pdf, height:Callable, draw:Callable):
    self.pdf, self.height, self.draw = pdf, height, draw
    self.narrow: list[tuple] = [] # `(turn, block)` waiting for the top of a column
    self.wide: list[tuple] = [] # `(turn, block)` waiting for the top of a page
    self._turn = 0 # the place in line the next block waiting gets
    self._setting = False # a block is being set: none other is placed until it is done
    self._hooked = False # whether `_page_opened` runs on each new page

  def defer(self, block) -> bool:
    """
    Whether `block` waits for the top of a frame:
    behind blocks already waiting, so their order holds,
    or when it misses the rest of this frame but a fresh one holds it.
    """
    if not self.narrow and not self.wide:
      height = self.height(block)
      if height <= self.pdf.content_height - self.pdf.y or height > self.pdf.fresh_height:
        return False
    self.narrow.append(self._queued(block))
    return True

  def defer_wide(self, block):
    """`block` waits for the top of the next page, above its columns: it must fit a page."""
    self.wide.append(self._queued(block))
    if not self._hooked:
      self.pdf.on_page_top(self._page_opened)
      self._hooked = True

  def opened(self, pdf):
    """
    A new frame: the first block waiting, when its turn has come, at its top.
    One block a frame, so the text goes on between those waiting instead of under a pile of them.
    One that misses this frame but fits a fresh one waits on,
    and one no frame holds starts here, running on as it would where it was written.
    """
    if self._setting or not self._next(self.narrow, self.wide): return
    height = self.height(self.narrow[0][1])
    if pdf.content_height - pdf.y < height <= pdf.fresh_height: return
    self._set(self.narrow)

  def flush(self):
    """
    Where the flow ends, the narrow blocks whose turn it is, following the text.
    Those behind a wide block still waiting wait on with it, for `take()`.
    """
    while self._next(self.narrow, self.wide): self._set(self.narrow)

  def take(self) -> list[tuple]:
    """
    `(block, wide)` of every block still waiting, in order, the queue left empty,
    for the caller to set where its columns end.
    """
    waiting = sorted([(turn, block, False) for turn, block in self.narrow]
      + [(turn, block, True) for turn, block in self.wide], key=lambda queued: queued[0])
    self.narrow, self.wide = [], []
    return [(block, wide) for _, block, wide in waiting]

  def _queued(self, block) -> tuple:
    """`block` with its place in line."""
    self._turn += 1
    return self._turn, block

  def _set(self, line:list):
    """Draw the first block of `line`, no other placed while it is being set."""
    self._setting = True
    try:
      self.draw(line.pop(0)[1])
    finally:
      self._setting = False

  def _page_opened(self, pdf, n:int):
    """A new page, still the full width: the wide blocks waiting whose turn it is that fit."""
    top = pdf.y
    while not self._setting and self._next(self.wide, self.narrow):
      if pdf.y > top and self.height(self.wide[0][1]) > pdf.content_height - pdf.y: break
      self._set(self.wide)

  @staticmethod
  def _next(line:list, other:list) -> bool:
    """Whether the first of `line` waits for nothing in `other` that came before it."""
    return bool(line) and (not other or line[0][0] < other[0][0])
