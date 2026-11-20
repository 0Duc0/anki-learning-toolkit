# Quick Note Mover

Quick Note Mover is deliberately separate from Card Stage Shifter. It replaces
Anki's repeated deck-chooser workflow with direct one-click destinations.

The fastest action is **Move selected notes here**. It sends all cards belonging
to the selected notes to Anki's current deck—the same deck represented by
**Current Deck** in the Browser sidebar. Use the first row-context action or
`Ctrl+Alt+Q` (⌥⌘Q on a Mac).

**Shortcuts (1.5):** ⌥⌘Q moves the selected notes here, ⌥⌘S moves them to the
saved target, ⇧⌥⌘S makes the current deck the saved target (Ctrl+Alt… on
Windows/Linux). All can be changed or turned off in the add-on's config.

For a fixed destination, use **Notes → Quick Note Move → Use current deck as
saved target**, or right-click any normal deck in the Browser sidebar and choose
**Use this deck as saved quick target**. The sidebar menu can also move the
current note selection to that deck immediately. **Choose another saved
target…** remains available for alphabetic stage groups.

The move starts immediately without a second destination dialog or preview.
Every card belonging to the selected notes moves together. Completion appears
as a nonmodal tooltip, and the complete operation remains one Undo step. Cards
inside filtered decks are rejected instead of being moved unexpectedly, and
filtered decks cannot be selected as destinations.

For safety, Quick Note Mover warns before cards are reassigned between `a.`,
`b.`, `c.`, … sibling stages in the same deck group. Cards already in the exact
destination do not trigger an unnecessary warning. The warning can be disabled
or enabled at any time under **Tools → Quick Note Mover → Warn before moving
between stages**.

Note content, review history, flags, and suspension are retained. Anki may adapt
cards currently inside a learning step to the target deck's options.

Version 1.4 binds queued actions and saved destinations to their collection,
cancels callbacks after a profile/full-sync transition, and freezes the selection
before saving the editor. Missing target IDs never fall back to Default. A move
requires working undo APIs and at least 1 GiB free space. Failed moves and failed
postchecks are automatically undone when possible; rollback failures receive an
explicit stop-and-check message. Repeated clicks cannot queue overlapping moves.
