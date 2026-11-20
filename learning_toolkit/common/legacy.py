"""The separate add-ons this toolkit replaces.

The manifest lists them under "conflicts", so Anki switches them off when the toolkit is
installed. If one is still switched on anyway, the matching module stays off (two copies
would add every menu entry, shortcut and hook twice).
"""

from __future__ import annotations

# module key -> folder names the old add-on used (package name, AnkiWeb ids if any)
LEGACY = {
    "stage_shifter": ("new_card_stage_shifter",),
    "note_mover": ("note_stage_mover", "quick_note_mover"),
    "change_deck": ("change_deck_counts",),
    "words_left": ("words_left", "Words_Left"),
    "deck_progress": ("deck_progress",),
    "search": ("simple_search_assistant",),
    "sound": ("sound_volume",),
    "study_clock": ("study_session_clock",),
}


def installed(mw) -> dict[str, list[tuple[str, bool]]]:
    """module key -> [(folder, enabled)] for old add-ons that are still installed."""
    try:
        present = set(mw.addonManager.allAddons())
    except Exception:
        return {}
    out: dict[str, list[tuple[str, bool]]] = {}
    for key, folders in LEGACY.items():
        for folder in folders:
            if folder in present:
                try:
                    enabled = bool(mw.addonManager.isEnabled(folder))
                except Exception:
                    enabled = True
                out.setdefault(key, []).append((folder, enabled))
    return out


def blocking(mw, key: str) -> list[str]:
    """Old add-ons that are switched on and would clash with module `key`."""
    return [folder for folder, enabled in installed(mw).get(key, []) if enabled]


def migrate_settings(mw, write_section, saved_section, keys=LEGACY) -> list[str]:
    """Copy each old add-on's saved settings into the toolkit once. Returns the modules copied.

    `saved_section(key)` must return only what the user saved in the toolkit (no defaults),
    so settings the user already changed in the toolkit are never overwritten."""
    copied = []
    for key, folders in keys.items():
        if saved_section(key):
            continue
        for folder in folders:
            try:
                saved = (mw.addonManager.addonMeta(folder) or {}).get("config")
            except Exception:
                saved = None
            if isinstance(saved, dict) and saved:
                write_section(key, saved)
                copied.append(key)
                break
    return copied


def switch_off(mw, folders: list[str]) -> None:
    for folder in folders:
        mw.addonManager.toggleEnabled(folder, enable=False)
