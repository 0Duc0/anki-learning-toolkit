# Simple Search Assistant

**Word search panel** (top of the Browser sidebar)
- `word_search_shortcut` (default `Ctrl+Shift+W`, Cmd+Shift+W on a Mac): jumps to the word box. Leave empty for none.
- `word_fields`: fields that hold the word itself. Exact / Contains / Related search only these.
- `meaning_fields`: fields that hold a short meaning or translation (Meaning mode).
  Field names are compared without case; names a note type does not have are skipped.
- `word_mode`, `word_deck`, `word_cards`, `word_panel_open` are remembered automatically.

**Cards ▾ button and Search Assistant dialog**
- `quick_combine` (true/false): a one-click card filter narrows what the Browser shows (true) or searches all decks (false).
- `shortcut` opens the Search Assistant dialog, `quick_shortcut` opens the Cards ▾ menu. Empty = none.
- `last_field_choice`, `last_match` are remembered automatically.
- `search_bar_field`: default field for Anki's own search bar, set with the "Search bar: … ▾" button next to
  the search bar (`@word` = the word fields, `@meaning` = meaning fields, or one field name such as `Traditional`).
  Plain words typed there then search only that field; searches with Anki syntax (`deck:`, `field:`, `OR` …)
  are left alone. Empty = off (Anki's normal all-fields search).

Restart Anki after changing a shortcut.
