# Deck Progress

Named progress counters below the deck list's heatmap. Anki Desktop 25.02 or
later; tested with the installed Anki 25.09.4 / Python 3.13 / Qt 6.9 APIs.

## Set up

1. In Anki, choose **Tools → Add-ons → Install from file…** and select
   `Deck_Progress_v1.0.0.ankiaddon`. Restart Anki.
2. Under the heatmap, click **Add your first counter**. You can also use
   **Tools → Learning Toolkit → Deck Progress…** or the add-on's **Config** button.
3. Enter a display name, such as **Japanese**, then click **Choose decks…**.
   Search and check one or more source decks. Click **Save**.
4. Use **＋ Add** for additional counters. Click any counter on the deck list to
   edit it. **Move up/down** changes the display order.

No decks are selected automatically. You control what each number represents.
Counters can track any subject, not only languages.

## Stage Shifter examples

- Choose `Language::Japanese::a. Frieren`, name it **Japanese**, and keep
  **Only a. stages** off: the chosen deck and optionally its subdecks are counted.
- Alternatively choose the Japanese parent, keep **Include subdecks** on and turn
  on **Only a. stages within this selection**. This combines all a. stages
  beneath that selection and discovers new ones automatically.
- Both `a. Frieren` and `a.Frieren` are recognized. The selection does not depend
  on the character's name or on the Stage Shifter's configured start/end letters.
- Counts refresh when you return to the deck list and after moves, undo, sync,
  and collection operations while on that screen. The counter does not run
  background counter queries during reviews; explicitly opening Settings can
  still request the current deck list. It never moves cards itself.

## What the number means

- **Studied cards:** selected cards whose current Anki answer count (`reps`) is
  greater than zero. New, unanswered cards do not count, even in an a. stage.
  A card's number of reviews does not multiply its contribution: it counts once.
- **Studied words (notes):** distinct Anki notes with at least one studied card
  in the selected decks. This is not a promise that every sibling card has been
  learned, nor a linguistic count of unique dictionary words.
- **Cards + words:** cards as the main number, note count underneath.
- **Show selected total:** adds the total selected cards/notes beside the
  studied count. The daily new-card limit does not cap these totals.
- **Suspended cards:** included by default if they have been studied. You can
  exclude them per counter. Buried cards retain their studied status.
- Filtered-deck cards are attributed to their original/home deck (`odid`).
- A deck rename preserves its counter because selections store stable deck IDs.
  Deleted decks produce a notice, not a silent replacement by a similarly named
  deck. Select their replacement in Settings.
- Overlapping parent/child selections are counted once per counter. Notes split
  between several selected decks also count once. Separate counters remain
  independent; their values should not be summed if their sources overlap.
- Resetting a card's progress resets its `reps`, so it leaves the studied count
  until it is answered again. This is current progress, not a lifetime reviewlog
  audit or a count of mastered words.

## Compatibility and data handling

- The panel is added after Review Heatmap's whole module, including its streak
  summary, and above Anki's separate bottom navigation. Without Heatmap it is
  placed after Anki's normal studied-today summary.
- It does not replace the deck list, modify Words Left's columns, or touch Study
  Session Clock's status bar. It does not import or modify Stage Shifter.
- Collection access is limited to Anki's serialized **QueryOp**, deck metadata
  reads, and parameterized **SELECT** queries. It does not open a second
  collection connection and has no save, scheduling, backup, recovery, sync,
  export, delete, or database-write feature.
- Explicitly saving settings writes only this add-on's JSON configuration via
  Anki's add-on manager. Settings are separated by Anki profile name and are
  local to this desktop installation; they do not automatically sync to phones.
- Closing a profile or a temporary full-sync/import/export close invalidates
  pending callbacks. Read errors show an unavailable state, without repeated
  error popups or invented zero counts.
- Home-screen replacements that remove both standard stats and Heatmap anchors
  may not show the panel. The Tools settings entry still works. Only desktop
  Anki/Qt was tested; mobile apps do not install desktop add-ons.

## Development

Source: `anki_addons/deck_progress`. Test fixture databases are synthetic and
temporary. No user collection or installed add-on is used for testing.

```sh
QT_QPA_PLATFORM=offscreen /path/to/Anki/python -m unittest discover \
  -s tests/deck_progress -p 'test_*.py' -v
QT_QPA_PLATFORM=offscreen /path/to/Anki/python tests/deck_progress/make_preview.py
node tests/deck_progress/check_web.mjs output/Deck_Progress_2026-11-19/preview-fixtures.json
python scripts/package_deck_progress.py
```
