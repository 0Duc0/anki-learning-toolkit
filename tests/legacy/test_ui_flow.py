"""UI flow of the stage shifter: real add-on code + real Anki collection, offscreen Qt.

Stand-ins: the main window, Anki's background-task plumbing (run synchronously)
and the modal exec() of the dialogs (we screenshot them instead of waiting).
"""
import os
import sys
import types

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _toolkit

import anki.lang

anki.lang.set_lang("en")

from aqt.qt import *

app = QApplication([])
_px = int(os.environ.get("PX", "0"))
if _px:
    _f = app.font(); _f.setPixelSize(_px); app.setFont(_f)
import aqt

import run_even_core as t  # fixtures (make_collection, USER_SIZES, stage_contents ...)

col, ids = t.make_collection(t.USER_SIZES)

SAVED = {}


class FakeMw(QMainWindow):
    def __init__(self):
        super().__init__()
        self.col = col
        self.form = types.SimpleNamespace(menuTools=QMenu("Tools", self))
        self.addonManager = types.SimpleNamespace(
            getConfig=lambda name: dict(SAVED) if SAVED else None,
            writeConfig=lambda name, cfg: SAVED.update(cfg),
        )


aqt.mw = FakeMw()
pkg = _toolkit.module("stage_shifter", flat=True)  # noqa: E402  (needs aqt.mw first)

MSGS = []
pkg.showInfo = lambda text, *a, **k: MSGS.append(("info", text))
pkg.showWarning = lambda text, *a, **k: MSGS.append(("warning", text))


class FakeCollectionOp:
    def __init__(self, parent, op):
        self.op = op

    def success(self, f):
        self._s = f
        return self

    def failure(self, f):
        self._f = f
        return self

    def run_in_background(self):
        try:
            result = self.op(col)
        except Exception as e:  # mirror Anki: failure callback
            self._f(e)
            return
        self._s(result)


pkg.CollectionOp = FakeCollectionOp


def run_sync(operation, label=None):
    operation._success(operation._op(col))


pkg._run_query = run_sync

CURRENT = {"name": "", "setup": lambda dlg: None, "accept": False}
SHOTS = _toolkit.SHOTS


def fake_exec(self):
    QApplication.processEvents()
    if self.objectName() == "stageShifterDialog":
        CURRENT["setup"](self)
        QApplication.processEvents()
        self.show()
        for _ in range(4):
            QApplication.processEvents()
        SQUEEZE.append((f"options {CURRENT['name']}", *squeezed(self)))
        self.grab().save(f"{SHOTS}ui_options_{CURRENT['name']}.png")
        return 1 if CURRENT["accept"] else 0
    if self.objectName() == "stageShiftPreview":
        self.show()
        for _ in range(4):
            QApplication.processEvents()
        SQUEEZE.append((f"preview {CURRENT['name']}", *squeezed(self)))
        self.grab().save(f"{SHOTS}ui_preview_{CURRENT['name']}.png")
        return 1
    return 0


QDialog.exec = fake_exec
SQUEEZE = []


def squeezed(dlg):
    """(number of visible word-wrapped labels, how many are shorter than their text needs)"""
    labels = [l for l in dlg.findChildren(QLabel) if l.wordWrap() and l.isVisibleTo(dlg)]
    bad = [l.text()[:30] for l in labels if l.height() < l.heightForWidth(l.width()) - 1]
    return len(labels), bad

FAILS = []


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


def sizes():
    return [len(s) for s in t.stage_contents(col, ids)]


def open_dialog(name, setup=lambda dlg: None, accept=False):
    CURRENT.update(name=name, setup=setup, accept=accept)
    MSGS.clear()
    groups = pkg.scan_groups(col)
    pkg._show_options(groups, None, (col, pkg._collection_epoch))


def find_check(dlg, prefix):
    return next(c for c in dlg.findChildren(QCheckBox) if c.text().startswith(prefix))


# A. dialog as it opens (Even off): regular controls enabled
state = {}
def setup_a(dlg):
    even = find_check(dlg, "Even")
    state["even_checked"] = even.isChecked()
    state["new_enabled"] = find_check(dlg, "New").isEnabled()
open_dialog("A_default", setup_a)
check(state["even_checked"] is False and state["new_enabled"], "A: Even is off by default, regular controls enabled")

# B. tick Even -> regular card-state controls are locked, then run the whole flow
def setup_b(dlg):
    find_check(dlg, "Even").setChecked(True)
    QApplication.processEvents()
    state["locked"] = find_check(dlg, "New").isEnabled() and find_check(dlg, "Review").isEnabled()
    state["summary"] = next(l.text() for l in dlg.findChildren(QLabel) if l.objectName() == "routeSummary")
before = sizes()
open_dialog("B_even", setup_b, accept=True)
check(state["locked"], "B: with Even the card states stay choosable")
check("refilled to 20 notes per stage" in state["summary"], f"B: route summary explains Even: {state['summary'][:90]}...")
after = sizes()
check(after == [20] * 10 + [6] + [0] * 4, f"B: full flow moved the queue into blocks of 20: {after}")
check(any("Rebalanced the queue" in m for _k, m in MSGS), f"B: success message shown: {MSGS[-1][1][:80] if MSGS else None}")
check(SAVED.get("even") is True and SAVED.get("even_notes") == 20, f"B: Even choice saved to config: even={SAVED.get('even')}")
check("include_learning" not in SAVED or SAVED["include_learning"] is False, "B: regular card-state choices not overwritten")
check(t.note_decks_consistent(col), "B: every note's cards are in one deck")

# C. run Even again -> nothing to move, friendly message
open_dialog("C_again", lambda dlg: None, accept=True)
check(sizes() == after, "C: second Even run changes nothing")
check(any("already holds the right number" in m for _k, m in MSGS), f"C: friendly 'nothing to move' message: {[m[:60] for _k, m in MSGS]}")

# D. dialog re-opens remembering Even (config), regular mode still works after unticking
def setup_d(dlg):
    even = find_check(dlg, "Even")
    state["remembered"] = even.isChecked()
    even.setChecked(False)
    QApplication.processEvents()
    state["unlocked"] = find_check(dlg, "New").isEnabled()
open_dialog("D_remembered", setup_d, accept=False)
check(state["remembered"] and state["unlocked"], "D: Even is remembered; unticking unlocks the regular controls")

# E. regular (non-even) flow still works end to end
SAVED.clear(); SAVED.update(even=False)
before = sizes()
def setup_e(dlg):
    pass
open_dialog("E_regular", setup_e, accept=True)
check(any("exactly one stage" in m for _k, m in MSGS), f"E: regular shift still reports 'exactly one stage': {[m[:50] for _k, m in MSGS]}")
check(sizes() != before, "E: regular shift moved cards")

for _name, _n, _bad in SQUEEZE:
    check(not _bad and _n > 0, f"layout: {_name}: none of {_n} wrapped labels is clipped {_bad}")
print("\nRESULT:", "ALL PASSED" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}")
sys.exit(1 if FAILS else 0)
