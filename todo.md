# Todo: dwa łamy natywnie w silniku

Odłożone 10.11.2026: przemyśleć, nie robić teraz.

## Cel

**Tryb dwułamowy ma być funkcją silnika markdown, a nie czymś, co każdy pakiet dokumentów składa sam z klocków rdzenia.**
Dokument prosi o łamy polem stylu, a resztę robi silnik: dzieli tekst na łamy, wyrównuje je na ostatniej stronie i rozciąga `<!-- group wide -->` na całą szerokość.
Działa to tak samo w `paper`, `legal`, pubmarq i md2paper, w PDF i w DOCX.

Pakietom zostaje tylko to, co ich własne.
W `legal` to miejsce, od którego łamy biegną, i koniec dokumentu pod nimi, a w pubmarq wygląd czasopisma.

## Stan dziś

Rdzeń to `PDF` i `DOCX`, silnik to `pdfmarq.md` i `docmarq.md`.
Łamy otwiera rdzeń, a tryb dwułamowy składają z nich pakiety dokumentów, każdy po swojemu.
Silnik stoi między nimi i tylko płynie przez łamy, które ktoś mu otworzył.

| Warstwa | Dwa łamy | Wyrównanie w PDF | `<!-- group wide -->` |
| --- | --- | --- | --- |
| rdzeń | `pdf.columns()`, `doc.columns()` | limit `height` podaje wywołujący | nie dotyczy |
| silnik | brak pola stylu | brak | zna składnię, składa jak zwykłą grupę |
| `paper` | brak | brak | zwykła grupa |
| `legal` | `columns=2`, od pierwszego `##` | własne, `legal.measure` | zwykła grupa |
| pubmarq | według czasopisma | własne, `balance()` | na całą szerokość |

Skutki:

- `paper`, a z nim md2paper, nie złoży dwułamowego dokumentu.
- Wyrównywanie łamów próbnym renderem jest napisane dwa razy.
  `pdfmarq.legal.measure` (`Probe`, `balanced_height`, `balanced_pages`) zaczyna od równego podziału i rośnie krokiem.
  `balance()` w pubmarq szuka limitu połowieniem przedziału i liczy się z pierwszą stroną pod tytułem oraz z grupami na górze stron.
- Grupę na całą szerokość ma tylko pubmarq.

W DOCX łamy wyrównuje sam Word, na końcu sekcji ciągłej, którą otwiera `doc.columns()`.
Brakuje tam więc tylko pola stylu i grupy na całą szerokość.

Wersje językowe obok siebie w `legal` to inny układ, z wierszami równanymi między łamami, i nie należą do tego zadania.

## Do przemyślenia

- Jak dokument prosi o łamy: polem stylu, bo opcje to wygląd, a frontmatter to treść.
  `LegalStyle` ma już `columns` i `column_gap`, więc mogą zejść do `MarkdownStyle`.
- Jedno wyrównanie ostatniej strony w PDF zamiast dwóch, na próbnym renderze silnika.
- `<!-- group wide -->` w miejscu, jak sekcja w Wordzie: łamy nad grupą wyrównane, grupa na całą szerokość, łamy dalej pod nią.
- Zasada czasopisma, czyli szeroki rysunek na górze następnej strony: zostaje w pubmarq albo staje się opcją.
  Kolejność rysunków jak w LaTeX, przez kolejkę bloków pływających.

## Zasady

- Bliźniaki: te same pola i nazwy w pdfmarq i docmarq, żeby md2paper i pakiety przechodziły z PDF na DOCX zmianą importu.
- Bez nowej składni.
- Warstwy rdzeń ← silnik ← dokumenty.
- Dowód porównaniem renderów przed zmianą i po niej.
