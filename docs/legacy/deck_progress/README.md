# Deck Progress

Named progress counters below the deck list's heatmap. Requires Anki Desktop
25.02 or later.

## Set up

1. In Anki, choose **Tools → Add-ons → Install from file…** and select
   `Deck_Progress_v1.3.0.ankiaddon`. Restart Anki. This updates the existing Deck
   Progress add-on and keeps your counters.
2. Under the heatmap, click **Add your first counter**. You can also use
   **Tools → Learning Toolkit → Deck Progress…** or the add-on's **Config** button.
3. On **Counter**, enter a name, such as **Japanese**, and click **Choose decks…**.
   Search and check one or more source decks. Choose **Cards**, **Notes**, or
   **Cards and notes** and set **Card states**. Click **Save**.
4. Open **Progress** to turn on **Show selected total**, **Show progress bar and
   percentage**, or both. Use **Choose goal decks…** to add decks with material
   you plan to learn. Set **Goal deck states** to filter those additional decks.
5. Use **Add** for additional counters. The sliders button next to **Deck
   progress** opens settings. Clicking a counter opens its settings directly.
   **Move up/down** changes the display order.

No decks are selected automatically. You control what each number represents.
Counters can track any subject, not only languages.

## Stage Shifter examples

- Choose `Language::Japanese::a. Frieren`, name it **Japanese**, and keep
  **Only a. stages** off: the chosen deck and optionally its subdecks are counted.
- Alternatively choose the Japanese parent, keep **Include subdecks** on and turn
  on **Only a. stages in counter decks**. This combines all a. stages
  beneath that selection and discovers new ones automatically.
- Both `a. Frieren` and `a.Frieren` are recognized. The selection does not depend
  on the character's name or on the Stage Shifter's configured start/end letters.
- Counts refresh when you return to the deck list and after moves, undo, sync,
  and collection operations while on that screen. The counter does not run
  background counter queries during reviews; explicitly opening Settings can
  still request the current deck list. It never moves cards itself.

## What the number means

- **Card states** defaults to **Answered at least once**, which uses the card's
  current Anki answer count (`reps > 0`). Choose **All states** to count every
  eligible card, or select any combination of **New**, **Learning**,
  **Relearning**, **Young review** (interval under 21 days), and **Mature
  review** (interval of at least 21 days). Select both review groups to count
  all cards in the review state.
- A note counts once when any of its selected cards matches the filter. A note
  can qualify in different counters if its cards are in different states.
  **Introduced** is the default note label for the answered filter. Set a
  **Card label** or **Note label** to use your own wording.
- With **Require every card of a note to match**, a note needs a matching card
  in the counter decks and every eligible sibling must match, including siblings
  in other decks. For fully learned notes, select **Young review** and **Mature
  review**, enable the note option, and turn off **Include suspended cards** to
  ignore suspended siblings.
- **Show selected total** displays the counter count over the goal total.
  **Show progress bar and percentage** displays the same ratio visually. The
  goal total includes all eligible cards from the counter decks and matching
  cards from additional goal decks. The note matching rule applies to the
  counter count. For example, with **New** as the goal deck
  filter, the extra contribution changes as cards enter or leave the New state.
  The daily new-card limit does not cap the goal.
- **Include subdecks**, **Include suspended cards**, and **Include buried
  cards** apply to both sets of decks. The **Only a. stages** filter applies to
  counter decks. Suspended and buried cards are included by default.
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
  may not show the panel. The Tools settings entry still works.
