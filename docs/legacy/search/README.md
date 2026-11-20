# Simple Search Assistant 3.2

A read-only search helper for Anki's Browser. Nothing in your cards, notes,
scheduling or review history is ever modified.

## Default field for the normal search bar (3.1, own button since 3.2)
Next to Anki's search bar there is a button **Search bar: all fields ▾**. Pick what plain words typed
in the search bar should look in: all fields (Anki's normal search), the word itself, the meaning, or
one field such as Traditional. The button is highlighted and shows the field while a default is on;
the current search re-runs at once. Anything with Anki search syntax (`deck:`, `Simplified:…`, `OR`,
`-`, `*`, `_`) still works exactly as before. The Search Assistant dialog keeps your last "Look in"
choice, even when a note is selected.

## Word search panel (new in 3.0)
At the top of the Browser sidebar (Cmd/Ctrl+Shift+W jumps there). Type a word, press Enter:

| Button | Finds | Example |
|---|---|---|
| Exact | only that word | 你 → 你 |
| Contains | words containing it (whole syllables for Vietnamese) | 你 → 你好, 你们 · cứ → cứ việc, not cứu |
| Related | words sharing a character or syllable | 你好 → 好人, 你们 · việc làm → làm việc |
| Meaning | the meaning / translation, whole words | eat → 吃, 食べる, ăn (not great) |
| Everywhere | every field incl. examples (the old broad search) | |

Exact/Contains/Related only look at the word fields (Simplified, Traditional, Word,
Reading, Vietnamese, Zeichen …), never at examples or long definitions – that is
what kept pulling in unrelated notes. "In:" limits the search to a deck such as
中文, "Cards:" adds New / Old / Due … Clicking another button or deck re-runs the
search at once. Everything is remembered. Right-click a note → Search Assistant →
"Words containing …" / "Related words".

## Search Assistant dialog
"Search in" (deck) now comes first, and "Look in" only lists the fields of note
types in those decks, grouped by note type, with "The word itself" (default),
"Meaning / translation" and "All fields" at the top. Two new match types: "Contains
the word" and "Shares a character or syllable". The dialog scrolls instead of
squeezing when space runs out.

## Earlier
- 2.0: Cards ▾ one-click filters (New, Old, Due today, …), search without text.
- Right-click "Find exact" now uses the word field (e.g. Word, not EntryID).
