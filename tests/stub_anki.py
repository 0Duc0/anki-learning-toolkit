"""A minimal Anki main window (offscreen) with the real AddonManager, for loading the toolkit in tests."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from aqt.qt import QAction, QApplication, QMainWindow, QMenu  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def make_mw(col=None, legacy: dict | None = None):
    """Return (mw, addons_dir). `legacy` = {folder: (enabled, config)} installs fake old add-ons."""
    import aqt
    from aqt.addons import AddonManager

    app = QApplication.instance() or QApplication(["test"])
    tmp = tempfile.mkdtemp(prefix="lt_test_")
    addons = os.path.join(tmp, "addons21")
    os.makedirs(addons)
    shutil.copytree(os.path.join(ROOT, "learning_toolkit"), os.path.join(addons, "learning_toolkit"))
    for folder, (enabled, cfg) in (legacy or {}).items():
        os.makedirs(os.path.join(addons, folder))
        with open(os.path.join(addons, folder, "__init__.py"), "w") as f:
            f.write("")
        import json
        with open(os.path.join(addons, folder, "meta.json"), "w") as f:
            json.dump({"disabled": not enabled, "config": cfg}, f)

    class PM:
        name = "User 1"

        def addonFolder(self):  # noqa: N802
            return addons

    mw = QMainWindow()
    mw.app = app
    mw.pm = PM()
    mw.col = col
    mw.state = "deckBrowser"
    mw.form = types.SimpleNamespace(menuTools=QMenu("Tools"), actionAdd_ons=QAction("Add-ons"))
    mw.addonManager = AddonManager(mw)
    aqt.mw = mw
    if addons not in sys.path:
        sys.path.insert(0, addons)
    for name in [m for m in sys.modules if m == "learning_toolkit" or m.startswith("learning_toolkit.")]:
        del sys.modules[name]
    return mw, addons


def menu_tree(menu: QMenu, indent: int = 0) -> list[str]:
    out = []
    for action in menu.actions():
        out.append(" " * indent + (action.text() or "----"))
        if action.menu():
            out += menu_tree(action.menu(), indent + 2)
    return out
