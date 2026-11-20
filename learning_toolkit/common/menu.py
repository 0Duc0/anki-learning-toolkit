"""Tools > Learning Toolkit: one menu for every module (and for Periodic Backup & Sync)."""

from __future__ import annotations

from aqt import mw
from aqt.qt import QAction, QMenu, qconnect

# Same object name the separate add-ons used, so Periodic Backup & Sync still joins this menu.
TOOLKIT_MENU_OBJECT = "codex_learning_toolkit_menu"


def submenu(parent: QMenu, object_name: str, title: str) -> QMenu:
    for action in parent.actions():
        menu = action.menu()
        if menu is not None and menu.objectName() == object_name:
            return menu
    menu = QMenu(title, parent)
    menu.setObjectName(object_name)
    parent.addMenu(menu)
    return menu


def toolkit_menu() -> QMenu:
    return submenu(mw.form.menuTools, TOOLKIT_MENU_OBJECT, "Learning Toolkit")


def add_action(menu: QMenu, text: str, callback, shortcut: str = "") -> QAction:
    action = QAction(text, mw)
    if shortcut:
        action.setShortcut(shortcut)
    qconnect(action.triggered, lambda _checked=False: callback())
    menu.addAction(action)
    return action
