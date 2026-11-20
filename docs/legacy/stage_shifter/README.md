# Card Stage Shifter

Detects direct sibling decks named `a.`, `b.`, `c.`, and so on, then moves a
frozen card selection exactly one stage.

The guided dialog clearly separates the route from the card filters. A live route
summary explains every one-step move and identifies the endpoint that will not
move. You can choose direction, start/end stage, card states, suspended cards,
and an optional maximum per source stage. The maximum can be measured in cards
or notes. A note limit keeps all matching sibling cards in the same source stage
together, so a note is never partially selected merely because the cap was hit.

The safe default is New cards only, suspended cards excluded, a maximum of 100
cards per source stage, from `e.` through `a.`. A preview lists every move before confirmation. No card or note is deleted,
scheduling data is not reset, and the complete shift is one Undo operation.

The final preview shows exact source, destination, note, and card counts. The
confirmed selection is frozen and validated immediately before it is applied;
if anything changed in the meantime, nothing moves and a new preview is required.
Open it from `Tools` → `Learning Toolkit` → `Card Organization` →
`Card Stage Shifter…` or the gear menu of a compatible parent deck.

## Even mode (2.5)

Tick **Even** to refill every stage to the same number of notes (20 by default)
instead of moving a fixed amount out of each stage. The not-started notes of
`a.` through the chosen source stage keep their queue order (stage by stage, then
card position) and are cut into blocks: `a.` gets the first block, `b.` the next,
and so on; the last block holds the remainder and the stages behind it are left
empty. Short stages are topped up from the ones behind them and over-full stages
hand their extras on, so the order never changes. A note can move more than one
stage when several stages are short. Running Even again moves nothing.

Even works toward `a.` with the card states you choose (New, Learning/Relearning, Review, optionally suspended) and replaces the per-stage limit. All
cards of a note move together. A note whose New cards sit in more than one stage
is left where it is and listed in the preview. If the chosen stages hold more
notes than they have room for, the last stage keeps the extra and the preview
says so. The preview shows every stage before and after, the apply step checks
the result and undoes itself if the numbers do not match, and the whole shift is
one Undo.

Version 2.4 rejects closed or changed collections, missing/renamed stage decks,
filtered cards, unavailable undo APIs, and storage with less than 1 GiB free.
If one stage fails or verification fails, the whole shift is automatically
undone while Anki's undo state is available. If storage errors prevent rollback,
the error explicitly tells you to stop changing/syncing and check the collection.
Suspended cards are never automatically activated, even when explicitly included.

## 2.5.1
Fixed overlapping hint texts in the options dialog with larger system fonts: the form now sits in a scroll area, the dialog is kept tall enough for its wrapped text and never taller than the screen, and the long Even explanation only shows when Even is ticked.
