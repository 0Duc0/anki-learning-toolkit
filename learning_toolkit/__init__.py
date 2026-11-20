"""Learning Toolkit – the study helpers for the a./b./c. stage workflow in one add-on.

Each part used to be its own add-on. They now share one menu (Tools › Learning Toolkit),
one settings file and one overview window, and each part can be switched off on its own.
A part that fails to start is reported in the overview; the other parts keep working.
"""

from __future__ import annotations

import importlib
import sys
import traceback

# key, title, one-line description, how to open it (attribute of the module, or a browser hint)
MODULES = (
    ("stage_shifter", "Card Stage Shifter",
     "Moves new cards one stage along the a./b./c. decks, or refills every stage to the same number of notes.",
     "start_shift"),
    ("note_mover", "Quick Note Mover",
     "Moves the selected notes to the current or a saved deck with one click or shortcut (Browser).",
     "browser"),
    ("change_deck", "Change Deck counts",
     "Puts “Change Deck…” in the Browser’s right-click menu and shows New/Learn/Due per deck in its dialog.",
     "browser"),
    ("words_left", "Words Left",
     "Adds a “Words left” column to the deck list: notes you have not started yet.",
     ""),
    ("deck_progress", "Deck Progress",
     "Named counters of studied cards or words below the deck list.",
     "deck_progress"),
    ("search", "Search Assistant",
     "Word search panel and search helper in the Browser: exact, contains, related, meaning.",
     "browser"),
    ("sound", "Sound Volume",
     "One volume, speed and loudness setting for all card audio, with shortcuts.",
     "open_dialog"),
    ("study_clock", "Study Session Clock",
     "Status-bar clock with focused study time and a per-deck time dashboard.",
     "show_details"),
)

STATUS: dict[str, str] = {}      # key -> "on" | "off" | "legacy" | "error"
DETAIL: dict[str, str] = {}      # key -> explanation for "legacy" / "error"


def _log(what: str) -> None:
    print(f"[learning_toolkit] {what}\n{traceback.format_exc()}", file=sys.stderr)


def module(key: str):
    return sys.modules.get(f"{__name__}.{key}")


def _load() -> None:
    from aqt import mw

    if mw is None:          # imported outside Anki (tests, tools)
        return
    from .common import config, legacy

    if not config.all_config().get("migrated_legacy_settings"):
        try:
            copied = legacy.migrate_settings(mw, config.write_section, config.saved_section)
            config.write_key("migrated_legacy_settings", True)
            if copied:
                print(f"[learning_toolkit] settings taken over from: {', '.join(copied)}", file=sys.stderr)
        except Exception:
            _log("could not take over the old add-ons' settings")

    for key, *_rest in MODULES:
        if not config.module_enabled(key):
            STATUS[key] = "off"
            continue
        clash = legacy.blocking(mw, key)
        if clash:
            STATUS[key] = "legacy"
            DETAIL[key] = ", ".join(clash)
            continue
        try:
            importlib.import_module(f"{__name__}.{key}")
            STATUS[key] = "on"
        except Exception as error:   # one broken part must never stop the others
            STATUS[key] = "error"
            DETAIL[key] = f"{type(error).__name__}: {error}"
            _log(f"the {key} part could not start")

    try:
        from . import hub

        hub.install()
    except Exception:
        _log("could not add the overview window")


_load()
