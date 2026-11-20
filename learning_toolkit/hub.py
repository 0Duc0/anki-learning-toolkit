"""Tools › Learning Toolkit › Overview & settings…  — every part on one page.

Shows each part with a short description, whether it is running, a switch to turn it on or
off (takes effect after a restart) and a button to open it. It also offers to switch off
old separate copies of these add-ons that are still enabled.
"""

from __future__ import annotations

import sys

from aqt import mw
from aqt.qt import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    Qt,
    QVBoxLayout,
    QWidget,
    qconnect,
)
from aqt.utils import askUser, showInfo, tooltip

from . import DETAIL, MODULES, STATUS, module
from .common import config, legacy
from .common.menu import add_action, toolkit_menu

PILL = {
    "on": ("Running", "#2e7d4f", "rgba(46,125,79,.14)"),
    "off": ("Switched off", "#7a7f87", "rgba(122,127,135,.16)"),
    "legacy": ("Paused – old add-on still on", "#a35b00", "rgba(214,138,0,.16)"),
    "error": ("Could not start", "#b3261e", "rgba(179,38,30,.13)"),
}
BROWSER_HINT = "Opens in the Browser (right-click a note, or the Notes menu)."


def _open(key: str, how: str) -> None:
    mod = module(key)
    if how == "browser":
        from aqt import dialogs

        dialogs.open("Browser", mw)
        return
    if how == "deck_progress" and mod is not None:
        controller = getattr(sys.modules.get(f"{mod.__name__}.controller"), "_controller", None)
        if controller is not None:
            controller.open_settings()
        return
    target = getattr(mod, how, None) if mod is not None else None
    if callable(target):
        target()


class Row(QFrame):
    def __init__(self, key: str, title: str, text: str, how: str) -> None:
        super().__init__()
        self.key = key
        self.setObjectName("ltRow")
        status = STATUS.get(key, "off")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(14)

        self.switch = QCheckBox()
        self.switch.setChecked(config.module_enabled(key))
        self.switch.setToolTip("Switch this part on or off (after restarting Anki)")
        self.switch.setAccessibleName(f"{title} on")
        lay.addWidget(self.switch, 0, Qt.AlignmentFlag.AlignTop)

        body = QVBoxLayout()
        body.setSpacing(3)
        head = QHBoxLayout()
        name = QLabel(f"<b>{title}</b>")
        head.addWidget(name)
        label, fg, bg = PILL[status]
        pill = QLabel(label)
        pill.setObjectName("ltPill")
        pill.setStyleSheet(f"color:{fg}; background:{bg};")
        if DETAIL.get(key):
            pill.setToolTip(DETAIL[key])
        head.addWidget(pill)
        head.addStretch(1)
        body.addLayout(head)
        desc = QLabel(text)
        desc.setWordWrap(True)
        desc.setObjectName("ltDesc")
        body.addWidget(desc)
        if status == "legacy":
            warn = QLabel(f"The separate add-on <b>{DETAIL[key]}</b> is still switched on, so this part waits. "
                          "Use “Switch off old add-ons” below.")
            warn.setWordWrap(True)
            warn.setObjectName("ltDesc")
            body.addWidget(warn)
        elif status == "error":
            err = QLabel(f"Error: {DETAIL.get(key, '')}")
            err.setWordWrap(True)
            err.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            err.setObjectName("ltDesc")
            body.addWidget(err)
        lay.addLayout(body, 1)

        if how:
            button = QPushButton("Open Browser" if how == "browser" else "Open")
            button.setEnabled(status == "on")
            if how == "browser":
                button.setToolTip(BROWSER_HINT)
            qconnect(button.clicked, lambda _c=False, k=key, h=how: _open(k, h))
            lay.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)


class Hub(QDialog):
    def __init__(self) -> None:
        super().__init__(mw)
        self.setWindowTitle("Learning Toolkit")
        self.setMinimumSize(640, 560)
        self.setStyleSheet(STYLE)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 14)
        root.setSpacing(10)

        title = QLabel("Learning Toolkit")
        title.setObjectName("ltTitle")
        root.addWidget(title)
        sub = QLabel("Your study helpers in one place. Untick a part to switch it off; "
                     "the change takes effect the next time Anki starts.")
        sub.setWordWrap(True)
        sub.setObjectName("ltDesc")
        root.addWidget(sub)

        inner = QWidget()
        rows = QVBoxLayout(inner)
        rows.setContentsMargins(0, 4, 0, 4)
        rows.setSpacing(8)
        self.rows = [Row(*m) for m in MODULES]
        for row in self.rows:
            rows.addWidget(row)
        rows.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidget(inner)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root.addWidget(scroll, 1)

        self.clashes = [f for items in legacy.installed(mw).values() for f, on in items if on]
        buttons = QDialogButtonBox()
        if self.clashes:
            off = buttons.addButton("Switch off old add-ons…", QDialogButtonBox.ButtonRole.ActionRole)
            qconnect(off.clicked, self._switch_off_legacy)
        edit = buttons.addButton("Edit settings file…", QDialogButtonBox.ButtonRole.ActionRole)
        qconnect(edit.clicked, self._edit_raw)
        save = buttons.addButton(QDialogButtonBox.StandardButton.Save)
        close = buttons.addButton(QDialogButtonBox.StandardButton.Close)
        qconnect(save.clicked, self._save)
        qconnect(close.clicked, self.reject)
        root.addWidget(buttons)

    def _save(self) -> None:
        changed = False
        for row in self.rows:
            want = row.switch.isChecked()
            if want != config.module_enabled(row.key):
                config.set_module_enabled(row.key, want)
                changed = True
        if changed:
            showInfo("Saved. Restart Anki to switch the changed parts on or off.", parent=self)
        else:
            tooltip("Nothing changed", parent=self)

    def _switch_off_legacy(self) -> None:
        names = "\n".join(f"• {f}" for f in self.clashes)
        if not askUser("These separate add-ons are replaced by the Learning Toolkit and are still on:\n\n"
                       f"{names}\n\nSwitch them off? Nothing is deleted, and you can switch them on again "
                       "under Tools › Add-ons. Restart Anki afterwards.", parent=self):
            return
        legacy.switch_off(mw, self.clashes)
        showInfo("Done. Please restart Anki.", parent=self)

    def _edit_raw(self) -> None:
        from aqt.addons import ConfigEditor

        ConfigEditor(self, config.PACKAGE, config.all_config())


def open_hub() -> None:
    Hub().exec()


def install() -> None:
    menu = toolkit_menu()
    first = menu.actions()[0] if menu.actions() else None
    action = add_action(menu, "Overview && settings…", open_hub)
    if first is not None:                      # keep the overview at the top of the menu
        menu.removeAction(action)
        menu.insertAction(first, action)
        menu.insertSeparator(first)
    mw.addonManager.setConfigAction(config.PACKAGE, open_hub)
    if any(STATUS.get(k) == "legacy" for k, *_ in MODULES):
        from aqt import gui_hooks

        def remind() -> None:
            tooltip("Learning Toolkit: some parts wait because the old separate add-ons are still on. "
                    "See Tools › Learning Toolkit › Overview.", period=8000)

        gui_hooks.main_window_did_init.append(remind)


STYLE = """
#ltTitle { font-size: 20px; font-weight: 650; }
#ltDesc { color: palette(placeholder-text); }
#ltRow { border: 1px solid palette(mid); border-radius: 10px; background: palette(base); }
#ltPill { border-radius: 9px; padding: 1px 8px; font-size: 11px; font-weight: 600; }
"""
