Ogarnięte. Mówisz że świetny i zajebisty — wiele rzeczy jest, ale jest też kilka rzeczy które kuleją. Idę po porządku, od najgrubszych do najmniejszych.



\## Architektura



\*\*`MarkdownRenderer` dziedziczy z 10 mixinów.\*\* To god-class przebrana za inheritance. Każdy mixin używa `self.pdf`, `self.style`, `self.\_indent\_mm`, `self.\_list\_depth`, `self.\_reset\_stroke` z `markdown.py`, `self.\_inline\_to\_segments` z innego mixina itd. Ukryte coupling, brak ownership, IDE/typecheckery się duszą. Albo zrób kompozycję (`renderer.blocks.render(...)`), albo zlej w jedną klasę i przestań udawać że to są niezależne moduły.



\*\*`NumberedCanvas` zapisuje cały stan strony przez `self.\_\_dict\_\_.copy()`.\*\* Działa, ale to fragile jak diabli — pamięć rośnie liniowo z liczbą stron (każda strona = pełen snapshot canvas'a), a jakakolwiek nowa wersja reportlaba która doda nested mutable state copy-by-reference rozjebie to po cichu. Plus replay zabija wszelkie streamy. Akceptowalne dla 50 stron, dla 500-stronicowego raportu — bida.



\*\*`MarkdownStyle` ma 60+ pól.\*\* Body, banner, callout, table, link, math, mini-banner, page numbering — wszystko jednym workiem. Po rok łamane jak edytujesz: nie wiesz co od czego zależy. Rozjeb na `BodyStyle / BannerStyle / TableStyle / LinkStyle` + komponuj.



\*\*Brak testów.\*\* W zipie nic. Dla biblioteki z deferred bookmarks, lookaheadem, page-break heuristics, NumberedCanvasem — to gra w ruletkę przy każdym update reportlaba. Choćby smoke testy że "renderuje markdown i nie wybucha".



\## Bugi/risky kawałki



\*\*`fonts.is\_builtin`:\*\*

```python

if family == "Times-Roman": return True

```

Łapie wszystkie mody. Dla `family="Times-Roman", mode="Bold"` → `builtin\_name` zwraca `"Times-Roman"` (bo mapy nie ma) i dostajesz Regular zamiast Bolda. Cicha pomyłka.



\*\*`TextMetrics.box\_fit` rekurencyjnie autoscale:\*\*

```python

return self.box\_fit(text, width, height, family, mode, size - autoscale, ...)

```

`size=12, autoscale=0.1` → \~120 ramek stosu. `autoscale=0.001` → 12000. Zrób pętlą.



\*\*`inline.\_wrap`\*\* nie sygnalizuje overflow gdy słowo szersze niż `width\_pt` — leci w prawo poza obszar bez ostrzeżenia. Renderer nie ma jak wiedzieć. `box\_fit` w `text.py` ma flagę `overflow`, `\_wrap` nie. Niespójność.



\*\*`Style.color` shape jest inconsistent.\*\* `with\_defaults` zwraca 3-tuple `(0,0,0)`, ale `PDF.color()` zapisuje 4-tuple `(r,g,b,a)`. Każdy `\_style.color` może być 3- albo 4-tuple zależnie kiedy ostatni raz dotykany.



\*\*`PDF.compress()` połyka błędy:\*\*

```python

except (subprocess.CalledProcessError, FileNotFoundError):

&#x20; if Path(temp).exists():

&#x20;   Path(temp).unlink()

```

Brak `gs` w systemie? Cicho, plik niezmieniony. User myśli że skompresowane. Minimum: `return bool` albo flaga `raise\_on\_error`.



\*\*`utils.parse\_color`\*\* nie waliduje hexa — `"zzzzzz"` rzuca `ValueError: invalid literal for int()` z głębi. Powinien rzucić swoim własnym z czytelnym message.



\*\*`parse\_margin`\*\* dla tupli z 4 elementów po cichu wywala 4-ty. CSS używa `top/right/bot/left` — ktoś z webu wepnie 4-tuplę i będzie się drapał czemu jeden margin zniknął.



\*\*`configure\_math\_fonts` w `MarkdownRenderer.\_\_init\_\_`\*\* mutuje globalny stan matplotliba (rcParams). Dwa renderery z różnym `math\_fontset` w tym samym procesie → drugi wygrywa, pierwszy ma broken math przy następnym renderze. Race condition.



\*\*`\_render\_tokens` zakłada że `paragraph\_open/inline/close` = 3 tokeny\*\* i robi `i += 3`. Plugin markdown-it który wstrzyknie attr token rozjebie indexing. Zrób `\_find\_close` jak gdzie indziej.



\## Trupy w szafie



\- `graphics.draw\_ellipse` — nikt nie woła, dead.

\- `graphics.set\_fill\_color/set\_stroke\_color/set\_fill\_grey` — duplikat tego co jest w `core.PDF`.

\- `tables.prepare\_table` legacy helper — wrap nad `TableBuilder.build`, jeden caller w `core.\_draw\_table`. Wyrzuć albo `TableBuilder` albo to.

\- `Cursor.copy()` ręcznie pisany choć dataclass ma `replace(self)`.

\- `Cursor.advance\_x` dla `Align.CENTER` po cichu nic nie robi.



\## Drobne



\- `core.py` ma sekcje typu `# Page setup`, `# Canvas`, `# Components` zamiast `#---` separatorów z twojego stylu. Niespójne z resztą.

\- Magic numbers w `inline.render\_rich`: `1.35`, `0.32`, `0.25`, `0.85`, `2.5`, `1.2` — komentarze są przy niektórych, większość bez. Wyciągnij do nazwanych stałych albo pól `Style`.

\- `\_\_dependencies\_\_ = \[..., "Pillow", "svglib"]` — `Pillow` ok jako pip-name, ale ImportError leci z `from PIL import` i user przy debugu się gubi. Daj komentarz albo `\_\_import\_name\_\_` mapping.



\## Co jest świetne (żeby było jasne)



\- Fluent API `PDF` — czytelne, przewidywalne.

\- Split `pdfmarq` vs `pdfmarq\[md]` z `\_\_extras\_\_` — czysto rozdzielone.

\- `RichSegment` jako jeden model dla bold/italic/code/math/link — dobra abstrakcja.

\- Deferred bookmarks pattern w `NumberedCanvas` — rozwiązuje realny problem reportlaba.

\- Lang presets — prostota, łatwo dodać kolejny język.



\## Priorytety jakbym to porządkował



1\. Testy (choćby 5 smoke testów)

2\. Fix `is\_builtin` dla `Times-Roman+Bold`

3\. `box\_fit` → pętla

4\. `\_wrap` → flaga overflow

5\. `Style.color` — wymuś 4-tuple albo 3-tuple wszędzie

6\. Rozjeb `MarkdownStyle` na sub-dataklasy



Reszta to cleanup który możesz robić bezboleśnie.




W TABELI troszke zmnieszać czcionkę wzgledem całosci dokumenty!