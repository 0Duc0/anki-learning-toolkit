"""Load Learning Toolkit modules the way the old single add-on tests loaded their packages.

The package is imported once with ``aqt.mw = None`` so its start-up code (which wires all
modules into a running Anki) stays out of the way; the module under test is then imported
against the test's stand-in main window.
"""
import importlib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
PKG = os.path.join(ROOT, "learning_toolkit")
INSTALLED = os.environ.get("LT_OLD_ADDONS", "/home/claude/work/installed")
SHOTS = os.environ.get("LT_SHOTS", "/tmp/lt_shots/")
os.makedirs(SHOTS, exist_ok=True)
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)


def core_path(module: str) -> str:
    return os.path.join(PKG, module, "core.py")


def old_core_path(repo: str) -> str:
    """core.py of the last stand-alone release, used as the behaviour baseline."""
    return os.path.join(INSTALLED, repo, "source", "core.py")


class FlatConfig:
    """Hands the module's settings straight to the test's stand-in ``addonManager``.

    The old tests check a flat settings dict; inside the toolkit each module only sees its own
    section (tested separately in ``tests/test_config.py``), so for these tests the section
    layer is replaced by a pass-through.
    """

    def getConfig(self, module=""):  # noqa: N802
        from aqt import mw
        return mw.addonManager.getConfig(module)

    def writeConfig(self, module, data):  # noqa: N802
        from aqt import mw
        mw.addonManager.writeConfig(module, data)

    def saved(self):
        return self.getConfig() or {}


def module(name: str, flat: bool = False):
    import aqt

    stub = aqt.mw
    aqt.mw = None
    try:
        importlib.import_module("learning_toolkit")
    finally:
        aqt.mw = stub
    mod = importlib.import_module("learning_toolkit." + name)
    if flat:
        for sub in list(sys.modules.values()):
            if getattr(sub, "__name__", "").startswith(mod.__name__) and hasattr(sub, "_CFG"):
                sub._CFG = FlatConfig()
    return mod
