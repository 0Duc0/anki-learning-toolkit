# Sound Volume

Easiest: **Tools → Sound Volume…** (changes apply immediately).

- `volume`: 0–200 (%). Above 100 boosts quiet recordings.
- `muted`: true/false.
- `speed`: playback speed 0.5–2.0 (pitch stays natural).
- `normalize`: true plays every recording at the same loudness (−18 LUFS). Each file is measured once with mpv (EBU R128) and the result is kept in `user_files/sound_loudness.json`.
- `step`: how many % one shortcut press changes.
- `volume_up_shortcut`, `volume_down_shortcut`, `mute_shortcut`: work in every Anki
  window (on a Mac, Ctrl means ⌘ and Alt means ⌥). Empty = no shortcut. Restart Anki
  after changing a shortcut.
- `show_tooltips`: show "Volume 80 %" briefly after a shortcut.

Only card audio played by Anki's built-in player (mpv) is affected; text-to-speech
voices are not.
