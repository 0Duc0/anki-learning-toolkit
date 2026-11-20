# Versions, upgrading and downgrading

Every part of the Learning Toolkit is also published as its own add-on. Both are built from the same code,
so a part behaves the same in the toolkit and on its own.

| You want | Download |
|---|---|
| All eight parts | `learning_toolkit-<version>.ankiaddon` from a `toolkit-v…` release |
| Only one part | `<package>-<version>.ankiaddon` from that part's release (e.g. `deck-progress-v1.4.0`) |
| An older version | the release of that version, or **Older versions** (the last stand-alone builds) |

All releases: [Releases](../../../releases). Each release lists what changed.

## Version numbers

`MAJOR.MINOR.PATCH` per part and for the toolkit (see [`tools/versions.json`](../tools/versions.json)):

- **PATCH** – fixes, nothing to relearn (2.4.0 → 2.4.1)
- **MINOR** – new options or behaviour; your settings keep working (1.3.0 → 1.4.0)
- **MAJOR** – a redesign; settings are converted automatically (3.4.0 → 4.0.0)

Whenever a part gets a new version, the toolkit gets one too, and its release names the parts that changed.

| Part | Package (folder) | Version |
|---|---|---|
| Card Stage Shifter | `new_card_stage_shifter` | 2.6.0 |
| Quick Note Mover | `note_stage_mover` | 1.5.1 |
| Change Deck counts | `change_deck_counts` | 1.1.1 |
| Words Left | `words_left` | 1.0.1 |
| Deck Progress | `deck_progress` | 1.4.0 |
| Search Assistant | `simple_search_assistant` | 4.0.0 |
| Sound Volume | `sound_volume` | 1.0.1 |
| Study Session Clock | `study_session_clock` | 2.4.1 |
| **Learning Toolkit** | `learning_toolkit` | 1.1.0 |

## Installing any file

Double-click the `.ankiaddon` (or *Tools › Add-ons › Install from file…*) and restart Anki.

## Upgrade a single add-on

Install the newer file. It uses the same folder as the version you have, so Anki replaces it and **keeps your
settings**. This also works from the old stand-alone versions (e.g. Deck Progress 1.3.0 → 1.4.0).

## From single add-ons to the toolkit

Install the toolkit and restart.

- The toolkit switches the single add-ons off (Anki's *conflicts*); nothing is deleted.
- On its first start it copies their settings once.
- Remove the single add-ons afterwards in *Tools › Add-ons* if you like.

## From the toolkit back to a single add-on

Install the single add-on and restart. While a single add-on is switched on, the toolkit pauses the same part
(the overview shows *Paused – old add-on still on*), so nothing runs twice. To use only the single add-on,
untick the part in *Tools › Learning Toolkit › Overview & settings…* or switch the toolkit off.

The single add-on keeps its own settings file: it starts with the settings it had before you moved to the
toolkit (or the defaults). Settings changed in the toolkit are not copied back.

## Downgrade

Install the older file over the newer one (same folder) and restart. Settings stay: a newer version only adds
keys, and older versions ignore keys they don't know. Going back over a **MAJOR** version (e.g. Search Assistant
4 → 3) keeps the shared settings; new options return to their defaults.

To go back to an older toolkit, install that `learning_toolkit-…` file the same way.

## Card Redesign, Backup & Sync

These two are separate add-ons with their own repositories and the same rules:
[anki-card-redesign](https://github.com/0Duc0/anki-card-redesign/releases),
[anki-backup-sync](https://github.com/0Duc0/anki-backup-sync/releases).
