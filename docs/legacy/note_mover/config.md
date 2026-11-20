# Quick Note Mover

Shortcuts (leave a value empty for the default, or write `none` for no shortcut;
on a Mac, Ctrl means ⌘ Cmd and Alt means ⌥ Option):

| Setting | Action | Default |
|---|---|---|
| `shortcut` | Move selected notes **here** (Anki's current deck) | `Ctrl+Alt+Q` (⌥⌘Q) |
| `saved_shortcut` | Move selected notes to the **saved target** | `Ctrl+Alt+S` (⌥⌘S) |
| `set_target_shortcut` | Use the current deck as the saved target | `Ctrl+Alt+Shift+S` (⇧⌥⌘S) |

All three work in the Browser and are listed under **Notes → Quick Note Move**.
If no saved target is set yet, the saved-target shortcut asks for one first.
Restart Anki after changing a shortcut.

`warn_before_stage_reassignment` defaults to `true`. It asks before selected
cards are reassigned from one `a.`, `b.`, `c.`, … stage to another stage in the
same deck group. You can change the same setting more conveniently under
**Tools → Quick Note Mover → Warn before moving between stages**.
