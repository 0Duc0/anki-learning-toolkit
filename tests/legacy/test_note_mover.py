"""Shortcuts for the Quick Note Move menu (offscreen Qt, stand-in main window)."""
import importlib.util
import os
import sys
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from aqt.qt import QApplication, QMainWindow, QMenu, QKeySequence

app = QApplication.instance() or QApplication([])
SAVED: dict = {}


class _AddonManager:
    def getConfig(self, _name): return dict(SAVED)
    def writeConfig(self, _name, config): SAVED.clear(); SAVED.update(config)
    def setConfigAction(self, *_a): pass


import aqt  # noqa: E402
aqt.mw = types.SimpleNamespace(addonManager=_AddonManager(), col=None, form=types.SimpleNamespace(menuTools=QMenu()))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _toolkit
pkg = _toolkit.module("note_mover")


class FakeBrowser(QMainWindow):
    def __init__(self):
        super().__init__()
        self.form = types.SimpleNamespace(menu_Notes=QMenu())
        self.col = None


def _menu_actions(browser):
    sub = [a for a in browser.form.menu_Notes.actions() if a.menu() is not None][0].menu()
    return {a.text().split(" →")[0]: a for a in sub.actions() if a.text()}


def test_default_shortcuts():
    SAVED.clear()
    b = FakeBrowser(); pkg._add_browser_menu(b)
    acts = _menu_actions(b)
    assert acts["Move selected notes here"].shortcut() == QKeySequence("Ctrl+Alt+Q")
    assert acts["Move selected notes to saved target"].shortcut() == QKeySequence("Ctrl+Alt+S")
    assert acts["Use current deck as saved target"].shortcut() == QKeySequence("Ctrl+Alt+Shift+S")


def test_shortcuts_come_from_config_and_can_be_turned_off():
    SAVED.clear(); SAVED.update({"note_mover": {"saved_shortcut": "Ctrl+Alt+J", "set_target_shortcut": "none"}})
    b = FakeBrowser(); pkg._add_browser_menu(b)
    acts = _menu_actions(b)
    assert acts["Move selected notes to saved target"].shortcut() == QKeySequence("Ctrl+Alt+J")
    assert acts["Use current deck as saved target"].shortcut().isEmpty()


def test_saved_shortcut_stays_usable_without_a_saved_target():
    """With no saved target the action asks for one, so its shortcut must never be disabled."""
    SAVED.clear()
    b = FakeBrowser(); pkg._add_browser_menu(b)
    b._quick_note_mover_saved_action.setEnabled(False)
    pkg._browser_alive = lambda *_a, **_k: True
    pkg._saved_target = lambda _b: None
    pkg._current_target = lambda _b: None
    pkg._refresh_actions(b)
    assert b._quick_note_mover_saved_action.isEnabled()
