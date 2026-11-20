"""Phase 1: real Anki 25.9.4 StudyDeck + real Collection/scheduler, offscreen Qt.

Only the main window (mw) and the Browser widget are stand-ins; everything the
add-on touches (StudyDeck, QListWidget, scheduler tree, QMenu) is the real thing.
"""
import os
import sys
import tempfile
import time
import types

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _toolkit

import anki.lang

anki.lang.set_lang("en")

from anki.collection import Collection
from aqt.qt import *

app = QApplication([])

import aqt
from aqt.studydeck import StudyDeck
from aqt.utils import tr

cdc = _toolkit.module("change_deck")

FAILS = []


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


# ---------------------------------------------------------------- collection
tmp = tempfile.mkdtemp()
col = Collection(os.path.join(tmp, "collection.anki2"))
basic = col.models.by_name("Basic")


def add_cards(deck_name, n, prefix):
    did = col.decks.id(deck_name)
    for i in range(n):
        note = col.new_note(basic)
        note["Front"] = f"{prefix}{i}"
        note["Back"] = "x"
        col.add_note(note, did)
    return did


big = add_cards("Language::中文::詞彙::a. 孫悟空", 30, "a")  # more than 20 new/day
mid = add_cards("Language::中文::詞彙::b. 豬八戒", 5, "b")
nolimit = add_cards("Language::中文::CC-CEDICT::HSK 1", 12, "h")
jp = add_cards("Language::日本語", 3, "j")
col.decks.id("Language::中文::詞彙::empty deck")

# a preset with 0 new/day for the dictionary deck
conf = col.decks.add_config_returning_id("no new")
cfg = col.decks.get_config(conf)
cfg["new"]["perDay"] = 0
col.decks.update_config(cfg)
d = col.decks.get(nolimit)
d["conf"] = conf
col.decks.save(d)

# make some cards due (review) and some in learning in deck b
cids_b = col.find_cards(f"did:{mid}")
now = int(time.time())
col.db.execute(
    "update cards set type=2, queue=2, due=?, ivl=10 where id in (%s)"
    % ",".join(str(c) for c in cids_b[:2]),
    col.sched.today - 1,
)
col.db.execute(
    "update cards set type=1, queue=1, due=?, left=1001 where id=?",
    now - 30,
    cids_b[2],
)

# collapsed deck: do children stay in the tree?
tree_parent = col.decks.get(col.decks.id("Language::中文"))
tree_parent["collapsed"] = True
col.decks.save(tree_parent)
col.decks.reset_default_conf if False else None


# notes with two cards; a few have one card moved to a sibling deck (split notes)
rev = col.models.by_name("Basic (and reversed card)")
split_nids = []
for i in range(6):
    note = col.new_note(rev)
    note["Front"] = f"r{i}"
    note["Back"] = "y"
    col.add_note(note, mid)
    if i < 3:
        card = note.cards()[1]
        card.did = big if i < 2 else nolimit  # two notes split a./b., one split b./HSK 1
        col.update_card(card)
        split_nids.append(note.id)
for i in range(2):  # a note whose both cards sit in the same deeper deck of another branch
    note = col.new_note(rev)
    note["Front"] = f"j{i}"
    note["Back"] = "z"
    col.add_note(note, jp)

# ------------------------------------------------------------------ oracle
def oracle():
    out = {}

    def walk(node):
        for ch in node.children:
            out[col.decks.name(ch.deck_id)] = (
                ch.new_count,
                ch.learn_count,
                ch.review_count,
            )
            walk(ch)

    walk(col.sched.deck_due_tree())
    return out


expected = oracle()
print("oracle sample:", {k: v for k, v in expected.items() if "::" in k})
check(expected["Language::中文::詞彙::a. 孫悟空"][0] == 20, "oracle: big deck capped at 20 new (limit applies)")
check(expected["Language::中文::CC-CEDICT::HSK 1"][0] == 0, "oracle: 0-limit deck shows 0 new")
check(expected["Language::中文::詞彙::b. 豬八戒"][1:] == (1, 2), "oracle: deck b has 1 learn / 2 due")


# --------------------------------------------------------------- fake mw
class FakeMw:
    def __init__(self, col):
        self.col = col
        self.pm = types.SimpleNamespace(profile={})
        self.progress = types.SimpleNamespace(timer=lambda *a, **k: None)

    def garbage_collect_on_dialog_finish(self, d):
        pass


aqt.mw = FakeMw(col)


class FakeBrowser(QWidget):
    pass


cdc.Browser = FakeBrowser  # the add-on's isinstance check target


def open_dialog(parent, title=None, **kw):
    return StudyDeck(
        aqt.mw,
        current="Language::中文::詞彙::a. 孫悟空",
        accept=tr.browsing_move_cards(),
        title=title if title is not None else tr.browsing_change_deck(),
        parent=parent,
        callback=lambda ret: None,
        **kw,
    )


# ---------------------------------------------------- dialog: browser case
br = FakeBrowser()
dlg = open_dialog(br)
app.processEvents()
lst = dlg.form.list

stock_names = [d.name for d in col.decks.all_names_and_ids(include_filtered=False, skip_empty_default=True)]
check(dlg.names == stock_names, "list shows the same decks in the same order as stock Anki")
check(lst.count() == len(stock_names), f"{lst.count()} rows, one per deck")

missing = [n for n in dlg.names if n not in expected]
check(not missing, f"every listed deck has counts (collapsed parents included); missing={missing}")
mismatch = []
for row, name in enumerate(dlg.names):
    got = lst.item(row).data(cdc.COUNTS_ROLE)
    if name in expected and tuple(got or ()) != expected[name]:
        mismatch.append((name, got, expected[name]))
check(not mismatch, f"every row's counts equal the scheduler's; mismatches={mismatch}")
check(isinstance(lst.itemDelegate(), cdc.CountsDelegate), "colour-column delegate installed")

# notes column: equals Anki's own search, subdecks included, split notes counted once
bad_notes = []
for row, name in enumerate(dlg.names):
    want = len(col.find_notes(f'"deck:{name}"'))
    got = lst.item(row).data(cdc.NOTES_ROLE)
    if got != want:
        bad_notes.append((name, got, want))
check(not bad_notes, f"note count of every deck equals Anki's own deck search; bad={bad_notes}")
check(len(split_nids) == 3 and all(len(col.get_note(n).cards()) == 2 for n in split_nids), "fixture has split notes")
parent_row = dlg.names.index("Language::中文::詞彙")
check(lst.item(parent_row).data(cdc.NOTES_ROLE) == len(col.find_notes('"deck:Language::中文::詞彙"')),
      "parent deck counts a split note once (no double count)")
nodes = {n: lst.item(r).data(cdc.NOTES_ROLE) for r, n in enumerate(dlg.names)}
check(nodes["Language::中文::詞彙::empty deck"] == 0, "empty deck shows 0 notes")
check(nodes["Language::日本語"] == 5, f"JP deck: 3 + 2 notes ({nodes['Language::日本語']})")
check("notes" in lst.item(parent_row).toolTip() and cdc._notes_text(1) == "1 note" and cdc._notes_text(1234) == "1,234 notes", "tooltip + wording (1 note / 1,234 notes)")


# filter box: still decorated, and selection still maps to the right deck
dlg.form.filter.setText("a. ")
dlg.redraw("a. ")
app.processEvents()
check(dlg.names == ["Language::中文::詞彙::a. 孫悟空"], f"filter narrows the list: {dlg.names}")
check(tuple(lst.item(0).data(cdc.COUNTS_ROLE)) == expected[dlg.names[0]], "filtered row still has counts")
dlg.redraw("")
app.processEvents()

# choosing a deck returns exactly its name (what Browser uses to move cards)
chosen = {}
dlg.callback = lambda ret: chosen.setdefault("name", ret.name)
target_row = dlg.names.index("Language::中文::詞彙::b. 豬八戒")
lst.setCurrentRow(target_row)
dlg.accept()
check(chosen.get("name") == "Language::中文::詞彙::b. 豬八戒", f"accept returns the selected deck name: {chosen}")

# render for a visual check
dlg2 = open_dialog(br)
dlg2.resize(640, 420)
app.processEvents()
dlg2.grab().save(_toolkit.SHOTS + "dialog_counts.png")

# ------------------------------------------- dialog: other StudyDeck users
other = StudyDeck(
    aqt.mw, title="Choose Deck", parent=br, callback=lambda r: None
)
app.processEvents()
check(other.form.list.item(0).data(cdc.COUNTS_ROLE) is None, "other dialogs (different title) are untouched")
check(not isinstance(other.form.list.itemDelegate(), cdc.CountsDelegate), "no delegate on other dialogs")
no_parent = StudyDeck(
    aqt.mw, title=tr.browsing_change_deck(), callback=lambda r: None
)
app.processEvents()
check(no_parent.form.list.item(0).data(cdc.COUNTS_ROLE) is None, "same title but no Browser parent is untouched")

# --------------------------------------------- failure: counts unavailable
real = cdc._deck_counts


def boom(mw):
    raise RuntimeError("scheduler exploded")


cdc._deck_counts = boom
sys_stderr, sys.stderr = sys.stderr, open(os.devnull, "w")
try:
    dlg3 = open_dialog(br)
    app.processEvents()
finally:
    sys.stderr = sys_stderr
check(dlg3.names == stock_names and dlg3.form.list.count() == len(stock_names), "counts failure: stock list still complete")
dlg3.form.list.setCurrentRow(1)
got = {}
dlg3.callback = lambda ret: got.setdefault("n", ret.name)
dlg3.accept()
check(got.get("n") == stock_names[1], "counts failure: choosing a deck still works")
cdc._deck_counts = real

# ------------------------------------------------------------ menu entry
class Form:
    pass


class FakeBrowser2:
    def __init__(self):
        self.form = Form()
        self.form.actionChange_Deck = QAction("Change Deck...")


def build_menu(texts):
    menu = QMenu()
    for t in texts:
        if t == "-":
            menu.addSeparator()
        else:
            menu.addAction(t)
    return menu


def order(menu):
    return [("-" if a.isSeparator() else a.text()) for a in menu.actions()]


qm1 = "Quick move 1 selected note here → a. 孫悟空"
qm2 = "Quick move 1 selected note → saved n. 玉皇大帝"

fb = FakeBrowser2()
m = build_menu([qm1, qm2, "-", "Add Notes...", "Delete"])
cdc._on_context_menu(fb, m)
m.aboutToShow.emit()
check(order(m) == [qm1, qm2, "Change Deck...", "-", "Add Notes...", "Delete"], f"entry sits right under the quick-move lines: {order(m)}")

# other add-on registers its lines AFTER ours: still correct
fb = FakeBrowser2()
m = build_menu(["Add Notes...", "Delete"])
cdc._on_context_menu(fb, m)  # ours first
m.insertAction(m.actions()[0], QAction(qm2, m))  # theirs afterwards
m.insertAction(m.actions()[0], QAction(qm1, m))
m.aboutToShow.emit()
check(order(m)[:3] == [qm1, qm2, "Change Deck..."], f"works when the quick-move add-on adds its lines later: {order(m)}")

# no quick-move lines -> top of the menu
fb = FakeBrowser2()
m = build_menu(["Add Notes...", "Delete"])
cdc._on_context_menu(fb, m)
m.aboutToShow.emit()
check(order(m)[0] == "Change Deck...", f"no quick-move lines -> top: {order(m)}")

# quick-move lines are the whole menu -> appended at the end
fb = FakeBrowser2()
m = build_menu([qm1, qm2])
cdc._on_context_menu(fb, m)
m.aboutToShow.emit()
check(order(m) == [qm1, qm2, "Change Deck..."], f"quick-move only -> appended: {order(m)}")

# already in the menu (cards mode) -> not duplicated
fb = FakeBrowser2()
m = QMenu()
m.addAction(fb.form.actionChange_Deck)
m.addAction("Delete")
cdc._on_context_menu(fb, m)
m.aboutToShow.emit()
check(order(m).count("Change Deck...") == 1, "no duplicate when Change Deck is already top-level")

# the entry is the original action: triggering it triggers Anki's own handler
fb = FakeBrowser2()
fired = []
fb.form.actionChange_Deck.triggered.connect(lambda: fired.append(1))
m = build_menu([qm1, "-"])
cdc._on_context_menu(fb, m)
m.aboutToShow.emit()
[a for a in m.actions() if a.text() == "Change Deck..."][0].trigger()
check(fired == [1], "clicking the entry fires Anki's own Change Deck action")

# broken browser object must not raise
m = build_menu([qm1])
cdc._on_context_menu(object(), m)
sys.stderr, keep = open(os.devnull, "w"), sys.stderr
try:
    m.aboutToShow.emit()
finally:
    sys.stderr = keep
check(True, "broken browser object: no exception escapes")

print("\nRESULT:", "ALL PASSED" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}")
col.close()
sys.exit(1 if FAILS else 0)
