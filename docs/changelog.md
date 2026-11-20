# Changelog

## Learning Toolkit 1.2.0 – 2026-11-20

- **Deck Progress 1.5.0**
  - The card-state row follows the counter's *Count* setting: cards, notes, or cards and notes (notes in brackets).
    In note mode each note counts once, in its most active state.
  - The finish estimate always counts the notes (or cards) you have never answered in the counter and goal decks.
    It no longer depends on which card states the counter counts, so a counter of mature cards doesn't make every
    note "left".
  - The pace also uses words started in the goal decks.
  - The estimate line is smaller and quieter; its tooltip explains the pace.

## Learning Toolkit 1.1.0 – 2026-11-20

- **Search Assistant 4.0.0**
  - Word search shows results while you type.
  - Four dropdowns: what to search (Auto, Word, Meaning, All fields), how the word matches, which deck, which cards.
  - *Auto*: characters search the word; Latin text searches the word and its meaning.
  - The deck follows the deck the Browser shows. Deck names with spaces, like *Tiếng Việt*, used to find nothing.
  - The search bar switches to Auto once.
  - The Search Assistant dialog is now a single form.
- **Deck Progress 1.4.0** (based on 1.3.0; the toolkit had 1.0.0)
  - Optional card states beside each counter, in Anki's colours. You can rename the states.
  - Finish estimate, either at a fixed pace or at your own pace:
    - your pace is new notes per study day, with recent days weighing more;
    - days off and long breaks don't lower it.
- **Card Stage Shifter 2.6.0**
  - Even mode also distributes Learning/Relearning, Review and suspended cards.
  - Every state is explained in the dialog.
  - Hint text is easier to read on dark themes.
- Every part is also published as its own add-on. It uses the old folder name and settings, so it installs over the earlier stand-alone version.
- Quick Note Mover 1.5.1, Change Deck counts 1.1.1, Words Left 1.0.1, Sound Volume 1.0.1, Study Session Clock 2.4.1: toolkit integration only.

## Learning Toolkit 1.0.0 – 2026-11-20

- Eight add-ons merged into one, with one menu, one settings file and an overview window.
- Old add-ons are switched off on install, and their settings are copied once.
